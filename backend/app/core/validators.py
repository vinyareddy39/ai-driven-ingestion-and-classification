"""Validation and Checksum Engine for Local-First Extraction.

Implements:
1. Verhoeff Algorithm for Aadhaar 12-digit checksum verification.
2. PAN format validation (5 uppercase letters, 4 digits, 1 uppercase letter).
3. GSTIN format validation (2 digit state code + PAN + entity code + Z + checksum).
4. IFSC code validation (4 letters + 0 + 6 alphanumeric).
5. Date format validation (ISO, DD/MM/YYYY, MM/DD/YYYY, named months).
6. Financial Math validation: subtotal + taxes == total (within 0.05 tolerance).
"""

import math
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 1. Verhoeff Algorithm (Dihedral Group D5 for Aadhaar 12-digit validation)
# ---------------------------------------------------------------------------
_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]

_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]

_VERHOEFF_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def validate_verhoeff(number_str: str) -> bool:
    """Validate a numeric string using the Verhoeff algorithm (returns True if valid)."""
    clean_digits = re.sub(r"\D", "", number_str)
    if not clean_digits:
        return False
    c = 0
    reversed_digits = [int(d) for d in reversed(clean_digits)]
    for i, d in enumerate(reversed_digits):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][d]]
    return c == 0


def generate_verhoeff_checksum(number_str: str) -> int:
    """Generate the Verhoeff check digit for an 11-digit prefix."""
    clean_digits = re.sub(r"\D", "", number_str)
    c = 0
    reversed_digits = [int(d) for d in reversed(clean_digits)]
    for i, d in enumerate(reversed_digits):
        c = _VERHOEFF_D[c][_VERHOEFF_P[(i + 1) % 8][d]]
    return _VERHOEFF_INV[c]


def validate_aadhaar(aadhaar_str: str) -> bool:
    """Aadhaar must be exactly 12 digits and satisfy Verhoeff checksum."""
    clean = re.sub(r"\s+", "", aadhaar_str)
    if not re.match(r"^\d{12}$", clean):
        return False
    # First digit cannot be 0 or 1 in standard Aadhaar
    if clean[0] in ("0", "1"):
        return False
    return validate_verhoeff(clean)


# ---------------------------------------------------------------------------
# 2. National ID & Tax Format Validators
# ---------------------------------------------------------------------------
PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_REGEX = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}$")
IFSC_REGEX = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
SSN_REGEX = re.compile(r"^(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}$")
PASSPORT_REGEX = re.compile(r"^[A-Z][0-9]{7,8}$")


def validate_pan(pan_str: str) -> bool:
    """PAN format: 5 letters, 4 digits, 1 letter. 4th letter is entity type."""
    clean = pan_str.strip().upper()
    if not PAN_REGEX.match(clean):
        return False
    # 4th character must be one of standard PAN status letters
    # P (Individual), C (Company), H (HUF), F (Firm), A (AOP), T (Trust), B (BOI), L (Local), J (Artificial Juridical), G (Govt)
    return clean[3] in "PCHFATBLJG"


def validate_gstin(gstin_str: str) -> bool:
    """GSTIN format: 2-digit state code + 10-char PAN + 1 entity code + Z + 1 checksum."""
    clean = gstin_str.strip().upper()
    if not GSTIN_REGEX.match(clean):
        return False
    state_code = int(clean[:2])
    if state_code < 1 or state_code > 38:
        return False
    pan_part = clean[2:12]
    return validate_pan(pan_part)


def validate_ifsc(ifsc_str: str) -> bool:
    """IFSC format: 4 alphabetic chars + '0' + 6 alphanumeric branch code."""
    clean = ifsc_str.strip().upper()
    return bool(IFSC_REGEX.match(clean))


# ---------------------------------------------------------------------------
# 3. Date Validation
# ---------------------------------------------------------------------------
DATE_PATTERNS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%m/%d/%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
]


def parse_and_validate_date(date_str: str) -> Tuple[bool, Optional[str]]:
    """Verify if string is a valid historical or contemporary calendar date."""
    clean = date_str.strip()
    for fmt in DATE_PATTERNS:
        try:
            dt = datetime.strptime(clean, fmt)
            # Reasonable date range: 1900 to 2100
            if 1900 <= dt.year <= 2100:
                return True, dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return False, None


# ---------------------------------------------------------------------------
# 4. Financial Math Validator: subtotal + taxes == total
# ---------------------------------------------------------------------------
def parse_currency_amount(val_str: str) -> Optional[float]:
    """Parse string containing currency symbol and commas into float."""
    if not val_str:
        return None
    # Remove currency symbols and spaces
    clean = re.sub(r"[^\d.,\-]", "", str(val_str).strip())
    if not clean:
        return None
    try:
        # Handle 1,250.50 vs 1.250,50
        if "," in clean and "." in clean:
            if clean.rfind(",") > clean.rfind("."):
                # European style 1.250,50
                clean = clean.replace(".", "").replace(",", ".")
            else:
                # Standard style 1,250.50
                clean = clean.replace(",", "")
        elif "," in clean:
            # Check if comma is decimal or thousands separator
            parts = clean.split(",")
            if len(parts) == 2 and len(parts[1]) <= 2:
                clean = clean.replace(",", ".")
            else:
                clean = clean.replace(",", "")
        return float(clean)
    except (ValueError, TypeError):
        return None


def validate_invoice_math(fields: List[Dict[str, Any]], tolerance: float = 0.05) -> Tuple[bool, str]:
    """Check if subtotal + tax == total (within tolerance)."""
    subtotal = None
    total = None
    tax_amounts = []

    for f in fields:
        lbl = str(f.get("label", "")).strip().lower()
        val = str(f.get("value", "")).strip()
        amt = parse_currency_amount(val)
        if amt is None:
            continue

        if lbl in ("subtotal", "sub-total", "sub total", "net amount", "taxable amount"):
            subtotal = amt
        elif lbl in ("total", "total amount", "grand total", "invoice total", "amount due"):
            total = amt
        elif any(k in lbl for k in ("tax", "gst", "cgst", "sgst", "igst", "vat")):
            tax_amounts.append(amt)

    if subtotal is not None and total is not None:
        total_tax = sum(tax_amounts)
        expected_total = subtotal + total_tax
        diff = abs(expected_total - total)
        if diff <= tolerance:
            return True, f"Math checks out: {subtotal:.2f} + {total_tax:.2f} == {total:.2f}"
        return False, f"Math mismatch: {subtotal:.2f} + {total_tax:.2f} != {total:.2f} (diff: {diff:.2f})"

    return False, "Subtotal or Total missing for math check"
