"""Unified PII evaluation on Holdout 3 [DEVELOPMENT SET] using a single shared matcher.
Evaluates all 8 ground truth entity types directly from the JSON files:
EMAIL_ADDRESS, IBAN_CODE, MEDICAL_LICENSE, PASSPORT, PERSON, PHONE_NUMBER, US_EIN, US_SSN.
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.pii import get_pii_detector

TYPE_MAP = {
    "EMAIL": "EMAIL_ADDRESS",
    "EMAIL_ADDRESS": "EMAIL_ADDRESS",
    "PHONE": "PHONE_NUMBER",
    "PHONE_NUMBER": "PHONE_NUMBER",
    "SSN": "US_SSN",
    "US_SSN": "US_SSN",
    "EIN": "US_EIN",
    "US_EIN": "US_EIN",
    "PASSPORT": "PASSPORT",
    "US_PASSPORT": "PASSPORT",
    "IBAN": "IBAN_CODE",
    "IBAN_CODE": "IBAN_CODE",
    "MEDICAL_LICENSE": "MEDICAL_LICENSE",
    "PERSON": "PERSON"
}

def clean_val(v: str) -> str:
    return re.sub(r"[\s\-\(\)\.,:]", "", str(v).lower())

def evaluate_pii_unified():
    print("=" * 80)
    print("UNIFIED PII EVALUATION ON HOLDOUT 3 [DEVELOPMENT SET] - ALL 8 ENTITIES")
    print("=" * 80)

    adapter = get_pii_detector()

    with open("data/ocr_cache_holdout3.json", "r", encoding="utf-8") as f:
        ocr_cache_h3 = json.load(f)

    holdout3_dir = Path("data/dataset/holdout3")
    json_files = sorted([jf for jf in holdout3_dir.glob("*.json") if jf.name != "manifest.json"])

    per_entity = defaultdict(lambda: {"gt": 0, "detected": 0, "tp": 0, "fp": 0, "fn": 0})
    total_gt = 0
    total_det = 0
    total_tp = 0
    total_fp = 0
    total_fn = 0

    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            gt = json.load(f)
        did = gt["doc_id"]
        gt_entities = gt.get("pii_entities", [])

        ocr_rec = ocr_cache_h3.get(did, {})
        text = ocr_rec.get("full_text", "")

        detected = adapter.detect(text)

        # Standardize detected
        norm_det = []
        for d in detected:
            std_t = TYPE_MAP.get(d.entity_type, d.entity_type)
            norm_det.append({
                "type": std_t,
                "text": d.text,
                "clean": clean_val(d.text)
            })

        # Standardize ground truth
        norm_gt = []
        for g in gt_entities:
            raw_t = g.get("type", g.get("entity_type", ""))
            std_t = TYPE_MAP.get(raw_t, raw_t)
            g_text = g.get("text", g.get("value", ""))
            norm_gt.append({
                "type": std_t,
                "text": g_text,
                "clean": clean_val(g_text)
            })

        # Match per entity type
        all_types = set([e["type"] for e in norm_gt] + [d["type"] for d in norm_det])

        for t in all_types:
            t_gt = [e for e in norm_gt if e["type"] == t]
            t_det = [d for d in norm_det if d["type"] == t]

            per_entity[t]["gt"] += len(t_gt)
            per_entity[t]["detected"] += len(t_det)
            total_gt += len(t_gt)
            total_det += len(t_det)

            matched_det = set()
            t_tp = 0
            for g in t_gt:
                g_c = g["clean"]
                found = False
                for idx, d in enumerate(t_det):
                    if idx in matched_det:
                        continue
                    d_c = d["clean"]
                    if g_c == d_c or (len(g_c) >= 5 and (g_c in d_c or d_c in g_c)):
                        matched_det.add(idx)
                        t_tp += 1
                        found = True
                        break

            t_fp = len(t_det) - t_tp
            t_fn = len(t_gt) - t_tp

            per_entity[t]["tp"] += t_tp
            per_entity[t]["fp"] += t_fp
            per_entity[t]["fn"] += t_fn
            total_tp += t_tp
            total_fp += t_fp
            total_fn += t_fn

    print(f"\n{'Entity Type':<18} | {'GT':<6} | {'Det':<6} | {'TP':<6} | {'FP':<6} | {'Recall %':<10} | {'Precision %':<12}")
    print("-" * 75)
    for et in sorted(per_entity.keys()):
        st = per_entity[et]
        rec = (st["tp"] / st["gt"] * 100) if st["gt"] > 0 else 0.0
        prec = (st["tp"] / st["detected"] * 100) if st["detected"] > 0 else 0.0
        print(f"{et:<18} | {st['gt']:<6} | {st['detected']:<6} | {st['tp']:<6} | {st['fp']:<6} | {rec:>8.2f}% | {prec:>10.2f}%")

    print("-" * 75)
    tot_rec = (total_tp / total_gt * 100) if total_gt > 0 else 0.0
    tot_prec = (total_tp / total_det * 100) if total_det > 0 else 0.0
    print(f"{'OVERALL':<18} | {total_gt:<6} | {total_det:<6} | {total_tp:<6} | {total_fp:<6} | {tot_rec:>8.2f}% | {tot_prec:>10.2f}%")

    print(f"\nTarget Verification:")
    print(f"  Target: Recall >= 98.0%, Precision >= 80.0%")
    status_rec = "PASS" if tot_rec >= 98.0 else "NOT MET (Phase 2 remains OPEN)"
    status_prec = "PASS" if tot_prec >= 80.0 else "NOT MET"
    print(f"  Overall Recall   : {tot_rec:.2f}% -> {status_rec}")
    print(f"  Overall Precision: {tot_prec:.2f}% -> {status_prec}")

if __name__ == "__main__":
    evaluate_pii_unified()
