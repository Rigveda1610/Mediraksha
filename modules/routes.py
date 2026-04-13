import io
import logging
import re
import uuid
from datetime import datetime

import requests
from flask import jsonify, render_template, request, send_file, session

from modules import audit
from modules.detection import detect_report_type
from modules.extraction import extract_pdf_text
from modules.pdf_generator import generate_pdf
from modules.prompts import build_prompt
from modules.providers import call_groq, groq_chat
from modules.sanitizer import sanitize_result
from modules.translation import translate_all_fields
from modules.validation import post_process_result

logger = logging.getLogger(__name__)


def register_routes(app):
    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/analyze", methods=["POST"])
    def analyze():
        try:
            api_key = (request.form.get("api_key", "") or "").strip()
            lang_code = (request.form.get("lang_code", "en") or "en").strip()
            lang_name = (request.form.get("lang_name", "English") or "English").strip()
            provider = "groq"

            if not api_key:
                logger.warning("Analyze request missing Groq API key")
                return jsonify({"success": False,
                                "error": "Groq API key is missing. Get a free key at console.groq.com/keys"}), 400

            report_text = ""
            filename_used = "Text input"
            if "file" in request.files:
                f = request.files["file"]
                if f and f.filename:
                    filename_used = f.filename
                    fb = f.read()
                    try:
                        report_text = (extract_pdf_text(fb)
                                       if f.filename.lower().endswith(".pdf")
                                       else fb.decode("utf-8", errors="ignore"))
                    except Exception as e:
                        logger.error("File read failed for %s: %s", filename_used, e)
                        return jsonify({"success": False,
                                        "error": f"Could not read file: {str(e)}"}), 400

            if not report_text.strip():
                report_text = (request.form.get("report_text") or "").strip()

            if not report_text:
                logger.warning("Analyze request missing report text")
                return jsonify({"success": False, "error": "No report text provided."}), 400
            if len(report_text) < 30:
                logger.warning("Analyze request rejected for short report text")
                return jsonify({"success": False,
                                "error": "Report text too short. Please provide more content."}), 400

            detected_type = detect_report_type(report_text)
            prompt = build_prompt(detected_type)
            result = call_groq(api_key, report_text, prompt)

            result["report_type"] = detected_type
            result = sanitize_result(result)
            result["report_type"] = detected_type
            result["translated_summary"] = ""

            result = post_process_result(result, detected_type, report_text)

            if lang_code != "en":
                translate_all_fields(provider, api_key, result, lang_name)

            report_id = str(uuid.uuid4())[:8].upper()
            result["report_id"] = report_id
            result["analyzed_at"] = datetime.now().strftime("%d %b %Y, %I:%M %p")

            patient_name = (result.get("patient_info") or {}).get("name") or "Unknown"
            diagnoses = result.get("diagnoses") or []
            risk = (result.get("key_highlights") or {}).get("risk_level", "N/A")
            audit_entry = {
                "id": report_id,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "patient": patient_name,
                "report_type": detected_type,
                "diagnoses": diagnoses[:3],
                "risk_level": risk,
                "language": lang_name,
                "file": filename_used,
                "words_in_report": len(report_text.split()),
            }
            audit.add_entry(audit_entry, max_audit=app.config["MAX_AUDIT"])

            session["last_report"] = report_text[:app.config["MAX_REPORT_LENGTH"]]
            session["last_api_key"] = api_key
            session.modified = True

            logger.info("Completed analysis %s as %s", report_id, detected_type)
            return jsonify({"success": True, "data": result,
                            "lang_name": lang_name,
                            "detected_type": detected_type,
                            "report_id": report_id})

        except RuntimeError as e:
            logger.error("Analyze runtime error: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500
        except requests.exceptions.ConnectionError:
            logger.error("Analyze failed due to connection error")
            return jsonify({"success": False,
                            "error": "No internet connection. Check your network."}), 503
        except requests.exceptions.Timeout:
            logger.error("Analyze failed due to timeout")
            return jsonify({"success": False,
                            "error": "Request timed out. Please try again."}), 504
        except Exception as e:
            logger.exception("Unexpected error in /analyze")
            return jsonify({"success": False,
                            "error": f"Unexpected error ({type(e).__name__}). Please try again."}), 500

    @app.route("/ask", methods=["POST"])
    def ask():
        """Chatbot Q&A — answers questions about the last analyzed report."""
        try:
            body = request.get_json(force=True)
            question = (body.get("question") or "").strip()
            api_key = (body.get("api_key") or session.get("last_api_key") or "").strip()
            context = session.get("last_report", "")

            if not question:
                logger.warning("Ask request missing question")
                return jsonify({"success": False, "error": "No question provided."}), 400
            if not api_key:
                logger.warning("Ask request missing API key")
                return jsonify({"success": False, "error": "API key missing."}), 400
            if not context:
                logger.warning("Ask request missing analyzed report context")
                return jsonify({"success": False,
                                "error": "No report loaded. Please analyze a report first."}), 400

            system_msg = (
                "You are MediRaksha, a helpful medical assistant. "
                "Answer the user's question based ONLY on the medical report provided. "
                "If the answer is not in the report, say clearly: 'This information is not mentioned in the report.' "
                "Be concise, clear, and use simple language. Do not make up information."
            )
            user_msg = f"MEDICAL REPORT:\n{context}\n\nQUESTION: {question}\n\nANSWER:"

            answer = groq_chat(api_key, system_msg, user_msg, max_tokens=500)
            logger.info("Answered follow-up question for current session")
            return jsonify({"success": True, "answer": answer})

        except RuntimeError as e:
            logger.error("Ask runtime error: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500
        except Exception as e:
            logger.exception("Ask request failed")
            return jsonify({"success": False, "error": f"Could not answer: {str(e)}"}), 500

    @app.route("/audit", methods=["GET"])
    def audit_log():
        """Return the audit log — last 100 analyses."""
        log = audit.get_log()
        return jsonify({"success": True, "log": log, "total": len(log)})

    @app.route("/audit/clear", methods=["POST"])
    def audit_clear():
        """Clear the audit log."""
        audit.clear_log()
        return jsonify({"success": True, "message": "Audit log cleared."})

    @app.route("/download_pdf", methods=["POST"])
    def download_pdf():
        try:
            body = request.get_json(force=True)
            summary_data = body.get("summary_data", {})
            lang_name = body.get("lang_name", "English")
            patient_name = ((summary_data.get("patient_info") or {}).get("name") or "Report")
            safe = re.sub(r"[^\w\s-]", "", patient_name).strip().replace(" ", "_")
            filename = f"MediRaksha_{safe}_{datetime.now().strftime('%d_%b_%Y')}.pdf"

            pdf_bytes = generate_pdf(summary_data, lang_name)
            logger.info("Generated PDF for %s", patient_name)
            return send_file(io.BytesIO(pdf_bytes),
                             mimetype="application/pdf",
                             as_attachment=True,
                             download_name=filename)
        except Exception as e:
            logger.exception("PDF generation failed")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "service": "MediRaksha"})
