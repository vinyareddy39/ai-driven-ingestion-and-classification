"""Extract 3 failure examples with raw OCR text for weak fields:
1. medical_report.patient_id
2. bank_statement.account_number
3. letter.sender
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.workers.field_extractor import SemanticGroundedExtractor
from app.workers.generic_extractor import GenericKeyValueExtractor

def normalize_val(val) -> str:
    if val is None:
        return ""
    s = str(val).strip().lower()
    s = re.sub(r"[/.]", "-", s)
    s = re.sub(r"\s+", " ", s)
    return s

def is_field_accurate(extracted, expected) -> bool:
    if extracted is None or expected is None:
        return False
    norm_ext = normalize_val(extracted)
    norm_exp = normalize_val(expected)
    if not norm_ext or not norm_exp:
        return False
    if norm_ext == norm_exp:
        return True
    if len(norm_exp) >= 6 and (norm_exp in norm_ext or norm_ext in norm_exp):
        return True
    return False

def main():
    print("=" * 80)
    print("WEAK FIELD DIAGNOSIS: 3 FAILURE EXAMPLES WITH RAW OCR TEXT")
    print("=" * 80)

    with open("data/ocr_cache_holdout3.json", "r", encoding="utf-8") as f:
        ocr_cache = json.load(f)

    holdout3_dir = Path("data/dataset/holdout3")
    json_files = sorted([jf for jf in holdout3_dir.glob("*.json") if jf.name != "manifest.json"])

    sem_ext = SemanticGroundedExtractor(fallback_extractor=GenericKeyValueExtractor())

    targets = {
        "medical_report": "patient_id",
        "bank_statement": "account_number",
        "letter": "sender"
    }

    failures = {k: [] for k in targets}

    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            gt = json.load(f)
        doc_cls = gt["doc_type"]
        if doc_cls not in targets:
            continue
        target_fld = targets[doc_cls]
        gt_fields = gt.get("fields", {})
        if target_fld not in gt_fields:
            continue

        exp_val = gt_fields[target_fld]
        did = gt["doc_id"]
        ocr_text = ocr_cache.get(did, {}).get("full_text", "")

        ext_fields, confs, _ = sem_ext.extract(ocr_text, doc_cls)
        ext_val = ext_fields.get(target_fld)

        if not is_field_accurate(ext_val, exp_val):
            failures[doc_cls].append({
                "doc_id": did,
                "field": target_fld,
                "expected": exp_val,
                "extracted": ext_val,
                "ocr_snippet": ocr_text[:600]
            })

    for doc_cls, fld in targets.items():
        print(f"\n=======================================================")
        print(f"CLASS: {doc_cls} | FIELD: {fld}")
        print(f"Total Failures Found: {len(failures[doc_cls])}")
        print(f"=======================================================")
        for i, fail in enumerate(failures[doc_cls][:3], 1):
            print(f"\n--- Failure Example #{i} (Doc ID: {fail['doc_id']}) ---")
            print(f"Expected Field Value : '{fail['expected']}'")
            print(f"Extracted Field Value: '{fail['extracted']}'")
            print(f"Raw OCR Text Snippet :\n\"\"\"\n{fail['ocr_snippet'].strip()}\n\"\"\"")

if __name__ == "__main__":
    main()
