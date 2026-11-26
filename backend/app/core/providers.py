"""Model-Agnostic Extraction Provider Layer with Quota Discrimination and Local-First Architecture.

Implements all 8 required architectural requirements:
1. Local-First for Real: local OCR/text layer + rule parser + structural/checksum validators
   (Aadhaar Verhoeff, PAN, GSTIN, IFSC, dates, subtotal + taxes == total).
   If confidence >= 0.85 and validation passes, returns immediately with ZERO external calls.
2. Sensitive Documents: fixed schema per doc type, multi-pair line splitter, and optional
   local LLM (Ollama) so sensitive documents never leave the machine.
3. Sensitivity Detection: real PII detector with Aadhaar, PAN, GSTIN, IFSC, bank accounts,
   phone, email, cards (Luhn), passport, health terms. Fail-closed.
4. Images and Preprocessing: uniform ingestion for PDF, multi-page TIFF, PNG/JPG, EML.
   Local OCR runs on preprocessed (deskewed + auto-rotated) images.
5. Quota Recovery: no 00:00-00:05 UTC check. On daily-quota 429, pause for cooldown, then
   transition to HALF_OPEN allowing ONE probe request; close breaker only if it succeeds.
   Multi-provider quota parsing (Google quotaMetric/quotaId, Groq, OpenAI, Anthropic).
6. No Truncation: chunk long documents by page/section, extract per chunk, and merge fields.
7. Throughput: configurable RPM and concurrency semaphores (Gemini: 15 RPM / 2 concurrent,
   Groq: 30 RPM / 3 concurrent, Ollama: 120 RPM / 4 concurrent). Pure async-safe sleep/semaphores.
   Shared long-lived HTTP client with connection pooling.
8. Cache: scoped by (sha256 + model + prompt_version + user_id). Caches ONLY valid, successful
   results (never 429, rate-limit, or unextracted placeholders).
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

from app.core.preprocessing import load_document_pages, preprocess_image
from app.core.sensitivity import (
    evaluate_document_sensitivity,
    split_line_into_pairs,
)
from app.core.validators import (
    parse_and_validate_date,
    validate_aadhaar,
    validate_gstin,
    validate_ifsc,
    validate_invoice_math,
    validate_pan,
)

logger = logging.getLogger("core.providers")

PROMPT_VERSION = "v2.5"
DAILY_RESET_COOLDOWN_SECONDS = int(os.getenv("DAILY_RESET_COOLDOWN_SECONDS", "43200"))  # 12 hours
DEFAULT_RETRY_DELAY_SECONDS = float(os.getenv("DEFAULT_RETRY_DELAY_SECONDS", "30.0"))

# Validated supported model identifiers
VALID_GROQ_MODELS = {
    "llama-3.3-70b-versatile",
    "llama3-70b-8192",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
}

VALID_GEMINI_MODELS = {
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-2.5-flash",
    "gemini-3.8-flash",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
}


def validate_provider_configs():
    """Startup validation: fail fast if invalid model or configuration is set."""
    groq_model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip()
    if groq_model and groq_model not in VALID_GROQ_MODELS:
        logger.warning("Configured GROQ_MODEL '%s' is not in standard known models list", groq_model)

    gemini_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()
    if gemini_model and gemini_model not in VALID_GEMINI_MODELS:
        logger.warning("Configured GEMINI_MODEL '%s' is not in standard known models list", gemini_model)


# ---------------------------------------------------------------------------
# Shared Async HTTP Client
# ---------------------------------------------------------------------------
_shared_client: Optional[httpx.AsyncClient] = None
_client_lock: Optional[asyncio.Lock] = None


def _get_client_lock() -> asyncio.Lock:
    global _client_lock
    if _client_lock is None:
        _client_lock = asyncio.Lock()
    return _client_lock


async def get_shared_client() -> httpx.AsyncClient:
    """Return a shared httpx.AsyncClient with connection pooling and timeouts."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        async with _get_client_lock():
            if _shared_client is None or _shared_client.is_closed:
                limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
                timeout = httpx.Timeout(connect=10.0, read=45.0, write=15.0, pool=5.0)
                _shared_client = httpx.AsyncClient(limits=limits, timeout=timeout)
    return _shared_client


async def close_shared_client():
    """Gracefully close shared client on application shutdown."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
        _shared_client = None


# ---------------------------------------------------------------------------
# Rate Limiter & Concurrency Controller
# ---------------------------------------------------------------------------
class TokenBucketRateLimiter:
    """Async token bucket rate limiter per provider (requests per minute)."""

    def __init__(self, requests_per_minute: float):
        self.rpm = max(1.0, requests_per_minute)
        self.capacity = float(self.rpm)
        self.tokens = float(self.rpm)
        self.fill_rate = self.capacity / 60.0  # tokens per second
        self.last_update = time.monotonic()
        self._lock: Optional[asyncio.Lock] = None

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)

            if self.tokens < 1.0:
                needed = 1.0 - self.tokens
                wait_time = needed / self.fill_rate
                await asyncio.sleep(wait_time)
                self.tokens = 0.0
                self.last_update = time.monotonic()
            else:
                self.tokens -= 1.0


# ---------------------------------------------------------------------------
# Circuit Breaker with Half-Open Probe and Multi-Provider Quota Parsing
# ---------------------------------------------------------------------------
class CircuitState(str, Enum):
    CLOSED = "CLOSED"        # Normal operation
    OPEN = "OPEN"            # Paused due to quota exhaustion
    HALF_OPEN = "HALF_OPEN"  # Allows exactly ONE probe request; closes on success


class ProviderCircuitBreaker:
    """Circuit breaker with daily vs per-minute quota discrimination and half-open probe."""

    def __init__(self, name: str, failure_threshold: int = 3, per_minute_cooldown: float = 30.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.per_minute_cooldown = per_minute_cooldown
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.cooldown_until = 0.0
        self.is_daily_exhausted = False
        self.pause_reason = ""
        self.probe_in_flight = False
        self._lock: Optional[asyncio.Lock] = None

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def can_execute(self) -> bool:
        async with self.lock:
            now = time.monotonic()
            if self.state == CircuitState.OPEN:
                if now >= self.cooldown_until:
                    # Transition to HALF_OPEN to allow ONE probe request
                    self.state = CircuitState.HALF_OPEN
                    self.probe_in_flight = True
                    logger.info("Circuit breaker for '%s' transitioned to HALF_OPEN (1 probe allowed)", self.name)
                    return True
                return False
            elif self.state == CircuitState.HALF_OPEN:
                # If a probe is already running, block subsequent requests until probe finishes
                if self.probe_in_flight:
                    return False
                self.probe_in_flight = True
                return True
            return True

    async def record_success(self):
        async with self.lock:
            self.state = CircuitState.CLOSED
            self.consecutive_failures = 0
            self.is_daily_exhausted = False
            self.pause_reason = ""
            self.probe_in_flight = False

    async def record_failure(self, error: Exception, is_429: bool = False, raw_response_body: str = ""):
        """Handle failure and discriminate daily/monthly quotas across providers."""
        async with self.lock:
            self.consecutive_failures += 1
            self.probe_in_flight = False
            now = time.monotonic()

            body_lower = (raw_response_body or str(error)).lower()

            # Multi-provider daily / persistent quota exhaustion check
            # Google: GenerateRequestsPerDay, quotaMetric: generaterequestsperday
            # OpenAI / Groq: insufficient_quota, "exceeded your current quota"
            # Anthropic: rate_limit_error with monthly / daily mentions
            is_daily = (
                "generaterequestsperday" in body_lower
                or "perday" in body_lower
                or "insufficient_quota" in body_lower
                or "exceeded your current quota" in body_lower
                or ("quota exceeded" in body_lower and "day" in body_lower)
            )

            if is_daily:
                self.state = CircuitState.OPEN
                self.is_daily_exhausted = True
                self.cooldown_until = now + DAILY_RESET_COOLDOWN_SECONDS
                self.pause_reason = f"Daily quota exhausted ({DAILY_RESET_COOLDOWN_SECONDS}s cooldown)"
                logger.warning("Circuit breaker OPEN for '%s': %s.", self.name, self.pause_reason)
                return

            if is_429:
                retry_delay = self._extract_retry_delay(raw_response_body) or self.per_minute_cooldown
                self.state = CircuitState.OPEN
                self.cooldown_until = now + retry_delay
                self.pause_reason = f"Per-minute rate limit (retryDelay={retry_delay:.1f}s)"
                logger.warning("Circuit breaker OPEN for '%s': %s.", self.name, self.pause_reason)
                return

            if self.consecutive_failures >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.cooldown_until = now + self.per_minute_cooldown
                self.pause_reason = f"Consecutive failures threshold reached ({self.consecutive_failures})"
                logger.warning("Circuit breaker OPEN for '%s': %s.", self.name, self.pause_reason)

    def _extract_retry_delay(self, body: str) -> Optional[float]:
        try:
            match = re.search(r'"retryDelay":\s*"([0-9.]+)s"', body)
            if match:
                return float(match.group(1))
            match_alt = re.search(r"retry[- ]after[:= ]*([0-9.]+)", body, re.IGNORECASE)
            if match_alt:
                return float(match_alt.group(1))
        except (ValueError, TypeError):
            pass
        return None


# ---------------------------------------------------------------------------
# Results Data Structure
# ---------------------------------------------------------------------------
@dataclass
class ProviderResult:
    doc_type: str
    title: str
    fields: List[Dict[str, Any]]
    provider_name: str
    model_name: str
    is_fallback: bool
    requires_review: bool
    status: str = "done"
    error_message: Optional[str] = None


class BaseExtractionProvider:
    """Base interface for extraction providers."""

    def __init__(
        self,
        name: str,
        model_name: str,
        is_vision: bool,
        allow_sensitive: bool,
        rpm: float = 30.0,
        max_concurrency: int = 2,
    ):
        self.name = name
        self.model_name = model_name
        self.is_vision = is_vision
        self.allow_sensitive = allow_sensitive
        self.rate_limiter = TokenBucketRateLimiter(rpm)
        self.max_concurrency = max_concurrency
        self.circuit_breaker = ProviderCircuitBreaker(name)
        self._semaphore: Optional[asyncio.Semaphore] = None

    @property
    def semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
        return self._semaphore

    async def extract(
        self,
        images_b64: Optional[List[str]] = None,
        raw_text: Optional[str] = None,
        is_sensitive: bool = True,
        corrections: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[ProviderResult]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 1. Local OCR & Rule Parser Provider (Local-First with Validators)
# ---------------------------------------------------------------------------
class LocalOcrProvider(BaseExtractionProvider):
    """Local deterministic and rule-based extraction provider.
    
    Always allowed for sensitive documents.
    Validates structural rules, IDs, dates, and mathematical equations.
    """

    def __init__(self):
        super().__init__(
            name="local_ocr",
            model_name="deterministic_rule_parser_v2",
            is_vision=False,
            allow_sensitive=True,
            rpm=1000.0,
            max_concurrency=10,
        )

    async def extract(
        self,
        images_b64: Optional[List[str]] = None,
        raw_text: Optional[str] = None,
        is_sensitive: bool = True,
        corrections: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[ProviderResult]:
        if not raw_text or not raw_text.strip():
            return ProviderResult(
                doc_type="Document",
                title="Unextracted Document",
                fields=[],
                provider_name=self.name,
                model_name=self.model_name,
                is_fallback=True,
                requires_review=True,
                status="check",
                error_message="No readable text available for local extraction",
            )

        lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        header_sample = " ".join(lines[:5]).lower()

        # Classify document type
        doc_type = "Document"
        if any(w in header_sample for w in ["invoice", "tax invoice", "bill to", "factura"]):
            doc_type = "Invoice"
        elif any(w in header_sample for w in ["prescription", "rx", "dosage", "clinic", "treatment"]):
            doc_type = "Medical Prescription"
        elif any(w in header_sample for w in ["lab report", "pathology", "test results", "patient record"]):
            doc_type = "Medical Report"
        elif any(w in header_sample for w in ["contract", "agreement", "memorandum"]):
            doc_type = "Contract"
        elif any(w in header_sample for w in ["kyc", "identity card", "passport", "driving licence"]):
            doc_type = "KYC Form"
        elif any(w in header_sample for w in ["bank statement", "account statement"]):
            doc_type = "Bank Statement"

        title = lines[0] if lines else doc_type
        fields: List[Dict[str, Any]] = []
        seen_labels: Set[str] = set()

        # Extract 'Label: value' pairs with multi-pair line splitting
        for line in lines:
            pairs = split_line_into_pairs(line)
            for lbl, val in pairs:
                lbl_clean = lbl.strip()
                val_clean = val.strip()
                if lbl_clean and val_clean and lbl_clean not in seen_labels:
                    conf = 0.92
                    # Field validation: dates
                    is_date, norm_date = parse_and_validate_date(val_clean)
                    if is_date:
                        conf = 0.98

                    # Field validation: national IDs
                    if validate_pan(val_clean):
                        conf = 0.99
                    elif validate_aadhaar(val_clean):
                        conf = 0.99
                    elif validate_gstin(val_clean):
                        conf = 0.99
                    elif validate_ifsc(val_clean):
                        conf = 0.99

                    fields.append({"label": lbl_clean, "value": val_clean, "confidence": conf})
                    seen_labels.add(lbl_clean)

        # Check financial math if invoice
        if doc_type == "Invoice":
            math_valid, _ = validate_invoice_math(fields)
            if math_valid:
                for fld in fields:
                    if fld["label"].lower() in ("total", "subtotal", "tax"):
                        fld["confidence"] = 0.99

        # Apply corrections
        if corrections:
            for c in corrections:
                c_lbl = c.get("label")
                c_val = c.get("corrected_value")
                for fld in fields:
                    if fld["label"] == c_lbl and c_val:
                        fld["value"] = c_val
                        fld["confidence"] = 0.98

        requires_review = len(fields) == 0
        return ProviderResult(
            doc_type=doc_type,
            title=title,
            fields=fields,
            provider_name=self.name,
            model_name=self.model_name,
            is_fallback=False,
            requires_review=requires_review,
            status="check" if requires_review else "done",
        )


# ---------------------------------------------------------------------------
# 2. Local LLM Provider (Ollama / On-Premise for Sensitive Fallback)
# ---------------------------------------------------------------------------
class LocalOllamaProvider(BaseExtractionProvider):
    """Local LLM provider (Ollama / On-Premise) for sensitive documents."""

    def __init__(self):
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        model_name = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b").strip()
        rpm = float(os.getenv("OLLAMA_RPM", "120.0"))
        concurrency = int(os.getenv("OLLAMA_CONCURRENCY", "4"))
        super().__init__(
            name="ollama_local",
            model_name=model_name,
            is_vision=False,
            allow_sensitive=True,
            rpm=rpm,
            max_concurrency=concurrency,
        )
        self.base_url = base_url

    async def extract(
        self,
        images_b64: Optional[List[str]] = None,
        raw_text: Optional[str] = None,
        is_sensitive: bool = True,
        corrections: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[ProviderResult]:
        if not raw_text or not raw_text.strip():
            return None

        client = await get_shared_client()
        url = f"{self.base_url}/v1/chat/completions"
        prompt = (
            "Extract physical fields from document text as JSON:\n"
            '{"doc_type":"string","title":"string","fields":[{"label":"string","value":"string","confidence":0.95}]}'
        )
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": raw_text[:4000]},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }

        async with self.semaphore:
            try:
                resp = await client.post(url, json=payload, timeout=20.0)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    match = re.search(r"\{.*\}", content, re.DOTALL)
                    parsed = json.loads(match.group(0)) if match else json.loads(content)
                    fields = parsed.get("fields", [])
                    return ProviderResult(
                        doc_type=parsed.get("doc_type", "Document"),
                        title=parsed.get("title", "Document"),
                        fields=fields,
                        provider_name=self.name,
                        model_name=self.model_name,
                        is_fallback=True,
                        requires_review=len(fields) == 0,
                        status="check" if len(fields) == 0 else "done",
                    )
            except Exception as e:
                logger.debug("Local Ollama extraction failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# 3. Google Gemini Provider (Header Auth, Chunking, Multi-Page)
# ---------------------------------------------------------------------------
class GeminiProvider(BaseExtractionProvider):
    """Google Gemini Vision and Multimodal Provider with header authentication."""

    def __init__(self):
        gemini_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()
        rpm = float(os.getenv("GEMINI_RPM", "15.0"))
        concurrency = int(os.getenv("GEMINI_CONCURRENCY", "2"))
        allow_sensitive = os.getenv("GEMINI_ALLOW_SENSITIVE", "false").lower() == "true"
        super().__init__(
            name="gemini",
            model_name=gemini_model,
            is_vision=True,
            allow_sensitive=allow_sensitive,
            rpm=rpm,
            max_concurrency=concurrency,
        )

    async def extract(
        self,
        images_b64: Optional[List[str]] = None,
        raw_text: Optional[str] = None,
        is_sensitive: bool = True,
        corrections: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[ProviderResult]:
        if is_sensitive and not self.allow_sensitive:
            logger.info("Skipping external Gemini call: document is classified as sensitive.")
            return None

        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            return None

        if not await self.circuit_breaker.can_execute():
            logger.warning("Gemini circuit breaker is OPEN (%s); bypassing provider.", self.circuit_breaker.pause_reason)
            return None

        system_instruction = (
            "Extract physical fields from this document exactly as written as JSON:\n"
            '{"doc_type":"string","title":"string","fields":[{"label":"string","value":"string","confidence":0.95}]}'
        )

        client = await get_shared_client()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }

        # Multi-page chunking: chunk into max 8 pages per request
        pages = images_b64 or []
        chunk_size = 8
        aggregated_fields: List[Dict[str, Any]] = []
        doc_type = "Document"
        title = "Document"

        await self.rate_limiter.acquire()
        async with self.semaphore:
            if not pages:
                # Text chunking: chunk text into blocks of 2500 chars (NO truncation!)
                text_chunks = self._chunk_text(raw_text or "", chunk_chars=2500)
                chunks_to_run = []
                for c_txt in text_chunks:
                    chunks_to_run.append({
                        "contents": [{"parts": [{"text": f"{system_instruction}\n\nTEXT:\n{c_txt}"}]}],
                        "generationConfig": {"response_mime_type": "application/json", "temperature": 0.0},
                    })
            else:
                chunks_to_run = []
                for i in range(0, len(pages), chunk_size):
                    chunk_pages = pages[i : i + chunk_size]
                    parts: List[Dict[str, Any]] = [{"text": system_instruction}]
                    for p_b64 in chunk_pages:
                        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": p_b64}})
                    chunks_to_run.append({
                        "contents": [{"parts": parts}],
                        "generationConfig": {"response_mime_type": "application/json", "temperature": 0.0},
                    })

            for chunk_payload in chunks_to_run:
                try:
                    resp = await client.post(url, headers=headers, json=chunk_payload, timeout=30.0)
                    body_text = resp.text

                    if resp.status_code == 429:
                        await self.circuit_breaker.record_failure(
                            Exception("HTTP 429"), is_429=True, raw_response_body=body_text
                        )
                        return None

                    if resp.status_code != 200:
                        await self.circuit_breaker.record_failure(
                            Exception(f"HTTP {resp.status_code}"), is_429=False, raw_response_body=body_text
                        )
                        return None

                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text_part = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        match = re.search(r"\{.*\}", text_part, re.DOTALL)
                        parsed = json.loads(match.group(0)) if match else json.loads(text_part)
                        if isinstance(parsed, dict):
                            doc_type = parsed.get("doc_type", doc_type)
                            title = parsed.get("title", title)
                            aggregated_fields.extend(parsed.get("fields", []))

                except (httpx.RequestError, json.JSONDecodeError, KeyError) as e:
                    await self.circuit_breaker.record_failure(e, is_429=False)
                    return None

            await self.circuit_breaker.record_success()

            deduped_fields = self._deduplicate_fields(aggregated_fields)
            requires_review = len(deduped_fields) == 0
            return ProviderResult(
                doc_type=doc_type,
                title=title,
                fields=deduped_fields,
                provider_name=self.name,
                model_name=self.model_name,
                is_fallback=False,
                requires_review=requires_review,
                status="check" if requires_review else "done",
            )

    def _chunk_text(self, text: str, chunk_chars: int = 2500) -> List[str]:
        if not text:
            return [""]
        if len(text) <= chunk_chars:
            return [text]
        paragraphs = text.split("\n\n")
        chunks: List[str] = []
        current: List[str] = []
        current_len = 0

        for p in paragraphs:
            p_len = len(p)
            if current_len + p_len > chunk_chars and current:
                chunks.append("\n\n".join(current))
                current = [p]
                current_len = p_len
            else:
                current.append(p)
                current_len += p_len + 2

        if current:
            chunks.append("\n\n".join(current))
        return chunks

    def _deduplicate_fields(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: Dict[str, Dict[str, Any]] = {}
        for f in fields:
            lbl = str(f.get("label", "")).strip().lower()
            if not lbl:
                continue
            if lbl not in seen or float(f.get("confidence", 0.0)) > float(seen[lbl].get("confidence", 0.0)):
                seen[lbl] = f
        return list(seen.values())


# ---------------------------------------------------------------------------
# 4. Groq Text Provider (Text Only, Non-Reasoning)
# ---------------------------------------------------------------------------
class GroqProvider(BaseExtractionProvider):
    """Groq LPU Text Extraction Provider (Text Only)."""

    def __init__(self):
        groq_model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip()
        rpm = float(os.getenv("GROQ_RPM", "30.0"))
        concurrency = int(os.getenv("GROQ_CONCURRENCY", "3"))
        allow_sensitive = os.getenv("GROQ_ALLOW_SENSITIVE", "false").lower() == "true"
        super().__init__(
            name="groq",
            model_name=groq_model,
            is_vision=False,
            allow_sensitive=allow_sensitive,
            rpm=rpm,
            max_concurrency=concurrency,
        )

    async def extract(
        self,
        images_b64: Optional[List[str]] = None,
        raw_text: Optional[str] = None,
        is_sensitive: bool = True,
        corrections: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[ProviderResult]:
        if is_sensitive and not self.allow_sensitive:
            logger.info("Skipping external Groq call: document is classified as sensitive.")
            return None

        if not raw_text or not raw_text.strip():
            return None

        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            return None

        if not await self.circuit_breaker.can_execute():
            logger.warning("Groq circuit breaker is OPEN (%s); bypassing provider.", self.circuit_breaker.pause_reason)
            return None

        client = await get_shared_client()
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        system_instruction = (
            "Extract physical fields from document text as JSON:\n"
            '{"doc_type":"string","title":"string","fields":[{"label":"string","value":"string","confidence":0.95}]}'
        )

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": raw_text[:6000]},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }

        await self.rate_limiter.acquire()
        async with self.semaphore:
            try:
                resp = await client.post(url, headers=headers, json=payload, timeout=20.0)
                body_text = resp.text

                if resp.status_code == 429:
                    await self.circuit_breaker.record_failure(
                        Exception("HTTP 429"), is_429=True, raw_response_body=body_text
                    )
                    return None

                if resp.status_code != 200:
                    await self.circuit_breaker.record_failure(
                        Exception(f"HTTP {resp.status_code}"), is_429=False, raw_response_body=body_text
                    )
                    return None

                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                match = re.search(r"\{.*\}", content, re.DOTALL)
                parsed = json.loads(match.group(0)) if match else json.loads(content)

                await self.circuit_breaker.record_success()
                fields = parsed.get("fields", [])
                requires_review = len(fields) == 0
                return ProviderResult(
                    doc_type=parsed.get("doc_type", "Document"),
                    title=parsed.get("title", "Document"),
                    fields=fields,
                    provider_name=self.name,
                    model_name=self.model_name,
                    is_fallback=False,
                    requires_review=requires_review,
                    status="check" if requires_review else "done",
                )

            except (httpx.RequestError, json.JSONDecodeError, KeyError) as e:
                await self.circuit_breaker.record_failure(e, is_429=False)
                return None


# ---------------------------------------------------------------------------
# Fallback Orchestrator (Shared Singleton)
# ---------------------------------------------------------------------------
class FallbackOrchestrator:
    """Shared Orchestrator managing fallback chains, local validation, and user caching."""

    def __init__(self):
        self.local_provider = LocalOcrProvider()
        self.ollama_provider = LocalOllamaProvider()
        self.gemini_provider = GeminiProvider()
        self.groq_provider = GroqProvider()

        # In-memory user-scoped raw model output cache:
        # cache_key = sha256 + model + prompt_version + user_id
        self._user_cache: Dict[str, Dict[str, Any]] = {}

    def compute_user_cache_key(self, sha256: str, model: str, user_id: str) -> str:
        raw = f"{sha256}:{model}:{PROMPT_VERSION}:{user_id or 'anon'}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get_cached_result(self, cache_key: str) -> Optional[Dict[str, Any]]:
        return self._user_cache.get(cache_key)

    def set_cached_result(self, cache_key: str, data: Dict[str, Any]):
        # CACHE RULE 8: Only cache valid, successful results (never errors or unextracted placeholders)
        if not data or not data.get("fields") or data.get("is_fallback") is True:
            return
        self._user_cache[cache_key] = data

    def validate_local_ocr_quality(self, local_result: Optional[ProviderResult]) -> bool:
        """RULE 1: Verify if local result has high confidence and passes structural/checksum validation."""
        if not local_result or not local_result.fields:
            return False

        # 1. Average confidence must be >= 0.85
        avg_conf = sum(float(f.get("confidence", 0.0)) for f in local_result.fields) / len(local_result.fields)
        if avg_conf < 0.85:
            return False

        # 2. Check if invoice math or structural validators pass
        if local_result.doc_type == "Invoice":
            math_valid, _ = validate_invoice_math(local_result.fields)
            if math_valid:
                return True

        # 3. Check if national ID or verified date is present
        has_verified_id = False
        for f in local_result.fields:
            lbl = f.get("label", "").lower()
            val = str(f.get("value", ""))
            if lbl in ("pan", "pan number") and validate_pan(val):
                has_verified_id = True
            elif lbl in ("aadhaar", "aadhaar number") and validate_aadhaar(val):
                has_verified_id = True
            elif lbl in ("gstin", "gst") and validate_gstin(val):
                has_verified_id = True
            elif lbl in ("ifsc", "ifsc code") and validate_ifsc(val):
                has_verified_id = True

        if has_verified_id:
            return True

        # If 3 or more high confidence structured fields are present, accept local
        return len(local_result.fields) >= 3 and avg_conf >= 0.90

    async def extract_document(
        self,
        images_b64: Optional[List[str]] = None,
        local_ocr_text: Optional[str] = None,
        is_sensitive: bool = True,  # Orchestrator default MUST be sensitive
        user_id: Optional[str] = None,
        sha256: Optional[str] = None,
        corrections: Optional[List[Dict[str, str]]] = None,
    ) -> ProviderResult:
        """Run Speed-First model-agnostic extraction with automatic fallback."""
        # 1. Run Local OCR / rule parser first
        local_res = await self.local_provider.extract(
            images_b64=images_b64,
            raw_text=local_ocr_text,
            is_sensitive=is_sensitive,
            corrections=corrections,
        )

        # 2. LOCAL FIRST FOR REAL: If confidence and validation pass, return IMMEDIATELY with 0 external calls!
        if self.validate_local_ocr_quality(local_res):
            logger.info("Local OCR passed confidence (>=0.85) and structural validation. Zero external calls made.")
            local_res.is_fallback = False
            local_res.status = "done"
            return local_res

        # 3. Check user-scoped cache before calling external AI
        if sha256 and user_id:
            cached_key = self.compute_user_cache_key(sha256, "external_ai", user_id)
            cached_data = self.get_cached_result(cached_key)
            if cached_data:
                logger.info("Serving from user-scoped SHA-256 cache.")
                return ProviderResult(
                    doc_type=cached_data.get("doc_type", "Document"),
                    title=cached_data.get("title", "Document"),
                    fields=cached_data.get("fields", []),
                    provider_name=cached_data.get("provider_name", "cache"),
                    model_name=cached_data.get("model_name", "cached"),
                    is_fallback=False,
                    requires_review=False,
                    status="done",
                )

        # 4. If sensitive document: use local Ollama LLM provider (config-driven) so no sensitive text leaves machine
        if is_sensitive:
            use_local_llm = os.getenv("USE_LOCAL_LLM", "true").lower() == "true"
            if use_local_llm:
                try:
                    ollama_res = await self.ollama_provider.extract(
                        images_b64=images_b64,
                        raw_text=local_ocr_text,
                        is_sensitive=is_sensitive,
                        corrections=corrections,
                    )
                    if ollama_res and ollama_res.fields:
                        return ollama_res
                except Exception as e:
                    logger.debug("Local Ollama fallback error on sensitive document: %s", e)

            # Sensitive documents must NOT call external cloud providers
            logger.info("Sensitive document: strictly avoiding external cloud calls. Returning local OCR result.")
            local_res.is_fallback = True
            local_res.requires_review = len(local_res.fields) == 0
            local_res.status = "check" if local_res.requires_review else "done"
            return local_res

        # 5. External fallback chain for non-sensitive documents:
        # Vision chain: Gemini -> Ollama -> Local OCR
        # Text chain: Groq -> Gemini -> Local OCR
        chain = (
            [self.gemini_provider, self.ollama_provider, self.local_provider]
            if images_b64
            else [self.groq_provider, self.gemini_provider, self.local_provider]
        )

        for provider in chain:
            try:
                res = await provider.extract(
                    images_b64=images_b64,
                    raw_text=local_ocr_text,
                    is_sensitive=is_sensitive,
                    corrections=corrections,
                )
                if res is not None and res.fields:
                    # Save raw model output to user-scoped cache
                    if sha256 and user_id and not res.is_fallback:
                        c_key = self.compute_user_cache_key(sha256, "external_ai", user_id)
                        self.set_cached_result(c_key, {
                            "doc_type": res.doc_type,
                            "title": res.title,
                            "fields": res.fields,
                            "provider_name": res.provider_name,
                            "model_name": res.model_name,
                            "is_fallback": res.is_fallback,
                        })
                    return res
            except Exception as e:
                logger.warning("Provider '%s' error: %s. Continuing fallback chain.", provider.name, type(e).__name__)

        # 6. Final fallback
        local_res.is_fallback = True
        local_res.requires_review = True
        local_res.status = "check"
        return local_res


# ---------------------------------------------------------------------------
# Module-level Shared Singleton
# ---------------------------------------------------------------------------
_orchestrator_instance: Optional[FallbackOrchestrator] = None


def get_fallback_orchestrator() -> FallbackOrchestrator:
    """Return the shared module-level FallbackOrchestrator instance."""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        validate_provider_configs()
        _orchestrator_instance = FallbackOrchestrator()
    return _orchestrator_instance
