import re
import sys
import json
import time
import difflib
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

def parse_and_normalize_date(raw_s: str):
    if not raw_s:
        return None
    # DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    m = re.search(r'\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b', raw_s)
    if m:
        d, m_val, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= d <= 31 and 1 <= m_val <= 12:
            return f"{y:04d}-{m_val:02d}-{d:02d}"
    # YYYY-MM-DD
    m2 = re.search(r'\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b', raw_s)
    if m2:
        y, m_val, d = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
        if 1 <= d <= 31 and 1 <= m_val <= 12:
            return f"{y:04d}-{m_val:02d}-{d:02d}"
    # DD/MM/YY
    m3 = re.search(r'\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2})\b', raw_s)
    if m3:
        d, m_val, y_short = int(m3.group(1)), int(m3.group(2)), int(m3.group(3))
        y = 2000 + y_short if y_short < 70 else 1900 + y_short
        if 1 <= d <= 31 and 1 <= m_val <= 12:
            return f"{y:04d}-{m_val:02d}-{d:02d}"
    return None

def extract_receipt_total(text: str):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # Search backwards for Grand Total or Total
    for line in reversed(lines):
        u = line.upper()
        if "SUBTOTAL" in u or "SUB TOTAL" in u or "TAX" in u or "CHANGE" in u or "CASH" in u:
            continue
        if "GRAND TOTAL" in u or "TOTAL" in u or "NET AMOUNT" in u or "AMOUNT DUE" in u:
            m = re.search(r'([0-9]+\.[0-9]{2})', line)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    pass
    return None

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.ocr import get_ocr_engine
from app.workers.stages import (
    stage_classify, stage_extract_fields, stage_pii_detect,
    stage_decision_gate, stage_audit_record
)

OCR_CACHE_SROIE = Path("data/real_sroie/ocr_cache_dev.json")

def get_sroie_ocr_cache(dev_records):
    cache = {}
    if OCR_CACHE_SROIE.exists():
        try:
            with open(OCR_CACHE_SROIE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            print(f"Loaded {len(cache)} cached SROIE OCR records.", flush=True)
        except Exception:
            cache = {}
            
    missing = [d for d in dev_records if d["doc_id"] not in cache]
    if missing:
        print(f"Extracting OCR for {len(missing)} real SROIE receipts using UB-Mannheim Tesseract 5.4.0 (4 threads)...", flush=True)
        ocr_engine = get_ocr_engine()
        t0 = time.time()
        
        def worker(d):
            img_path = Path(d["image_file"])
            with open(img_path, "rb") as pf:
                b = pf.read()
            res = ocr_engine.extract_text(b, "jpg")
            return d["doc_id"], {
                "full_text": res.full_text,
                "engine_name": res.engine_name,
                "engine_version": res.engine_version
            }

        with ThreadPoolExecutor(max_workers=4) as ex:
            for i, (did, rec) in enumerate(ex.map(worker, missing), 1):
                cache[did] = rec
                if i % 10 == 0 or i == len(missing):
                    print(f"  SROIE OCR progress: {i}/{len(missing)} done ({time.time()-t0:.1f}s)...", flush=True)
                    
        with open(OCR_CACHE_SROIE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        print(f"SROIE OCR cache saved to {OCR_CACHE_SROIE}", flush=True)
        
    return cache

def evaluate_sroie_dev():
    with open("data/real_sroie/dataset/annotations.json", "r", encoding="utf-8") as f:
        all_records = json.load(f)

    # 50% Dev / 50% Sealed Split
    half = len(all_records) // 2
    dev_records = all_records[:half]
    sealed_records = all_records[half:]

    split_info = {
        "dataset": "ICDAR 2019 SROIE (Scanned Receipts OCR and Information Extraction)",
        "source": "https://huggingface.co/datasets/jsdnrs/ICDAR2019-SROIE",
        "total_receipts": len(all_records),
        "dev_count": len(dev_records),
        "sealed_count": len(sealed_records),
        "dev_ids": [r["doc_id"] for r in dev_records],
        "sealed_ids": [r["doc_id"] for r in sealed_records]
    }
    with open("data/real_sroie/splits.json", "w", encoding="utf-8") as f:
        json.dump(split_info, f, indent=2)

    print("=" * 80)
    print("REAL DOCUMENT BASELINE EVALUATION: SROIE RECEIPTS DEV SET (50 RECEIPTS)")
    print("=" * 80)
    print(f"Total Dev Receipts: {len(dev_records)} (50 Sealed Receipts held for Blind Test)")

    ocr_cache = get_sroie_ocr_cache(dev_records)

    field_stats = {
        "vendor_name": {"correct": 0, "expected": 0},
        "invoice_date": {"correct": 0, "expected": 0},
        "total_amount": {"correct": 0, "expected": 0},
        "vendor_address": {"correct": 0, "expected": 0}
    }

    class_counts = defaultdict(int)
    auto_accepted = 0

    for r in dev_records:
        did = r["doc_id"]
        gt = r["ground_truth"]
        ocr_rec = ocr_cache[did]
        text = ocr_rec["full_text"]

        # 1. Classification
        cls_res = stage_classify(text)
        pred_cls = cls_res["predicted_class"]
        conf = cls_res["confidence"]
        class_counts[pred_cls] += 1

        # 2. Field Extraction (Receipts map to invoice / purchase_order schema)
        ext_fields, field_confs, is_valid = stage_extract_fields(text, "invoice")
        
        # Also run direct receipt key extraction for vendor/total/date/address
        for fk in ["vendor_name", "invoice_date", "total_amount", "vendor_address"]:
            expected_val = gt.get(fk)
            if not expected_val:
                continue
            field_stats[fk]["expected"] += 1
            extracted_val = ext_fields.get(fk)
            
            # If standard invoice extractor missed vendor_name on receipts,
            # receipt headers usually have the company on the first 1-3 lines
            if fk == "vendor_name" and not extracted_val:
                lines = [line.strip() for line in text.split("\n") if len(line.strip()) > 3]
                if lines:
                    extracted_val = lines[0]
            elif fk == "invoice_date":
                if not extracted_val:
                    date_iso = parse_and_normalize_date(text)
                    if date_iso:
                        extracted_val = date_iso
                else:
                    extracted_val = parse_and_normalize_date(str(extracted_val)) or extracted_val
            elif fk == "total_amount":
                rtot = extract_receipt_total(text)
                if rtot is not None:
                    extracted_val = rtot

            match = False
            if extracted_val is not None and expected_val is not None:
                exp_s = str(expected_val).strip().lower()
                ext_s = str(extracted_val).strip().lower()
                
                if fk == "invoice_date":
                    exp_iso = parse_and_normalize_date(exp_s)
                    ext_iso = parse_and_normalize_date(ext_s)
                    if exp_iso and ext_iso and exp_iso == ext_iso:
                        match = True
                    elif exp_s == ext_s:
                        match = True
                elif fk == "total_amount":
                    try:
                        exp_num = float(re.sub(r"[^\d.]", "", exp_s))
                        ext_num = float(re.sub(r"[^\d.]", "", ext_s))
                        if abs(exp_num - ext_num) < 0.05:
                            match = True
                    except Exception:
                        pass
                else:
                    if exp_s == ext_s:
                        match = True
                    else:
                        ratio = difflib.SequenceMatcher(None, exp_s, ext_s).ratio()
                        if ratio >= 0.70 or exp_s in ext_s or ext_s in exp_s:
                            match = True

            if match:
                field_stats[fk]["correct"] += 1

    print("\n--- SROIE REAL DOCUMENT FIELD EXTRACTION ACCURACY (DEV HALF) ---")
    print(f"{'Field Name':<20} | {'Extracted':<10} | {'Expected':<10} | {'Accuracy (%)':<12}")
    print("-" * 60)
    total_corr = 0
    total_exp = 0
    for fk, st in field_stats.items():
        corr = st["correct"]
        exp = st["expected"]
        acc = (corr / exp * 100) if exp > 0 else 0.0
        print(f"{fk:<20} | {corr:<10} | {exp:<10} | {acc:<12.2f}")
        total_corr += corr
        total_exp += exp

    overall_acc = (total_corr / total_exp * 100) if total_exp > 0 else 0.0
    print("-" * 60)
    print(f"{'OVERALL FIELDS':<20} | {total_corr:<10} | {total_exp:<10} | {overall_acc:<12.2f}")

    print("\n--- CLASSIFICATION ON REAL RECEIPTS ---")
    for cls, cnt in class_counts.items():
        print(f"  - {cls:<16}: {cnt} ({cnt/len(dev_records)*100:.1f}%)")
    print("=" * 80)

if __name__ == "__main__":
    evaluate_sroie_dev()
