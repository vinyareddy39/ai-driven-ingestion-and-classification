"""Run leave-one-family-out field extraction in BOTH directions:
Direction 1: Tune on Family v1, test on Family v2 (Holdout 3)
Direction 2: Tune on Family v2, test on Family v1 (Holdout 2)
"""

import difflib
import json
import re
import sys
import time
from collections import defaultdict
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
    try:
        ext_clean = re.sub(r"[^\d.]", "", str(extracted))
        exp_clean = re.sub(r"[^\d.]", "", str(expected))
        if ext_clean and exp_clean and "." in exp_clean:
            if abs(float(ext_clean) - float(exp_clean)) < 0.05:
                return True
    except (ValueError, TypeError):
        pass
    norm_ext = normalize_val(extracted)
    norm_exp = normalize_val(expected)
    if not norm_ext or not norm_exp:
        return False
    if norm_ext == norm_exp:
        return True
    if len(norm_exp) >= 6 and (norm_exp in norm_ext or norm_ext in norm_exp):
        return True
    if difflib.SequenceMatcher(None, norm_ext, norm_exp).ratio() >= 0.85:
        return True
    return False

def run_dir_eval(dataset_name: str, ocr_cache_path: str, data_dir_path: str):
    with open(ocr_cache_path, "r", encoding="utf-8") as f:
        ocr_cache = json.load(f)
    data_dir = Path(data_dir_path)
    json_files = sorted([jf for jf in data_dir.glob("*.json") if jf.name != "manifest.json"])

    fallback = GenericKeyValueExtractor()
    extractor = SemanticGroundedExtractor(fallback_extractor=fallback)

    per_class = defaultdict(lambda: {"expected": 0, "accurate": 0})
    total_exp = 0
    total_acc = 0

    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            gt = json.load(f)
        did = gt["doc_id"]
        doc_cls = gt["doc_type"]
        if doc_cls == "unknown":
            continue
        gt_fields = gt.get("fields", {})
        ocr_rec = ocr_cache.get(did, {})
        text = ocr_rec.get("full_text", "")

        ext_fields, confs, is_valid = extractor.extract(text, doc_cls)

        for fk, fv in gt_fields.items():
            total_exp += 1
            per_class[doc_cls]["expected"] += 1
            ext_val = ext_fields.get(fk)
            if is_field_accurate(ext_val, fv):
                total_acc += 1
                per_class[doc_cls]["accurate"] += 1

    return per_class, total_acc, total_exp

def main():
    print("=" * 80)
    print("BIDIRECTIONAL LEAVE-ONE-FAMILY-OUT FIELD EXTRACTION BENCHMARK")
    print("=" * 80)

    # Direction 1: Family v1 -> Test on Family v2 (Holdout 3)
    p_c_1, acc_1, exp_1 = run_dir_eval(
        "Family v2 (Holdout 3)",
        "data/ocr_cache_holdout3.json",
        "data/dataset/holdout3"
    )

    # Direction 2: Family v2 -> Test on Family v1 (Holdout 2)
    p_c_2, acc_2, exp_2 = run_dir_eval(
        "Family v1 (Holdout 2)",
        "data/ocr_cache_holdout2.json",
        "data/dataset/holdout2"
    )

    print(f"\n{'Class Name':<18} | {'Direction 1 (v1 -> v2 Holdout 3)':<30} | {'Direction 2 (v2 -> v1 Holdout 2)':<30}")
    print(f"{'':<18} | {'Accurate / Expected':<20} {'Field %':<8} | {'Accurate / Expected':<20} {'Field %':<8}")
    print("-" * 84)

    all_classes = sorted(set(list(p_c_1.keys()) + list(p_c_2.keys())))
    for cls in all_classes:
        s1 = p_c_1.get(cls, {"accurate": 0, "expected": 0})
        s2 = p_c_2.get(cls, {"accurate": 0, "expected": 0})
        pct1 = (s1["accurate"] / s1["expected"] * 100) if s1["expected"] > 0 else 0.0
        pct2 = (s2["accurate"] / s2["expected"] * 100) if s2["expected"] > 0 else 0.0
        str1 = f"{s1['accurate']:>4} / {s1['expected']:<4} ({pct1:>6.2f}%)"
        str2 = f"{s2['accurate']:>4} / {s2['expected']:<4} ({pct2:>6.2f}%)"
        print(f"{cls:<18} | {str1:<29} | {str2:<29}")

    print("-" * 84)
    tot_pct1 = (acc_1 / exp_1 * 100) if exp_1 > 0 else 0.0
    tot_pct2 = (acc_2 / exp_2 * 100) if exp_2 > 0 else 0.0
    tot_str1 = f"{acc_1:>4} / {exp_1:<4} ({tot_pct1:>6.2f}%)"
    tot_str2 = f"{acc_2:>4} / {exp_2:<4} ({tot_pct2:>6.2f}%)"
    print(f"{'OVERALL':<18} | {tot_str1:<29} | {tot_str2:<29}")

if __name__ == "__main__":
    main()
