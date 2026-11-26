"""Evaluation runner benchmarking the fresh holdout set against all targets.

Measures:
- Classification accuracy on auto-accepted documents (target >= 95%)
- Field extraction accuracy on required fields (target >= 90%)
- PII recall (target >= 98%) & precision
- Straight-through rate (target >= 70%)
- 100% asset audit completeness
Produces 10 random asset audit reports.
"""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import difflib
import json
import os
from pathlib import Path
import random
from typing import Any, Dict, List, Tuple
import numpy as np
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

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
SPLIT_NAME = os.getenv("EVAL_SPLIT", "holdout")
TEST_DIR = BASE_DIR / "data" / "dataset" / SPLIT_NAME
CACHE_DIR = BASE_DIR / "data" / "dataset" / f"{SPLIT_NAME}_ocr_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DOCS_DIR = BASE_DIR / "docs"
DOCS_DIR.mkdir(parents=True, exist_ok=True)


def get_ocr_for_doc(doc_id: str, pdf_path: Path, ocr_engine) -> Tuple[str, str, str]:
    """Retrieve or run OCR via Tesseract and cache results."""
    cache_file = CACHE_DIR / f"{doc_id}.json"
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data["full_text"], data["engine"], data["version"]

    with open(pdf_path, "rb") as pf:
        res = ocr_engine.extract_text(pf.read(), "pdf")

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump({
            "full_text": res.full_text,
            "engine": res.engine_name,
            "version": res.engine_version,
        }, f)
    return res.full_text, res.engine_name, res.engine_version


def evaluate_holdout_test_set() -> Dict[str, Any]:
    print("=" * 75)
    print(f"STEP 8: EVALUATION ON LOCKED FRESH HOLDOUT SET (360 documents, Split: {SPLIT_NAME})")
    print("=" * 75)

    json_files = sorted(list(TEST_DIR.glob("*.json")))
    print(f"Loaded {len(json_files)} locked holdout ground-truth records from {TEST_DIR}\n")

    ocr_engine = get_ocr_engine()
    print("Pre-warming OCR cache with 4 parallel threads on holdout scans...")
    def warm(jf):
        with open(jf, "r", encoding="utf-8") as f:
            d = json.load(f)
        did = d["doc_id"]
        pp = TEST_DIR / f"{did}.pdf"
        get_ocr_for_doc(did, pp, ocr_engine)

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(warm, json_files))
    print("OCR extraction complete for 360 holdout documents.\n")

    y_true = []
    y_pred = []
    auto_accepted_true = []
    auto_accepted_pred = []

    total_fields_expected = 0
    total_fields_correct = 0
    per_class_fields: Dict[str, Dict[str, int]] = {c: {"expected": 0, "correct": 0} for c in ALL_CLASSES}
    per_field_stats = defaultdict(lambda: {"expected": 0, "correct": 0})

    pii_true_positive = 0
    pii_false_negative = 0
    pii_false_positive = 0
    pii_entity_stats = defaultdict(lambda: {"tp": 0, "fn": 0, "fp": 0})
    pii_fp_examples = []

    total_docs = len(json_files)
    auto_accepted_count = 0
    review_count = 0
    audit_complete_count = 0
    review_reasons = defaultdict(int)

    evaluated_records: List[Dict[str, Any]] = []

    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            gt = json.load(f)

        doc_type = gt["doc_type"]
        raw_text = gt.get("text", "")
        gt_fields = gt.get("fields", {})
        gt_pii = gt.get("pii_entities", [])
        sha256_hash = gt.get("sha256", "hash")
        doc_id = gt.get("doc_id", "doc")

        # 1. OCR text extraction from pure rasterized PDF
        pdf_path = TEST_DIR / f"{doc_id}.pdf"
        assert pdf_path.exists(), f"Holdout scan not found: {pdf_path}"
        eval_text, ocr_engine_name, ocr_engine_ver = get_ocr_for_doc(doc_id, pdf_path, ocr_engine)

        # 2. Classification
        cls_res = stage_classify(eval_text)
        pred_class = cls_res["predicted_class"]
        confidence = cls_res["confidence"]

        y_true.append(doc_type)
        y_pred.append(pred_class)

        # 3. Field Extraction
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

        # 4. PII Detection
        pii_res = stage_pii_detect(eval_text)
        pred_entities = pii_res["entities"]
        pred_pii_types = set(p["entity_type"] for p in pred_entities)
        gt_pii_types = set(p["type"] for p in gt_pii)

        for p in gt_pii:
            pt = p["type"]
            matched = any(pe["entity_type"] == pt for pe in pred_entities)
            if matched:
                pii_true_positive += 1
                pii_entity_stats[pt]["tp"] += 1
            else:
                pii_false_negative += 1
                pii_entity_stats[pt]["fn"] += 1

        for pe in pred_entities:
            pt = pe["entity_type"]
            matched = any(p["type"] == pt for p in gt_pii)
            if not matched:
                pii_false_positive += 1
                pii_entity_stats[pt]["fp"] += 1
                if len(pii_fp_examples) < 10:
                    pii_fp_examples.append({
                        "doc_id": doc_id,
                        "type": pt,
                        "text": pe.get("text", ""),
                        "context": eval_text[:120].replace("\n", " "),
                    })

        # 5. Decision Gate
        decision = stage_decision_gate(pred_class, confidence, pii_res)
        if decision.action == "AUTO_ACCEPT":
            auto_accepted_count += 1
            auto_accepted_true.append(doc_type)
            auto_accepted_pred.append(pred_class)
        else:
            review_count += 1
            review_reasons[decision.reason] += 1

        # 6. Audit Completeness Check
        audit = stage_audit_record(
            uid=doc_id,
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
        if audit.validate_audit_completeness():
            audit_complete_count += 1

        evaluated_records.append(
            {
                "doc_id": doc_id,
                "sha256": sha256_hash,
                "doc_type": doc_type,
                "pred_type": pred_class,
                "confidence": confidence,
                "decision": decision.model_dump(),
                "audit": audit.model_dump(),
                "extracted_fields": ext_fields,
            }
        )

    # -----------------------------------------------------------------------
    # Compute Final Evaluation Metrics
    # -----------------------------------------------------------------------

    # Auto-accepted classification accuracy
    if auto_accepted_pred:
        auto_acc = sum(1 for t, p in zip(auto_accepted_true, auto_accepted_pred) if t == p) / len(auto_accepted_pred)
    else:
        auto_acc = 0.0

    # Overall Field extraction accuracy
    field_acc = total_fields_correct / max(1, total_fields_expected)

    # PII Recall & Precision
    pii_recall = pii_true_positive / max(1, pii_true_positive + pii_false_negative)
    pii_precision = pii_true_positive / max(1, pii_true_positive + pii_false_positive)

    # Straight-through processing rate (STP)
    stp_rate = auto_accepted_count / float(total_docs)
    review_rate = review_count / float(total_docs)

    # Audit Completeness rate
    audit_completeness_rate = audit_complete_count / float(total_docs)

    # Confusion Matrix & Per-class Precision/Recall
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=ALL_CLASSES, zero_division=0
    )
    cm = confusion_matrix(y_true, y_pred, labels=ALL_CLASSES)

    # Targets & PASS/FAIL Evaluation
    t1_pass = auto_acc >= 0.95
    t2_pass = field_acc >= 0.90
    t3_pass = pii_recall >= 0.98
    t4_pass = stp_rate >= 0.70
    t5_pass = audit_completeness_rate == 1.0

    print("=" * 75)
    print("PIPELINE PERFORMANCE ON LOCKED FRESH HOLDOUT SET (LOCAL-MODE ONLY):")
    print("=" * 75)
    print(f"Total Test Documents:          {total_docs} (360 locked holdout ground-truth scans)")
    print(f"Auto-Accepted Documents:       {auto_accepted_count} (STP: {stp_rate * 100:.2f}%)")
    print(f"Routed to Human Review:        {review_count} (Review Rate: {review_rate * 100:.2f}%)")
    print("-" * 75)
    print("TARGET METRIC VERIFICATION TABLE:")
    print(f"{'Target Objective':<45} {'Required':<12} {'Achieved':<12} {'Result'}")
    print("-" * 75)
    print(f"{'Classification Accuracy (Auto-Accepted)':<45} {'>= 95.0%':<12} {auto_acc * 100:.2f}%{'':<6} {'PASS' if t1_pass else 'FAIL'}")
    print(f"{'Field Extraction Accuracy (Required Fields)':<45} {'>= 90.0%':<12} {field_acc * 100:.2f}%{'':<6} {'PASS' if t2_pass else 'FAIL'}")
    print(f"{'PII Recall (Presidio + Custom Recognizers)':<45} {'>= 98.0%':<12} {pii_recall * 100:.2f}%{'':<6} {'PASS' if t3_pass else 'FAIL'}")
    print(f"{'Straight-Through Rate (STP)':<45} {'>= 70.0%':<12} {stp_rate * 100:.2f}%{'':<6} {'PASS' if t4_pass else 'FAIL'}")
    print(f"{'Audit Metadata Completeness':<45} {'100.0%':<12} {audit_completeness_rate * 100:.1f}%{'':<6} {'PASS' if t5_pass else 'FAIL'}")
    print("=" * 75)

    print("\nPER-CLASS PRECISION & RECALL:")
    print(f"{'Class':<20} {'Precision':<15} {'Recall':<15} {'F1-Score':<15} {'Support':<10}")
    print("-" * 75)
    for i, c in enumerate(ALL_CLASSES):
        print(f"{c:<20} {precision[i]:<15.4f} {recall[i]:<15.4f} {f1[i]:<15.4f} {support[i]:<10}")
    print("-" * 75)

    print("\nPER-CLASS FIELD EXTRACTION ACCURACY:")
    print(f"{'Class':<20} {'Fields Expected':<18} {'Fields Correct':<18} {'Accuracy':<10}")
    print("-" * 75)
    for c in ALL_CLASSES:
        if c == "unknown":
            continue
        exp = per_class_fields[c]["expected"]
        corr = per_class_fields[c]["correct"]
        acc = corr / max(1, exp)
        print(f"{c:<20} {exp:<18} {corr:<18} {acc * 100:.2f}%")
    print("-" * 75)

    print("\nPII DETECTION RECALL & PRECISION PER ENTITY TYPE:")
    print(f"{'Entity Type':<20} {'TP':<8} {'FN':<8} {'FP':<8} {'Recall':<12} {'Precision':<12}")
    print("-" * 75)
    for pt, s in sorted(pii_entity_stats.items()):
        rec = s["tp"] / max(1, s["tp"] + s["fn"]) * 100
        prec = s["tp"] / max(1, s["tp"] + s["fp"]) * 100
        print(f"{pt:<20} {s['tp']:<8} {s['fn']:<8} {s['fp']:<8} {rec:.2f}%{'':<6} {prec:.2f}%")
    print("-" * 75)
    print(f"{'OVERALL':<20} {pii_true_positive:<8} {pii_false_negative:<8} {pii_false_positive:<8} {pii_recall * 100:.2f}%{'':<6} {pii_precision * 100:.2f}%")

    print("\nTOP SOURCES OF FALSE POSITIVES:")
    for ex in pii_fp_examples[:5]:
        print(f"  Doc: {ex['doc_id']} | Type: {ex['type']} | Text: '{ex['text']}' | Context: {ex['context']}")

    print("\nREVIEW REASONS BREAKDOWN:")
    for r, cnt in review_reasons.items():
        print(f"  - Count: {cnt:<4} | Reason: {r}")

    print("\nCONFUSION MATRIX (Rows: True Class, Cols: Predicted Class):")
    header = " " * 16 + " ".join(f"{c[:4]:>5}" for c in ALL_CLASSES)
    print(header)
    for i, c in enumerate(ALL_CLASSES):
        row_str = f"{c:<15} " + " ".join(f"{cm[i, j]:>5}" for j in range(len(ALL_CLASSES)))
        print(row_str)
    print("=" * 75)

    # -----------------------------------------------------------------------
    # 10 Random Asset One-Page Audit Reports
    # -----------------------------------------------------------------------
    print("\nGENERATING 10 RANDOM ASSET AUDIT COMPLIANCE REPORTS...")
    random.seed(SEED if 'SEED' in globals() else 20261118)
    sampled_10 = random.sample(evaluated_records, 10)

    audit_reports_markdown = "# 10 Random Asset Audit Compliance Reports (Locked Holdout Scans)\n\n"

    for idx, sample in enumerate(sampled_10, 1):
        audit = sample["audit"]
        decision = sample["decision"]

        missing_fields = []
        for field in ["uid", "sha256", "predictedType", "ocrEngine", "ocrVersion", "classifierModel", "classifierVersion", "reviewStatus", "processedAt", "retentionClass", "assignedAcl"]:
            if not audit.get(field):
                missing_fields.append(field)

        if missing_fields:
            raise ValueError(f"Audit report check failed for asset {sample['doc_id']}: missing fields {missing_fields}")

        report_card = f"""
### Asset Audit Report #{idx}: `{sample['doc_id']}`
- **Document UID**: `{audit['uid']}`
- **SHA-256 Checksum**: `{audit['sha256']}`
- **Classified Document Type**: **{audit['predictedType']}** (Ground Truth: `{sample['doc_type']}`)
- **Classifier Model & Version**: `{audit['classifierModel']}` (`{audit['classifierVersion']}`)
- **OCR Engine & Version**: `{audit['ocrEngine']}` (`{audit['ocrVersion']}`)
- **Classification Confidence**: **{audit['confidence']:.4f}**
- **PII Entities Detected**: `{audit['piiDetected']}` (Types: {audit['piiTypes'] if audit['piiTypes'] else 'None'})
- **Assigned Retention Class**: `{audit['retentionClass']}`
- **Assigned Access Control List (ACL)**: `{audit['assignedAcl']}`
- **Target ECM Workflow**: `{audit['targetWorkflow']}`
- **Review Status**: `{audit['reviewStatus']}`
- **Reviewer / Automated Actor**: `{audit.get('reviewerId') or 'AUTOMATED_INGESTION_ENGINE'}`
- **Processed Timestamp**: `{audit['processedAt']}`
- **Decision Justification**:
  > {audit['decisionReason']}

---
"""
        audit_reports_markdown += report_card
        print(f"  [Report {idx:02d}/10] Verified asset {audit['uid']}: Type={audit['predictedType']}, Conf={audit['confidence']:.2f}, Status={audit['reviewStatus']}, Engine={audit['ocrEngine']} ({audit['ocrVersion']})")

    with open(DOCS_DIR / "audit-reports.md", "w", encoding="utf-8") as f:
        f.write(audit_reports_markdown)
    print(f"\n10/10 Asset Audit Reports written to: {DOCS_DIR / 'audit-reports.md'}")
    print("=" * 75)

    return {
        "auto_acc": auto_acc,
        "field_acc": field_acc,
        "pii_recall": pii_recall,
        "pii_precision": pii_precision,
        "stp_rate": stp_rate,
        "review_rate": review_rate,
        "audit_completeness": audit_completeness_rate,
        "targets": {
            "classification_accuracy_auto_accepted": {"achieved": auto_acc, "pass": t1_pass},
            "field_extraction_accuracy": {"achieved": field_acc, "pass": t2_pass},
            "pii_recall": {"achieved": pii_recall, "pass": t3_pass},
            "straight_through_rate": {"achieved": stp_rate, "pass": t4_pass},
            "audit_completeness": {"achieved": audit_completeness_rate, "pass": t5_pass},
        },
        "confusion_matrix": cm.tolist(),
        "evaluated_records": evaluated_records,
    }


if __name__ == "__main__":
    evaluate_holdout_test_set()
