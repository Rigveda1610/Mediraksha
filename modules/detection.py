import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# STEP 0 — AUTO REPORT TYPE DETECTION
# Runs before main analysis using keywords
# so we can adapt the prompt accordingly
# ─────────────────────────────────────────
REPORT_TYPE_KEYWORDS = {
    "Lab Report": [
        "haemoglobin", "hemoglobin", "wbc", "rbc", "platelet", "glucose",
        "creatinine", "urea", "bilirubin", "cholesterol", "triglyceride",
        "hba1c", "tsh", "t3", "t4", "esr", "crp", "sodium", "potassium",
        "reference range", "normal range", "test result", "laboratory",
        "pathology", "specimen", "sample", "urine", "serum", "plasma",
        "blood test", "complete blood count", "cbc", "lipid profile",
        "liver function", "kidney function", "thyroid"
    ],
    "Prescription": [
        "tablet", "capsule", "mg", "ml", "syrup", "injection", "ointment",
        "twice daily", "once daily", "thrice daily", "bd", "od", "tds",
        "after food", "before food", "days", "weeks", "rx", "sig:",
        "dispense", "refill", "dosage", "dose", "route", "oral", "iv",
        "prescribed by", "prescription", "pharmacy"
    ],
    "Discharge Summary": [
        "discharge", "admitted", "admission date", "discharge date",
        "length of stay", "ward", "bed number", "inpatient", "icu",
        "intensive care", "discharge diagnosis", "discharge instructions",
        "follow up", "condition on discharge", "hospital course"
    ],
    "Radiology Report": [
        "x-ray", "xray", "ct scan", "mri", "ultrasound", "echo",
        "echocardiogram", "radiograph", "impression", "findings",
        "no acute", "opacity", "lucency", "lesion", "mass", "nodule",
        "fracture", "dislocation", "radiologist", "imaging"
    ],
    "Mental Capacity Assessment": [
        "mental capacity", "capacity", "welfare", "property", "affairs",
        "decision", "retain", "understand", "weigh", "communicate",
        "dementia", "cognitive", "mental capacity act", "deputyship",
        "lasting power", "assessment"
    ],
    "Outpatient Report": [
        "outpatient", "opd", "clinic", "consultation", "follow-up visit",
        "chief complaint", "history of present illness", "physical examination",
        "vital signs", "blood pressure", "pulse", "temperature", "weight"
    ],
    "Specialist Referral": [
        "referral", "refer", "referred to", "specialist", "please review",
        "kindly review", "further management", "opinion requested",
        "for further", "please see"
    ]
}

def detect_report_type(text):
    logger.info("Detecting report type")
    """
    Automatically detect the type of medical report
    by counting keyword matches. Returns the best match
    or 'General Medical Report' as fallback.
    """
    text_lower = text.lower()
    scores = {}
    for rtype, keywords in REPORT_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[rtype] = score
    if not scores:
        return "General Medical Report"
    return max(scores, key=scores.get)
