"""
MediRaksha - AI Medical Report Summarizer
==========================================
HOW TO RUN:
  Step 1: pip install flask requests pdfplumber pypdf reportlab
  Step 2: python app.py
  Step 3: Open http://localhost:5000 in your browser
"""

import os, io, json, re, requests, uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, session

import pdfplumber, pypdf
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY

app = Flask(__name__)
app.secret_key = "mediraksha-audit-secret-2025"

# ─────────────────────────────────────────
# IN-MEMORY AUDIT LOG
# Stores last 100 analysis records
# ─────────────────────────────────────────
AUDIT_LOG = []
MAX_AUDIT = 100


# ─────────────────────────────────────────
# PDF TEXT EXTRACTION
# ─────────────────────────────────────────
def extract_pdf_text(file_bytes):
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                t = page.extract_text()
                if t:
                    text += f"\n--- Page {i+1} ---\n{t}\n"
    except Exception:
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            for i, page in enumerate(reader.pages):
                text += f"\n--- Page {i+1} ---\n{page.extract_text()}\n"
        except Exception as e:
            raise RuntimeError(f"Cannot read PDF: {e}")
    return text.strip()


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


# ─────────────────────────────────────────
# ADAPTIVE ANALYSIS PROMPT
# Changes based on detected report type
# so the AI knows what fields to focus on
# ─────────────────────────────────────────
# ─────────────────────────────────────────
# SPECIALIZED PROMPTS PER REPORT TYPE
#
# Each prompt is completely custom —
# not just a hint appended to a generic base.
# This ensures strict field separation and
# correct medical interpretation per type.
# ─────────────────────────────────────────

# ── SHARED JSON STRUCTURE RULES ──────────
_JSON_RULES = """
STRICT RULES — read carefully:
1. Return ONLY valid JSON. No markdown, no preamble, no explanation.
2. Extract ONLY what is explicitly in the document. Never invent or assume.
3. Every key must be present. Use null or [] if not available.
4. Do NOT mix field types — diagnoses must be medical conditions only, never lab values.
5. plain_summary: Write 2-3 clean, complete sentences for a patient or family member.
   - Use confident, direct language. Do NOT use phrases like "may indicate", "could suggest",
     "it appears", "seems to", "possibly", "might be".
   - Use: "The results show...", "The report confirms...", "The patient has...",
     "Treatment includes...", "Follow-up is recommended..."
   - Do NOT repeat the same information twice in the summary.
   - Do NOT end with an incomplete sentence.
6. clinical_findings: Write as a clean paragraph or bullet points. Never as a raw Python
   dict, JSON object, or key-value pairs like {'key': 'value'}.
7. assessment_opinion: Use definitive clinical language. Avoid hedging phrases.

Required JSON structure (ALL keys mandatory):
{
  "patient_info": {
    "name": "patient full name or null",
    "age_gender": "age and gender or null",
    "id": "any ID number or null",
    "occupation": "occupation or null",
    "living_situation": "living arrangement or null"
  },
  "doctor_info": {
    "name": "doctor/technician/lab name or null",
    "hospital": "hospital/clinic/lab name and address or null",
    "qualifications": "credentials or registration number or null",
    "exam_date": "date of report/test/exam or null",
    "relationship": "doctor-patient relationship or null"
  },
  "diagnoses": [],
  "medical_history": null,
  "clinical_findings": null,
  "lab_results": null,
  "medications": [],
  "assessment_opinion": null,
  "recommendations": null,
  "prognosis": null,
  "plain_summary": "2-3 clear, direct sentences for a patient or family member",
  "key_highlights": {
    "primary_diagnosis": "3-5 words",
    "risk_level": "Low or Moderate or High or Critical",
    "capacity_status": "Has Capacity or Lacks Capacity or Not Assessed",
    "follow_up": "follow-up info or N/A",
    "metric1_label": "most important value label",
    "metric1_value": "value with unit",
    "metric2_label": "second value label",
    "metric2_value": "value with unit"
  }
}
"""

# ── LAB REPORT PROMPT ────────────────────
PROMPT_LAB = """You are MediRaksha, a clinical lab report interpreter. Analyze the laboratory report and return ONLY valid JSON.

CRITICAL FOR LAB REPORTS — strictly follow these rules:
- "diagnoses" field: ONLY include formally stated medical diagnoses (e.g., "Anemia", "Diabetes Mellitus", "Hypothyroidism"). NEVER put raw lab values, test names, or morphology terms like "Aniso(+)", "Poikilocytosis", "Microcytic" in diagnoses. Those belong in lab_results.
- "lab_results" field: Include ALL test names, their values, units, and reference ranges. Format each test as: "Test Name: value unit (reference: low-high) [NORMAL/LOW/HIGH/CRITICAL]"
- "clinical_findings" field: Morphological observations like Anisocytosis, Poikilocytosis, Hypochromia, target cells — these are microscopic findings, not diagnoses.
- "assessment_opinion" field: Overall lab interpretation — which results are abnormal and what they suggest clinically.
- "diagnoses" field: Only include conditions that are EXPLICITLY stated as diagnoses OR that you can confidently interpret (e.g., if Hemoglobin is 8.0 g/dL with low MCV and MCH, you may infer "Iron Deficiency Anemia" as the interpreted diagnosis).

For key_highlights:
- metric1 should be the most abnormal or critical lab value
- metric2 should be the second most significant abnormal value
- risk_level: Low = all normal; Moderate = mild abnormalities; High = significant abnormalities; Critical = life-threatening values
""" + _JSON_RULES

# ── PRESCRIPTION PROMPT ──────────────────
PROMPT_PRESCRIPTION = """You are MediRaksha, a clinical pharmacist AI. Analyze the prescription and return ONLY valid JSON.

CRITICAL FOR PRESCRIPTIONS:
- "medications" field: Extract EVERY drug with exact name, strength (mg/ml), form (tablet/capsule/syrup), dose, frequency, route, and duration. Format: "Drug Name Strength form — Dose, Frequency, Route, Duration"
- "diagnoses" field: Only the medical condition being treated, if explicitly written. Never infer from medication names.
- "lab_results" field: null — prescriptions do not have lab results.
- "clinical_findings" field: null unless physical examination findings are documented.
- "assessment_opinion" field: Prescribing doctor's note or clinical impression if written.
- "recommendations" field: Any patient counselling, dietary advice, or warnings written on the prescription.
- "key_highlights": metric1 = most important/high-risk drug, metric2 = second drug. Risk = Low for routine; Moderate if multiple chronic disease drugs; High if steroids/anticoagulants/narcotics; Critical if emergency medications.
""" + _JSON_RULES

# ── DISCHARGE SUMMARY PROMPT ─────────────
PROMPT_DISCHARGE = """You are MediRaksha, a hospital discharge summary analyzer. Return ONLY valid JSON.

CRITICAL FOR DISCHARGE SUMMARIES:
- "diagnoses" field: Final discharge diagnosis/diagnoses only — NOT admitting complaints.
- "medical_history" field: Events DURING this hospitalization — procedures done, treatment given, hospital course.
- "clinical_findings" field: Patient's condition AT DISCHARGE — vital signs, examination on discharge day.
- "lab_results" field: Key investigation results during admission (blood tests, imaging, ECG etc.).
- "medications" field: Discharge medications only — what patient goes home with.
- "recommendations" field: Discharge instructions — activity restrictions, diet, follow-up appointments, warning signs.
- "assessment_opinion" field: Summary of entire hospital stay and outcome.
- In key_highlights: metric1 = admission date or length of stay, metric2 = discharge condition.
""" + _JSON_RULES

# ── RADIOLOGY PROMPT ─────────────────────
PROMPT_RADIOLOGY = """You are MediRaksha, a radiology report interpreter. Return ONLY valid JSON.

CRITICAL FOR RADIOLOGY REPORTS:
- "diagnoses" field: ONLY the radiologist's final impression/conclusion (e.g., "Consolidation — likely pneumonia", "No acute intracranial pathology"). Not individual findings.
- "clinical_findings" field: ALL individual radiological findings — what was seen on the scan/image. Include location, size, density, and characteristics.
- "lab_results" field: Technical parameters — modality (X-ray/CT/MRI/USG), body part, contrast used, sequences used.
- "assessment_opinion" field: Radiologist's full impression and recommendation for clinical correlation.
- "medical_history" field: Clinical indication / reason for the scan if mentioned.
- "recommendations" field: Radiologist's follow-up imaging recommendations.
- In key_highlights: metric1 = most significant finding with location, metric2 = second finding. Risk based on severity of radiological findings.
""" + _JSON_RULES

# ── MENTAL CAPACITY PROMPT ───────────────
PROMPT_MENTAL_CAPACITY = """You are MediRaksha, a mental capacity assessment analyzer. Return ONLY valid JSON.

CRITICAL FOR MENTAL CAPACITY ASSESSMENTS:
- "diagnoses" field: Formal medical diagnoses only (e.g., "Dementia", "Stroke", "Schizophrenia").
- "clinical_findings" field: ALL cognitive test findings — orientation (time/place/person), memory tests, arithmetic tests, currency recognition, communication ability. Be detailed.
- "assessment_opinion" field: Doctor's full opinion on whether the patient has/lacks mental capacity for BOTH personal welfare AND property/affairs. Include the legal basis.
- "capacity_status" in key_highlights: MUST be "Has Capacity" or "Lacks Capacity" — never "Not Assessed" unless explicitly unresolved.
- "prognosis" field: Whether capacity is likely to improve, deteriorate, or remain unchanged.
- "recommendations" field: Deputyship, lasting power of attorney, or other legal actions recommended.
- In key_highlights: metric1 = capacity for personal welfare (Has/Lacks), metric2 = capacity for property/affairs (Has/Lacks).
""" + _JSON_RULES

# ── OUTPATIENT REPORT PROMPT ─────────────
PROMPT_OUTPATIENT = """You are MediRaksha, a clinical note analyzer. Return ONLY valid JSON.

CRITICAL FOR OUTPATIENT/OPD REPORTS:
- "diagnoses" field: Final working diagnosis or differential diagnoses stated by the doctor.
- "clinical_findings" field: Chief complaint + history of presenting illness + physical examination findings + vital signs (BP, pulse, temperature, SpO2, weight).
- "medical_history" field: Past medical history, surgical history, family history, social history.
- "lab_results" field: Any investigations ordered or results reviewed during this visit.
- "medications" field: All medications prescribed or continued during this visit.
- "recommendations" field: Treatment plan, lifestyle advice, investigations ordered, follow-up date.
- In key_highlights: metric1 = most critical vital sign or finding, metric2 = key diagnosis-supporting finding.
""" + _JSON_RULES

# ── SPECIALIST REFERRAL PROMPT ───────────
PROMPT_REFERRAL = """You are MediRaksha, a referral letter analyzer. Return ONLY valid JSON.

CRITICAL FOR SPECIALIST REFERRAL LETTERS:
- "diagnoses" field: Patient's current diagnosis or working diagnosis — reason for referral.
- "medical_history" field: Relevant clinical history and background the specialist needs to know.
- "clinical_findings" field: Examination findings and investigations done by the referring doctor.
- "assessment_opinion" field: Reason for referral and what specific opinion/management is being sought.
- "recommendations" field: What the referring doctor is asking the specialist to do.
- "doctor_info": Include BOTH the referring doctor AND the specialist being referred to if mentioned.
""" + _JSON_RULES

# ── GENERAL MEDICAL REPORT PROMPT ────────
PROMPT_GENERAL = """You are MediRaksha, a medical document analyzer. Return ONLY valid JSON.

Analyze this medical document carefully and extract all available clinical information.
Map content to the most appropriate field. Be flexible with unstructured content.

Key rules:
- "diagnoses": Medical conditions, diseases, disorders ONLY — not symptoms, not lab values, not morphological terms.
- "clinical_findings": Symptoms, examination findings, observations.
- "lab_results": Any numerical test results with values and units.
- "medications": Any drugs, treatments, or therapies mentioned.
""" + _JSON_RULES

# ── PROMPT MAP ───────────────────────────
PROMPT_MAP = {
    "Lab Report":                PROMPT_LAB,
    "Prescription":              PROMPT_PRESCRIPTION,
    "Discharge Summary":         PROMPT_DISCHARGE,
    "Radiology Report":          PROMPT_RADIOLOGY,
    "Mental Capacity Assessment":PROMPT_MENTAL_CAPACITY,
    "Outpatient Report":         PROMPT_OUTPATIENT,
    "Specialist Referral":       PROMPT_REFERRAL,
    "General Medical Report":    PROMPT_GENERAL,
}

def build_prompt(report_type):
    """Return the fully specialized prompt for the detected report type."""
    return PROMPT_MAP.get(report_type, PROMPT_GENERAL)


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


# ─────────────────────────────────────────
# MEDICAL POST-PROCESSING ENGINE
#
# Runs AFTER the AI returns its result.
# Provides intelligent interpretation:
# 1. Lab value abnormality detection
# 2. Clinical condition inference from values
# 3. Diagnosis cleanup (removes non-diagnoses)
# 4. Risk level auto-correction
# 5. Missing field auto-population
# ─────────────────────────────────────────

# Known morphological/microscopic terms that
# must NEVER appear in the diagnoses field
LAB_MORPHOLOGY_TERMS = {
    "aniso", "anisocytosis", "poikilocytosis", "hypochromia", "microcytic",
    "macrocytic", "normocytic", "normochromic", "hypochromic", "target cells",
    "rouleaux", "spherocytes", "schistocytes", "elliptocytes", "acanthocytes",
    "burr cells", "tear drop", "basophilic stippling", "polychromasia",
    "aniso+", "aniso(+)", "poikilo+", "poikilo(+)", "hypo+", "hypo(+)",
    "micro", "macro", "blast", "band", "segmented", "eosinophil",
    "neutrophil", "lymphocyte", "monocyte", "thrombocytopenia",
    "leukocytosis", "leukopenia", "neutrophilia", "lymphocytosis",
}

# Known lab test names that must NEVER be in diagnoses
LAB_TEST_NAMES = {
    "haemoglobin", "hemoglobin", "hb", "hgb", "hct", "pcv",
    "wbc", "rbc", "platelets", "plt", "mcv", "mch", "mchc", "rdw",
    "esr", "crp", "glucose", "fasting", "postprandial", "hba1c",
    "creatinine", "urea", "bun", "uric acid", "sodium", "potassium",
    "chloride", "bicarbonate", "calcium", "phosphorus", "magnesium",
    "bilirubin", "sgot", "sgpt", "ast", "alt", "alp", "ggt",
    "albumin", "protein", "globulin", "cholesterol", "triglycerides",
    "hdl", "ldl", "vldl", "tsh", "t3", "t4", "ft3", "ft4",
    "psa", "cea", "afp", "ferritin", "iron", "tibc", "transferrin",
    "vitamin b12", "vitamin d", "folate", "reticulocyte",
    "prothrombin", "pt", "aptt", "inr", "fibrinogen", "d-dimer",
}

# Reference ranges for common lab tests (SI units)
# Format: (low_normal, high_normal, critical_low, critical_high, unit)
LAB_REFERENCE_RANGES = {
    # Haematology
    "haemoglobin_male":   (13.0, 17.0, 7.0,  20.0, "g/dL"),
    "haemoglobin_female": (11.5, 15.5, 7.0,  20.0, "g/dL"),
    "haemoglobin":        (11.5, 17.0, 7.0,  20.0, "g/dL"),
    "wbc":                (4.0,  11.0, 2.0,  30.0, "×10³/µL"),
    "platelets":          (150,  400,  50,   1000, "×10³/µL"),
    "mcv":                (80,   100,  60,   120,  "fL"),
    "mch":                (27,   33,   20,   40,   "pg"),
    "mchc":               (31.5, 36,   28,   38,   "g/dL"),
    "hct":                (36,   50,   20,   60,   "%"),
    "esr_male":           (0,    15,   0,    100,  "mm/hr"),
    "esr_female":         (0,    20,   0,    100,  "mm/hr"),
    "esr":                (0,    20,   0,    100,  "mm/hr"),
    # Chemistry
    "glucose_fasting":    (70,   100,  40,   500,  "mg/dL"),
    "glucose_random":     (70,   140,  40,   500,  "mg/dL"),
    "glucose":            (70,   140,  40,   500,  "mg/dL"),
    "hba1c":              (4.0,  5.7,  0,    15,   "%"),
    "creatinine_male":    (0.74, 1.35, 0,    10,   "mg/dL"),
    "creatinine_female":  (0.59, 1.04, 0,    10,   "mg/dL"),
    "creatinine":         (0.6,  1.4,  0,    10,   "mg/dL"),
    "urea":               (7,    20,   0,    100,  "mg/dL"),
    "sodium":             (136,  145,  120,  160,  "mEq/L"),
    "potassium":          (3.5,  5.1,  2.5,  6.5,  "mEq/L"),
    "bilirubin_total":    (0.2,  1.2,  0,    15,   "mg/dL"),
    "sgpt":               (7,    56,   0,    1000, "U/L"),
    "sgot":               (10,   40,   0,    1000, "U/L"),
    "alt":                (7,    56,   0,    1000, "U/L"),
    "ast":                (10,   40,   0,    1000, "U/L"),
    "cholesterol":        (0,    200,  0,    500,  "mg/dL"),
    "triglycerides":      (0,    150,  0,    1000, "mg/dL"),
    "hdl":                (40,   60,   0,    100,  "mg/dL"),
    "ldl":                (0,    100,  0,    300,  "mg/dL"),
    "tsh":                (0.4,  4.0,  0,    100,  "mIU/L"),
    "calcium":            (8.5,  10.5, 6.0,  13.0, "mg/dL"),
    "uric_acid":          (3.5,  7.2,  0,    15,   "mg/dL"),
}

# ─────────────────────────────────────────
# CLINICAL INFERENCE RULES
#
# STRICT design — each rule:
# 1. Only fires if value is ACTUALLY extracted
# 2. Only fires if value is TRULY outside range
# 3. Produces only ONE diagnosis per condition group
#    (most severe match wins — no duplicates)
# 4. "possible" language used only when borderline
# ─────────────────────────────────────────

# Priority-ordered rules per condition group.
# Within each group, FIRST matching rule wins.
# Groups: anaemia, diabetes, kidney, liver, lipids, thyroid, electrolytes, cells
CLINICAL_INFERENCE_RULES = {

    "anaemia": [
        # Severity tiers — first match wins
        ("haemoglobin", "low",  7.0,  "Severe Anaemia"),
        ("haemoglobin", "low", 10.0,  "Moderate Anaemia"),
        ("haemoglobin", "low", 11.5,  "Mild Anaemia"),
    ],
    "anaemia_type": [
        # MCV-based type — only fires if haemoglobin is ALSO low
        ("mcv", "low",  80.0, "Microcytic Anaemia"),
        ("mcv", "high", 100.0,"Macrocytic Anaemia"),
    ],
    "diabetes": [
        ("hba1c",   "high", 6.5,  "Diabetes Mellitus"),
        ("hba1c",   "high", 5.7,  "Pre-Diabetes"),
        ("glucose",  "high", 125, "Impaired Fasting Glucose"),
    ],
    "kidney": [
        ("creatinine", "high", 2.0, "Chronic Kidney Disease"),
        ("creatinine", "high", 1.4, "Renal Impairment"),
    ],
    "liver_enzyme": [
        ("sgpt", "high", 200, "Significant Hepatitis / Liver Injury"),
        ("sgpt", "high",  56, "Elevated Liver Enzymes"),
        ("sgot", "high", 200, "Significant Hepatitis / Liver Injury"),
        ("sgot", "high",  40, "Elevated Liver Enzymes"),
    ],
    "lipids": [
        ("cholesterol", "high", 240, "Hypercholesterolaemia"),
        ("ldl",         "high", 160, "High LDL Cholesterol"),
        ("triglycerides","high", 200,"Hypertriglyceridaemia"),
    ],
    "thyroid": [
        ("tsh", "high", 10.0, "Hypothyroidism"),
        ("tsh", "high",  4.0, "Subclinical Hypothyroidism"),
        ("tsh", "low",   0.1, "Hyperthyroidism"),
        ("tsh", "low",   0.4, "Subclinical Hyperthyroidism"),
    ],
    "sodium": [
        ("sodium", "low",  125, "Severe Hyponatraemia"),
        ("sodium", "low",  136, "Hyponatraemia"),
        ("sodium", "high", 155, "Severe Hypernatraemia"),
        ("sodium", "high", 145, "Hypernatraemia"),
    ],
    "potassium": [
        ("potassium", "low",  3.0, "Hypokalaemia"),
        ("potassium", "high", 5.5, "Hyperkalaemia"),
    ],
    "wbc_count": [
        # NOTE: WBC and platelets are lab findings, NOT standalone diagnoses.
        # They go into clinical_findings, not diagnoses.
        # We only record them as supporting observations.
        ("wbc",      "high", 11.0, None),   # → clinical_findings only
        ("wbc",      "low",   4.0, None),   # → clinical_findings only
        ("platelets","low",  150,  None),   # → clinical_findings only
        ("platelets","high", 400,  None),   # → clinical_findings only
    ],
}

# Mapping of test abnormalities → clinical_findings label
# (for things that are observations, not diagnoses)
LAB_OBSERVATION_LABELS = {
    ("wbc",      "high"): "Leukocytosis (elevated WBC)",
    ("wbc",      "low"):  "Leukopenia (low WBC)",
    ("platelets","low"):  "Thrombocytopenia (low platelets)",
    ("platelets","high"): "Thrombocytosis (elevated platelets)",
    ("esr",      "high"): "Elevated ESR (raised inflammatory marker)",
    ("crp",      "high"): "Elevated CRP (raised inflammatory marker)",
    ("rdw",      "high"): "Elevated RDW (red cell size variation)",
    ("mch",      "low"):  "Low MCH (hypochromic red cells)",
    ("mchc",     "low"):  "Low MCHC (hypochromic red cells)",
}


def extract_lab_value(text, test_name):
    """
    Extract a numerical value and its unit for a given test from text.
    Returns (normalized_value, unit_string) or (None, None).
    Normalizes raw cell counts (cells/cumm) → ×10³/µL automatically.
    """
    text = text.lower()
    unit_pattern = (r"cells/cumm|/cumm|cells/mm3|/mm3|×10[³3]/µl|x10[³3]/µl"
                    r"|10[³3]/µl|×10\^3|x10\^3|g/dl|mg/dl|u/l|iu/l|meq/l"
                    r"|mmol/l|%|fl|pg|mm/hr|miu/l|ng/ml|pg/ml|µg/dl|mcg/dl")
    patterns = [
        rf"{re.escape(test_name)}\s*[:\-=]\s*(\d+\.?\d*)\s*({unit_pattern})?",
        rf"{re.escape(test_name)}\s+(\d+\.?\d*)\s*({unit_pattern})?",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                value = float(m.group(1))
                unit  = (m.group(2) or "").strip().lower()
                # Normalize raw cell counts (e.g. 7200 cells/cumm → 7.2 ×10³/µL)
                if unit in ("cells/cumm", "/cumm", "cells/mm3", "/mm3",
                            "cells/µl", "/µl", "cells/ul", "/ul"):
                    if value > 100:
                        value = round(value / 1000, 2)
                        unit  = "×10³/µl"
                return value, unit
            except (ValueError, IndexError, TypeError):
                pass
    return None, None


def _value_matches_unit(unit, test_name):
    """
    Validate that the extracted unit is compatible with the test.
    Returns True if compatible or unknown (permissive by default).
    """
    unit = (unit or "").lower().strip()
    if not unit:
        return True
    CELL_TESTS = {"wbc", "rbc", "platelets", "plt"}
    CELL_UNITS = {"×10³/µl", "10³/µl"}
    t = test_name.lower()
    if t in CELL_TESTS and unit and unit not in CELL_UNITS:
        return False
    return True


def is_lab_term(text):
    """
    Returns True if the text is a lab finding/value/test name
    rather than a clinical diagnosis.
    Whitelists known valid diagnoses that contain lab-related words.
    """
    t = text.lower().strip()

    # Whitelist — valid diagnoses even if they contain lab-sounding words
    DIAGNOSIS_WHITELIST = [
        "anaemia", "anemia", "diabetes", "hypothyroidism", "hyperthyroidism",
        "iron deficiency", "vitamin b12 deficiency", "vitamin d deficiency",
        "folate deficiency", "chronic kidney disease", "liver disease",
        "liver failure", "renal failure", "renal impairment", "hypertension",
        "hyperlipidaemia", "hyperlipidemia", "dyslipidaemia", "dyslipidemia",
        "hyperkalaemia", "hypokalaemia", "hyponatraemia", "hypernatraemia",
        "hypercalcaemia", "hypocalcaemia", "hyperglycaemia", "hypoglycaemia",
        "subclinical", "impaired fasting", "pre-diabetes",
    ]
    for wl in DIAGNOSIS_WHITELIST:
        if wl in t:
            return False

    # Morphological/microscopic terms → not diagnoses
    for term in LAB_MORPHOLOGY_TERMS:
        if term in t:
            return True

    # Pure test names (exact or starts with)
    for test in LAB_TEST_NAMES:
        if t == test or t.startswith(test + " ") or t.startswith(test + ":"):
            return True

    # Raw numerical lab values (e.g. "8.2 g/dL")
    if re.search(r"^\d+\.?\d*\s*(g/dl|mg/dl|u/l|iu/l|meq/l|%|fl|pg|mm/hr)", t):
        return True

    # Morphology notation: Aniso(+), Aniso(++), Poikilo (+)
    if re.search(r"^\w+\s*\([+]+\)$", t) or re.search(r"^\w+\([+]+\)$", t):
        return True

    return False


def infer_conditions_from_lab_text(lab_text):
    """
    Strictly rule-based condition inference.
    - Runs each condition GROUP, takes the FIRST (most severe) matching rule
    - WBC/platelet abnormalities → clinical_findings observations, NOT diagnoses
    - Returns: (diagnoses_list, observations_list)
    """
    if not lab_text:
        return [], []

    diagnoses     = []
    observations  = []
    seen_groups   = set()

    # First check if haemoglobin is low (needed for anaemia_type group)
    hb_value, _ = extract_lab_value(lab_text, "haemoglobin")
    hb_is_low = hb_value is not None and hb_value < 11.5

    for group, rules in CLINICAL_INFERENCE_RULES.items():
        if group in seen_groups:
            continue

        for test_name, direction, threshold, condition in rules:
            value, unit = extract_lab_value(lab_text, test_name)
            if value is None:
                continue
            if not _value_matches_unit(unit, test_name):
                continue

            fires = (direction == "low"  and value < threshold) or \
                    (direction == "high" and value > threshold)

            if not fires:
                continue

            # anaemia_type only fires if haemoglobin is also low
            if group == "anaemia_type" and not hb_is_low:
                continue

            # wbc_count → goes to observations, not diagnoses
            if group == "wbc_count":
                obs_key = (test_name, direction)
                label = LAB_OBSERVATION_LABELS.get(obs_key)
                if label and label not in observations:
                    observations.append(f"{label}: {value}")
                seen_groups.add(group)
                break  # first match per group

            # Normal diagnosis condition
            if condition and condition not in diagnoses:
                diagnoses.append(condition)
            seen_groups.add(group)
            break  # first (most severe) match wins per group

    # Also check other observation-type tests
    for (test_name, direction), label in LAB_OBSERVATION_LABELS.items():
        if test_name in ("wbc", "platelets"):
            continue  # already handled above
        value, unit = extract_lab_value(lab_text, test_name)
        if value is None:
            continue
        threshold = {"esr": 20, "crp": 5, "rdw": 15, "mch": 27, "mchc": 31.5}.get(test_name)
        if threshold is None:
            continue
        fires = (direction == "low"  and value < threshold) or \
                (direction == "high" and value > threshold)
        if fires and label not in observations:
            observations.append(label)

    return diagnoses, observations


def calculate_risk_from_labs(lab_text):
    """
    Determine risk level strictly from extracted lab values.
    Uses unit-aware extraction + normalization.
    """
    if not lab_text:
        return "Low"

    risk = "Low"
    risk_order = {"Low": 0, "Moderate": 1, "High": 2, "Critical": 3}

    for test_name, (low, high, crit_low, crit_high, unit) in LAB_REFERENCE_RANGES.items():
        value, extracted_unit = extract_lab_value(lab_text, test_name)
        if value is None:
            continue
        if not _value_matches_unit(extracted_unit, test_name):
            continue

        if (crit_low is not None and value <= crit_low) or \
           (crit_high is not None and value >= crit_high):
            return "Critical"
        elif value < low or value > high:
            current = risk_order.get(risk, 0)
            if current < risk_order["High"]:
                risk = "High"

    return risk


def post_process_result(result, report_type, raw_text):
    """
    Strict post-processing for all report types.

    For Lab Reports:
    - COMPLETELY REPLACES AI diagnoses with rule-based validated diagnoses
    - Limits to max 3 confirmed diagnoses
    - WBC/platelet abnormalities → clinical_findings (not diagnoses)
    - Morphology terms → clinical_findings (not diagnoses)
    - Risk level computed strictly from actual values

    For all report types:
    - Removes lab terms/values from diagnoses field
    - Limits diagnoses to 3 maximum
    """
    if not isinstance(result, dict):
        return result

    lab_text = result.get("lab_results") or ""

    # ── FOR LAB REPORTS: full replacement ────────────────────────────────
    if report_type == "Lab Report":

        # Step A: Run strictly validated inference
        inferred_diagnoses, observations = infer_conditions_from_lab_text(
            lab_text or raw_text
        )

        # Step B: Remove ALL AI-generated diagnoses and replace with
        #         only rule-validated ones — AI is not trusted for diagnosis
        #         on lab reports because it hallucinates based on text patterns
        validated_diagnoses = inferred_diagnoses[:3]  # max 3
        result["diagnoses"] = validated_diagnoses

        # Step C: Build clean, structured clinical_findings
        findings_parts = []

        # Preserve AI clinical_findings (narrative examination findings)
        existing_cf = result.get("clinical_findings") or ""
        if existing_cf:
            # Clean up raw dict/JSON-like content if AI returned it poorly
            existing_cf = re.sub(r"\{[^}]*\}", "", existing_cf).strip()
            existing_cf = re.sub(r"\[[^\]]*\]", "", existing_cf).strip()
            existing_cf = re.sub(r"'[^']*'\s*:", "", existing_cf).strip()
            if existing_cf:
                findings_parts.append(existing_cf)

        # Add rule-based lab observations in clean bullet format
        if observations:
            obs_bullets = "\n".join(f"• {o}" for o in observations)
            findings_parts.append(f"Lab Observations:\n{obs_bullets}")

        # Add morphological findings if any
        original_ai_dx = list(result.get("diagnoses") or [])
        moved = [d for d in original_ai_dx if d and is_lab_term(d)]
        if moved:
            morph_bullets = "\n".join(f"• {m}" for m in moved)
            findings_parts.append(f"Morphological Findings:\n{morph_bullets}")

        result["clinical_findings"] = "\n\n".join(
            p for p in findings_parts if p.strip()
        ).strip() or existing_cf

        # Step D: Store inferred for summary enrichment
        result["interpreted_conditions"] = inferred_diagnoses

        # Step E: Risk level — compute from actual values, overrides AI
        computed_risk = calculate_risk_from_labs(lab_text or raw_text)
        if result.get("key_highlights"):
            result["key_highlights"]["risk_level"] = computed_risk

        # Step F: Update primary_diagnosis in highlights
        kh = result.get("key_highlights") or {}
        if validated_diagnoses:
            kh["primary_diagnosis"] = validated_diagnoses[0][:50]
        elif not kh.get("primary_diagnosis") or is_lab_term(kh.get("primary_diagnosis","")):
            kh["primary_diagnosis"] = "No confirmed diagnosis"
        result["key_highlights"] = kh

        # Step G: Build clean, professional plain summary
        # Replace AI summary with a properly structured one based on validated data
        plain = result.get("plain_summary") or ""
        if validated_diagnoses:
            dx_str = " and ".join(validated_diagnoses) if len(validated_diagnoses) <= 2 \
                     else ", ".join(validated_diagnoses[:-1]) + ", and " + validated_diagnoses[-1]
            risk   = (result.get("key_highlights") or {}).get("risk_level", "")
            obs_str = ""
            if observations:
                obs_str = " Additional findings include: " + "; ".join(observations) + "."
            # Only rewrite if AI summary doesn't already mention the key diagnosis
            first_dx_word = validated_diagnoses[0].split()[0].lower()
            if first_dx_word not in plain.lower():
                result["plain_summary"] = (
                    f"Based on the laboratory results, {dx_str} "
                    f"{'has' if len(validated_diagnoses)==1 else 'have'} been identified.{obs_str} "
                    f"{'Prompt medical attention is advised.' if risk in ('High','Critical') else 'Follow-up with your doctor is recommended.'}"
                ).strip()
        elif not validated_diagnoses and plain:
            if "normal" not in plain.lower() and "within" not in plain.lower():
                result["plain_summary"] = (
                    "All measured values in this report are within normal reference ranges. "
                    "No significant abnormalities were detected. "
                    "Routine follow-up with your doctor is recommended."
                )

    # ── FOR ALL OTHER REPORT TYPES ────────────────────────────────────────
    else:
        # Clean AI diagnoses — remove lab terms and limit to 3
        raw_dx = result.get("diagnoses") or []
        moved_to_findings = []
        clean_dx = []

        for dx in raw_dx:
            if not dx:
                continue
            if is_lab_term(dx):
                moved_to_findings.append(dx)
            else:
                clean_dx.append(dx)

        # Limit to 3 most important
        result["diagnoses"] = clean_dx[:3]

        # Move incorrectly placed lab terms to clinical_findings
        if moved_to_findings:
            existing = result.get("clinical_findings") or ""
            note = "Morphological findings: " + "; ".join(moved_to_findings)
            result["clinical_findings"] = (
                f"{existing}\n{note}".strip() if existing else note
            )

        # Fix primary diagnosis if it was a lab term
        kh = result.get("key_highlights") or {}
        if kh.get("primary_diagnosis") and is_lab_term(kh["primary_diagnosis"]):
            kh["primary_diagnosis"] = (
                result["diagnoses"][0][:50] if result["diagnoses"]
                else "See clinical findings"
            )
            result["key_highlights"] = kh

    return result


def parse_ai_json(raw):
    """
    4-layer JSON parser — handles all failure modes:
    Layer 1: Direct parse
    Layer 2: Strip markdown fences then parse
    Layer 3: Regex extract first JSON object
    Layer 4: Return safe empty result (never raises)
    """
    if not raw or not raw.strip():
        print("WARNING: AI returned empty response — using fallback result")
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
    print(f"WARNING: All JSON parse attempts failed. Raw response: {raw[:200]}")
    fallback = dict(EMPTY_RESULT)
    fallback["plain_summary"] = (
        "The AI could not produce a structured response for this document. "
        "Please try again or switch to a different AI provider."
    )
    return fallback


# ─────────────────────────────────────────
# AI PROVIDERS — Analysis
# Each accepts a prompt built per report type
# ─────────────────────────────────────────
# ─────────────────────────────────────────
# AI PROVIDER — Groq only
# Free · No credit card · 30 req/min
# Get key: console.groq.com/keys
# ─────────────────────────────────────────
def call_groq(api_key, report, prompt):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                      headers=headers, json={
                          "model": "llama-3.3-70b-versatile",
                          "messages": [
                              {"role": "system", "content": prompt},
                              {"role": "user",   "content": "Analyze this medical document:\n\n" + report}
                          ],
                          "temperature": 0.1, "max_tokens": 2500
                      }, timeout=60)
    if not r.ok:
        if r.status_code == 401:
            raise RuntimeError("Invalid Groq API key. Get a free key at console.groq.com/keys")
        if r.status_code == 429:
            raise RuntimeError("Groq rate limit reached. Please wait a moment and try again.")
        err = (r.json() or {}).get("error") or {}
        raise RuntimeError(f"Groq error {r.status_code}: {err.get('message','Unknown')}")
    choices = (r.json() or {}).get("choices") or []
    if not choices:
        return dict(EMPTY_RESULT)
    raw = ((choices[0] or {}).get("message") or {}).get("content") or ""
    return parse_ai_json(raw)


def groq_chat(api_key, system_msg, user_msg, max_tokens=600):
    """Generic Groq call for translation and Q&A."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                      headers=headers, json={
                          "model": "llama-3.3-70b-versatile",
                          "messages": [
                              {"role": "system", "content": system_msg},
                              {"role": "user",   "content": user_msg}
                          ],
                          "temperature": 0.2, "max_tokens": max_tokens
                      }, timeout=45)
    if not r.ok:
        raise RuntimeError(f"Groq error {r.status_code}")
    choices = (r.json() or {}).get("choices") or []
    return ((choices[0] or {}).get("message") or {}).get("content", "").strip()


# ─────────────────────────────────────────
# LANGUAGE MAP — native names for better
# translation accuracy with all models
# ─────────────────────────────────────────
LANG_NATIVE = {
    "English":  "English",
    "Hindi":    "Hindi (हिन्दी)",
    "Marathi":  "Marathi (मराठी)",
    "Bengali":  "Bengali (বাংলা)",
    "Tamil":    "Tamil (தமிழ்)",
    "Telugu":   "Telugu (తెలుగు)",
    "Kannada":  "Kannada (ಕನ್ನಡ)",
    "Gujarati": "Gujarati (ગુજરાતી)",
    "Punjabi":  "Punjabi (ਪੰਜਾਬੀ)",
    "Malayalam":"Malayalam (മലയാളം)",
}


def _raw_translate(provider, api_key, prompt):
    """Translation via Groq — Groq is the only provider."""
    return groq_chat(api_key,
                     "You are a professional medical translator. Return ONLY the translated text.",
                     prompt, max_tokens=1500)


def translate_all_fields(provider, api_key, result, lang_name):
    """
    Translate ALL key text fields into the selected language.
    Uses a single API call with a structured block to avoid
    multiple round-trips and ensure consistent output.

    Fields translated:
      - plain_summary        → translated_summary (shown in UI card)
      - medical_history      → translated_medical_history
      - clinical_findings    → translated_clinical_findings
      - assessment_opinion   → translated_assessment_opinion
      - prognosis            → translated_prognosis
      - recommendations      → translated_recommendations
    """
    native = LANG_NATIVE.get(lang_name, lang_name)

    # Collect non-empty fields to translate
    fields = {}
    for key in ["plain_summary", "medical_history", "clinical_findings",
                "assessment_opinion", "prognosis", "recommendations"]:
        val = result.get(key, "")
        if val and str(val).strip() not in ("", "null", "None", "N/A"):
            fields[key] = str(val).strip()

    if not fields:
        return  # Nothing to translate

    # Build a single structured prompt for all fields
    blocks = "\n\n".join(
        f"[{k.upper()}]\n{v}" for k, v in fields.items()
    )

    prompt = (
        f"You are a professional medical translator.\n"
        f"Translate each labeled block below into {native}.\n"
        f"Keep the same [LABEL] headers exactly as shown.\n"
        f"Translate ONLY the text under each label. Return nothing else.\n\n"
        f"{blocks}"
    )

    try:
        raw = _raw_translate(provider, api_key, prompt)

        # Parse each translated block back
        for key in fields:
            pattern = rf"\[{key.upper()}\]\s*([\s\S]*?)(?=\n\[|\Z)"
            m = re.search(pattern, raw, re.IGNORECASE)
            translated_val = m.group(1).strip() if m else ""

            if key == "plain_summary":
                # This is the main translation shown in the UI
                result["translated_summary"] = translated_val or raw.strip()
            else:
                result[f"translated_{key}"] = translated_val

    except Exception as e:
        # Non-fatal — if translation fails, show error message in UI
        result["translated_summary"] = f"[Translation failed: {str(e)}. Please try again.]"
        print(f"Translation error: {e}")


# ─────────────────────────────────────────
# PDF GENERATION
# ─────────────────────────────────────────
def generate_pdf(data, lang_name):
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


# ─────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        api_key   = (request.form.get("api_key", "") or "").strip()
        lang_code = (request.form.get("lang_code", "en") or "en").strip()
        lang_name = (request.form.get("lang_name", "English") or "English").strip()
        # Always Groq — provider field kept for compatibility but ignored
        provider  = "groq"

        if not api_key:
            return jsonify({"success": False,
                            "error": "Groq API key is missing. Get a free key at console.groq.com/keys"}), 400

        # ── Extract report text ──────────────────
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
                    return jsonify({"success": False,
                                    "error": f"Could not read file: {str(e)}"}), 400

        if not report_text.strip():
            report_text = (request.form.get("report_text") or "").strip()

        if not report_text:
            return jsonify({"success": False, "error": "No report text provided."}), 400
        if len(report_text) < 30:
            return jsonify({"success": False,
                            "error": "Report text too short. Please provide more content."}), 400

        # ── STEP 1: Auto-detect report type ──────
        detected_type = detect_report_type(report_text)

        # ── STEP 2: Build adaptive prompt ────────
        prompt = build_prompt(detected_type)

        # ── STEP 3: AI analysis via Groq ─────────
        result = call_groq(api_key, report_text, prompt)

        # ── STEP 4: Validate + sanitize ──────────
        result["report_type"]        = detected_type
        result = sanitize_result(result)
        result["report_type"]        = detected_type
        result["translated_summary"] = ""

        # ── STEP 5: Medical post-processing ──────
        result = post_process_result(result, detected_type, report_text)

        # ── STEP 6: Translation ───────────────────
        if lang_code != "en":
            translate_all_fields(provider, api_key, result, lang_name)

        # ── STEP 7: Add unique report ID ─────────
        report_id = str(uuid.uuid4())[:8].upper()
        result["report_id"]   = report_id
        result["analyzed_at"] = datetime.now().strftime("%d %b %Y, %I:%M %p")

        # ── STEP 8: Write to Audit Log ───────────
        patient_name = (result.get("patient_info") or {}).get("name") or "Unknown"
        diagnoses    = result.get("diagnoses") or []
        risk         = (result.get("key_highlights") or {}).get("risk_level", "N/A")
        audit_entry  = {
            "id":           report_id,
            "timestamp":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "patient":      patient_name,
            "report_type":  detected_type,
            "diagnoses":    diagnoses[:3],
            "risk_level":   risk,
            "language":     lang_name,
            "file":         filename_used,
            "words_in_report": len(report_text.split()),
        }
        AUDIT_LOG.insert(0, audit_entry)
        if len(AUDIT_LOG) > MAX_AUDIT:
            AUDIT_LOG.pop()

        # Store report text for Q&A chatbot
        session["last_report"]  = report_text[:5000]
        session["last_api_key"] = api_key
        session.modified = True

        return jsonify({"success": True, "data": result,
                        "lang_name": lang_name,
                        "detected_type": detected_type,
                        "report_id": report_id})

    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 500
    except requests.exceptions.ConnectionError:
        return jsonify({"success": False,
                        "error": "No internet connection. Check your network."}), 503
    except requests.exceptions.Timeout:
        return jsonify({"success": False,
                        "error": "Request timed out. Please try again."}), 504
    except Exception as e:
        print(f"UNEXPECTED ERROR in /analyze: {type(e).__name__}: {e}")
        return jsonify({"success": False,
                        "error": f"Unexpected error ({type(e).__name__}). Please try again."}), 500


@app.route("/ask", methods=["POST"])
def ask():
    """Chatbot Q&A — answers questions about the last analyzed report."""
    try:
        body     = request.get_json(force=True)
        question = (body.get("question") or "").strip()
        api_key  = (body.get("api_key") or session.get("last_api_key") or "").strip()
        context  = session.get("last_report", "")

        if not question:
            return jsonify({"success": False, "error": "No question provided."}), 400
        if not api_key:
            return jsonify({"success": False, "error": "API key missing."}), 400
        if not context:
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
        return jsonify({"success": True, "answer": answer})

    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 500
    except Exception as e:
        return jsonify({"success": False, "error": f"Could not answer: {str(e)}"}), 500


@app.route("/audit", methods=["GET"])
def audit_log():
    """Return the audit log — last 100 analyses."""
    return jsonify({"success": True, "log": AUDIT_LOG, "total": len(AUDIT_LOG)})


@app.route("/audit/clear", methods=["POST"])
def audit_clear():
    """Clear the audit log."""
    AUDIT_LOG.clear()
    return jsonify({"success": True, "message": "Audit log cleared."})


@app.route("/download_pdf", methods=["POST"])
def download_pdf():
    try:
        body         = request.get_json(force=True)
        summary_data = body.get("summary_data", {})
        lang_name    = body.get("lang_name", "English")
        patient_name = ((summary_data.get("patient_info") or {}).get("name") or "Report")
        safe         = re.sub(r"[^\w\s-]", "", patient_name).strip().replace(" ", "_")
        filename     = f"MediRaksha_{safe}_{datetime.now().strftime('%d_%b_%Y')}.pdf"

        pdf_bytes = generate_pdf(summary_data, lang_name)
        return send_file(io.BytesIO(pdf_bytes),
                         mimetype="application/pdf",
                         as_attachment=True,
                         download_name=filename)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "MediRaksha"})


# ─────────────────────────────────────────
if __name__ == "__main__":
    print()
    print("=" * 50)
    print("  MediRaksha - AI Medical Report Summarizer")
    print("=" * 50)
    print("  Server running at: http://localhost:5000")
    print("  Open that URL in your browser")
    print("  Press Ctrl+C to stop")
    print("=" * 50)
    print()
    app.run(debug=True, host="0.0.0.0", port=5000)
