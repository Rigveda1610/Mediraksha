import logging
import re

logger = logging.getLogger(__name__)


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
    logger.info("Post-processing result for report type %s", report_type)
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
