"""Unified LLM Client Interface and Data Residency Router.

RESIDENCY RULES:
- High-risk / PII / health classes:
  ('medical_report', 'kyc_form', 'bank_statement', 'claim_form', 'prescriptions')
  are STRICTLY RESTRICTED to local models (e.g. local Ollama / vLLM endpoint).
  Routing these to a hosted external API is a security violation and is explicitly blocked.
- If the local endpoint is unavailable or offline, the router falls back to the deterministic
  rule-based extractor and routes the document to the human review queue.
- Low-risk classes ('receipt', 'invoice', 'unknown') may utilize hosted LLMs if configured.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
import urllib.request
import urllib.error

from app.core.settings import get_app_settings

logger = logging.getLogger("ecm.llm_residency")

RESTRICTED_CLASSES = {
    "medical_report",
    "kyc_form",
    "bank_statement",
    "claim_form",
    "prescriptions",
    "prescription",
}


class DataResidencyViolationError(Exception):
    """Raised when an attempt is made to route residency-restricted documents to hosted APIs."""
    pass


class LLMClient(ABC):
    """Abstract interface for LLM completions with JSON schema grounding."""

    @abstractmethod
    def complete(self, prompt: str, json_schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Generate response conforming to optional JSON schema."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if backend endpoint is reachable."""
        pass


class LocalLLMClient(LLMClient):
    """Local OpenAI-compatible client (e.g. Ollama, vLLM, LocalAI)."""

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        settings = get_app_settings()
        self.base_url = (base_url or settings.LLM_LOCAL_BASE_URL).rstrip("/")
        self.model = model or settings.LLM_LOCAL_MODEL

    def is_available(self) -> bool:
        try:
            # Query models endpoint or health
            url = f"{self.base_url}/models"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def complete(self, prompt: str, json_schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a structured document field extractor. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
        }
        if json_schema:
            payload["response_format"] = {"type": "json_object"}

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            return json.loads(content)


class HostedLLMClient(LLMClient):
    """Hosted external LLM client (OpenAI, Anthropic, Gemini)."""

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        settings = get_app_settings()
        self.provider = provider or settings.LLM_HOSTED_PROVIDER or "openai"
        self.api_key = api_key or settings.LLM_HOSTED_API_KEY or ""
        self.model = model or settings.LLM_HOSTED_MODEL or "gpt-4o-mini"

    def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 5)

    def complete(self, prompt: str, json_schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.is_available():
            raise RuntimeError("Hosted LLM API key not configured in environment.")

        # Real hosted call stub/client (e.g. OpenAI / Anthropic SDK)
        # Note: ONLY allowed for low-risk classes (receipt, invoice, unknown)
        raise NotImplementedError("Hosted LLM endpoint configured for synthetic benchmarks only.")


class LLMResidencyRouter:
    """Enforces data residency boundaries between local and hosted AI models."""

    def __init__(
        self,
        local_client: Optional[LocalLLMClient] = None,
        hosted_client: Optional[HostedLLMClient] = None,
    ):
        self.local_client = local_client or LocalLLMClient()
        self.hosted_client = hosted_client or HostedLLMClient()
        settings = get_app_settings()
        self.allowed_hosted_classes = {
            c.strip().lower() for c in settings.LLM_ALLOW_HOSTED_CLASSES.split(",") if c.strip()
        }

    def route(self, doc_class: str) -> Tuple[str, Optional[LLMClient]]:
        """Determine backend for document class, enforcing residency.
        
        Returns:
            (backend_name: 'local' | 'hosted' | 'deterministic_fallback', client: Optional[LLMClient])
        """
        clean_class = doc_class.lower().strip()

        # 1. STRICT RESIDENCY CHECK: Health, KYC, Bank, Claims must NEVER touch hosted APIs
        if clean_class in RESTRICTED_CLASSES:
            # Check if local endpoint is reachable
            if self.local_client.is_available():
                return "local", self.local_client
            else:
                logger.warning(
                    f"Local LLM offline for residency-restricted class '{clean_class}'. "
                    f"Falling back to deterministic rule extractor (routing to human review)."
                )
                return "deterministic_fallback", None

        # 2. Check low-risk classes permitted for hosted
        if clean_class in self.allowed_hosted_classes:
            if self.hosted_client.is_available():
                return "hosted", self.hosted_client
            if self.local_client.is_available():
                return "local", self.local_client
            return "deterministic_fallback", None

        # Default fallback
        if self.local_client.is_available():
            return "local", self.local_client
        return "deterministic_fallback", None

    def execute_with_residency(
        self,
        doc_class: str,
        prompt: str,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute completion ensuring residency restrictions."""
        clean_class = doc_class.lower().strip()

        # Enforce that caller cannot force hosted backend on restricted class
        if clean_class in RESTRICTED_CLASSES:
            if not self.local_client.is_available():
                return {
                    "status": "FALLBACK_TO_DETERMINISTIC",
                    "reason": "Local model offline; residency policy prevents hosted API routing.",
                }

        backend_name, client = self.route(clean_class)
        if backend_name == "deterministic_fallback" or client is None:
            return {
                "status": "FALLBACK_TO_DETERMINISTIC",
                "reason": "No LLM endpoint available.",
            }

        return client.complete(prompt, json_schema=json_schema)


class ReceiptExtractor:
    """Deterministic, schema-grounded field extractor for receipt documents.
    
    Extracts:
    - merchant_name (grounded in header lines)
    - date (ISO normalized YYYY-MM-DD)
    - total_amount (from final Total line)
    - tax_amount (from Tax/VAT line)
    - currency (USD, EUR, GBP, INR, etc.)
    """

    DATE_PATTERNS = [
        # YYYY-MM-DD or YYYY/MM/DD
        r"\b(20\d\d)[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b",
        # DD/MM/YYYY or DD-MM-YYYY
        r"\b(0[1-9]|[12]\d|3[01])[-/](0[1-9]|1[0-2])[-/](20\d\d)\b",
        # MM/DD/YYYY
        r"\b(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/(20\d\d)\b",
    ]

    TOTAL_PATTERNS = [
        r"(?:total|amount\s+due|balance\s+due|grand\s+total|net\s+total)\s*[:=]?\s*[$€£₹]?\s*(\d+[.,]\d{2})",
        r"[$€£₹]\s*(\d+[.,]\d{2})\s*(?:total)?",
    ]

    TAX_PATTERNS = [
        r"(?:tax|vat|gst|sales\s+tax)\s*[:=]?\s*[$€£₹]?\s*(\d+[.,]\d{2})",
    ]

    CURRENCY_SYMBOLS = {
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
        "₹": "INR",
        "usd": "USD",
        "eur": "EUR",
        "gbp": "GBP",
        "inr": "INR",
    }

    def extract(self, ocr_text: str) -> Dict[str, Any]:
        """Extract grounded receipt fields from line-broken OCR text."""
        lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
        if not lines:
            return {}

        fields: Dict[str, Any] = {}
        grounding: Dict[str, str] = {}
        confidences: Dict[str, float] = {}

        # 1. Merchant Name: first line that is alphabetic and not a date or keyword
        for line in lines[:4]:
            if len(line) >= 3 and not re.search(r"\b(receipt|tax\s+invoice|date|welcome|thank\s+you)\b", line, re.I):
                clean_merchant = re.sub(r"^[#*•\s]+|[#*•\s]+$", "", line)
                fields["merchant_name"] = clean_merchant
                grounding["merchant_name"] = line
                confidences["merchant_name"] = 0.92
                break

        # 2. Date Extraction & ISO Normalization
        for line in lines:
            date_found = False
            for pat in self.DATE_PATTERNS:
                m = re.search(pat, line)
                if m:
                    g = m.groups()
                    if len(g[0]) == 4:  # YYYY-MM-DD
                        iso_date = f"{g[0]}-{g[1]}-{g[2]}"
                    else:  # DD-MM-YYYY or MM-DD-YYYY
                        iso_date = f"{g[2]}-{g[1]}-{g[0]}"
                    fields["date"] = iso_date
                    grounding["date"] = line
                    confidences["date"] = 0.95
                    date_found = True
                    break
            if date_found:
                break

        # 3. Currency Detection
        detected_curr = "USD"
        for line in lines:
            for sym, code in self.CURRENCY_SYMBOLS.items():
                if sym in line.lower():
                    detected_curr = code
                    break
        fields["currency"] = detected_curr

        # 4. Total Amount: Scan from the bottom up to capture final total
        for line in reversed(lines):
            found_total = False
            for pat in self.TOTAL_PATTERNS:
                m = re.search(pat, line, re.I)
                if m:
                    amt_str = m.group(1).replace(",", ".")
                    try:
                        fields["total_amount"] = float(amt_str)
                        grounding["total_amount"] = line
                        confidences["total_amount"] = 0.95
                        found_total = True
                        break
                    except ValueError:
                        pass
            if found_total:
                break

        # 5. Tax Amount
        for line in lines:
            found_tax = False
            for pat in self.TAX_PATTERNS:
                m = re.search(pat, line, re.I)
                if m:
                    amt_str = m.group(1).replace(",", ".")
                    try:
                        fields["tax_amount"] = float(amt_str)
                        grounding["tax_amount"] = line
                        confidences["tax_amount"] = 0.90
                        found_tax = True
                        break
                    except ValueError:
                        pass
            if found_tax:
                break

        return {
            "fields": fields,
            "grounding": grounding,
            "confidences": confidences,
        }
