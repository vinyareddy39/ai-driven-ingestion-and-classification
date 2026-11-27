"""Extract 5 SROIE total_amount failures on Dev Receipts with raw OCR text."""

import json
import re
from pathlib import Path

def extract_receipt_total(text: str):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in reversed(lines):
        u = line.upper()
        if any(skip in u for skip in ["SUBTOTAL", "SUB TOTAL", "TAX", "CHANGE", "CASH", "ROUNDING"]):
            continue
        if any(kw in u for kw in ["GRAND TOTAL", "TOTAL", "NET AMOUNT", "AMOUNT DUE", "TOTAL RM"]):
            m = re.search(r'([0-9]+\.[0-9]{2})', line)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    pass
    return None

def main():
    print("=" * 80)
    print("SROIE DEV SET: 5 REAL RECEIPT TOTAL_AMOUNT FAILURES WITH RAW OCR TEXT")
    print("=" * 80)

    with open("data/real_sroie/ocr_cache_dev.json", "r", encoding="utf-8") as f:
        cache = json.load(f)

    with open("data/real_sroie/dataset/annotations.json", "r", encoding="utf-8") as f:
        all_records = json.load(f)

    dev_records = all_records[:50]
    failures = []

    for r in dev_records:
        did = r["doc_id"]
        gt = r["ground_truth"]
        expected_total = gt.get("total_amount")
        text = cache.get(did, {}).get("full_text", "")

        extracted_total = extract_receipt_total(text)

        match = False
        if extracted_total is not None and expected_total is not None:
            try:
                exp_num = float(re.sub(r"[^\d.]", "", str(expected_total)))
                ext_num = float(re.sub(r"[^\d.]", "", str(extracted_total)))
                if abs(exp_num - ext_num) < 0.05:
                    match = True
            except Exception:
                pass

        if not match:
            failures.append({
                "doc_id": did,
                "expected": expected_total,
                "extracted": extracted_total,
                "ocr_snippet": text[:500]
            })

    print(f"Total Failures Found: {len(failures)} out of 50 receipts\n")
    for i, fail in enumerate(failures[:5], 1):
        print(f"--- SROIE Failure Example #{i} (Receipt ID: {fail['doc_id']}) ---")
        print(f"Expected Ground Truth Total : '{fail['expected']}'")
        print(f"Extracted Total from OCR    : {fail['extracted']}")
        print(f"Raw OCR Text Snippet        :\n\"\"\"\n{fail['ocr_snippet'].strip()}\n\"\"\"\n")

if __name__ == "__main__":
    main()
