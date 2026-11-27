import os
import json
import math
import re
from collections import defaultdict

EVIDENCE_DIR = "evidence/20261126_212000"
GT_DIR = os.path.join(EVIDENCE_DIR, "ground_truth")
RAW_DIR = os.path.join(EVIDENCE_DIR, "raw_outputs")
METRICS_PATH = os.path.join(RAW_DIR, "computed_accuracy_metrics.json")
REPORT_TEXT_PATH = os.path.join(RAW_DIR, "computed_accuracy_metrics.txt")

def levenshtein_distance(s1, s2):
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    distances = range(len(s1) + 1)
    for i2, c2 in enumerate(s2):
        distances_ = [i2+1]
        for i1, c1 in enumerate(s1):
            if c1 == c2:
                distances_.append(distances[i1])
            else:
                distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
        distances = distances_
    return distances[-1]

def compute_cer(gt, pred, normalize=False):
    if normalize:
        gt = re.sub(r'\s+', ' ', gt.lower().strip())
        pred = re.sub(r'\s+', ' ', pred.lower().strip())
    if not gt:
        return 0.0 if not pred else 1.0
    dist = levenshtein_distance(gt, pred)
    return min(1.0, dist / len(gt))

def compute_wer(gt, pred, normalize=False):
    if normalize:
        w_gt = re.sub(r'[^\w\s]', '', gt.lower()).split()
        w_pred = re.sub(r'[^\w\s]', '', pred.lower()).split()
    else:
        w_gt = gt.split()
        w_pred = pred.split()
    if not w_gt:
        return 0.0 if not w_pred else 1.0
    dist = levenshtein_distance(w_gt, w_pred)
    return min(1.0, dist / len(w_gt))

def wilson_ci(k, n, z=1.96):
    """95% Wilson Score confidence interval for proportions."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + (z**2) / n
    centre = (p + (z**2) / (2 * n)) / denom
    spread = (z / denom) * math.sqrt((p * (1 - p) / n) + ((z**2) / (4 * (n**2))))
    return (max(0.0, round(centre - spread, 4)), min(1.0, round(centre + spread, 4)))

def main():
    print("[METRICS] Loading ground truth and scraped results...")
    
    # 1. Load Ground Truth
    ground_truth = {}
    if os.path.exists(GT_DIR):
        for fn in os.listdir(GT_DIR):
            if fn.endswith(".json"):
                with open(os.path.join(GT_DIR, fn), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    base_key = data.get("file") or fn.replace(".json", "")
                    ground_truth[base_key] = data

    # 2. Load Real UI Scraped Results or Database Files
    import sqlite3
    conn = sqlite3.connect("data/ecm_pipeline.db")
    c = conn.cursor()
    c.execute("""
        SELECT f.id, f.original_name, f.stage, f.status, f.doc_type, f.check_reasons, 
               f.document_summary, f.raw_text_by_page, f.created_at, f.finished_at
        FROM files f
        ORDER BY f.created_at DESC
    """)
    db_files = c.fetchall()

    # Match evaluated files
    total_evaluated = 0
    correct_group_count = 0
    routing_correct_count = 0
    confusion_matrix = defaultdict(lambda: defaultdict(int))
    wrongly_grouped = []
    
    # Field extraction counters
    field_exact_matches = 0
    field_norm_matches = 0
    total_expected_fields = 0
    total_extracted_fields = 0
    per_kind_extraction = defaultdict(lambda: {"expected": 0, "matched": 0, "extracted": 0})
    
    # OCR metrics
    cer_raw_list = []
    cer_norm_list = []
    wer_raw_list = []
    wer_norm_list = []
    
    # Confidence calibration
    bands = {"0.90-1.00": [0, 0], "0.80-0.89": [0, 0], "0.70-0.79": [0, 0], "<0.70": [0, 0]}
    
    # Unflagged wrong
    unflagged_wrong = []
    
    per_file_rows = []

    seen_files = set()
    for row in db_files:
        fid, orig_name, stage, status, doc_type, check_reasons, summary, raw_text_json, created, finished = row
        if orig_name in seen_files:
            continue
        
        # Match with ground truth
        matched_gt = None
        for k, v in ground_truth.items():
            if k == orig_name or k.startswith(orig_name.rsplit(".", 1)[0]) or orig_name.startswith(k.rsplit(".", 1)[0]):
                matched_gt = v
                break
        
        if not matched_gt:
            continue
            
        seen_files.add(orig_name)
        total_evaluated += 1
        
        expected_type = matched_gt.get("expected_type", "unknown")
        actual_type = doc_type or "unknown"
        
        # Group determination
        is_failed = stage == "Failed" or status == "Failed" or actual_type == "Could not read"
        group_assigned = "Could not read" if is_failed else actual_type
        
        confusion_matrix[expected_type][group_assigned] += 1
        
        # Segregation accuracy check
        is_type_match = expected_type.lower() == actual_type.lower() or (expected_type == "unknown" and actual_type in ["unknown", "Document"])
        if is_type_match:
            correct_group_count += 1
        else:
            wrongly_grouped.append({"file": orig_name, "expected": expected_type, "actual": actual_type, "group": group_assigned})
            
        # Routing check
        expected_routing = matched_gt.get("expected_routing", f"{expected_type.upper()}_PROCESSING_SYSTEM" if expected_type != "unknown" else "MANUAL_TRIAGE_QUEUE")
        actual_routing = f"{actual_type.upper()}_PROCESSING_SYSTEM" if actual_type not in ["unknown", "Could not read", "Document"] else "MANUAL_TRIAGE_QUEUE"
        if expected_routing == actual_routing:
            routing_correct_count += 1
            
        # Fetch fields for this file
        c.execute("SELECT label, value, confidence FROM fields WHERE file_id=?", (fid,))
        extracted_fields = c.fetchall()
        total_extracted_fields += len(extracted_fields)
        
        gt_fields = matched_gt.get("expected_fields", {})
        total_expected_fields += len(gt_fields)
        per_kind_extraction[expected_type]["expected"] += len(gt_fields)
        per_kind_extraction[expected_type]["extracted"] += len(extracted_fields)
        
        file_field_matches = 0
        for exp_lbl, exp_val in gt_fields.items():
            match_found = False
            for act_lbl, act_val, conf in extracted_fields:
                val_clean_exp = re.sub(r'[\s$,.-]', '', str(exp_val).lower())
                val_clean_act = re.sub(r'[\s$,.-]', '', str(act_val).lower())
                if val_clean_exp == val_clean_act:
                    match_found = True
                    field_norm_matches += 1
                    if str(exp_val).strip() == str(act_val).strip():
                        field_exact_matches += 1
                    break
            if match_found:
                file_field_matches += 1
                per_kind_extraction[expected_type]["matched"] += 1

        # Confidence calibration
        for act_lbl, act_val, conf in extracted_fields:
            c_val = float(conf) if conf is not None else 0.95
            if c_val >= 0.90:
                b_name = "0.90-1.00"
            elif c_val >= 0.80:
                b_name = "0.80-0.89"
            elif c_val >= 0.70:
                b_name = "0.70-0.79"
            else:
                b_name = "<0.70"
            bands[b_name][1] += 1
            # Check correctness against gt
            if any(re.sub(r'[\s$,.-]', '', str(v).lower()) == re.sub(r'[\s$,.-]', '', str(act_val).lower()) for v in gt_fields.values()):
                bands[b_name][0] += 1

        # Text / OCR CER/WER
        gt_text = matched_gt.get("full_text", "")
        if gt_text and raw_text_json:
            try:
                raw_dict = json.loads(raw_text_json)
                act_text = " ".join(raw_dict.values())
            except:
                act_text = str(raw_text_json)
            if act_text:
                cer_raw = compute_cer(gt_text, act_text, normalize=False)
                cer_norm = compute_cer(gt_text, act_text, normalize=True)
                wer_raw = compute_wer(gt_text, act_text, normalize=False)
                wer_norm = compute_wer(gt_text, act_text, normalize=True)
                cer_raw_list.append(cer_raw)
                cer_norm_list.append(cer_norm)
                wer_raw_list.append(wer_raw)
                wer_norm_list.append(wer_norm)

        # Check wrong but not flagged
        has_flag = status in ["Done, check", "Needs check", "Failed"] or bool(check_reasons)
        is_wrong = not is_type_match or (gt_fields and file_field_matches < len(gt_fields))
        if is_wrong and not has_flag:
            unflagged_wrong.append({"file": orig_name, "expected": expected_type, "actual": actual_type})

        per_file_rows.append({
            "file": orig_name,
            "expected_kind": expected_type,
            "found_kind": actual_type,
            "group": group_assigned,
            "status": status,
            "check_reasons": check_reasons or "-",
            "details_extracted": len(extracted_fields),
            "ground_truth_fields": len(gt_fields)
        })

    # Compute Final Scores
    segregation_accuracy = round(correct_group_count / max(1, total_evaluated), 4)
    routing_accuracy = round(routing_correct_count / max(1, total_evaluated), 4)
    
    field_precision = round(field_norm_matches / max(1, total_extracted_fields), 4)
    field_recall = round(field_norm_matches / max(1, total_expected_fields), 4)
    field_f1 = round(2 * (field_precision * field_recall) / max(0.0001, (field_precision + field_recall)), 4)
    
    mean_cer_raw = round(sum(cer_raw_list) / max(1, len(cer_raw_list)), 4)
    mean_cer_norm = round(sum(cer_norm_list) / max(1, len(cer_norm_list)), 4)
    mean_wer_raw = round(sum(wer_raw_list) / max(1, len(wer_raw_list)), 4)
    mean_wer_norm = round(sum(wer_norm_list) / max(1, len(wer_norm_list)), 4)
    
    ci_segregation = wilson_ci(correct_group_count, total_evaluated)
    ci_routing = wilson_ci(routing_correct_count, total_evaluated)
    ci_recall = wilson_ci(field_norm_matches, total_expected_fields)

    calibration_results = {}
    for b_name, (corr, tot) in bands.items():
        acc = round(corr / max(1, tot), 4) if tot > 0 else 0.0
        calibration_results[b_name] = {"correct": corr, "total": tot, "accuracy": acc}

    metrics = {
        "total_documents_evaluated": total_evaluated,
        "segregation": {
            "correct": correct_group_count,
            "total": total_evaluated,
            "accuracy": segregation_accuracy,
            "confidence_interval_95": ci_segregation,
            "wrongly_grouped": wrongly_grouped,
            "confusion_matrix": confusion_matrix
        },
        "routing": {
            "correct": routing_correct_count,
            "total": total_evaluated,
            "accuracy": routing_accuracy,
            "confidence_interval_95": ci_routing
        },
        "extraction": {
            "precision": field_precision,
            "recall": field_recall,
            "f1_score": field_f1,
            "exact_matches": field_exact_matches,
            "normalized_matches": field_norm_matches,
            "total_expected": total_expected_fields,
            "total_extracted": total_extracted_fields,
            "confidence_interval_recall_95": ci_recall,
            "per_kind": per_kind_extraction
        },
        "ocr_accuracy": {
            "mean_cer_raw": mean_cer_raw,
            "mean_cer_normalized": mean_cer_norm,
            "mean_wer_raw": mean_wer_raw,
            "mean_wer_normalized": mean_wer_norm,
            "samples_evaluated": len(cer_raw_list)
        },
        "confidence_calibration": calibration_results,
        "wrong_but_not_flagged": {
            "count": len(unflagged_wrong),
            "files": unflagged_wrong
        },
        "per_file_table": per_file_rows
    }

    with open(METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    with open(REPORT_TEXT_PATH, "w", encoding="utf-8") as f:
        f.write("COMPUTED ACCURACY AND SEGREGATION METRICS\n")
        f.write("=========================================\n")
        f.write(f"Total Evaluated Documents: {total_evaluated}\n")
        f.write(f"Segregation Accuracy: {segregation_accuracy * 100:.2f}% (95% CI: {ci_segregation[0]*100:.1f}% - {ci_segregation[1]*100:.1f}%)\n")
        f.write(f"Routing Accuracy: {routing_accuracy * 100:.2f}% (95% CI: {ci_routing[0]*100:.1f}% - {ci_routing[1]*100:.1f}%)\n")
        f.write(f"Extraction Precision: {field_precision * 100:.2f}%\n")
        f.write(f"Extraction Recall: {field_recall * 100:.2f}% (95% CI: {ci_recall[0]*100:.1f}% - {ci_recall[1]*100:.1f}%)\n")
        f.write(f"Extraction F1 Score: {field_f1 * 100:.2f}%\n")
        f.write(f"OCR Character Error Rate (Raw): {mean_cer_raw * 100:.2f}%\n")
        f.write(f"OCR Character Error Rate (Normalized): {mean_cer_norm * 100:.2f}%\n")
        f.write(f"OCR Word Error Rate (Normalized): {mean_wer_norm * 100:.2f}%\n")
        f.write(f"Wrong but Not Flagged Count: {len(unflagged_wrong)}\n\n")
        f.write("CONFIDENCE CALIBRATION:\n")
        for b, d in calibration_results.items():
            f.write(f"  Band {b}: {d['correct']}/{d['total']} = {d['accuracy']*100:.1f}%\n")

    print(f"[METRICS] Computed metrics successfully written to {METRICS_PATH} and {REPORT_TEXT_PATH}")

if __name__ == "__main__":
    main()
