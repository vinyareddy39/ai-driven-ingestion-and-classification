"""Blind Single-Pass Evaluation on Locked Fresh Holdout 4 (Seed 20261125).

360 pure 300 DPI rasterized scans with no embedded text layer.
100% of scans processed through UB-Mannheim Tesseract 5.4.0 OCR.
Evaluates classification, field extraction, PII recall/precision,
straight-through processing (STP), and audit trail completeness.
"""

import difflib
import json
from pathlib import Path
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.ocr import get_ocr_engine
from app.adapters.pii import match_pii_entity
from app.workers.stages import (
    stage_classify, stage_extract_fields, stage_pii_detect,
    stage_decision_gate, stage_audit_record
)

ALL_CLASSES = [
    "invoice", "contract", "kyc_form", "bank_statement",
    "medical_report", "purchase_order", "letter", "claim_form", "unknown"
]

CACHE_FILE = Path("data/ocr_cache_holdout4.json")


def get_or_build_ocr_cache(holdout_dir: Path, json_files: list) -> dict:
    cache = {}
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            print(f"Loaded {len(cache)} cached Holdout 4 OCR records from {CACHE_FILE}", flush=True)
        except Exception:
            cache = {}

    missing_files = [jf for jf in json_files if jf.stem not in cache]
    if missing_files:
        print(f"Executing Tesseract OCR on {len(missing_files)} Holdout 4 scanned pages with 4 worker threads...", flush=True)
        ocr_engine = get_ocr_engine()
        t0 = time.time()

        def ocr_worker(jf):
            with open(jf, "r", encoding="utf-8") as f:
                gt = json.load(f)
            did = gt["doc_id"]
            pdf_path = holdout_dir / gt["file_name"]
            with open(pdf_path, "rb") as pf:
                b = pf.read()
            res = ocr_engine.extract_text(b, "pdf")
            return did, {
                "full_text": res.full_text,
                "engine_name": res.engine_name,
                "engine_version": res.engine_version
            }

        with ThreadPoolExecutor(max_workers=4) as ex:
            for i, (did, rec) in enumerate(ex.map(ocr_worker, missing_files), 1):
                cache[did] = rec
                if i % 30 == 0 or i == len(missing_files):
                    print(f"  Holdout 4 OCR progress: {i:3d}/{len(missing_files)} done ({time.time()-t0:.1f}s)...", flush=True)

        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        print(f"Holdout 4 OCR cache saved to {CACHE_FILE}\n", flush=True)

    return cache


def run_holdout4_eval():
    holdout_dir = Path("data/dataset/holdout4")
    json_files = sorted([jf for jf in holdout_dir.glob("*.json") if jf.name != "manifest.json"])
    print("=" * 80, flush=True)
    print("FINAL BLIND EVALUATION: LOCKED FRESH HOLDOUT 4 (Seed 20261125)")
    print("=" * 80, flush=True)
    print(f"Total Holdout 4 Scanned Documents: {len(json_files)}", flush=True)

    ocr_cache = get_or_build_ocr_cache(holdout_dir, json_files)

    # Verify OCR engine integrity on sample assets
    sample_engines = set()
    for did, rec in list(ocr_cache.items())[:10]:
        sample_engines.add(f"{rec['engine_name']} v{rec['engine_version']}")
    print(f"OCR Engines Active: {', '.join(sample_engines)}\n", flush=True)

    y_true = []
    y_pred = []
    auto_accepted_true = []
    auto_accepted_pred = []

    total_fields_expected = 0
    total_fields_correct = 0
    per_class_fields = {c: {"expected": 0, "correct": 0} for c in ALL_CLASSES}
    per_field_stats = defaultdict(lambda: {"expected": 0, "correct": 0})

    pii_tp = 0
    pii_fn = 0
    pii_fp = 0
    pii_entity_stats = defaultdict(lambda: {"tp": 0, "fn": 0, "fp": 0})
    pii_fp_examples = []
    pii_miss_examples = []

    auto_accepted_count = 0
    review_count = 0
    audit_complete_count = 0
    review_reasons = defaultdict(int)

    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            gt = json.load(f)
        did = gt["doc_id"]
        doc_type = gt["doc_type"]
        gt_fields = gt.get("fields", {})
        gt_pii = gt.get("pii_entities", [])
        sha256_hash = gt.get("sha256", "hash")

        ocr_rec = ocr_cache[did]
        eval_text = ocr_rec["full_text"]
        ocr_engine_name = ocr_rec["engine_name"]
        ocr_engine_ver = ocr_rec["engine_version"]

        # 1. Classification
        cls_res = stage_classify(eval_text)
        pred_class = cls_res["predicted_class"]
        confidence = cls_res["confidence"]

        y_true.append(doc_type)
        y_pred.append(pred_class)

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
                elif isinstance(fv, float) and isinstance(ext_val, (int, float)) and abs(ext_val - fv) < 0.05:
                    match = True
                elif difflib.SequenceMatcher(None, str(ext_val).lower().strip(), str(fv).lower().strip()).ratio() >= 0.80:
                    match = True

            if match:
                total_fields_correct += 1
                per_class_fields[doc_type]["correct"] += 1
                per_field_stats[fk]["correct"] += 1

        # 3. PII Detection (using unified match_pii_entity)
        pii_res = stage_pii_detect(eval_text)
        pred_entities = pii_res["entities"]

        for p in gt_pii:
            pt = p["type"]
            pval = p.get("value", "")
            matched = match_pii_entity(pt, pval, pred_entities)
            if matched:
                pii_tp += 1
                pii_entity_stats[pt]["tp"] += 1
            else:
                pii_fn += 1
                pii_entity_stats[pt]["fn"] += 1
                if len(pii_miss_examples) < 10:
                    pii_miss_examples.append({
                        "doc_id": did,
                        "type": pt,
                        "expected_val": pval,
                        "snippet": eval_text[:120].replace("\n", " ")
                    })

        for pe in pred_entities:
            pt = pe["entity_type"]
            det_text = pe.get("text", "")
            matched = any(match_pii_entity(p["type"], p.get("value", ""), [{"entity_type": pt, "text": det_text}]) for p in gt_pii)
            if not matched:
                pii_fp += 1
                pii_entity_stats[pt]["fp"] += 1
                if len(pii_fp_examples) < 10:
                    pii_fp_examples.append({
                        "doc_id": did,
                        "type": pt,
                        "text": det_text,
                        "snippet": eval_text[:120].replace("\n", " ")
                    })

        # 4. Decision Gate
        decision = stage_decision_gate(pred_class, confidence, pii_res, extraction_valid=is_valid)
        if decision.action == "AUTO_ACCEPT":
            auto_accepted_count += 1
            auto_accepted_true.append(doc_type)
            auto_accepted_pred.append(pred_class)
        else:
            review_count += 1
            review_reasons[decision.reason] += 1

        # 5. Audit Completeness
        audit = stage_audit_record(
            uid=did,
            sha256_hash=sha256_hash,
            decision=decision,
            metadata_fields={
                "ocr_engine": ocr_engine_name,
                "ocr_version": ocr_engine_ver,
                "classifier_model": cls_res["model_name"],
                "classifier_version": cls_res["model_version"],
                "field_confidences": field_confs,
                "pii_detected": pii_res["pii_detected"],
                "pii_types": pii_res["pii_types"],
            },
        )
        if audit.uid == did and audit.sha256 == sha256_hash and audit.ocrEngine and audit.processedAt:
            audit_complete_count += 1

    # Metrics Computation
    overall_cls_acc = sum(1 for yt, yp in zip(y_true, y_pred) if yt == yp) / len(y_true) * 100.0
    auto_accepted_cls_acc = (
        sum(1 for yt, yp in zip(auto_accepted_true, auto_accepted_pred) if yt == yp) / max(1, len(auto_accepted_true)) * 100.0
    )
    field_acc = (total_fields_correct / max(1, total_fields_expected)) * 100.0
    pii_recall = (pii_tp / max(1, pii_tp + pii_fn)) * 100.0
    pii_precision = (pii_tp / max(1, pii_tp + pii_fp)) * 100.0
    stp_rate = (auto_accepted_count / len(json_files)) * 100.0
    audit_completeness = (audit_complete_count / len(json_files)) * 100.0

    print("=" * 80)
    print("HOLDOUT 4 TARGET COMPLIANCE SUMMARY (LOCAL MODE ONLY)")
    print("=" * 80)
    print(f"Classification Accuracy (Auto-Accepted): {auto_accepted_cls_acc:6.2f}% ({sum(1 for yt, yp in zip(auto_accepted_true, auto_accepted_pred) if yt == yp)}/{len(auto_accepted_true)}) [Target >= 95%] -> {'PASS' if auto_accepted_cls_acc >= 95.0 else 'FAIL'}")
    print(f"Overall Classification Accuracy:         {overall_cls_acc:6.2f}% ({sum(1 for yt, yp in zip(y_true, y_pred) if yt == yp)}/{len(y_true)})")
    print(f"Field Extraction Accuracy:                {field_acc:6.2f}% ({total_fields_correct}/{total_fields_expected}) [Target >= 90%] -> {'PASS' if field_acc >= 90.0 else 'FAIL'}")
    print(f"PII Recall:                               {pii_recall:6.2f}% ({pii_tp}/{pii_tp + pii_fn}) [Target >= 98%] -> {'PASS' if pii_recall >= 98.0 else 'FAIL'}")
    print(f"PII Precision:                            {pii_precision:6.2f}% ({pii_tp}/{pii_tp + pii_fp}) [Target >= 80%] -> {'PASS' if pii_precision >= 80.0 else 'FAIL'}")
    print(f"Straight-Through Processing (STP) Rate:   {stp_rate:6.2f}% ({auto_accepted_count}/{len(json_files)}) [Target >= 70%] -> {'PASS' if stp_rate >= 70.0 else 'FAIL'}")
    print(f"Audit Trail Completeness:                {audit_completeness:6.2f}% ({audit_complete_count}/{len(json_files)}) [Target 100%] -> {'PASS' if audit_completeness == 100.0 else 'FAIL'}")

    # Confusion Matrix
    print("\n" + "-" * 80)
    print("CONFUSION MATRIX (True \\ Predicted)")
    print("-" * 80)
    matrix = {c1: {c2: 0 for c2 in ALL_CLASSES} for c1 in ALL_CLASSES}
    for yt, yp in zip(y_true, y_pred):
        matrix[yt][yp] += 1

    header = f"{'':16} " + " ".join(f"{c[:7]:>7}" for c in ALL_CLASSES)
    print(header)
    for c1 in ALL_CLASSES:
        row = f"{c1:16} " + " ".join(f"{matrix[c1][c2]:7d}" for c2 in ALL_CLASSES)
        print(row)

    # Per-Class Precision / Recall
    print("\n" + "-" * 80)
    print("PER-CLASS CLASSIFICATION PRECISION & RECALL")
    print("-" * 80)
    print(f"{'Class':<20} {'Precision':<14} {'Recall':<14} {'F1-Score':<14} {'Support':<8}")
    for c in ALL_CLASSES:
        tp = matrix[c][c]
        pred_total = sum(matrix[other][c] for other in ALL_CLASSES)
        true_total = sum(matrix[c][other] for other in ALL_CLASSES)
        prec = (tp / pred_total * 100.0) if pred_total > 0 else 0.0
        rec = (tp / true_total * 100.0) if true_total > 0 else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
        print(f"{c:<20} {prec:10.2f}%   {rec:10.2f}%   {f1:10.2f}%   {true_total:6d}")

    # Per-Class Field Extraction
    print("\n" + "-" * 80)
    print("PER-CLASS FIELD EXTRACTION ACCURACY")
    print("-" * 80)
    print(f"{'Class':<22} {'Extracted':<12} {'Expected':<12} {'Accuracy':<10}")
    for c in ALL_CLASSES:
        if c == "unknown": continue
        st = per_class_fields[c]
        acc = (st["correct"] / max(1, st["expected"])) * 100.0
        print(f"{c:<22} {st['correct']:10d}   {st['expected']:10d}   {acc:9.2f}%")

    # PII Entity Breakdown
    print("\n" + "-" * 80)
    print("PII ENTITY PERFORMANCE (Recall & Precision)")
    print("-" * 80)
    print(f"{'Entity Type':<25} {'TP':<7} {'FN':<7} {'FP':<7} {'Recall':<12} {'Precision':<12}")
    for et, stats in sorted(pii_entity_stats.items()):
        tp_e = stats["tp"]
        fn_e = stats["fn"]
        fp_e = stats["fp"]
        rec_e = (tp_e / max(1, tp_e + fn_e)) * 100.0
        prec_e = (tp_e / max(1, tp_e + fp_e)) * 100.0
        print(f"{et:<25} {tp_e:5d}   {fn_e:5d}   {fp_e:5d}   {rec_e:9.2f}%   {prec_e:9.2f}%")

    # Routing & Review Breakdown
    print("\n" + "-" * 80)
    print("ROUTING & REVIEW DECISION BREAKDOWN")
    print("-" * 80)
    print(f"Auto-Accepted Documents: {auto_accepted_count} ({stp_rate:.2f}%)")
    print(f"Sent to Human Review:     {review_count} ({100.0 - stp_rate:.2f}%)")
    print("Review Reasons Breakdown:")
    for r, count in sorted(review_reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {r}: {count}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_holdout4_eval()
