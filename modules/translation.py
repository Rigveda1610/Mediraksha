import logging
import re

from modules.providers import groq_chat

logger = logging.getLogger(__name__)


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
        logger.warning("Translation error: %s", e)
