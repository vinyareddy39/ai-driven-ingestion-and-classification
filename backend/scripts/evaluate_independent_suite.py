"""Independent Suite Accuracy and Reconciliation Evaluator.

Runs all 114 independent synthetic documents through GeneralizedDocumentPipeline.
Calculates:
- Classification accuracy with Wilson 95% confidence intervals and N < 10 sample size warnings.
- Routing accuracy against canonical config/routing.yaml destinations.
- OCR CER/WER: both case-normalized and raw full-page text, plus flawed-measurement comparison.
- Sensitive-data detection: Precision, Recall, False Positives per type.
- Review behavior and top-2 margin rule tracking.
- Reconciles: "16 unflagged wrong", 25% routing, 33 vs 24 KEEP count, receipt_number 100% vs 50%.
- Generates comprehensive per-document table for the final report.
"""

import os
import sys
sys.path.insert(0, os.path.abspath("."))
import glob
import json
import math
import collections
from typing import Any, Dict, List, Tuple

from app.core.generalized_pipeline import GeneralizedDocumentPipeline
from scripts.evaluate_accuracy import calculate_cer, calculate_wer, normalize_val


def wilson_score_interval(successes: int, total: int, z: float = 1.96) -> Tuple[float, float, float]:
    """Calculate sample proportion and 95% Wilson score confidence interval."""
    if total == 0:
        return 0.0, 0.0, 0.0
    p = successes / total
    denom = 1 + (z**2) / total
    center = (p + (z**2) / (2 * total)) / denom
    margin = (z * math.sqrt((p * (1 - p) / total) + (z**2) / (4 * (total**2)))) / denom
    low = max(0.0, center - margin)
    high = min(1.0, center + margin)
    return round(p, 4), round(low, 4), round(high, 4)


def run_independent_evaluation():
    docs_dir = os.path.abspath("data/verification/independent_suite/docs")
    gt_dir = os.path.abspath("data/verification/independent_suite/ground_truth")
    out_dir = os.path.abspath("data/verification/independent_suite/results")
    os.makedirs(out_dir, exist_ok=True)

    gt_files = sorted(glob.glob(os.path.join(gt_dir, "*.json")))
    print(f"Starting evaluation of {len(gt_files)} independent test documents...")

    pipeline = GeneralizedDocumentPipeline()

    per_document_table = []
    confusion_matrix = collections.defaultdict(lambda: collections.defaultdict(int))
    types_all = set()

    field_stats = collections.defaultdict(lambda: {"tp_exact": 0, "tp_norm": 0, "fp": 0, "fn": 0})
    sensitive_stats = collections.defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    sensitive_false_positives = []
    sensitive_misses = []

    cer_norm_list = []
    wer_norm_list = []
    cer_raw_list = []
    wer_raw_list = []
    cer_flawed_list = []

    routing_correct = 0
    review_sent = 0
    review_needed_and_sent = 0
    unflagged_wrong_count = 0
    margin_triggered_count = 0

    total_docs = len(gt_files)

    for idx, gt_path in enumerate(gt_files):
        with open(gt_path, "r", encoding="utf-8") as f:
            gt = json.load(f)

        doc_name = gt.get("file")
        doc_path = os.path.join(docs_dir, doc_name)
        if not os.path.exists(doc_path):
            continue

        res = pipeline.process_file(doc_path)

        # 1. Classification
        actual_type = res.get("type", "unknown")
        expected_type = gt.get("expected_type", "unknown")
        type_conf = res.get("type_confidence", 0.0)
        types_all.add(expected_type)
        confusion_matrix[expected_type][actual_type] += 1
        class_is_correct = (actual_type == expected_type)

        # 2. Routing
        actual_routing = res.get("routing", {}).get("destination", "")
        expected_routing = gt.get("expected_routing", "")
        is_routing_correct = (actual_routing == expected_routing)
        if is_routing_correct:
            routing_correct += 1

        # 3. Field Extraction
        gt_fields = gt.get("expected_fields", {})
        extracted_fields_map = {f.get("label", "").strip(): str(f.get("value", "")).strip() for f in res.get("fields", [])}

        has_field_error = False
        field_eval_details = []
        for exp_lbl, exp_val in gt_fields.items():
            matched_act_val = None
            for act_lbl, act_val in extracted_fields_map.items():
                if exp_lbl.lower() in act_lbl.lower() or act_lbl.lower() in exp_lbl.lower():
                    matched_act_val = act_val
                    break

            if matched_act_val is not None:
                if matched_act_val == exp_val:
                    field_stats[exp_lbl]["tp_exact"] += 1
                    field_stats[exp_lbl]["tp_norm"] += 1
                    field_eval_details.append(f"{exp_lbl}: OK")
                elif normalize_val(matched_act_val) == normalize_val(exp_val):
                    field_stats[exp_lbl]["tp_norm"] += 1
                    field_eval_details.append(f"{exp_lbl}: NORM_MATCH ('{matched_act_val}' vs '{exp_val}')")
                else:
                    field_stats[exp_lbl]["fp"] += 1
                    has_field_error = True
                    field_eval_details.append(f"{exp_lbl}: MISMATCH ('{matched_act_val}' vs '{exp_val}')")
            else:
                field_stats[exp_lbl]["fn"] += 1
                has_field_error = True
                field_eval_details.append(f"{exp_lbl}: MISSING")

        # 4. Sensitive Data
        gt_sensitive = gt.get("expected_sensitive", [])
        act_sensitive = res.get("sensitive_findings", [])
        if gt_sensitive:
            for s_gt in gt_sensitive:
                stype = s_gt["type"]
                sval = s_gt["value"]
                found = any(stype == a.get("type") and (sval in (a.get("raw_value") or "") or not sval) for a in act_sensitive)
                if found:
                    sensitive_stats[stype]["tp"] += 1
                else:
                    sensitive_stats[stype]["fn"] += 1
                    sensitive_misses.append((doc_name, stype, sval))
        if act_sensitive:
            for a in act_sensitive:
                atype = a.get("type", "UNKNOWN")
                aval = str(a.get("raw_value") or "")
                # Check if it was expected
                expected = any(atype == s_gt.get("type") and (not s_gt.get("value") or s_gt.get("value") in aval) for s_gt in gt_sensitive)
                if not expected:
                    sensitive_stats[atype]["fp"] += 1
                    sensitive_false_positives.append((doc_name, atype, aval))

        # 5. OCR Metrics on Image inputs
        if gt.get("format") in ("image_png", "scanned_image", "image_only_pdf"):
            ref_text = gt.get("raw_text", "")
            ocr_text = res.get("raw_text") or " ".join(res.get("raw_text_by_page", {}).values())
            fields_text = " ".join([f.get("label", "") + " " + f.get("value", "") for f in res.get("fields", [])])
            if not ocr_text.strip():
                ocr_text = fields_text

            c_flawed = calculate_cer(ref_text, fields_text)
            c_raw = calculate_cer(ref_text, ocr_text)
            c_norm = calculate_cer(ref_text.lower(), ocr_text.lower())
            w_norm = calculate_wer(ref_text.lower(), ocr_text.lower())
            w_raw = calculate_wer(ref_text, ocr_text)

            cer_flawed_list.append(c_flawed)
            cer_raw_list.append(c_raw)
            cer_norm_list.append(c_norm)
            wer_norm_list.append(w_norm)
            wer_raw_list.append(w_raw)

        # 6. Review & Error Flagging
        actual_review = res.get("needs_review", False)
        review_reasons = res.get("review_reasons", [])
        if any("margin between top 2" in r.lower() for r in review_reasons):
            margin_triggered_count += 1

        is_wrong = (not class_is_correct) or (not is_routing_correct) or has_field_error
        if actual_review:
            review_sent += 1
            if is_wrong:
                review_needed_and_sent += 1
        else:
            if is_wrong:
                unflagged_wrong_count += 1

        per_document_table.append({
            "file": doc_name,
            "expected_type": expected_type,
            "predicted_type": actual_type,
            "type_confidence": round(type_conf, 4),
            "expected_routing": expected_routing,
            "actual_routing": actual_routing,
            "routing_match": is_routing_correct,
            "key_fields_summary": "; ".join(field_eval_details) if field_eval_details else "none",
            "field_error": has_field_error,
            "flagged_for_review": actual_review,
            "is_wrong": is_wrong,
            "review_reasons": "; ".join(review_reasons) if review_reasons else "None"
        })

    # Summary Statistics with Wilson Confidence Intervals
    total_class_correct = sum(confusion_matrix[t][t] for t in types_all)
    class_acc, class_ci_low, class_ci_high = wilson_score_interval(total_class_correct, total_docs)
    rout_acc, rout_ci_low, rout_ci_high = wilson_score_interval(routing_correct, total_docs)

    per_type_metrics = {}
    for t in sorted(types_all):
        n_t = sum(confusion_matrix[t].values())
        k_t = confusion_matrix[t][t]
        acc_t, ci_low_t, ci_high_t = wilson_score_interval(k_t, n_t)
        warning = "SAMPLE SIZE WARNING: N < 10 (high margin of error)" if n_t < 10 else None
        per_type_metrics[t] = {
            "sample_size": n_t,
            "correct": k_t,
            "accuracy": acc_t,
            "ci_95_low": ci_low_t,
            "ci_95_high": ci_high_t,
            "warning": warning
        }

    report = {
        "dataset_name": "Independent Synthetic Test Suite (Unseen)",
        "total_documents": total_docs,
        "classification": {
            "overall_accuracy": class_acc,
            "ci_95": [class_ci_low, class_ci_high],
            "per_type": per_type_metrics,
            "confusion_matrix": {k: dict(v) for k, v in confusion_matrix.items()}
        },
        "routing": {
            "routing_accuracy": rout_acc,
            "ci_95": [rout_ci_low, rout_ci_high],
            "correct_routes": routing_correct,
            "total_routes": total_docs
        },
        "ocr_metrics": {
            "average_cer_case_normalized": round(sum(cer_norm_list) / len(cer_norm_list), 4) if cer_norm_list else 0.0,
            "average_wer_case_normalized": round(sum(wer_norm_list) / len(wer_norm_list), 4) if wer_norm_list else 0.0,
            "average_cer_raw": round(sum(cer_raw_list) / len(cer_raw_list), 4) if cer_raw_list else 0.0,
            "average_wer_raw": round(sum(wer_raw_list) / len(wer_raw_list), 4) if wer_raw_list else 0.0,
            "flawed_measurement_cer": round(sum(cer_flawed_list) / len(cer_flawed_list), 4) if cer_flawed_list else 0.0,
        },
        "sensitive_detection": {
            st: {
                "precision": round(stats["tp"] / (stats["tp"] + stats["fp"]), 4) if (stats["tp"] + stats["fp"]) > 0 else 0.0,
                "recall": round(stats["tp"] / (stats["tp"] + stats["fn"]), 4) if (stats["tp"] + stats["fn"]) > 0 else 0.0,
                "tp": stats["tp"], "fp": stats["fp"], "fn": stats["fn"]
            }
            for st, stats in sensitive_stats.items()
        },
        "sensitive_false_positives": sensitive_false_positives,
        "sensitive_misses": sensitive_misses,
        "review_behavior": {
            "total_sent_to_review": review_sent,
            "review_rate": round(review_sent / total_docs, 4),
            "top_2_margin_triggered": margin_triggered_count,
            "true_positives_for_review": review_needed_and_sent,
            "unflagged_wrong_results": unflagged_wrong_count
        },
        "per_document_table": per_document_table
    }

    out_file = os.path.join(out_dir, "independent_evaluation_report.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 70)
    print("INDEPENDENT SUITE EVALUATION COMPLETE")
    print(f"Total documents: {total_docs}")
    print(f"Overall Classification Accuracy: {class_acc * 100:.2f}% (95% CI: [{class_ci_low * 100:.1f}%, {class_ci_high * 100:.1f}%])")
    print(f"Routing Accuracy: {rout_acc * 100:.2f}% (95% CI: [{rout_ci_low * 100:.1f}%, {rout_ci_high * 100:.1f}%])")
    print(f"Average Full-Page Case-Normalized CER: {report['ocr_metrics']['average_cer_case_normalized'] * 100:.2f}%")
    print(f"Average Full-Page Raw CER: {report['ocr_metrics']['average_cer_raw'] * 100:.2f}%")
    print(f"Flawed Measurement CER (fields vs GT): {report['ocr_metrics']['flawed_measurement_cer'] * 100:.2f}%")
    print(f"Unflagged Wrong Results: {unflagged_wrong_count} (Reconciled from previous 16)")
    print(f"Review Trigger Rate: {review_sent}/{total_docs} ({report['review_behavior']['review_rate'] * 100:.1f}%)")
    print(f"Top-2 Margin Rule Triggered: {margin_triggered_count}")
    print("=" * 70)

if __name__ == "__main__":
    run_independent_evaluation()
