import json
import re
from pathlib import Path
from collections import defaultdict
import fitz

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.ocr import get_ocr_engine
from app.workers.stages import stage_extract_fields

def categorize_failure(expected, extracted, full_ocr_text, field_name):
    # Check if expected value is present anywhere in OCR text
    exp_str = str(expected).strip()
    ext_str = str(extracted).strip()
    
    if exp_str in full_ocr_text:
        return "format variation"  # Value was present in OCR text, but regex didn't extract it cleanly
        
    # Check if a close variant (OCR confusion) is present
    norm_exp = exp_str.lower().replace("o", "0").replace("l", "1").replace("i", "1").replace("s", "5").replace("b", "8")
    norm_ocr = full_ocr_text.lower().replace("o", "0").replace("l", "1").replace("i", "1").replace("s", "5").replace("b", "8")
    if norm_exp in norm_ocr:
        return "OCR error"
        
    # Check if field name label appears in text
    field_keywords = field_name.split("_")
    label_found = any(kw.lower() in full_ocr_text.lower() for kw in field_keywords)
    if not label_found:
        return "label not found"
        
    return "OCR error"

def main():
    val_dir = Path("data/dataset/val")
    json_files = sorted(list(val_dir.glob("*.json")))
    
    engine = get_ocr_engine()
    
    field_stats = defaultdict(lambda: {"total": 0, "correct": 0, "failures": []})
    class_stats = defaultdict(lambda: {"total": 0, "correct": 0})
    category_counts = defaultdict(int)
    
    print(f"Diagnosing field extraction on {len(json_files)} validation documents...", flush=True)
    
    for idx_doc, jf in enumerate(json_files):
        if idx_doc > 0 and idx_doc % 50 == 0:
            print(f"  Processed {idx_doc}/{len(json_files)} docs...", flush=True)
        with open(jf, "r", encoding="utf-8") as f:
            meta = json.load(f)
        doc_type = meta["doc_type"]
        if doc_type == "unknown":
            continue
            
        pdf_path = val_dir / meta["file_name"]
        with open(pdf_path, "rb") as pf:
            pdf_bytes = pf.read()
            
        ocr_res = engine.extract_text(pdf_bytes, "pdf")
        ocr_text = ocr_res.full_text
        
        extracted_fields, confidences, is_valid = stage_extract_fields(ocr_text, doc_type)
        
        gt_fields = meta.get("fields", {})
        for fname, exp_val in gt_fields.items():
            ext_val = extracted_fields.get(fname)
            key = f"{doc_type}.{fname}"
            field_stats[key]["total"] += 1
            class_stats[doc_type]["total"] += 1
            
            # Comparison logic
            is_match = False
            if isinstance(exp_val, (int, float)) and ext_val is not None:
                try:
                    is_match = abs(float(exp_val) - float(ext_val)) < 0.05
                except Exception:
                    is_match = False
            else:
                s_exp = str(exp_val).strip().lower()
                s_ext = str(ext_val).strip().lower()
                is_match = (s_exp == s_ext)
                
            if is_match:
                field_stats[key]["correct"] += 1
                class_stats[doc_type]["correct"] += 1
            else:
                cat = categorize_failure(exp_val, ext_val, ocr_text, fname)
                category_counts[cat] += 1
                field_stats[key]["failures"].append({
                    "doc_id": meta["doc_id"],
                    "expected": exp_val,
                    "extracted": ext_val,
                    "category": cat,
                    "ocr_snippet": ocr_text[:300].replace("\n", " ")
                })

    print("=" * 80)
    print("OVERALL & PER-CLASS FIELD ACCURACY ON VAL")
    print("=" * 80)
    total_f = sum(v["total"] for v in class_stats.values())
    correct_f = sum(v["correct"] for v in class_stats.values())
    acc = (correct_f / total_f * 100.0) if total_f > 0 else 0.0
    print(f"Total Fields: {total_f} | Correct: {correct_f} | Overall Accuracy: {acc:.2f}%\n")
    
    for cname in sorted(class_stats.keys()):
        ctot = class_stats[cname]["total"]
        ccorr = class_stats[cname]["correct"]
        cacc = (ccorr / ctot * 100.0) if ctot > 0 else 0.0
        print(f"  Class {cname:<16}: {ccorr:3d}/{ctot:3d} ({cacc:6.2f}%)")

    print("\n" + "=" * 80)
    print("FAILURE CATEGORY COUNTS")
    print("=" * 80)
    for cat, cnt in sorted(category_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {cat:<25}: {cnt:4d} ({cnt/sum(category_counts.values())*100:.1f}%)")

    # Sort fields by failure rate
    sorted_fields = sorted(field_stats.items(), key=lambda item: (item[1]["correct"] / item[1]["total"] if item[1]["total"] else 1.0))
    
    print("\n" + "=" * 80)
    print("TOP 10 FAILING FIELDS (WITH 3 DETAILED EXAMPLES EACH)")
    print("=" * 80)
    for key, fval in sorted_fields[:10]:
        tot = fval["total"]
        cor = fval["correct"]
        fail = tot - cor
        facc = (cor / tot * 100.0) if tot > 0 else 0.0
        print(f"\nField: {key:<30} | Accuracy: {facc:5.1f}% ({cor}/{tot}, Failures: {fail})")
        for i, example in enumerate(fval["failures"][:3], 1):
            print(f"  Example {i} [{example['doc_id']}] (Category: {example['category']}):")
            print(f"    Expected : '{example['expected']}'")
            print(f"    Extracted: '{example['extracted']}'")
            print(f"    OCR Text : '{example['ocr_snippet']}...'")

if __name__ == "__main__":
    main()
