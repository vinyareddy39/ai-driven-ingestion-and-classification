"""
Evaluation Script for Table and Field Extraction Verification:
1. Evaluates 15 synthetic documents with varying table shapes (3-8 columns, ruled & unruled).
2. Measures table-cell extraction accuracy against ground truth.
3. Measures same-line label/value pairing accuracy.
4. Counts orphan unlabelled fields (confirms 0 from table cells).
5. Confirms NO header cells converted into loose label/value pairs.
6. Analyzes confidence distributions (verifies NO fixed 0.90 or 0.50 values).
7. Reports arithmetic verification results.
"""

import os
import sys
import json
import glob

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.generalized_pipeline import GeneralizedDocumentPipeline

INPUTS_DIR = os.path.join("table_eval_suite", "inputs")
EXPECTED_DIR = os.path.join("table_eval_suite", "expected")
RESULTS_PATH = os.path.join("table_eval_suite", "table_verification_results.json")

def evaluate_suite():
    pdf_files = sorted(glob.glob(os.path.join(INPUTS_DIR, "*.pdf")))
    pipeline = GeneralizedDocumentPipeline()
    
    total_docs = len(pdf_files)
    total_expected_cells = 0
    correct_cells = 0
    total_expected_headers = 0
    correct_headers = 0
    
    total_expected_pairs = 0
    correct_pairs = 0
    
    orphan_unlabelled_count = 0
    table_cell_leak_count = 0
    header_leak_count = 0
    
    fixed_90_label_conf_count = 0
    fixed_50_val_conf_count = 0
    
    label_confidences = []
    value_confidences = []
    
    arithmetic_checks_total = 0
    arithmetic_verified_count = 0
    
    doc_results = []

    print(f"Running evaluation on {total_docs} synthetic documents...")

    for pdf_path in pdf_files:
        doc_id = os.path.splitext(os.path.basename(pdf_path))[0]
        expected_path = os.path.join(EXPECTED_DIR, f"{doc_id}.json")
        with open(expected_path, "r", encoding="utf-8") as f:
            expected = json.load(f)

        pipe_res = pipeline.process_file(pdf_path)
        
        extracted_tables = pipe_res.get("tables", [])
        extracted_fields = pipe_res.get("fields", [])
        
        # 1. Table Extraction Accuracy
        exp_headers = expected["headers"]
        exp_rows = expected["rows"]
        
        doc_cells_total = sum(len(r) for r in exp_rows)
        total_expected_cells += doc_cells_total
        total_expected_headers += len(exp_headers)
        
        doc_cells_correct = 0
        doc_headers_correct = 0
        
        detected_tbl = None
        for tbl in extracted_tables:
            if len(tbl.get("headers", [])) == len(exp_headers):
                detected_tbl = tbl
                break
        if not detected_tbl and extracted_tables:
            detected_tbl = extracted_tables[0]
        if detected_tbl:
            det_headers = [h.strip().lower() for h in detected_tbl.get("headers", [])]
            for eh in exp_headers:
                if any(eh.strip().lower() in dh or dh in eh.strip().lower() for dh in det_headers):
                    correct_headers += 1
                    doc_headers_correct += 1
                    
            det_rows = detected_tbl.get("rows", [])
            for r_idx, exp_r in enumerate(exp_rows):
                if r_idx < len(det_rows):
                    det_r = det_rows[r_idx]
                    cells = det_r.get("cells", det_r)
                    for c_idx, exp_c in enumerate(exp_r):
                        # Match cell value in any cell of the row
                        exp_str = str(exp_c).strip().lower()
                        found = False
                        for dh, dv in cells.items():
                            if exp_str == str(dv).strip().lower():
                                found = True
                                break
                        if found:
                            correct_cells += 1
                            doc_cells_correct += 1
                            
            # Arithmetic checks
            checks = detected_tbl.get("arithmetic_checks", [])
            arithmetic_checks_total += len(checks)
            for chk in checks:
                if chk.get("status") == "verified" or chk.get("valid"):
                    arithmetic_verified_count += 1
        
        # 2. Check for Table Cell / Header Leak into Loose Fields
        loose_labels = [f.get("label", "").strip().lower() for f in extracted_fields]
        loose_values = [f.get("value", "").strip().lower() for f in extracted_fields]
        
        for eh in exp_headers:
            # Header cells should NEVER be turned into loose field values
            if eh.strip().lower() in loose_values:
                header_leak_count += 1
                
        for r in exp_rows:
            for cell in r:
                # Table cell values should NOT appear as orphan loose unlabelled fields
                cell_str = str(cell).strip().lower()
                for fld in extracted_fields:
                    if not fld.get("label", "").strip() and fld.get("value", "").strip().lower() == cell_str:
                        table_cell_leak_count += 1
                        
        # 3. Same-Line Pairing Accuracy
        exp_pairs = expected.get("same_line_pairs", [])
        total_expected_pairs += len(exp_pairs)
        doc_pairs_correct = 0
        for exp_lbl, exp_val in exp_pairs:
            matched = False
            for fld in extracted_fields:
                f_lbl = fld.get("label", "").strip().lower()
                f_val = fld.get("value", "").strip().lower()
                e_lbl = exp_lbl.strip().lower()
                e_val = exp_val.strip().lower()
                if (e_lbl in f_lbl or f_lbl in e_lbl) and (e_val == f_val or e_val.replace("$", "") == f_val.replace("$", "")):
                    matched = True
                    break
            if matched:
                correct_pairs += 1
                doc_pairs_correct += 1
                
        # 4. Orphan Unlabelled Count & Confidence Distributions
        doc_unlabelled = 0
        for fld in extracted_fields:
            lbl = fld.get("label", "").strip()
            lbl_c = fld.get("label_confidence")
            val_c = fld.get("value_confidence")
            
            if not lbl:
                doc_unlabelled += 1
                orphan_unlabelled_count += 1
                # Must be None for unlabelled
                if lbl_c == 0.90:
                    fixed_90_label_conf_count += 1
            else:
                if lbl_c is not None:
                    label_confidences.append(lbl_c)
                    if lbl_c == 0.90:
                        fixed_90_label_conf_count += 1
                        
            if val_c is not None:
                value_confidences.append(val_c)
                if val_c == 0.50:
                    fixed_50_val_conf_count += 1

        doc_results.append({
            "doc_id": doc_id,
            "table_detected": bool(detected_tbl),
            "headers_matched": f"{doc_headers_correct}/{len(exp_headers)}",
            "cells_matched": f"{doc_cells_correct}/{doc_cells_total}",
            "pairs_matched": f"{doc_pairs_correct}/{len(exp_pairs)}",
            "unlabelled_fields": doc_unlabelled,
        })

    cell_acc = round((correct_cells / total_expected_cells * 100), 2) if total_expected_cells > 0 else 0
    header_acc = round((correct_headers / total_expected_headers * 100), 2) if total_expected_headers > 0 else 0
    pair_acc = round((correct_pairs / total_expected_pairs * 100), 2) if total_expected_pairs > 0 else 0

    summary = {
        "total_documents": total_docs,
        "table_cell_accuracy": f"{cell_acc}% ({correct_cells}/{total_expected_cells})",
        "header_accuracy": f"{header_acc}% ({correct_headers}/{total_expected_headers})",
        "label_pairing_accuracy": f"{pair_acc}% ({correct_pairs}/{total_expected_pairs})",
        "table_cell_leaks_into_fields": table_cell_leak_count,
        "header_cells_as_values": header_leak_count,
        "fixed_90_label_confidences": fixed_90_label_conf_count,
        "fixed_50_value_confidences": fixed_50_val_conf_count,
        "orphan_unlabelled_count": orphan_unlabelled_count,
        "arithmetic_checks_total": arithmetic_checks_total,
        "arithmetic_verified": arithmetic_verified_count,
        "label_confidence_range": [min(label_confidences) if label_confidences else None, max(label_confidences) if label_confidences else None],
        "value_confidence_range": [min(value_confidences) if value_confidences else None, max(value_confidences) if value_confidences else None],
        "per_document": doc_results,
    }

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "="*60)
    print("TABLE & FIELD VERIFICATION RESULTS")
    print("="*60)
    print(f"Total Documents Tested: {total_docs}")
    print(f"Table Cell Accuracy: {summary['table_cell_accuracy']}")
    print(f"Header Extraction Accuracy: {summary['header_accuracy']}")
    print(f"Same-Line Label Pairing Accuracy: {summary['label_pairing_accuracy']}")
    print(f"Header Cells Discarded from Loose Fields: {header_leak_count == 0} (Leak count: {header_leak_count})")
    print(f"Table Cells Isolated from Loose Fields: {table_cell_leak_count == 0} (Leak count: {table_cell_leak_count})")
    print(f"Fixed 90% Label Confidences: {fixed_90_label_conf_count} (Expected: 0)")
    print(f"Fixed 50% Value Confidences: {fixed_50_val_conf_count} (Expected: 0)")
    print(f"Label Confidence Range: {summary['label_confidence_range']}")
    print(f"Value Confidence Range: {summary['value_confidence_range']}")
    print(f"Arithmetic Checks: {arithmetic_verified_count}/{arithmetic_checks_total} verified")
    print(f"Results saved to {RESULTS_PATH}")
    print("="*60)

if __name__ == "__main__":
    evaluate_suite()
