"""Comprehensive Structure Extraction Evaluation Suite.

Evaluates GeneralizedDocumentPipeline across all 40 documents in structure_eval_suite/inputs.
Measures:
  1. Structure accuracy per type (all 17 types)
  2. Label/value pairing accuracy (precision, recall, F1)
  3. Table cell extraction accuracy
  4. Checkbox state accuracy (selected, empty, unclear)
  5. Barcode & QR decode accuracy
  6. Orphan unlabeled count (target 0: must have printed label, suggested, or hint 'needs label')
  7. Repeating header/footer leakage share (target 0%)
  8. Footnote & watermark leakage share (target 0%)
  9. Confidence distributions (value_conf, label_conf, structure_conf)
"""

import os
import sys
import re
import json
import time

sys.path.insert(0, os.path.abspath("."))
from collections import defaultdict
from app.core.generalized_pipeline import GeneralizedDocumentPipeline

INPUTS_DIR = os.path.abspath("structure_eval_suite/inputs")
EXPECTED_DIR = os.path.abspath("structure_eval_suite/expected")


def normalize_text(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def run_evaluation():
    pipeline = GeneralizedDocumentPipeline()
    input_files = sorted([f for f in os.listdir(INPUTS_DIR) if not f.startswith(".")])

    total_files = len(input_files)
    print(f"=== Starting Structure Evaluation Suite ({total_files} documents) ===")

    # Metrics accumulators
    structure_counts_expected = defaultdict(int)
    structure_counts_detected = defaultdict(int)
    structure_counts_correct = defaultdict(int)

    pairing_true_positives = 0
    pairing_false_positives = 0
    pairing_false_negatives = 0

    table_cells_expected = 0
    table_cells_correct = 0

    checkbox_states_expected = 0
    checkbox_states_correct = 0

    barcodes_expected = 0
    barcodes_correct = 0

    signatures_expected = 0
    signatures_correct = 0

    lists_expected = 0
    lists_correct = 0

    orphan_unlabeled_count = 0
    header_footer_leakage_count = 0
    footnote_watermark_leakage_count = 0

    val_confidences = []
    lbl_confidences = []
    struct_confidences = []

    per_doc_results = []
    t_start = time.perf_counter()

    for idx, fname in enumerate(input_files, 1):
        fpath = os.path.join(INPUTS_DIR, fname)
        exp_name = fname.replace(".pdf", ".expected.json").replace(".png", ".expected.json")
        exp_path = os.path.join(EXPECTED_DIR, exp_name)

        if not os.path.exists(exp_path):
            print(f"Warning: Expected file {exp_name} missing. Skipping.")
            continue

        with open(exp_path, "r", encoding="utf-8") as f_in:
            expected = json.load(f_in)

        # Process through full pipeline
        t0 = time.perf_counter()
        res = pipeline.process_file(fpath)
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)

        actual_fields = res.get("fields", [])
        actual_regions = res.get("regions", [])
        actual_tables = res.get("tables", [])
        actual_lists = res.get("lists", [])
        actual_checkboxes = res.get("checkboxes", [])
        actual_signatures = res.get("signatures", [])
        actual_codes = res.get("codes", [])

        # 1. Structure types present
        detected_types = set(r.get("structure_type") for r in actual_regions)
        # Also check fields metadata
        for fld in actual_fields:
            if fld.get("structure_type"):
                detected_types.add(fld.get("structure_type"))
        for t in actual_tables:
            detected_types.add("table")
        for c in actual_codes:
            detected_types.add("barcode_qr")
        for s in actual_signatures:
            detected_types.add("signature_stamp")
        for l in actual_lists:
            detected_types.add("list")
        for cb in actual_checkboxes:
            detected_types.add("checkbox_group")

        expected_structures = set(expected.get("expected_structures", []))
        for st in expected_structures:
            structure_counts_expected[st] += 1
            if st in detected_types:
                structure_counts_correct[st] += 1
        for dt in detected_types:
            structure_counts_detected[dt] += 1

        # 2. Label/Value Pairing Accuracy
        exp_fields = expected.get("expected_fields", {})
        actual_kv = {}
        for fld in actual_fields:
            lbl = fld.get("label", "").strip()
            val = fld.get("value", "").strip()
            if lbl:
                actual_kv[normalize_text(lbl)] = val
            # Check for orphan unlabelled
            if not lbl and val:
                hint = fld.get("hint")
                sug = fld.get("suggested_label")
                # Allowed if it has a suggested label or hint 'needs label'
                if not sug and hint != "needs label":
                    orphan_unlabeled_count += 1

            # Confidences tracking
            if fld.get("value_confidence") is not None:
                val_confidences.append(float(fld["value_confidence"]))
            if fld.get("label_confidence") is not None:
                lbl_confidences.append(float(fld["label_confidence"]))
            if fld.get("structure_confidence") is not None:
                struct_confidences.append(float(fld["structure_confidence"]))

        for exp_k, exp_v in exp_fields.items():
            norm_k = normalize_text(exp_k)
            matched = False
            for act_k, act_v in actual_kv.items():
                if norm_k in act_k or act_k in norm_k:
                    # Found key, check value overlap
                    if normalize_text(exp_v) in normalize_text(act_v) or normalize_text(act_v) in normalize_text(exp_v):
                        pairing_true_positives += 1
                        matched = True
                        break
            if not matched:
                pairing_false_negatives += 1

        for act_k in actual_kv:
            matched = any(norm_k in act_k or act_k in norm_k for norm_k in [normalize_text(k) for k in exp_fields])
            if not matched:
                pairing_false_positives += 1

        # 3. Table cell extraction
        exp_tables = expected.get("expected_tables", [])
        if exp_tables and actual_tables:
            for exp_tbl in exp_tables:
                exp_headers = exp_tbl.get("headers", [])
                exp_rows = exp_tbl.get("row_count", 0)
                table_cells_expected += len(exp_headers) * exp_rows
                # Check actual table headers
                for act_tbl in actual_tables:
                    act_headers = act_tbl.get("headers", [])
                    act_rows = act_tbl.get("rows", [])
                    common_headers = set(normalize_text(h) for h in exp_headers) & set(normalize_text(h) for h in act_headers)
                    table_cells_correct += len(common_headers) * min(exp_rows, len(act_rows))

        # 4. Checkboxes
        exp_cbs = expected.get("expected_checkboxes", {})
        for cb_label, exp_state in exp_cbs.items():
            checkbox_states_expected += 1
            norm_cb = normalize_text(cb_label)
            cb_found = False
            for act_cb in actual_checkboxes:
                for opt in act_cb.get("options", []):
                    if norm_cb in normalize_text(opt.get("label", "")):
                        if opt.get("state") == exp_state:
                            checkbox_states_correct += 1
                        cb_found = True
                        break
                if cb_found:
                    break
            if not cb_found:
                # Check in fields
                for fld in actual_fields:
                    if norm_cb in normalize_text(fld.get("label", "")) or norm_cb in normalize_text(fld.get("value", "")):
                        v_lower = fld.get("value", "").lower()
                        if exp_state == "selected" and ("selected" in v_lower or "[x]" in v_lower):
                            checkbox_states_correct += 1
                            break
                        elif exp_state == "empty" and ("empty" in v_lower or "[ ]" in v_lower):
                            checkbox_states_correct += 1
                            break
                        elif exp_state == "unclear" and ("unclear" in v_lower or "[?]" in v_lower):
                            checkbox_states_correct += 1
                            break

        # 5. Barcodes & QR
        exp_barcodes = expected.get("expected_codes", [])
        for bc in exp_barcodes:
            barcodes_expected += 1
            exp_data = normalize_text(bc.get("data", ""))
            matched = False
            for act_bc in actual_codes:
                meta = act_bc.get("metadata", {})
                act_data = normalize_text(meta.get("decoded_value", act_bc.get("data", act_bc.get("text", ""))))
                if exp_data in act_data or act_data in exp_data or (not exp_data and act_data):
                    barcodes_correct += 1
                    matched = True
                    break
            if not matched:
                for fld in actual_fields:
                    if fld.get("structure_type") == "barcode_qr":
                        fld_val = normalize_text(fld.get("value", ""))
                        if exp_data in fld_val or fld_val in exp_data:
                            barcodes_correct += 1
                            break

        # 6. Signatures
        exp_sigs = expected.get("expected_signatures", [])
        for sig in exp_sigs:
            signatures_expected += 1
            exp_signer = normalize_text(sig.get("signer", ""))
            matched = False
            for act_sig in actual_signatures:
                meta = act_sig.get("metadata", {})
                act_status = meta.get("status", act_sig.get("status"))
                act_signer = normalize_text(meta.get("printed_signer", act_sig.get("printed_signer", "")))
                act_text = normalize_text(act_sig.get("text", ""))
                if act_status == "present" or (exp_signer and (exp_signer in act_signer or exp_signer in act_text)):
                    signatures_correct += 1
                    matched = True
                    break
            if not matched:
                for fld in actual_fields:
                    if fld.get("structure_type") == "signature_stamp":
                        signatures_correct += 1
                        break

        # 7. Lists
        exp_lists = expected.get("expected_lists", [])
        for l in exp_lists:
            lists_expected += 1
            if len(actual_lists) > 0 or any(fld.get("structure_type") == "list" for fld in actual_fields):
                lists_correct += 1

        # 8. Leakage check for repeating headers/footers, footnotes, watermarks
        hf_texts = [normalize_text(t) for t in expected.get("header_footer_texts", [])]
        fn_texts = [normalize_text(t) for t in expected.get("footnote_texts", [])]
        wm_texts = [normalize_text(t) for t in expected.get("watermark_texts", [])]

        for fld in actual_fields:
            lbl_val = f"{normalize_text(fld.get('label', ''))} {normalize_text(fld.get('value', ''))}"
            for hf in hf_texts:
                if len(hf) > 8 and hf in lbl_val and fld.get("structure_type") not in ["header_footer"]:
                    header_footer_leakage_count += 1
            for fn in fn_texts:
                if len(fn) > 12 and fn in lbl_val and fld.get("structure_type") not in ["footnote"]:
                    footnote_watermark_leakage_count += 1
            for wm in wm_texts:
                if len(wm) > 8 and wm in lbl_val and fld.get("structure_type") not in ["watermark"]:
                    footnote_watermark_leakage_count += 1

        per_doc_results.append({
            "file": fname,
            "expected_type": expected.get("document_type", "Document"),
            "detected_type": res.get("type", "Document"),
            "structures_detected": list(detected_types),
            "fields_count": len(actual_fields),
            "tables_count": len(actual_tables),
            "latency_ms": latency_ms,
        })
        print(f"[{idx:02d}/40] {fname}: {len(detected_types)} structures detected, {len(actual_fields)} fields in {latency_ms}ms")

    total_eval_time = round(time.perf_counter() - t_start, 2)

    # Calculate overall metrics
    precision = pairing_true_positives / (pairing_true_positives + pairing_false_positives) if (pairing_true_positives + pairing_false_positives) > 0 else 1.0
    recall = pairing_true_positives / (pairing_true_positives + pairing_false_negatives) if (pairing_true_positives + pairing_false_negatives) > 0 else 1.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    table_acc = (table_cells_correct / table_cells_expected) if table_cells_expected > 0 else 1.0
    checkbox_acc = (checkbox_states_correct / checkbox_states_expected) if checkbox_states_expected > 0 else 1.0
    barcode_acc = (barcodes_correct / barcodes_expected) if barcodes_expected > 0 else 1.0
    sig_acc = (signatures_correct / signatures_expected) if signatures_expected > 0 else 1.0
    list_acc = (lists_correct / lists_expected) if lists_expected > 0 else 1.0

    # Summary structure accuracy per type
    all_17_types = [
        "label_value_pair", "table", "list", "paragraph", "heading", "form_row",
        "checkbox_group", "signature_stamp", "handwriting", "image_logo",
        "chart_diagram", "barcode_qr", "header_footer", "footnote", "watermark",
        "side_by_side", "other"
    ]

    structure_type_accuracy = {}
    for st in all_17_types:
        exp_n = structure_counts_expected[st]
        corr_n = structure_counts_correct[st]
        acc = (corr_n / exp_n) if exp_n > 0 else 1.0
        structure_type_accuracy[st] = {
            "expected_count": exp_n,
            "detected_count": structure_counts_detected[st],
            "correct_count": corr_n,
            "accuracy": round(acc * 100, 1),
        }

    # Confidence distribution stats
    conf_stats = {
        "value_confidence": {
            "mean": round(float(sum(val_confidences) / len(val_confidences)), 4) if val_confidences else 0.0,
            "min": round(float(min(val_confidences)), 4) if val_confidences else 0.0,
            "max": round(float(max(val_confidences)), 4) if val_confidences else 0.0,
            "count": len(val_confidences),
        },
        "label_confidence": {
            "mean": round(float(sum(lbl_confidences) / len(lbl_confidences)), 4) if lbl_confidences else 0.0,
            "min": round(float(min(lbl_confidences)), 4) if lbl_confidences else 0.0,
            "max": round(float(max(lbl_confidences)), 4) if lbl_confidences else 0.0,
            "count": len(lbl_confidences),
        },
        "structure_confidence": {
            "mean": round(float(sum(struct_confidences) / len(struct_confidences)), 4) if struct_confidences else 0.0,
            "min": round(float(min(struct_confidences)), 4) if struct_confidences else 0.0,
            "max": round(float(max(struct_confidences)), 4) if struct_confidences else 0.0,
            "count": len(struct_confidences),
        },
    }

    results_summary = {
        "total_documents_evaluated": total_files,
        "total_evaluation_time_sec": total_eval_time,
        "pairing_metrics": {
            "precision": round(precision * 100, 2),
            "recall": round(recall * 100, 2),
            "f1_score": round(f1 * 100, 2),
            "true_positives": pairing_true_positives,
            "false_positives": pairing_false_positives,
            "false_negatives": pairing_false_negatives,
        },
        "specialized_accuracies": {
            "table_cell_accuracy": round(table_acc * 100, 2),
            "checkbox_state_accuracy": round(checkbox_acc * 100, 2),
            "barcode_qr_accuracy": round(barcode_acc * 100, 2),
            "signature_accuracy": round(sig_acc * 100, 2),
            "list_accuracy": round(list_acc * 100, 2),
        },
        "leakage_and_cleanliness": {
            "orphan_unlabeled_count": orphan_unlabeled_count,
            "header_footer_leakage_count": header_footer_leakage_count,
            "footnote_watermark_leakage_count": footnote_watermark_leakage_count,
            "header_footer_leakage_share_pct": 0.0 if header_footer_leakage_count == 0 else round((header_footer_leakage_count / len(val_confidences)) * 100, 2),
        },
        "structure_type_accuracy": structure_type_accuracy,
        "confidence_distributions": conf_stats,
        "per_document_results": per_doc_results,
    }

    out_path = os.path.abspath("structure_eval_suite/evaluation_summary.json")
    with open(out_path, "w", encoding="utf-8") as f_out:
        json.dump(results_summary, f_out, indent=2)

    print("\n=== EVALUATION RESULTS SUMMARY ===")
    print(f"Total Documents: {total_files} in {total_eval_time}s")
    print(f"Pairing Precision: {results_summary['pairing_metrics']['precision']}% | Recall: {results_summary['pairing_metrics']['recall']}% | F1: {results_summary['pairing_metrics']['f1_score']}%")
    print(f"Table Accuracy: {results_summary['specialized_accuracies']['table_cell_accuracy']}%")
    print(f"Checkbox Accuracy: {results_summary['specialized_accuracies']['checkbox_state_accuracy']}%")
    print(f"Barcode/QR Accuracy: {results_summary['specialized_accuracies']['barcode_qr_accuracy']}%")
    print(f"Signature Accuracy: {results_summary['specialized_accuracies']['signature_accuracy']}%")
    print(f"List Accuracy: {results_summary['specialized_accuracies']['list_accuracy']}%")
    print(f"Orphan Unlabeled Count: {orphan_unlabeled_count} (Target: 0)")
    print(f"Header/Footer Leakage: {header_footer_leakage_count} (Target: 0)")
    print(f"Footnote/Watermark Leakage: {footnote_watermark_leakage_count} (Target: 0)")
    print(f"\nDetailed evaluation results saved to: {out_path}")


if __name__ == "__main__":
    run_evaluation()
