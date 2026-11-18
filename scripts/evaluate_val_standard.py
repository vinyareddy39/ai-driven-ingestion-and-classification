import json
import difflib
from pathlib import Path
from collections import defaultdict
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.ocr import get_ocr_engine
from app.workers.stages import stage_extract_fields

def evaluate_val_fields():
    val_dir = Path("data/dataset/val")
    json_files = sorted(list(val_dir.glob("*.json")))
    engine = get_ocr_engine()
    
    total_expected = 0
    total_correct = 0
    per_class = defaultdict(lambda: {"expected": 0, "correct": 0})
    per_field = defaultdict(lambda: {"expected": 0, "correct": 0, "failures": []})
    
    print(f"Evaluating field accuracy on {len(json_files)} val documents with standard metric...", flush=True)
    for i, jf in enumerate(json_files):
        if i > 0 and i % 50 == 0:
            print(f"  Processed {i}/{len(json_files)}...", flush=True)
        with open(jf, "r", encoding="utf-8") as f:
            meta = json.load(f)
        doc_type = meta["doc_type"]
        if doc_type == "unknown":
            continue
            
        pdf_path = val_dir / meta["file_name"]
        with open(pdf_path, "rb") as pf:
            pdf_bytes = pf.read()
            
        ocr_res = engine.extract_text(pdf_bytes, "pdf")
        ext_fields, _, _ = stage_extract_fields(ocr_res.full_text, doc_type)
        gt_fields = meta.get("fields", {})
        
        for fk, fv in gt_fields.items():
            total_expected += 1
            per_class[doc_type]["expected"] += 1
            per_field[fk]["expected"] += 1
            
            ext_val = ext_fields.get(fk)
            match = False
            if ext_val is not None:
                if str(ext_val).lower().strip() == str(fv).lower().strip():
                    match = True
                elif isinstance(fv, float) and isinstance(ext_val, (int, float)) and abs(ext_val - fv) < 0.01:
                    match = True
                elif difflib.SequenceMatcher(None, str(ext_val).lower().strip(), str(fv).lower().strip()).ratio() >= 0.80:
                    match = True
                    
            if match:
                total_correct += 1
                per_class[doc_type]["correct"] += 1
                per_field[fk]["correct"] += 1
            else:
                per_field[fk]["failures"].append({
                    "doc_id": meta["doc_id"],
                    "expected": fv,
                    "extracted": ext_val,
                    "ocr_snippet": ocr_res.full_text[:200].replace("\n", " ")
                })
                
    acc = total_correct / total_expected * 100.0 if total_expected else 0.0
    print(f"\nOverall Field Accuracy on Val: {total_correct}/{total_expected} ({acc:.2f}%)")
    for c, stats in sorted(per_class.items()):
        c_acc = stats["correct"] / stats["expected"] * 100.0 if stats["expected"] else 0.0
        print(f"  {c:<16}: {stats['correct']:3d}/{stats['expected']:3d} ({c_acc:.2f}%)")
        
    print("\nTop 10 failing fields:")
    sorted_f = sorted(per_field.items(), key=lambda x: x[1]["correct"]/x[1]["expected"] if x[1]["expected"] else 1.0)
    for fk, stats in sorted_f[:10]:
        f_acc = stats["correct"] / stats["expected"] * 100.0 if stats["expected"] else 0.0
        print(f"  {fk:<25}: {stats['correct']:2d}/{stats['expected']:2d} ({f_acc:.2f}%)")
        for fail in stats["failures"][:2]:
            print(f"    Expected: '{fail['expected']}' | Extracted: '{fail['extracted']}'")

if __name__ == "__main__":
    evaluate_val_fields()
