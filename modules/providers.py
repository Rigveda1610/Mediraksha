import logging

import requests

from modules.sanitizer import EMPTY_RESULT, parse_ai_json

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# AI PROVIDERS — Analysis
# Each accepts a prompt built per report type
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


def call_openai(api_key, report, prompt):
    """Call OpenAI API for medical report analysis. Model: gpt-5-mini."""
    logger.info("Sending analysis request to OpenAI")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r = requests.post("https://api.openai.com/v1/chat/completions",
                      headers=headers, json={
                          "model": "gpt-5-mini",
                          "messages": [
                              {"role": "system", "content": prompt},
                              {"role": "user",   "content": "Analyze this medical document:\n\n" + report}
                          ],
                          "temperature": 0.1,
                          "max_tokens": 2500
                      }, timeout=90)
    if not r.ok:
        logger.error("OpenAI analysis request failed with status %s", r.status_code)
        if r.status_code == 401:
            raise RuntimeError("Invalid OpenAI API key. Get a key at platform.openai.com/api-keys")
        if r.status_code == 429:
            raise RuntimeError("OpenAI rate limit reached. Please wait a moment and try again.")
        if r.status_code == 404:
            raise RuntimeError("Model gpt-5-mini not available. Check your OpenAI plan.")
        err = (r.json() or {}).get("error") or {}
        raise RuntimeError(f"OpenAI error {r.status_code}: {err.get('message', 'Unknown')}")
    choices = (r.json() or {}).get("choices") or []
    if not choices:
        logger.warning("OpenAI analysis response had no choices")
        return dict(EMPTY_RESULT)
    raw = ((choices[0] or {}).get("message") or {}).get("content") or ""
    return parse_ai_json(raw)


def openai_chat(api_key, system_msg, user_msg, max_tokens=600):
    """Generic OpenAI call for translation and Q&A. Model: gpt-5-mini."""
    logger.info("Sending OpenAI chat request")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r = requests.post("https://api.openai.com/v1/chat/completions",
                      headers=headers, json={
                          "model": "gpt-5-mini",
                          "messages": [
                              {"role": "system", "content": system_msg},
                              {"role": "user",   "content": user_msg}
                          ],
                          "temperature": 0.2,
                          "max_tokens": max_tokens
                      }, timeout=60)
    if not r.ok:
        logger.error("OpenAI chat request failed with status %s", r.status_code)
        if r.status_code == 401:
            raise RuntimeError("Invalid OpenAI API key. Get a key at platform.openai.com/api-keys")
        if r.status_code == 429:
            raise RuntimeError("OpenAI rate limit reached. Please wait a moment and try again.")
        if r.status_code == 404:
            raise RuntimeError("Model gpt-5-mini not available. Check your OpenAI plan.")
        err = (r.json() or {}).get("error") or {}
        raise RuntimeError(f"OpenAI error {r.status_code}: {err.get('message', 'Unknown')}")
    choices = (r.json() or {}).get("choices") or []
    return ((choices[0] or {}).get("message") or {}).get("content", "").strip()


def call_ai(provider, api_key, report, prompt):
    """Dispatch to the correct AI provider for analysis."""
    if provider == "openai":
        return call_openai(api_key, report, prompt)
    return call_groq(api_key, report, prompt)


def chat_ai(provider, api_key, system_msg, user_msg, max_tokens=600):
    """Dispatch to the correct AI provider for chat/translation."""
    if provider == "openai":
        return openai_chat(api_key, system_msg, user_msg, max_tokens)
    return groq_chat(api_key, system_msg, user_msg, max_tokens)
