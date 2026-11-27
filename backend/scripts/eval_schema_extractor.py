import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import difflib
import time
from collections import defaultdict
from app.workers.field_extractor import SemanticGroundedExtractor, CLASS_SCHEMAS

# Fallback regex extractor
from app.workers.generic_extractor import GenericKeyValueExtractor

def evaluate_cross_family():
    print("=" * 80)
    print("EVALUATING SCHEMA-DRIVEN GROUNDED EXTRACTOR (LEAVE-ONE-FAMILY-OUT)")
    print("=" * 80)

    # Initialize extractor with regex fallback
    fallback = GenericKeyValueExtractor()
    extractor = SemanticGroundedExtractor(fallback_extractor=fallback)

    # Load Holdout 3 (Template Family v2 - 1120 target fields)
    with open("data/ocr_cache_holdout3.json", "r", encoding="utf-8") as f:
        ocr_cache_h3 = json.load(f)

    holdout3_dir = Path("data/dataset/holdout3")
    json_files = sorted([jf for jf in holdout3_dir.glob("*.json") if jf.name != "manifest.json"])

    total_expected = 0
    total_correct = 0
    per_class_stats = defaultdict(lambda: {"expected": 0, "correct": 0})
    per_field_stats = defaultdict(lambda: {"expected": 0, "correct": 0})

    t0 = time.time()
    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            gt = json.load(f)
        did = gt["doc_id"]
        doc_cls = gt["doc_type"]
        gt_fields = gt.get("fields", {})

        ocr_rec = ocr_cache_h3.get(did, {})
        text = ocr_rec.get("full_text", "")

        ext_fields, confs, is_valid = extractor.extract(text, doc_cls)

        for fk, fv in gt_fields.items():
            total_expected += 1
            per_class_stats[doc_cls]["expected"] += 1
            per_field_stats[fk]["expected"] += 1

            ext_val = ext_fields.get(fk)
            match = False
            if ext_val is not None:
                exp_s = str(fv).strip().lower()
                ext_s = str(ext_val).strip().lower()
                if exp_s == ext_s:
                    match = True
                elif isinstance(fv, float) and isinstance(ext_val, (int, float)) and abs(ext_val - fv) < 0.05:
                    match = True
                elif difflib.SequenceMatcher(None, exp_s, ext_s).ratio() >= 0.80:
                    match = True

            if match:
                total_correct += 1
                per_class_stats[doc_cls]["correct"] += 1
                per_field_stats[fk]["correct"] += 1

    elapsed = time.time() - t0
    overall_acc = (total_correct / total_expected * 100) if total_expected > 0 else 0.0
    mean_latency = (elapsed / len(json_files)) * 1000
    grounding_fail_share = (extractor.grounding_failures / extractor.total_extractions * 100) if extractor.total_extractions > 0 else 0.0

    print(f"\n--- CROSS-FAMILY FIELD ACCURACY (Holdout 3: 1120 Fields) ---")
    print(f"{'Class':<20} | {'Correct':<10} | {'Expected':<10} | {'Accuracy (%)':<12}")
    print("-" * 60)
    for cls in sorted(per_class_stats.keys()):
        st = per_class_stats[cls]
        acc = (st["correct"] / st["expected"] * 100) if st["expected"] > 0 else 0.0
        status = "PASS" if acc >= 70.0 else "FAIL"
        print(f"{cls:<20} | {st['correct']:<10} | {st['expected']:<10} | {acc:<12.2f} [{status}]")

    print("-" * 60)
    status_overall = "PASS" if overall_acc >= 85.0 else "FAIL"
    print(f"{'OVERALL':<20} | {total_correct:<10} | {total_expected:<10} | {overall_acc:<12.2f} [{status_overall}]")

    print(f"\n--- OPERATIONAL & COST METRICS ---")
    print(f"Total Evaluated Documents:           {len(json_files)}")
    print(f"Total Evaluated Fields:              {total_expected}")
    print(f"Average Extraction Latency:          {mean_latency:.2f} ms/doc")
    print(f"Throughput:                          {len(json_files)/elapsed:.1f} docs/sec")
    print(f"Cost per Document:                   $0.0000 (Local zero-shot semantic schema execution)")
    print(f"Share of Values Failing Grounding:   {grounding_fail_share:.2f}% ({extractor.grounding_failures}/{extractor.total_extractions})")
    print("=" * 80)

if __name__ == "__main__":
    evaluate_cross_family()
