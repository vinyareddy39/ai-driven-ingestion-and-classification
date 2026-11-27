"""Diagnose SROIE 50 Dev Receipts Extraction Failures.

Runs extraction only (forced doc_type='invoice', no classifier).
Categorizes every field failure into:
- Extractor not run (field not in schema)
- OCR dropped value (ground truth not present in OCR text)
- Value present but unmatched (present in OCR text but not extracted correctly)
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.workers.stages import stage_extract_fields

def clean_str(s):
    if s is None:
        return ""
    return re.sub(r"[^\w\d]", "", str(s).lower())

def is_val_in_ocr(expected_val, ocr_text):
    if not expected_val or not ocr_text:
        return False
    exp_c = clean_str(expected_val)
    ocr_c = clean_str(ocr_text)
    if exp_c in ocr_c:
        return True
    # If date, check components
    m = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})', str(expected_val))
    if m:
        d, mo, yr = m.groups()
        if f"{int(d)}" in ocr_text and f"{int(mo)}" in ocr_text:
            return True
    # If number, check numeric string
    num_m = re.search(r'(\d+\.\d{2})', str(expected_val))
    if num_m and num_m.group(1) in ocr_text:
        return True
    return False

def matches_expected(extracted_val, expected_val, field_name):
    if extracted_val is None or expected_val is None:
        return False
    ext_s = str(extracted_val).strip().lower()
    exp_s = str(expected_val).strip().lower()

    if field_name == "total_amount":
        try:
            ext_num = float(re.sub(r"[^\d.]", "", ext_s))
            exp_num = float(re.sub(r"[^\d.]", "", exp_s))
            return abs(ext_num - exp_num) < 0.05
        except Exception:
            pass
    elif field_name == "invoice_date":
        # Check date equivalence
        ext_c = re.sub(r"[^\d]", "", ext_s)
        exp_c = re.sub(r"[^\d]", "", exp_s)
        if ext_c == exp_c:
            return True
        # Check standard ISO comparison
        m_exp = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})', exp_s)
        m_ext = re.search(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})', ext_s)
        if m_exp and m_ext:
            d, m, y = int(m_exp.group(1)), int(m_exp.group(2)), int(m_exp.group(3))
            y2, m2, d2 = int(m_ext.group(1)), int(m_ext.group(2)), int(m_ext.group(3))
            if y == y2 and m == m2 and d == d2:
                return True
    else:
        ext_c = clean_str(ext_s)
        exp_c = clean_str(exp_s)
        if ext_c == exp_c or exp_c in ext_c or ext_c in exp_c:
            return True
    return False

def main():
    with open("data/real_sroie/ocr_cache_dev.json", "r", encoding="utf-8") as f:
        ocr_cache = json.load(f)

    with open("data/real_sroie/dataset/annotations.json", "r", encoding="utf-8") as f:
        annotations = json.load(f)[:50]

    schema_fields = ["vendor_name", "invoice_date", "total_amount"]
    all_fields = ["vendor_name", "invoice_date", "total_amount", "vendor_address"]

    stats = {
        fk: {"expected": 0, "correct": 0, "not_run": 0, "ocr_dropped": 0, "present_unmatched": 0}
        for fk in all_fields
    }

    for r in annotations:
        did = r["doc_id"]
        gt = r["ground_truth"]
        ocr_text = ocr_cache.get(did, {}).get("full_text", "")

        # Forced doc_type="invoice"
        extracted, confs, _ = stage_extract_fields(ocr_text, "invoice")

        for fk in all_fields:
            exp_val = gt.get(fk)
            if not exp_val:
                continue
            stats[fk]["expected"] += 1
            ext_val = extracted.get(fk)

            if fk not in schema_fields:
                stats[fk]["not_run"] += 1
                continue

            if matches_expected(ext_val, exp_val, fk):
                stats[fk]["correct"] += 1
            else:
                if is_val_in_ocr(exp_val, ocr_text):
                    stats[fk]["present_unmatched"] += 1
                else:
                    stats[fk]["ocr_dropped"] += 1

    print("=" * 80)
    print("SROIE DEV SET (50 RECEIPTS) EXTRACTION-ONLY FAILURE DIAGNOSIS")
    print("=" * 80)
    print(f"{'Field':<16} | {'Expected':<8} | {'Correct':<8} | {'Not Run':<8} | {'OCR Dropped':<11} | {'Present Unmatched':<18}")
    print("-" * 80)
    for fk in all_fields:
        s = stats[fk]
        print(f"{fk:<16} | {s['expected']:<8} | {s['correct']:<8} | {s['not_run']:<8} | {s['ocr_dropped']:<11} | {s['present_unmatched']:<18}")

if __name__ == "__main__":
    main()
