"""Extraction Accuracy and Calibration Evaluation Suite (Part 2).

Evaluates 32 documents against paired Ground Truth JSONs:
- Classification accuracy, per-type accuracy, confusion matrix
- Key fields: Precision, Recall, F1, exact-match vs normalized-match
- Sensitive-data detection: Precision, Recall, False Positives
- Routing accuracy
- OCR / text quality: CER and WER on image inputs
- Confidence calibration: Binned empirical accuracy vs predicted confidence
- Review behavior: Review trigger rate, True Positives for review, Unflagged Errors
- Hallucination check
- Robustness: 3x repeatability check
- Top 10 worst failures
"""

import os
import sys
import glob
import json
import collections
import re
from difflib import SequenceMatcher

sys.path.insert(0, os.path.abspath("."))
from app.core.generalized_pipeline import GeneralizedDocumentPipeline

def calculate_cer(reference: str, hypothesis: str) -> float:
    if not reference:
        return 0.0 if not hypothesis else 1.0
    matcher = SequenceMatcher(None, reference, hypothesis)
    return 1.0 - matcher.ratio()

def calculate_wer(reference: str, hypothesis: str) -> float:
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    matcher = SequenceMatcher(None, ref_words, hyp_words)
    return 1.0 - matcher.ratio()

def normalize_val(val: str) -> str:
    if not val:
        return ""
    # Strip currency, spaces, punctuation
    s = str(val).lower().strip()
    s = s.replace("$", "").replace(",", "").replace("-", "").replace("/", "")
    return " ".join(s.split())

def run_evaluation():
    pipeline = GeneralizedDocumentPipeline()
    docs_dir = "data/verification/accuracy_suite/docs"
    gt_dir = "data/verification/accuracy_suite/ground_truth"

    gt_files = sorted(glob.glob(os.path.join(gt_dir, "*.json")))
    print(f"Loaded {len(gt_files)} Ground Truth definitions.")

    # Tracking structures
    doc_results = []
    confusion_matrix = collections.defaultdict(lambda: collections.defaultdict(int))
    types_all = set()

    field_stats = collections.defaultdict(lambda: {"tp_exact": 0, "tp_norm": 0, "fp": 0, "fn": 0})
    sensitive_stats = collections.defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    sensitive_false_positives = []
    per_document_records = []

    cer_scores_norm = []
    wer_scores_norm = []
    cer_scores_raw = []
    wer_scores_raw = []
    cer_scores_flawed = []
    wer_scores_flawed = []

    calibration_bins = {
        "0.5-0.6": {"total": 0, "correct": 0},
        "0.6-0.7": {"total": 0, "correct": 0},
        "0.7-0.8": {"total": 0, "correct": 0},
        "0.8-0.9": {"total": 0, "correct": 0},
        "0.9-1.0": {"total": 0, "correct": 0},
    }

    routing_correct = 0
    total_docs = len(gt_files)
    review_sent = 0
    review_needed_and_sent = 0
    unflagged_errors = 0
    hallucinated_fields = []
    failures_list = []

    # Repeatability test dictionary: doc_name -> list of outputs
    repeat_checks = collections.defaultdict(list)

    for gt_path in gt_files:
        with open(gt_path, "r", encoding="utf-8") as f:
            gt = json.load(f)
        
        doc_name = gt["document_name"]
        doc_path = os.path.join(docs_dir, doc_name)
        
        # 1. Pipeline Execution (Run 1)
        res = pipeline.process_file(doc_path)
        
        # 2. Robustness Check (Runs 2 & 3)
        res_r2 = pipeline.process_file(doc_path)
        res_r3 = pipeline.process_file(doc_path)
        
        diff_r2 = (res["type"] != res_r2["type"] or len(res["fields"]) != len(res_r2["fields"]))
        diff_r3 = (res["type"] != res_r3["type"] or len(res["fields"]) != len(res_r3["fields"]))
        repeat_checks[doc_name] = not (diff_r2 or diff_r3)

        # Classification check
        actual_type = res.get("type", "unknown")
        expected_type = gt.get("expected_type", "unknown")
        types_all.add(expected_type)
        types_all.add(actual_type)
        confusion_matrix[expected_type][actual_type] += 1
        class_is_correct = (actual_type == expected_type)

        # Confidence Calibration tracking
        conf = res.get("type_confidence", 0.0)
        bin_key = None
        if 0.5 <= conf < 0.6: bin_key = "0.5-0.6"
        elif 0.6 <= conf < 0.7: bin_key = "0.6-0.7"
        elif 0.7 <= conf < 0.8: bin_key = "0.7-0.8"
        elif 0.8 <= conf < 0.9: bin_key = "0.8-0.9"
        elif 0.9 <= conf <= 1.0: bin_key = "0.9-1.0"
        
        if bin_key:
            calibration_bins[bin_key]["total"] += 1
            if class_is_correct:
                calibration_bins[bin_key]["correct"] += 1

        # Routing Check
        actual_routing = res.get("routing", {}).get("destination", "")
        expected_routing = gt.get("expected_routing", "")
        is_routing_correct = (actual_routing == expected_routing)
        if is_routing_correct:
            routing_correct += 1
        else:
            failures_list.append({
                "doc": doc_name,
                "aspect": "Routing",
                "expected": expected_routing,
                "actual": actual_routing,
                "cause": f"Classification was '{actual_type}' instead of '{expected_type}'"
            })

        # Field Extraction Scoring
        gt_fields = gt.get("expected_fields", {})
        extracted_fields_map = {f.get("label", "").strip(): str(f.get("value", "")).strip() for f in res.get("fields", [])}
        extracted_keys_clean = [re.sub(r"[^\w\s]", "", k).lower().strip() for k in extracted_fields_map.keys()]

        has_field_error = False
        for exp_lbl, exp_val in gt_fields.items():
            matched_act_val = None
            # Find matching label
            for act_lbl, act_val in extracted_fields_map.items():
                if exp_lbl.lower() in act_lbl.lower() or act_lbl.lower() in exp_lbl.lower():
                    matched_act_val = act_val
                    break
            
            if matched_act_val is not None:
                # Exact match
                if matched_act_val == exp_val:
                    field_stats[exp_lbl]["tp_exact"] += 1
                    field_stats[exp_lbl]["tp_norm"] += 1
                elif normalize_val(matched_act_val) == normalize_val(exp_val):
                    field_stats[exp_lbl]["tp_norm"] += 1
                    failures_list.append({
                        "doc": doc_name,
                        "aspect": f"Field ({exp_lbl})",
                        "expected": exp_val,
                        "actual": matched_act_val,
                        "cause": "Formatting/delimiter variation"
                    })
                else:
                    field_stats[exp_lbl]["fp"] += 1
                    has_field_error = True
                    failures_list.append({
                        "doc": doc_name,
                        "aspect": f"Field ({exp_lbl})",
                        "expected": exp_val,
                        "actual": matched_act_val,
                        "cause": "Value misextraction / segmentation error"
                    })
            else:
                field_stats[exp_lbl]["fn"] += 1
                has_field_error = True
                failures_list.append({
                    "doc": doc_name,
                    "aspect": f"Field ({exp_lbl})",
                    "expected": exp_val,
                    "actual": "(missing)",
                    "cause": "Label was not recognized or missing from output"
                })

        # Hallucination Check: Extracted fields that do not exist in doc
        for act_lbl, act_val in extracted_fields_map.items():
            if act_lbl and act_val:
                # If neither the label nor the value appears in raw_text
                raw_ref = gt.get("raw_text", "").lower()
                if act_val.lower() not in raw_ref and len(act_val) > 3:
                    hallucinated_fields.append((doc_name, act_lbl, act_val))

        # Sensitive Findings Scoring
        gt_sensitive = gt.get("expected_sensitive", [])
        act_sensitive = res.get("sensitive_findings", [])
        if gt_sensitive:
            for s_gt in gt_sensitive:
                stype = s_gt["type"]
                sval = s_gt["value"]
                found = any(sval in (a.get("raw_value") or "") or stype == a.get("type") for a in act_sensitive)
                if found:
                    sensitive_stats[stype]["tp"] += 1
                else:
                    sensitive_stats[stype]["fn"] += 1
        elif act_sensitive:
            for a in act_sensitive:
                sensitive_stats[a.get("type", "UNKNOWN")]["fp"] += 1
                sensitive_false_positives.append((doc_name, a.get("type"), a.get("raw_value")))

        # OCR CER/WER on image inputs
        if gt.get("format") in ("image_png", "scanned_image", "image_only_pdf"):
            flawed_fields_text = " ".join([f.get("label", "") + " " + f.get("value", "") for f in res.get("fields", [])])
            ocr_text = res.get("raw_text") or " ".join(res.get("raw_text_by_page", {}).values())
            if not ocr_text.strip():
                ocr_text = flawed_fields_text

            raw_ref = gt.get("raw_text", "")
            
            # Flawed CER/WER (fields vs raw_text)
            cer_flawed = calculate_cer(raw_ref, flawed_fields_text)
            wer_flawed = calculate_wer(raw_ref, flawed_fields_text)
            cer_scores_flawed.append(cer_flawed)
            wer_scores_flawed.append(wer_flawed)
            
            # Full-Page Raw CER/WER
            cer_raw = calculate_cer(raw_ref, ocr_text)
            wer_raw = calculate_wer(raw_ref, ocr_text)
            cer_scores_raw.append(cer_raw)
            wer_scores_raw.append(wer_raw)
            
            # Full-Page Case-Normalized CER/WER
            cer_norm = calculate_cer(raw_ref.lower(), ocr_text.lower())
            wer_norm = calculate_wer(raw_ref.lower(), ocr_text.lower())
            cer_scores_norm.append(cer_norm)
            wer_scores_norm.append(wer_norm)

        # Review Behavior Evaluation
        actual_review = res.get("needs_review", False)
        is_wrong = (not class_is_correct) or (not is_routing_correct) or has_field_error
        if actual_review:
            review_sent += 1
            if is_wrong:
                review_needed_and_sent += 1
        else:
            if is_wrong:
                unflagged_errors += 1
                failures_list.append({
                    "doc": doc_name,
                    "aspect": "CRITICAL: Unflagged Wrong Result",
                    "expected": f"Type={expected_type}, Review=True",
                    "actual": f"Type={actual_type}, Review=False",
                    "cause": "Confidence threshold was satisfied despite incorrect output."
                })

        per_document_records.append({
            "file": doc_name,
            "expected_type": expected_type,
            "predicted_type": actual_type,
            "type_confidence": round(type_conf, 4),
            "expected_routing": expected_routing,
            "actual_routing": actual_routing,
            "routing_match": is_routing_correct,
            "field_error": has_field_error,
            "flagged_for_review": actual_review,
            "is_wrong": is_wrong,
            "review_reasons": res.get("review_reasons", [])
        })

    # Summary Calculations
    total_class_correct = sum(confusion_matrix[t][t] for t in types_all)
    class_acc = (total_class_correct / total_docs) if total_docs > 0 else 0.0
    routing_acc = (routing_correct / total_docs) if total_docs > 0 else 0.0

    avg_cer_norm = (sum(cer_scores_norm) / len(cer_scores_norm)) if cer_scores_norm else 0.0
    avg_wer_norm = (sum(wer_scores_norm) / len(wer_scores_norm)) if wer_scores_norm else 0.0
    avg_cer_raw = (sum(cer_scores_raw) / len(cer_scores_raw)) if cer_scores_raw else 0.0
    avg_wer_raw = (sum(wer_scores_raw) / len(wer_scores_raw)) if wer_scores_raw else 0.0
    avg_cer_flawed = (sum(cer_scores_flawed) / len(cer_scores_flawed)) if cer_scores_flawed else 0.0
    avg_wer_flawed = (sum(wer_scores_flawed) / len(wer_scores_flawed)) if wer_scores_flawed else 0.0

    repeatable_count = sum(1 for v in repeat_checks.values() if v)
    repeat_rate = (repeatable_count / total_docs) if total_docs > 0 else 0.0

    eval_output = {
        "total_documents": total_docs,
        "classification": {
            "overall_accuracy": round(class_acc, 4),
            "confusion_matrix": {k: dict(v) for k, v in confusion_matrix.items()},
            "per_type_accuracy": {
                t: round(confusion_matrix[t][t] / sum(confusion_matrix[t].values()), 4)
                for t in types_all if sum(confusion_matrix[t].values()) > 0
            }
        },
        "key_fields": {
            lbl: {
                "tp_exact": stats["tp_exact"],
                "tp_norm": stats["tp_norm"],
                "fp": stats["fp"],
                "fn": stats["fn"],
                "precision": round(stats["tp_norm"] / (stats["tp_norm"] + stats["fp"]), 4) if (stats["tp_norm"] + stats["fp"]) > 0 else 0.0,
                "recall": round(stats["tp_norm"] / (stats["tp_norm"] + stats["fn"]), 4) if (stats["tp_norm"] + stats["fn"]) > 0 else 0.0,
                "f1": round(2 * stats["tp_norm"] / (2 * stats["tp_norm"] + stats["fp"] + stats["fn"]), 4) if (2 * stats["tp_norm"] + stats["fp"] + stats["fn"]) > 0 else 0.0
            }
            for lbl, stats in field_stats.items()
        },
        "sensitive_detection": {
            st: {
                "precision": round(stats["tp"] / (stats["tp"] + stats["fp"]), 4) if (stats["tp"] + stats["fp"]) > 0 else 0.0,
                "recall": round(stats["tp"] / (stats["tp"] + stats["fn"]), 4) if (stats["tp"] + stats["fn"]) > 0 else 0.0,
            }
            for st, stats in sensitive_stats.items()
        },
        "sensitive_false_positives": sensitive_false_positives,
        "routing_accuracy": round(routing_acc, 4),
        "ocr_metrics": {
            "average_cer_case_normalized": round(avg_cer_norm, 4),
            "average_wer_case_normalized": round(avg_wer_norm, 4),
            "average_cer_raw": round(avg_cer_raw, 4),
            "average_wer_raw": round(avg_wer_raw, 4),
            "average_cer_flawed_measurement": round(avg_cer_flawed, 4),
            "average_wer_flawed_measurement": round(avg_wer_flawed, 4)
        },
        "confidence_calibration": {
            b: {
                "total": data["total"],
                "correct": data["correct"],
                "empirical_accuracy": round(data["correct"] / data["total"], 4) if data["total"] > 0 else 0.0
            }
            for b, data in calibration_bins.items()
        },
        "review_behavior": {
            "review_rate": round(review_sent / total_docs, 4),
            "total_sent_to_review": review_sent,
            "true_positives_for_review": review_needed_and_sent,
            "unflagged_wrong_results": unflagged_errors
        },
        "hallucinations_detected": hallucinated_fields,
        "robustness_repeatability_rate": round(repeat_rate, 4),
        "per_document_table": per_document_records,
        "top_failures": failures_list[:10]
    }

    os.makedirs("data/verification/accuracy_suite/results", exist_ok=True)
    out_file = "data/verification/accuracy_suite/results/part2_accuracy_report.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(eval_output, f, indent=2)

    print("\n" + "=" * 70)
    print("PART 2 EXTRACTION ACCURACY EVALUATION COMPLETE")
    print(f"Overall Classification Accuracy: {class_acc * 100:.2f}%")
    print(f"Routing Accuracy: {routing_acc * 100:.2f}%")
    print(f"Review Rate: {review_sent}/{total_docs} ({review_sent/total_docs*100:.1f}%)")
    print(f"Unflagged Wrong Results (Critical Failure): {unflagged_errors}")
    print(f"Repeatability Rate (3x): {repeat_rate * 100:.2f}%")
    print(f"Average Image CER: {avg_cer * 100:.2f}%, WER: {avg_wer * 100:.2f}%")
    print("=" * 70)

if __name__ == "__main__":
    run_evaluation()
