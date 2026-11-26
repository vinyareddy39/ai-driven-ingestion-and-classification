"""Sanity and Format Verification Engine.

Performs arithmetic cross-checks (e.g. subtotal + tax = total),
calendar date parsing, and monetary format verification.
Degrades confidence and flags human review on failed sanity checks.
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _parse_amount(text: str) -> Optional[float]:
    """Extract numeric decimal amount from text string."""
    tokens = str(text).strip().split()
    if not tokens:
        return None
    # Examine tokens in reverse (the actual amount is almost always the last token)
    for token in reversed(tokens):
        clean = re.sub(r"[^\d.,-]", "", token)
        if not clean or not any(c.isdigit() for c in clean):
            continue
        # Handle European format 1.234,56 vs US 1,234.56
        if "," in clean and "." in clean:
            if clean.rfind(",") > clean.rfind("."):
                clean = clean.replace(".", "").replace(",", ".")
            else:
                clean = clean.replace(",", "")
        elif "," in clean:
            parts = clean.split(",")
            if len(parts) == 2 and len(parts[1]) == 2:
                clean = clean.replace(",", ".")
            else:
                clean = clean.replace(",", "")

        try:
            return float(clean)
        except ValueError:
            continue
    return None


def run_sanity_checks(
    fields: List[Dict[str, Any]],
    table_rows: List[Dict[str, Any]],
    review_threshold: float = 0.85,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Run arithmetic and format sanity checks on extracted fields."""
    updated_fields = [dict(f) for f in fields]
    review_reasons: List[str] = []

    # 1. Identify key financial fields
    subtotal_val: Optional[float] = None
    tax_val: Optional[float] = None
    total_val: Optional[float] = None
    total_idx: Optional[int] = None

    for idx, f in enumerate(updated_fields):
        lbl = f.get("label", "").lower().strip()
        val_str = str(f.get("value", "")).strip()

        # Check for total / balance
        if any(w in lbl for w in ["total amount", "grand total", "total due", "balance due", "amount due"]) or lbl == "total":
            parsed = _parse_amount(val_str)
            if parsed is not None:
                total_val = parsed
                total_idx = idx

        # Check for subtotal / net amount
        elif "subtotal" in lbl or "net amount" in lbl:
            parsed = _parse_amount(val_str)
            if parsed is not None:
                subtotal_val = parsed

        # Check for tax / vat
        elif any(w in lbl for w in ["tax", "vat", "gst", "sales tax"]) and "id" not in lbl and "no" not in lbl:
            parsed = _parse_amount(val_str)
            if parsed is not None:
                tax_val = parsed

    # 2. Arithmetic Sanity: Subtotal + Tax = Total
    if subtotal_val is not None and tax_val is not None and total_val is not None:
        expected_total = subtotal_val + tax_val
        delta = abs(expected_total - total_val)
        if delta > 0.06:
            reason = (
                f"Arithmetic check failed: Subtotal ({subtotal_val:.2f}) + Tax ({tax_val:.2f}) "
                f"= {expected_total:.2f}, but Total is {total_val:.2f} (delta {delta:.2f})."
            )
            review_reasons.append(reason)
            if total_idx is not None:
                updated_fields[total_idx]["confidence"] = min(0.60, updated_fields[total_idx].get("confidence", 0.90))
                updated_fields[total_idx]["needs_review"] = True

    # 3. Arithmetic Sanity: Line Item Amounts Sum vs Subtotal/Total
    if table_rows and (subtotal_val is not None or total_val is not None):
        line_amounts: List[float] = []
        for r in table_rows:
            chosen_amt = None
            # Priority 1: total / line total / amount / extended (explicitly not unit price)
            for k, v in r.items():
                k_low = k.lower()
                if ("total" in k_low or "amount" in k_low or "extended" in k_low) and "unit" not in k_low:
                    amt = _parse_amount(v)
                    if amt is not None:
                        chosen_amt = amt
                        break
            # Priority 2: fallback to price or cost if no explicit line total column
            if chosen_amt is None:
                for k, v in r.items():
                    if "price" in k.lower() or "cost" in k.lower():
                        amt = _parse_amount(v)
                        if amt is not None:
                            chosen_amt = amt
                            break
            if chosen_amt is not None:
                line_amounts.append(chosen_amt)
        if len(line_amounts) >= 2:
            sum_lines = sum(line_amounts)
            target = subtotal_val if subtotal_val is not None else total_val
            if target and abs(sum_lines - target) > 0.50:
                reason = (
                    f"Line items sum ({sum_lines:.2f}) does not match summary total ({target:.2f})."
                )
                review_reasons.append(reason)

    # 4. Format Sanity Checks: Dates & Amounts
    for idx, f in enumerate(updated_fields):
        lbl = f.get("label", "").lower().strip()
        val_str = str(f.get("value", "")).strip()

        # Date Format Check
        if "date" in lbl or "collected on" in lbl or "dob" in lbl:
            # Check if parseable
            has_valid_date = False
            for fmt in (
                "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d",
                "%d-%m-%Y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y",
                "%d %B %Y", "%d %b %Y"
            ):
                try:
                    # Strip extra trailing tokens
                    clean_date_str = re.sub(r"[^\w\s/.-]", "", val_str).strip()
                    datetime.strptime(clean_date_str, fmt)
                    has_valid_date = True
                    break
                except ValueError:
                    pass

            if not has_valid_date and re.search(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}", val_str):
                # Malformed numbers in date
                reason = f"Unparseable date in field '{f.get('label')}': '{val_str}'"
                review_reasons.append(reason)
                updated_fields[idx]["confidence"] = min(0.55, updated_fields[idx].get("confidence", 0.90))
                updated_fields[idx]["needs_review"] = True

        # Amount Format Check
        if any(w in lbl for w in ["amount", "price", "fee", "cost", "salary", "subtotal", "total"]):
            parsed = _parse_amount(val_str)
            if parsed is None and any(c.isdigit() for c in val_str):
                reason = f"Malformed monetary amount in field '{f.get('label')}': '{val_str}'"
                review_reasons.append(reason)
                updated_fields[idx]["confidence"] = min(0.50, updated_fields[idx].get("confidence", 0.90))
                updated_fields[idx]["needs_review"] = True

    return updated_fields, review_reasons
