"""Asynchronous Multi-Provider LLM & Vision Pool.

Features:
- Async httpx client with connection pooling and timeouts.
- Per-provider concurrency caps (asyncio.Semaphore) and rate limiters.
- Retries ONLY on 429 / 5xx with exponential backoff + jitter (max 3 tries).
- Immediate failover on hard errors or exhaustion: Groq -> Gemini -> Ollama -> Deterministic Fallback.
- Non-reasoning models with compact JSON output and max_tokens=1024.
- Page 1 classification with parallel multi-page extraction.
"""

import asyncio
import base64
import json
import logging
import os
import random
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("async_provider_pool")

# Prompt and model version constants for user-scoped cache keys
PROMPT_VERSION = "v1.2"
MODEL_VERSION = "groq-20b-gemini-flash"

# Concurrency limits per provider (thread-safe across event loops)
PROVIDER_SEMAPHORES: Dict[str, threading.Semaphore] = {}


def get_semaphore(provider: str, limit: int = 3) -> threading.Semaphore:
    if provider not in PROVIDER_SEMAPHORES:
        PROVIDER_SEMAPHORES[provider] = threading.Semaphore(limit)
    return PROVIDER_SEMAPHORES[provider]


class ThreadRateLimiter:
    """Thread-safe token bucket rate limiter for external providers."""

    def __init__(self, calls_per_second: float):
        self.calls_per_second = calls_per_second
        self.interval = 1.0 / calls_per_second if calls_per_second > 0 else 0
        self.last_call = 0.0
        self._lock = threading.Lock()

    def wait(self):
        if self.calls_per_second <= 0:
            return
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_call
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            self.last_call = time.monotonic()


RATE_LIMITERS = {
    "groq": ThreadRateLimiter(calls_per_second=5.0),
    "gemini": ThreadRateLimiter(calls_per_second=2.0),
    "ollama": ThreadRateLimiter(calls_per_second=10.0),
}


def build_system_prompt(corrections: Optional[List[Dict[str, str]]] = None) -> str:
    few_shot = ""
    if corrections:
        few_shot = "\nLEARNED CORRECTIONS:\n"
        for c in corrections[:8]:  # Inject at most 5-10 learned corrections per doc type
            few_shot += f"- Doc '{c.get('doc_type')}', label '{c.get('label')}': original '{c.get('original_value')}', correct '{c.get('corrected_value')}'.\n"

    return (
        "Extract visible details from this document exactly as written.\n"
        "RULES:\n"
        "- ZERO DEFAULTS: Only extract fields physically present. Never invent or assume fields.\n"
        "- EXACT VALUES: Preserve exact casing, punctuation, commas, suffixes ('MD', 'PhD', 'Jr.').\n"
        "- Return ONLY valid compact JSON with no markdown wrapping or reasoning commentary:\n"
        '{"doc_type":"string","title":"string","fields":[{"label":"string","value":"string","confidence":0.95}]}'
        + few_shot
    )


async def call_groq_text_async(
    client: httpx.AsyncClient,
    raw_text: str,
    system_prompt: str,
    on_retry: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Groq LPU text extraction with non-reasoning compact model."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "openai/gpt-oss-20b",
        "messages": [
            {"role": "user", "content": f"{system_prompt}\n\nDOCUMENT:\n{raw_text[:4000]}"}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
        "max_tokens": 1024,
    }

    sem = get_semaphore("groq", limit=3)
    limiter = RATE_LIMITERS["groq"]

    for attempt in range(3):
        try:
            limiter.wait()
            with sem:
                resp = await client.post(url, headers=headers, json=payload, timeout=8.0)

            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt < 2:
                    if on_retry:
                        on_retry("retrying", f"Groq {resp.status_code}, backing off")
                    delay = (0.5 * (2 ** attempt)) + random.uniform(0.05, 0.25)
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.warning(f"Groq text exhausted 3 retries (status {resp.status_code}); failing over.")
                    return None

            if resp.status_code != 200:
                logger.warning(f"Groq text returned {resp.status_code}; failing over immediately.")
                return None

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict) and parsed.get("fields"):
                    return parsed
            return None
        except Exception:
            # On network error or connection failure, fail over immediately to next provider
            return None
    return None


async def call_gemini_text_async(
    client: httpx.AsyncClient,
    raw_text: str,
    system_prompt: str,
    on_retry: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Gemini text extraction with non-reasoning compact model."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    model = "gemini-flash-latest"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": f"{system_prompt}\n\nDOCUMENT:\n{raw_text[:4000]}"}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.0,
            "maxOutputTokens": 1024,
        },
    }

    sem = get_semaphore("gemini", limit=2)
    limiter = RATE_LIMITERS["gemini"]

    for attempt in range(3):
        try:
            limiter.wait()
            with sem:
                resp = await client.post(url, json=payload, timeout=8.0)

            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt < 2:
                    if on_retry:
                        on_retry("retrying", f"Gemini {resp.status_code}, backing off")
                    delay = (0.6 * (2 ** attempt)) + random.uniform(0.1, 0.3)
                    await asyncio.sleep(delay)
                    continue
                else:
                    return None

            if resp.status_code != 200:
                return None

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return None
            content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict) and parsed.get("fields"):
                    return parsed
            return None
        except Exception:
            return None
    return None


async def call_ollama_text_async(
    client: httpx.AsyncClient,
    raw_text: str,
    system_prompt: str,
) -> Optional[Dict[str, Any]]:
    """Local Ollama text extraction."""
    url = "http://127.0.0.1:11434/api/generate"
    payload = {
        "model": "qwen2.5-coder:7b",
        "prompt": f"{system_prompt}\n\nDOCUMENT:\n{raw_text[:4000]}",
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0, "num_predict": 1024},
    }

    sem = get_semaphore("ollama", limit=2)
    try:
        with sem:
            resp = await client.post(url, json=payload, timeout=6.0)
        if resp.status_code == 200:
            content = resp.json().get("response", "")
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict) and parsed.get("fields"):
                    return parsed
    except Exception:
        pass
    return None


def deterministic_text_fallback(raw_text: str) -> Dict[str, Any]:
    """Safe deterministic fallback parser that never fails."""
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    doc_type = "Document"
    title = lines[0] if lines else "Document"

    first_block = " ".join(lines[:6]).lower()
    if any(k in first_block for k in ["invoice", "factura", "facture", "rechnung"]):
        doc_type = "Invoice"
    elif any(k in first_block for k in ["contract", "agreement", "accord", "vertrag"]):
        doc_type = "Contract"
    elif any(k in first_block for k in ["memorandum", "memo"]):
        doc_type = "Memorandum"
    elif any(k in first_block for k in ["medical", "patient", "clinic", "diagnosis"]):
        doc_type = "Medical Report"
    elif any(k in first_block for k in ["report", "rapport", "expense"]):
        doc_type = "Report"
    elif any(k in first_block for k in ["terms", "conditions"]):
        doc_type = "Terms and Conditions"

    fields = []
    seen = set()
    for line in lines[:30]:
        if ":" in line:
            parts = line.split(":", 1)
            k, v = parts[0].strip(), parts[1].strip()
            if k and v and k not in seen and len(k) <= 40:
                fields.append({"label": k, "value": v, "confidence": 0.90})
                seen.add(k)
        elif any(c in line for c in ["$", "€", "£", "₹"]) and "Total" not in seen:
            fields.append({"label": "Amount", "value": line, "confidence": 0.85})
            seen.add("Total")

    if not fields and lines:
        fields.append({"label": "Title", "value": lines[0][:80], "confidence": 0.85})
        if len(lines) > 1:
            fields.append({"label": "Summary", "value": lines[1][:120], "confidence": 0.80})

    return {"doc_type": doc_type, "title": title, "fields": fields}


async def call_groq_vision_async(
    client: httpx.AsyncClient,
    img_b64: str,
    system_prompt: str,
    on_retry: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Groq Vision async call with concurrency cap and exponential retry."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "qwen/qwen3.8-27b",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": system_prompt + "\nPlease extract visible fields as JSON."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                ],
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
        "max_tokens": 1024,
    }

    sem = get_semaphore("groq_vision", limit=2)
    limiter = RATE_LIMITERS["groq"]

    for attempt in range(3):
        try:
            limiter.wait()
            with sem:
                resp = await client.post(url, headers=headers, json=payload, timeout=12.0)

            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt < 2:
                    if on_retry:
                        on_retry("retrying", f"Groq Vision {resp.status_code}, retrying")
                    delay = (0.5 * (2 ** attempt)) + random.uniform(0.05, 0.25)
                    await asyncio.sleep(delay)
                    continue
                else:
                    return None

            if resp.status_code != 200:
                return None

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict) and parsed.get("fields"):
                    return parsed
            return None
        except Exception:
            return None
    return None


async def call_gemini_vision_async(
    client: httpx.AsyncClient,
    img_b64: str,
    system_prompt: str,
    on_retry: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Gemini Vision async call with concurrency cap and exponential retry."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    model = "gemini-flash-latest"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": system_prompt + "\nPlease extract visible fields as JSON."},
                    {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
                ]
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.0,
            "maxOutputTokens": 1024,
        },
    }

    sem = get_semaphore("gemini_vision", limit=2)
    limiter = RATE_LIMITERS["gemini"]

    for attempt in range(3):
        try:
            limiter.wait()
            with sem:
                resp = await client.post(url, json=payload, timeout=12.0)

            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt < 2:
                    if on_retry:
                        on_retry("retrying", f"Gemini Vision {resp.status_code}, retrying")
                    delay = (0.6 * (2 ** attempt)) + random.uniform(0.1, 0.3)
                    await asyncio.sleep(delay)
                    continue
                else:
                    return None

            if resp.status_code != 200:
                return None

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return None
            content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict) and parsed.get("fields"):
                    return parsed
            return None
        except Exception:
            return None
    return None


async def call_ollama_vision_async(
    client: httpx.AsyncClient,
    img_b64: str,
    system_prompt: str,
) -> Optional[Dict[str, Any]]:
    """Local Ollama vision async call."""
    url = "http://localhost:11434/v1/chat/completions"
    payload = {
        "model": "moondream",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": system_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                ],
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
        "max_tokens": 1024,
    }

    sem = get_semaphore("ollama_vision", limit=1)
    try:
        with sem:
            resp = await client.post(url, json=payload, timeout=15.0)
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict) and parsed.get("fields"):
                    return parsed
    except Exception:
        pass
    return None


async def extract_text_async(
    raw_text: str,
    corrections: Optional[List[Dict[str, str]]] = None,
    on_retry: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute text extraction pipeline through async provider pool."""
    prompt = build_system_prompt(corrections)
    async with httpx.AsyncClient() as client:
        # 1. Groq
        res = await call_groq_text_async(client, raw_text, prompt, on_retry=on_retry)
        if res:
            return res
        # 2. Gemini
        res = await call_gemini_text_async(client, raw_text, prompt, on_retry=on_retry)
        if res:
            return res
        # 3. Ollama
        res = await call_ollama_text_async(client, raw_text, prompt)
        if res:
            return res

    # 4. Safe Deterministic Fallback
    return deterministic_text_fallback(raw_text)


async def extract_vision_async(
    img_b64: str,
    corrections: Optional[List[Dict[str, str]]] = None,
    on_retry: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute vision extraction pipeline through async provider pool."""
    prompt = build_system_prompt(corrections)
    async with httpx.AsyncClient() as client:
        # 1. Groq Vision
        res = await call_groq_vision_async(client, img_b64, prompt, on_retry=on_retry)
        if res:
            return res
        # 2. Gemini Vision
        res = await call_gemini_vision_async(client, img_b64, prompt, on_retry=on_retry)
        if res:
            return res
        # 3. Ollama Vision
        res = await call_ollama_vision_async(client, img_b64, prompt)
        if res:
            return res

    # Graceful return with check flag
    return {
        "doc_type": "Document",
        "title": "Document",
        "fields": [
            {"label": "Note", "value": "Rate limit reached during scan. Click to edit details manually.", "confidence": 0.50}
        ],
    }


def classify_from_page1(first_page_text: str) -> Tuple[str, bool]:
    """Classify doc type from Page 1.
    
    Returns (doc_type, needs_multi_page).
    Only multi-page document types (Contracts, Reports, Medical records) extract subsequent pages.
    """
    text_lower = first_page_text[:1500].lower()
    if any(k in text_lower for k in ["contract", "agreement", "lease", "accord", "vertrag"]):
        return "Contract", True
    elif any(k in text_lower for k in ["medical", "patient", "clinical", "lab report", "diagnosis", "health"]):
        return "Medical Report", True
    elif any(k in text_lower for k in ["financial statement", "balance sheet", "annual report", "bank statement", "expense report"]):
        return "Report", True
    elif any(k in text_lower for k in ["invoice", "factura", "facture", "rechnung", "bill"]):
        return "Invoice", False
    elif any(k in text_lower for k in ["receipt", "recibo", "quittung"]):
        return "Receipt", False
    elif any(k in text_lower for k in ["memorandum", "memo"]):
        return "Memorandum", False
    elif any(k in text_lower for k in ["terms", "conditions"]):
        return "Terms and Conditions", True
    return "Document", False


async def extract_multipage_text_async(
    pages_text: List[str],
    corrections: Optional[List[Dict[str, str]]] = None,
    on_retry: Optional[Any] = None,
) -> Dict[str, Any]:
    """Classify from page 1, determine if further pages are needed, and extract in parallel."""
    if not pages_text:
        return {"doc_type": "Document", "title": "Document", "fields": []}

    doc_type, needs_multi = classify_from_page1(pages_text[0])
    
    # If single page is enough or document has only 1 page, extract page 1 only
    if not needs_multi or len(pages_text) == 1:
        res = await extract_text_async(pages_text[0], corrections=corrections, on_retry=on_retry)
        if not res.get("doc_type") or res.get("doc_type") == "Document":
            res["doc_type"] = doc_type
        return res

    # Multi-page needed: extract pages 1..min(len, 3) in parallel
    needed_pages = pages_text[:3]
    tasks = [extract_text_async(p_text, corrections=corrections, on_retry=on_retry) for p_text in needed_pages]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    combined_fields = []
    seen_labels = set()
    title = ""

    for i, r in enumerate(results):
        if isinstance(r, dict):
            if not title and r.get("title"):
                title = r.get("title")
            for f in r.get("fields", []):
                lbl = f.get("label", "").strip()
                if lbl and lbl not in seen_labels:
                    seen_labels.add(lbl)
                    combined_fields.append(f)

    return {
        "doc_type": doc_type,
        "title": title or "Document",
        "fields": combined_fields,
    }

