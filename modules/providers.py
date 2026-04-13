import logging

import requests

from modules.sanitizer import EMPTY_RESULT, parse_ai_json

logger = logging.getLogger(__name__)


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
    logger.info("Sending analysis request to Groq")
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
        logger.error("Groq analysis request failed with status %s", r.status_code)
        if r.status_code == 401:
            raise RuntimeError("Invalid Groq API key. Get a free key at console.groq.com/keys")
        if r.status_code == 429:
            raise RuntimeError("Groq rate limit reached. Please wait a moment and try again.")
        err = (r.json() or {}).get("error") or {}
        raise RuntimeError(f"Groq error {r.status_code}: {err.get('message','Unknown')}")
    choices = (r.json() or {}).get("choices") or []
    if not choices:
        logger.warning("Groq analysis response had no choices")
        return dict(EMPTY_RESULT)
    raw = ((choices[0] or {}).get("message") or {}).get("content") or ""
    return parse_ai_json(raw)


def groq_chat(api_key, system_msg, user_msg, max_tokens=600):
    """Generic Groq call for translation and Q&A."""
    logger.info("Sending Groq chat request")
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
        logger.error("Groq chat request failed with status %s", r.status_code)
        raise RuntimeError(f"Groq error {r.status_code}")
    choices = (r.json() or {}).get("choices") or []
    return ((choices[0] or {}).get("message") or {}).get("content", "").strip()
