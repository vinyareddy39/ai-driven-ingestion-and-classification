"""Comprehensive PII and Sensitivity Detection Engine.

Implements:
1. Multi-pattern detectors for:
   - Aadhaar (with and without spaces, validated via Verhoeff)
   - PAN (5 letters, 4 digits, 1 letter)
   - GSTIN (15-character Indian tax ID)
   - IFSC (Indian bank branch routing code)
   - Bank Account Numbers (9 to 18 digits with contextual keywords)
   - Phone numbers (Indian 10-digit and international E.164)
   - Email addresses
   - Payment Card numbers (13-19 digits, validated via Luhn algorithm)
   - Passport numbers
   - Clinical and medical health terminology
2. Fail-closed sensitivity decision gate (low confidence or Medical/KYC/unknown => sensitive).
3. Fixed field schemas per document type.
4. Intelligent multi-pair line splitter: splits lines containing multiple 'Label: value' pairs.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.validators import validate_aadhaar, validate_pan, validate_gstin, validate_ifsc


# ---------------------------------------------------------------------------
# Luhn Algorithm for Credit/Debit Card Validation
# ---------------------------------------------------------------------------
def validate_luhn(card_number_str: str) -> bool:
    """Validate payment card number using Luhn algorithm."""
    clean = re.sub(r"\D", "", card_number_str)
    if len(clean) < 13 or len(clean) > 19:
        return False
    digits = [int(d) for d in clean]
    checksum = 0
    reverse_digits = digits[::-1]
    for i, d in enumerate(reverse_digits):
        if i % 2 == 1:
            d = d * 2
            if d > 9:
                d -= 9
        checksum += d
    return (checksum % 10) == 0


# ---------------------------------------------------------------------------
# Regex Patterns for Sensitive Data Detection
# ---------------------------------------------------------------------------
AADHAAR_PATTERN = re.compile(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b")
PAN_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
GSTIN_PATTERN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}\b")
IFSC_PATTERN = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
PASSPORT_PATTERN = re.compile(r"\b[A-Z][0-9]{7,8}\b")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")

# Phone patterns: Indian 10-digit starting 6-9, or US / International formats
PHONE_PATTERNS = [
    re.compile(r"\b(?:\+91[-.\s]?)?[6-9]\d{9}\b"),
    re.compile(r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    re.compile(r"\b\+\d{1,3}[-.\s]?\d{6,14}\b"),
]

# Bank account: 9-18 digits preceded or followed by contextual hints
BANK_ACCOUNT_PATTERN = re.compile(
    r"(?i)\b(?:account|acct|a/c|acc\.?|bank\s*a/c)(?:\s*(?:no\.?|number|#))?[:\s]*(\d{9,18})\b"
)

# Card patterns: groups of 4 digits or continuous 13-19 digits
CARD_PATTERN = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{1,4}\b|\b\d{13,19}\b")

# Health terms
HEALTH_TERMS_REGEX = re.compile(
    r"\b(patient|mrn|medical\s*record|diagnosis|rx|prescription|physician|doctor|hospital|clinic|"
    r"admission|dosage|medication|pathology|specimen|treatment|clinical|tablet|capsule|mg|ml|"
    r"blood\s*pressure|glucose|cholesterol|symptoms|discharge|consultation|dr\.)\b",
    re.IGNORECASE,
)

SENSITIVE_DOC_TYPES = {
    "medical report",
    "prescription",
    "medical prescription",
    "lab report",
    "patient record",
    "kyc form",
    "bank statement",
    "tax document",
    "payroll",
    "national id",
    "passport",
    "id document",
    "unknown",
}


# ---------------------------------------------------------------------------
# Sensitivity Evaluator
# ---------------------------------------------------------------------------
def evaluate_document_sensitivity(
    text: str,
    doc_type: Optional[str] = None,
    confidence: float = 0.0,
) -> Tuple[bool, str, List[Dict[str, str]]]:
    """Evaluate document text and metadata to decide if it must remain strictly on-premise.
    
    Returns:
        (is_sensitive: bool, reason: str, entities_found: List[Dict[str, str]])
    """
    entities: List[Dict[str, str]] = []

    # Extract all PII entities from text
    if text:
        # Aadhaar Detection
        for m in AADHAAR_PATTERN.finditer(text):
            val = m.group(0)
            clean = re.sub(r"\s+", "", val)
            if validate_aadhaar(clean):
                entities.append({"type": "AADHAAR", "value": val})

        # PAN Detection
        for m in PAN_PATTERN.finditer(text):
            val = m.group(0)
            if validate_pan(val):
                entities.append({"type": "PAN", "value": val})

        # GSTIN Detection
        for m in GSTIN_PATTERN.finditer(text):
            val = m.group(0)
            if validate_gstin(val):
                entities.append({"type": "GSTIN", "value": val})

        # IFSC Detection
        for m in IFSC_PATTERN.finditer(text):
            val = m.group(0)
            if validate_ifsc(val):
                entities.append({"type": "IFSC", "value": val})

        # Bank Account Detection
        for m in BANK_ACCOUNT_PATTERN.finditer(text):
            val = m.group(1)
            entities.append({"type": "BANK_ACCOUNT", "value": val})

        # Payment Cards
        for m in CARD_PATTERN.finditer(text):
            val = m.group(0)
            clean = re.sub(r"\D", "", val)
            if validate_luhn(clean):
                entities.append({"type": "PAYMENT_CARD", "value": val})

        # Email & Phone
        for m in EMAIL_PATTERN.finditer(text):
            entities.append({"type": "EMAIL", "value": m.group(0)})

        for pat in PHONE_PATTERNS:
            for m in pat.finditer(text):
                entities.append({"type": "PHONE", "value": m.group(0)})

        # Passport
        for m in PASSPORT_PATTERN.finditer(text):
            entities.append({"type": "PASSPORT", "value": m.group(0)})

        # Health terms
        health_matches = HEALTH_TERMS_REGEX.findall(text)
        if len(health_matches) >= 2:
            entities.append({"type": "HEALTH_TERMS", "value": ", ".join(set(health_matches[:5]))})

    # Fail closed decision checks
    norm_doc = (doc_type or "unknown").strip().lower()
    if entities:
        types_str = ", ".join(sorted(set(e["type"] for e in entities)))
        return True, f"Sensitive PII entities identified: {types_str}", entities

    if norm_doc in SENSITIVE_DOC_TYPES or confidence < 0.85:
        reason = f"Fail closed: doc type '{doc_type}' is sensitive or confidence ({confidence:.2f}) < 0.85"
        return True, reason, entities

    if not text:
        return True, "No text provided (fail closed)", entities

    return False, "Standard non-sensitive document", entities


# ---------------------------------------------------------------------------
# Multi-Pair Line Splitter
# ---------------------------------------------------------------------------
# Regex to match Label: Value pairs even when several appear on a single line
# Example: "Patient: John Doe    Age: 45    MRN: 994821"
_MULTI_PAIR_PATTERN = re.compile(
    r"(?:^|[\t|;,]|\s{2,})([A-Za-z0-9\s/_\-]{2,30}?):\s*([^:\n]+?)(?=(?:[\t|;,]|\s{2,})[A-Za-z0-9\s/_\-]{2,30}?:|$)"
)


def split_line_into_pairs(line: str) -> List[Tuple[str, str]]:
    """Extract all 'Label: value' pairs from a line, preserving multiple pairs per line."""
    pairs: List[Tuple[str, str]] = []
    clean_line = line.strip()
    if not clean_line or ":" not in clean_line:
        return pairs

    # Try multi-pair extraction first
    matches = list(_MULTI_PAIR_PATTERN.finditer(clean_line))
    if len(matches) > 1:
        for m in matches:
            lbl = m.group(1).strip()
            val = m.group(2).strip()
            # Clean trailing punctuation
            val = re.sub(r"[\s,;]+$", "", val)
            if lbl and val:
                pairs.append((lbl, val))
        return pairs

    # Single colon or standard fallback
    parts = clean_line.split(":", 1)
    if len(parts) == 2:
        lbl, val = parts[0].strip(), parts[1].strip()
        if lbl and val and len(lbl) <= 40:
            pairs.append((lbl, val))

    return pairs



