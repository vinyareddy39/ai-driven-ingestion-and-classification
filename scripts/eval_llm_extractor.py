"""Evaluate LLMFieldExtractor on Holdout 2 and Holdout 3 [DEVELOPMENT SETS].
Measures:
- Field accuracy per class and per field
- Visual grounding failure rate (values rejected because not grounded in raw OCR)
- Token consumption and dollar cost per document
- Per-document execution latency
"""

import difflib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.workers.field_extractor import LLMFieldExtractor, CLASS_SCHEMAS

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

def evaluate_split(split_name: str, ocr_cache_path: str, data_dir_path: str):
    print("=" * 80)
    print(f"LLM FIELD EXTRACTOR EVALUATION: {split_name} [DEVELOPMENT SET]")
    print("=" * 80)

    with open(ocr_cache_path, "r", encoding="utf-8") as f:
        ocr_cache = json.load(f)

    data_dir = Path(data_dir_path)
    json_files = sorted([jf for jf in data_dir.glob("*.json") if jf.name != "manifest.json"])

    extractor = LLMFieldExtractor()

    stats_class = defaultdict(lambda: {"expected": 0, "extracted": 0, "accurate": 0})
    stats_field = defaultdict(lambda: {"expected": 0, "accurate": 0})
    total_expected = 0
    total_extracted = 0
    total_accurate = 0

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
            total_expected += 1
            stats_class[doc_cls]["expected"] += 1
            stats_field[f"{doc_cls}.{fk}"]["expected"] += 1

            ext_v = ext_fields.get(fk)
            if ext_v is not None:
                total_extracted += 1
                stats_class[doc_cls]["extracted"] += 1

            if is_field_accurate(ext_v, fv):
                total_accurate += 1
                stats_class[doc_cls]["accurate"] += 1
                stats_field[f"{doc_cls}.{fk}"]["accurate"] += 1

    overall_acc = (total_accurate / total_expected * 100) if total_expected > 0 else 0.0
    grounding_fail_rate = (extractor.grounding_failures / (extractor.total_docs * 4) * 100) if extractor.total_docs > 0 else 0.0
    avg_cost_doc = extractor.total_cost / extractor.total_docs if extractor.total_docs > 0 else 0.0

    print(f"\n--- PER-CLASS ACCURACY ({split_name}) ---")
    print(f"{'Class Name':<18} | {'Expected':<10} | {'Extracted':<10} | {'Accurate':<10} | {'Accuracy %':<12}")
    print("-" * 68)
    for c in sorted(stats_class.keys()):
        st = stats_class[c]
        acc_pct = (st["accurate"] / st["expected"] * 100) if st["expected"] > 0 else 0.0
        print(f"{c:<18} | {st['expected']:<10} | {st['extracted']:<10} | {st['accurate']:<10} | {acc_pct:>9.2f}%")
    print("-" * 68)
    print(f"{'OVERALL':<18} | {total_expected:<10} | {total_extracted:<10} | {total_accurate:<10} | {overall_acc:>9.2f}%")

    print(f"\n--- LLM COST, LATENCY & GROUNDING METRICS ({split_name}) ---")
    print(f"Total Documents Evaluated:    {extractor.total_docs}")
    print(f"Total Tokens Modeled:         {extractor.total_tokens:,} tokens")
    print(f"Tokens per Document:          {extractor.total_tokens / extractor.total_docs:.1f} tokens/doc")
    print(f"Total Modeled Cost:           ${extractor.total_cost:.5f}")
    print(f"Cost per Document:            ${avg_cost_doc:.6f} / doc")
    print(f"Visual Grounding Failures:    {extractor.grounding_failures} fields rejected")
    print(f"Grounding Failure Rate:       {grounding_fail_rate:.2f}%")
    print(f"Execution Latency p50:        {np.percentile(extractor.latency_records, 50)*1000:.2f} ms")
    print(f"Execution Latency p95:        {np.percentile(extractor.latency_records, 95)*1000:.2f} ms")
    print(f"Execution Latency Mean:       {np.mean(extractor.latency_records)*1000:.2f} ms")

def main():
    evaluate_split("Holdout 3 (Family v2)", "data/ocr_cache_holdout3.json", "data/dataset/holdout3")
    print("\n\n")
    evaluate_split("Holdout 2 (Family v1)", "data/ocr_cache_holdout2.json", "data/dataset/holdout2")

if __name__ == "__main__":
    main()
