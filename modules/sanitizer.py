import json
import logging
import re

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# ROBUST JSON PARSER — 4 fallback layers
# Handles empty, malformed, partial JSON
# ─────────────────────────────────────────
EMPTY_RESULT = {
    "patient_info":     {"name": None, "age_gender": None, "id": None,
                         "occupation": None, "living_situation": None},
    "doctor_info":      {"name": None, "hospital": None, "qualifications": None,
                         "exam_date": None, "relationship": None},
    "diagnoses":        [],
    "medical_history":  None,
    "clinical_findings":None,
    "lab_results":      None,
    "medications":      [],
    "assessment_opinion":None,
    "recommendations":  None,
    "prognosis":        None,
    "plain_summary":    "Could not generate summary. The AI response was incomplete.",
    "key_highlights": {
        "primary_diagnosis": "Not determined",
        "risk_level":        "Not Assessed",
        "capacity_status":   "Not Assessed",
        "follow_up":         "N/A",
        "metric1_label":     "N/A", "metric1_value": "N/A",
        "metric2_label":     "N/A", "metric2_value": "N/A",
    }
}

def safe_str(v):
    """Return string value or None — never crashes on None/wrong type."""
    if v is None: return None
    s = str(v).strip()
    return None if s.lower() in ("null","none","n/a","","[]","{}") else s

def safe_list(v):
    """Return clean list — never crashes."""
    if not v: return []
    if isinstance(v, list):
        return [str(i).strip() for i in v if i and str(i).strip()
                not in ("null","none","n/a","")]
    if isinstance(v, str):
        cleaned = v.strip().strip("[]")
        if not cleaned: return []
        return [i.strip().strip('"\'') for i in cleaned.split(",") if i.strip()]
    return []

def safe_dict(v, keys):
    """Return dict with guaranteed keys — never crashes."""
    if not isinstance(v, dict): v = {}
    return {k: safe_str(v.get(k)) for k in keys}

def sanitize_result(result):
    """
    Deep sanitize the AI result — ensures every field exists and
    has the correct type. Prevents all NoneType errors downstream.
    """
    if not isinstance(result, dict):
        return dict(EMPTY_RESULT)

    pi_keys = ["name","age_gender","id","occupation","living_situation"]
    di_keys = ["name","hospital","qualifications","exam_date","relationship"]
    kh_keys = ["primary_diagnosis","risk_level","capacity_status","follow_up",
               "metric1_label","metric1_value","metric2_label","metric2_value"]

    return {
        "patient_info":      safe_dict(result.get("patient_info"), pi_keys),
        "doctor_info":       safe_dict(result.get("doctor_info"),  di_keys),
        "diagnoses":         safe_list(result.get("diagnoses")),
        "medical_history":   safe_str(result.get("medical_history")),
        "clinical_findings": safe_str(result.get("clinical_findings")),
        "lab_results":       safe_str(result.get("lab_results")),
        "medications":       safe_list(result.get("medications")),
        "assessment_opinion":safe_str(result.get("assessment_opinion")),
        "recommendations":   safe_str(result.get("recommendations")),
        "prognosis":         safe_str(result.get("prognosis")),
        "plain_summary":     safe_str(result.get("plain_summary")) or
                             "Summary not available. Please try again.",
        "translated_summary":safe_str(result.get("translated_summary")) or "",
        "key_highlights":    safe_dict(result.get("key_highlights"), kh_keys),
        # Preserve any extra translated fields
        **{k: safe_str(v) for k, v in result.items()
           if k.startswith("translated_") and k != "translated_summary"},
    }

def parse_ai_json(raw):
    """
    4-layer JSON parser — handles all failure modes:
    Layer 1: Direct parse
    Layer 2: Strip markdown fences then parse
    Layer 3: Regex extract first JSON object
    Layer 4: Return safe empty result (never raises)
    """
    if not raw or not raw.strip():
        logger.warning("AI returned empty response — using fallback result")
        return dict(EMPTY_RESULT)

    clean = raw.strip()

    # Layer 1 — direct parse
    try:
        return sanitize_result(json.loads(clean))
    except Exception:
        pass

    # Layer 2 — strip markdown fences
    clean = re.sub(r"^```json\s*", "", clean, flags=re.I)
    clean = re.sub(r"^```\s*",     "", clean, flags=re.I)
    clean = re.sub(r"\s*```$",     "", clean).strip()
    try:
        return sanitize_result(json.loads(clean))
    except Exception:
        pass

    # Layer 3 — extract first JSON object via regex
    m = re.search(r"\{[\s\S]*\}", clean)
    if m:
        try:
            return sanitize_result(json.loads(m.group(0)))
        except Exception:
            # Try fixing common JSON issues (trailing commas, unquoted nulls)
            fixed = re.sub(r",\s*([}\]])", r"\1", m.group(0))  # trailing commas
            try:
                return sanitize_result(json.loads(fixed))
            except Exception:
                pass

    # Layer 4 — safe fallback, never crash
    logger.warning("All JSON parse attempts failed. Raw response: %s", raw[:200])
    fallback = dict(EMPTY_RESULT)
    fallback["plain_summary"] = (
        "The AI could not produce a structured response for this document. "
        "Please try again or switch to a different AI provider."
    )
    return fallback
