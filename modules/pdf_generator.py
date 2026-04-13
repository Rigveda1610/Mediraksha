import io
import logging
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# PDF GENERATION
# ─────────────────────────────────────────
def generate_pdf(data, lang_name):
    logger.info("Generating PDF in %s", lang_name)
    buf = io.BytesIO()
    W, _ = A4
    cw = W - 36 * mm

    doc = SimpleDocTemplate(buf, pagesize=A4,
          rightMargin=18*mm, leftMargin=18*mm,
          topMargin=18*mm, bottomMargin=18*mm)

    def ps(name, **kw):
        return ParagraphStyle(name, **kw)

    wh_bold = ps("wb", fontName="Helvetica-Bold",  fontSize=10, textColor=colors.white)
    lbl     = ps("lb", fontName="Helvetica-Bold",  fontSize=9,
                 textColor=colors.HexColor("#0d3b5e"), spaceAfter=1)
    val     = ps("vl", fontName="Helvetica", fontSize=9.5,
                 textColor=colors.HexColor("#222"), leading=14, spaceAfter=4)
    body    = ps("bd", fontName="Helvetica", fontSize=9.5,
                 textColor=colors.HexColor("#333"), leading=15,
                 spaceAfter=6, alignment=TA_JUSTIFY)
    foot    = ps("ft", fontName="Helvetica", fontSize=7.5,
                 textColor=colors.HexColor("#888"), alignment=TA_CENTER)
    diag    = ps("dg", fontName="Helvetica-Bold", fontSize=11,
                 textColor=colors.HexColor("#c0392b"), spaceAfter=4, leftIndent=6)
    ef_hdr  = ps("ef", fontName="Helvetica-Bold", fontSize=9,
                 textColor=colors.HexColor("#0d3b5e"), spaceAfter=3)
    summ    = ps("sm", fontName="Helvetica", fontSize=9.5,
                 textColor=colors.HexColor("#1a3a4a"), leading=15)

    story = []

    banner = Table([
        [Paragraph("<b>MediRaksha — AI Medical Report Summary</b>",
                   ps("bh", fontName="Helvetica-Bold", fontSize=15,
                      textColor=colors.white, alignment=TA_CENTER))],
        [Paragraph("AI-Powered  ·  Confidential Medical Document",
                   ps("bs", fontName="Helvetica", fontSize=8,
                      textColor=colors.HexColor("#b0e0df"), alignment=TA_CENTER))]
    ], colWidths=[cw])
    banner.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#0d3b5e")),
        ("TOPPADDING",    (0,0),(-1,-1), 10),
        ("BOTTOMPADDING", (0,0),(-1,-1), 10),
    ]))
    story.append(banner)
    story.append(Spacer(1, 3*mm))

    gd = datetime.now().strftime("%d %B %Y, %I:%M %p")
    meta_row = Table([[
        Paragraph(f"<b>Generated:</b> {gd}",
                  ps("ml", fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#555"))),
        Paragraph(f"<b>Language:</b> {lang_name}",
                  ps("mc", fontName="Helvetica", fontSize=8,
                     textColor=colors.HexColor("#555"), alignment=TA_CENTER)),
        Paragraph("<b>System:</b> MediRaksha AI",
                  ps("mr", fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#555"))),
    ]], colWidths=[cw/3]*3)
    meta_row.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#f5f9fc")),
        ("GRID",          (0,0),(-1,-1), 0.4, colors.HexColor("#dde8f0")),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (0,0),(-1,-1), 6),
    ]))
    story.append(meta_row)
    story.append(Spacer(1, 5*mm))

    def sec(title):
        story.append(Spacer(1, 2*mm))
        t = Table([[Paragraph(f"<b>{title}</b>", wh_bold)]], colWidths=[cw])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#0e7c7b")),
            ("TOPPADDING",    (0,0),(-1,-1), 6),
            ("BOTTOMPADDING", (0,0),(-1,-1), 6),
            ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ]))
        story.append(t)
        story.append(Spacer(1, 2*mm))

    def fld(label, value):
        if not value or str(value).strip() in ("", "null", "None", "N/A"):
            return
        row = Table([[Paragraph(label, lbl), Paragraph(str(value), val)]],
                    colWidths=[44*mm, cw-44*mm])
        row.setStyle(TableStyle([
            ("BACKGROUND", (0,0),(-1,-1), colors.white),
            ("GRID",       (0,0),(-1,-1), 0.3, colors.HexColor("#e0e8ee")),
            ("VALIGN",     (0,0),(-1,-1), "TOP"),
            ("TOPPADDING",    (0,0),(-1,-1), 4),
            ("BOTTOMPADDING", (0,0),(-1,-1), 4),
            ("LEFTPADDING",   (0,0),(-1,-1), 6),
        ]))
        story.append(row)
        story.append(Spacer(1, 1))

    def bdy(text):
        v = str(text or "").strip()
        if v and v not in ("null", "None", "N/A"):
            story.append(Paragraph(v, body))

    def empty(v):
        return not v or str(v).strip() in ("", "null", "None", "N/A")

    pi = data.get("patient_info") or {}
    sec("PATIENT INFORMATION")
    fld("Full Name",        pi.get("name"))
    fld("Age / Gender",     pi.get("age_gender"))
    fld("ID / Reference",   pi.get("id"))
    fld("Occupation",       pi.get("occupation"))
    fld("Living Situation", pi.get("living_situation"))

    di = data.get("doctor_info") or {}
    sec("EXAMINING DOCTOR")
    fld("Doctor Name",    di.get("name"))
    fld("Hospital",       di.get("hospital"))
    fld("Qualifications", di.get("qualifications"))
    fld("Exam Date",      di.get("exam_date"))
    fld("Relationship",   di.get("relationship"))

    dx = data.get("diagnoses") or []
    if dx:
        sec("DIAGNOSIS")
        story.append(Paragraph("  ·  ".join(dx), diag))

    sec("MEDICAL HISTORY & CLINICAL FINDINGS")
    bdy(data.get("medical_history"))
    if not empty(data.get("clinical_findings")):
        story.append(Paragraph("<b>Examination Findings:</b>", ef_hdr))
        bdy(data.get("clinical_findings"))

    if not empty(data.get("lab_results")):
        sec("INVESTIGATION RESULTS")
        bdy(data.get("lab_results"))

    meds = [m for m in (data.get("medications") or [])
            if m and str(m).strip() not in ("N/A","null","None","Not mentioned")]
    if meds:
        sec("MEDICATIONS / PRESCRIPTIONS")
        for m in meds:
            story.append(Paragraph(f"• {m}", body))

    if not empty(data.get("assessment_opinion")):
        sec("CLINICAL ASSESSMENT & OPINION")
        bdy(data.get("assessment_opinion"))

    if not empty(data.get("recommendations")):
        sec("RECOMMENDATIONS / FOLLOW-UP")
        bdy(data.get("recommendations"))

    if not empty(data.get("prognosis")):
        sec("PROGNOSIS")
        bdy(data.get("prognosis"))

    sec("AI PLAIN LANGUAGE SUMMARY")
    plain = data.get("plain_summary", "")
    if plain:
        t = Table([[Paragraph(plain, summ)]], colWidths=[cw])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#f0f9f9")),
            ("TOPPADDING",    (0,0),(-1,-1), 8),
            ("BOTTOMPADDING", (0,0),(-1,-1), 8),
            ("LEFTPADDING",   (0,0),(-1,-1), 10),
            ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ]))
        story.append(t)

    # ── TRANSLATED SECTIONS (all fields) ──
    if lang_name.lower() != "english":
        trans_fields = [
            ("translated_summary",           "SUMMARY"),
            ("translated_medical_history",   "MEDICAL HISTORY"),
            ("translated_clinical_findings", "CLINICAL FINDINGS"),
            ("translated_assessment_opinion","CLINICAL ASSESSMENT"),
            ("translated_prognosis",         "PROGNOSIS"),
            ("translated_recommendations",   "RECOMMENDATIONS"),
        ]
        has_any = any(
            not empty(data.get(k)) for k, _ in trans_fields
        )
        if has_any:
            sec(f"TRANSLATED CONTENT — {lang_name.upper()}")
            for field_key, field_label in trans_fields:
                val = data.get(field_key, "")
                if not empty(val):
                    story.append(Paragraph(
                        f"<b>{field_label}:</b>",
                        ps("tlbl", fontName="Helvetica-Bold", fontSize=9,
                           textColor=colors.HexColor("#0e7c7b"), spaceAfter=3)
                    ))
                    t2 = Table([[Paragraph(str(val), summ)]], colWidths=[cw])
                    t2.setStyle(TableStyle([
                        ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#f0f9f9")),
                        ("TOPPADDING",    (0,0),(-1,-1), 6),
                        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
                        ("LEFTPADDING",   (0,0),(-1,-1), 10),
                        ("RIGHTPADDING",  (0,0),(-1,-1), 10),
                    ]))
                    story.append(t2)
                    story.append(Spacer(1, 3*mm))

    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#ccc")))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "DISCLAIMER: This AI-generated summary is for informational purposes only. "
        "It does not replace professional medical advice. "
        "Always consult a qualified healthcare professional for medical decisions.",
        foot))

    doc.build(story)
    buf.seek(0)
    return buf.read()
