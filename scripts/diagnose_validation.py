"""Diagnostic script for Step B: Evaluate on validation set to diagnose field extraction, PII, and STP."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import difflib
import json
from pathlib import Path
import re
from typing import Any, Dict, List

from app.adapters.classifier import ALL_CLASSES, get_classifier
from app.adapters.ocr import get_ocr_engine
from app.adapters.pii import get_pii_detector
from app.workers.stages import (
    stage_audit_record,
    stage_classify,
    stage_decision_gate,
    stage_extract_fields,
    stage_pii_detect,
)

BASE_DIR = Path(__file__).resolve().parent.parent
VAL_DIR = BASE_DIR / "data" / "dataset" / "val"
CACHE_DIR = BASE_DIR / "data" / "dataset" / "val_ocr_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def get_ocr_for_doc(doc_id: str, pdf_path: Path, ocr_engine) -> str:
    cache_file = CACHE_DIR / f"{doc_id}.json"
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)["full_text"]

    with open(pdf_path, "rb") as pf:
        res = ocr_engine.extract_text(pf.read(), "pdf")
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump({"full_text": res.full_text, "engine": res.engine_name, "version": res.engine_version}, f)
    return res.full_text

def run_diagnostics():
    print("=" * 75)
    print("DIAGNOSTIC RUN ON VALIDATION SET (360 Scans)")
    print("=" * 75)

    json_files = sorted(list(VAL_DIR.glob("*.json")))
    ocr_engine = get_ocr_engine()

    total_fields_expected = 0
    total_fields_correct = 0
    per_class_fields = defaultdict(lambda: {"expected": 0, "correct": 0})
    per_field_stats = defaultdict(lambda: {"expected": 0, "correct": 0})
    field_failures = defaultdict(list)

    pii_entity_stats = defaultdict(lambda: {"tp": 0, "fn": 0, "fp": 0})
    pii_false_positives_examples = []

    review_reasons = defaultdict(int)
    auto_accepted_count = 0
    review_count = 0

    cls_correct = 0
    cls_total = len(json_files)

    print("Pre-warming OCR cache with 4 parallel threads on 360 validation scans...")
    def warm(jf):
        with open(jf, "r", encoding="utf-8") as f:
            d = json.load(f)
        did = d["doc_id"]
        pp = VAL_DIR / f"{did}.pdf"
        get_ocr_for_doc(did, pp, ocr_engine)

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(warm, json_files))
    print("OCR extraction complete for 360 files.\n")

    for idx, jf in enumerate(json_files, 1):
        with open(jf, "r", encoding="utf-8") as f:
            gt = json.load(f)

        doc_type = gt["doc_type"]
        doc_id = gt["doc_id"]
        gt_fields = gt.get("fields", {})
        gt_pii = gt.get("pii_entities", [])
        sha256 = gt.get("sha256", "sha")

        pdf_path = VAL_DIR / f"{doc_id}.pdf"
        assert pdf_path.exists(), f"PDF not found: {pdf_path}"
        eval_text = get_ocr_for_doc(doc_id, pdf_path, ocr_engine)

        # 1. Classification
        cls_res = stage_classify(eval_text)
        pred_class = cls_res["predicted_class"]
        conf = cls_res["confidence"]
        if pred_class == doc_type:
            cls_correct += 1

        # 2. Field Extraction
        ext_fields, field_confs, is_valid = stage_extract_fields(eval_text, pred_class)
        for fk, fv in gt_fields.items():
            total_fields_expected += 1
            per_class_fields[doc_type]["expected"] += 1
            per_field_stats[fk]["expected"] += 1

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
                total_fields_correct += 1
                per_class_fields[doc_type]["correct"] += 1
                per_field_stats[fk]["correct"] += 1
            else:
                field_failures[fk].append({
                    "doc_id": doc_id,
                    "doc_type": doc_type,
                    "expected": fv,
                    "extracted": ext_val,
                    "ocr_snippet": eval_text[:200].replace("\n", " "),
                })

        # 3. PII Detection
        pii_res = stage_pii_detect(eval_text)
        pred_entities = pii_res["entities"]
        pred_types = set(p.get("entity_type") for p in pred_entities)
        gt_types = set(p["type"] for p in gt_pii)

        for p in gt_pii:
            pt = p["type"]
            matched = any(pe.get("entity_type") == pt for pe in pred_entities)
            if matched:
                pii_entity_stats[pt]["tp"] += 1
            else:
                pii_entity_stats[pt]["fn"] += 1

        for pe in pred_entities:
            pt = pe.get("entity_type")
            matched = any(p["type"] == pt for p in gt_pii)
            if not matched:
                pii_entity_stats[pt]["fp"] += 1
                if len(pii_false_positives_examples) < 20:
                    pii_false_positives_examples.append({
                        "doc_id": doc_id,
                        "type": pt,
                        "text": pe.get("text", ""),
                        "ocr_snippet": eval_text[:150].replace("\n", " "),
                    })

        # 4. Decision Gate
        decision = stage_decision_gate(pred_class, conf, pii_res)
        if decision.action == "AUTO_ACCEPT":
            auto_accepted_count += 1
        else:
            review_count += 1
            review_reasons[decision.reason] += 1

    # -----------------------------------------------------------------------
    # Output Diagnostics
    # -----------------------------------------------------------------------
    print(f"\nClassification Accuracy on Val: {cls_correct}/{cls_total} = {cls_correct/cls_total*100:.2f}%")
    print(f"Overall Field Extraction Accuracy: {total_fields_correct}/{total_fields_expected} = {total_fields_correct/max(1, total_fields_expected)*100:.2f}%\n")

    print("PER-CLASS FIELD EXTRACTION ACCURACY:")
    print(f"{'Class':<20} {'Expected':<12} {'Correct':<12} {'Accuracy':<10}")
    print("-" * 55)
    for c in ALL_CLASSES:
        if c == "unknown":
            continue
        exp = per_class_fields[c]["expected"]
        corr = per_class_fields[c]["correct"]
        acc = corr / max(1, exp) * 100
        print(f"{c:<20} {exp:<12} {corr:<12} {acc:.2f}%")

    print("\nPER-FIELD EXTRACTION ACCURACY:")
    print(f"{'Field Name':<25} {'Expected':<12} {'Correct':<12} {'Accuracy':<10}")
    print("-" * 60)
    sorted_fields = sorted(per_field_stats.items(), key=lambda x: x[1]["correct"]/max(1, x[1]["expected"]))
    for fk, st in sorted_fields:
        acc = st["correct"] / max(1, st["expected"]) * 100
        print(f"{fk:<25} {st['expected']:<12} {st['correct']:<12} {acc:.2f}%")

    print("\n10 WORST FIELDS AND SAMPLE FAILURES:")
    for fk, st in sorted_fields[:10]:
        acc = st["correct"] / max(1, st["expected"]) * 100
        print(f"\nField: {fk} (Accuracy: {acc:.2f}%, Failures: {len(field_failures[fk])})")
        for fail in field_failures[fk][:3]:
            print(f"  Doc: {fail['doc_id']} ({fail['doc_type']}) | Expected: '{fail['expected']}' | Extracted: '{fail['extracted']}'")
            print(f"    OCR: {fail['ocr_snippet'][:120]}...")

    print("\n" + "=" * 75)
    print("PII RECALL & PRECISION PER ENTITY TYPE:")
    print(f"{'Entity Type':<20} {'TP':<8} {'FN':<8} {'FP':<8} {'Recall':<12} {'Precision':<12}")
    print("-" * 75)
    total_tp = sum(s["tp"] for s in pii_entity_stats.values())
    total_fn = sum(s["fn"] for s in pii_entity_stats.values())
    total_fp = sum(s["fp"] for s in pii_entity_stats.values())
    for pt, s in sorted(pii_entity_stats.items()):
        rec = s["tp"] / max(1, s["tp"] + s["fn"]) * 100
        prec = s["tp"] / max(1, s["tp"] + s["fp"]) * 100
        print(f"{pt:<20} {s['tp']:<8} {s['fn']:<8} {s['fp']:<8} {rec:.2f}%{'':<6} {prec:.2f}%")
    overall_rec = total_tp / max(1, total_tp + total_fn) * 100
    overall_prec = total_tp / max(1, total_tp + total_fp) * 100
    print("-" * 75)
    print(f"{'OVERALL':<20} {total_tp:<8} {total_fn:<8} {total_fp:<8} {overall_rec:.2f}%{'':<6} {overall_prec:.2f}%")

    print("\nTOP SOURCES OF FALSE POSITIVES:")
    for ex in pii_false_positives_examples[:5]:
        print(f"  Doc: {ex['doc_id']} | Type: {ex['type']} | Text: '{ex['text']}' | Context: {ex['ocr_snippet']}")

    print("\n" + "=" * 75)
    print(f"STRAIGHT-THROUGH RATE (STP): {auto_accepted_count}/{cls_total} = {auto_accepted_count/cls_total*100:.2f}%")
    print(f"REVIEW RATE: {review_count}/{cls_total} = {review_count/cls_total*100:.2f}%")
    print("REVIEW REASONS BREAKDOWN:")
    for r, cnt in review_reasons.items():
        print(f"  - Count: {cnt:<4} | Reason: {r}")
    print("=" * 75)

if __name__ == "__main__":
    run_diagnostics()
