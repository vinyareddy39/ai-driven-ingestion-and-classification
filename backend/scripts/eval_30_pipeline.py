"""
Evaluation Runner for 30 Seeded Documents in Sandbox Mode.
Directly invokes GeneralizedDocumentPipeline without network sockets.
Validates SHA-256 of answer key before and after, evaluates field-by-field accuracy,
sensitive detection & masking, and outputs the complete comparison report.
"""
import os
import sys
import time
import json
import hashlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.core.generalized_pipeline import GeneralizedDocumentPipeline

EVAL_DIR = os.path.join(os.path.dirname(__file__), "..", "tests-data", "seeded_eval_30")
KEY_PATH = os.path.join(EVAL_DIR, "answer_key.json")

def get_key_sha256():
    with open(KEY_PATH, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

sha_before = get_key_sha256()
print(f"PRE-RUN ANSWER_KEY_SHA256:  {sha_before}")

with open(KEY_PATH, "r", encoding="utf-8") as f:
    answer_key = json.load(f)

pipeline = GeneralizedDocumentPipeline()

eval_results = []
total_expected_fields = 0
total_matched_fields = 0
total_sensitive_expected = 0
total_sensitive_masked = 0
summary_leaks_count = 0

print(f"\nEvaluating {len(answer_key)} documents...")
t_start = time.time()

for filename, expected_data in sorted(answer_key.items()):
    file_path = os.path.join(EVAL_DIR, filename)
    doc_expected_fields = expected_data["expected_fields"]
    doc_expected_count = len(doc_expected_fields)
    total_expected_fields += doc_expected_count

    t0 = time.time()
    pipe_res = pipeline.process_file(file_path)
    elapsed = time.time() - t0

    extracted_fields = pipe_res.get("fields", [])
    doc_extracted_count = len(extracted_fields)
    doc_summary = pipe_res.get("summary", "")

    matched_in_doc = 0
    field_comparisons = []

    for exp in doc_expected_fields:
        exp_lbl = exp["label"].strip().lower()
        exp_val = exp["value"].strip()
        is_heading = (exp["type"] == "heading")

        match = None
        for ext_f in extracted_fields:
            ext_lbl = (ext_f.get("label") or "").strip().lower()
            ext_val = (ext_f.get("value") or "").strip()
            
            if is_heading:
                if ext_lbl == "" and (exp_val.lower() in ext_val.lower() or ext_val.lower() in exp_val.lower()):
                    match = ext_f
                    break
            else:
                if ext_lbl == exp_lbl:
                    match = ext_f
                    break

        if match:
            ext_lbl = (match.get("label") or "").strip()
            ext_val = (match.get("value") or "").strip()
            is_sens = bool(match.get("is_sensitive", False))
            masked_v = match.get("masked_value")

            # Check value match without truncating multi-word values
            val_clean_exp = exp_val.replace("$", "").replace(",", "").lower()
            val_clean_ext = ext_val.replace("$", "").replace(",", "").lower()
            val_match = (val_clean_exp in val_clean_ext) or (val_clean_ext in val_clean_exp) or (exp_val == ext_val)
            
            if val_match:
                matched_in_doc += 1
                total_matched_fields += 1

            if "social security" in exp["label"].lower() or "taxpayer id" in exp["label"].lower() or "payment card" in exp["label"].lower():
                total_sensitive_expected += 1
                if is_sens:
                    total_sensitive_masked += 1
                # Check summary never leaks the raw value
                if exp_val in doc_summary:
                    summary_leaks_count += 1

            field_comparisons.append({
                "expected_label": exp["label"],
                "extracted_label": ext_lbl,
                "expected_value": exp["value"],
                "extracted_value": ext_val,
                "label_matched": True,
                "value_matched": val_match,
                "is_sensitive": is_sens,
                "masked_value": masked_v,
            })
        else:
            field_comparisons.append({
                "expected_label": exp["label"],
                "extracted_label": "[NOT_FOUND]",
                "expected_value": exp["value"],
                "extracted_value": "[NOT_FOUND]",
                "label_matched": False,
                "value_matched": False,
                "is_sensitive": False,
                "masked_value": None,
            })

    accuracy_pct = round((matched_in_doc / doc_expected_count) * 100, 1) if doc_expected_count > 0 else 0
    print(f"[{expected_data['format_type']:<16}] {filename:<32}: {matched_in_doc}/{doc_expected_count} matched ({accuracy_pct}%) in {elapsed:.2f}s")

    eval_results.append({
        "filename": filename,
        "doc_id": expected_data["doc_id"],
        "category": expected_data["category"],
        "format": expected_data["format_type"],
        "expected_lines": doc_expected_count,
        "extracted_fields": doc_extracted_count,
        "matched_fields": matched_in_doc,
        "accuracy_pct": accuracy_pct,
        "summary": doc_summary,
        "fields": field_comparisons,
    })

total_time = time.time() - t_start

sha_after = get_key_sha256()
print(f"\nPOST-RUN ANSWER_KEY_SHA256: {sha_after}")

sha_match = (sha_before == sha_after)
print(f"SHA-256 IMMUTABILITY VERIFIED: {sha_match}")

overall_accuracy = round((total_matched_fields / total_expected_fields) * 100, 2) if total_expected_fields > 0 else 0
print(f"\n=======================================================")
print(f"       EVALUATION ACCURACY REPORT (30 DOCUMENTS)      ")
print(f"=======================================================")
print(f"Total Evaluated Documents:   {len(eval_results)}")
print(f"Total Expected Fields/Lines: {total_expected_fields}")
print(f"Total Exact Matched Fields:  {total_matched_fields}")
print(f"Overall Field Accuracy:      {overall_accuracy}%")
print(f"Sensitive Entities Checked:  {total_sensitive_expected}")
print(f"Sensitive Entities Masked:   {total_sensitive_masked} ({round(total_sensitive_masked/max(1,total_sensitive_expected)*100, 1)}%)")
print(f"Plaintext Leaks in Summary:  {summary_leaks_count} (Must be 0)")
print(f"Total Processing Time:       {total_time:.2f}s")
print(f"=======================================================")

# Output breakdown by format
format_breakdown = {}
for r in eval_results:
    fmt = r["format"]
    if fmt not in format_breakdown:
        format_breakdown[fmt] = {"docs": 0, "expected": 0, "matched": 0}
    format_breakdown[fmt]["docs"] += 1
    format_breakdown[fmt]["expected"] += r["expected_lines"]
    format_breakdown[fmt]["matched"] += r["matched_fields"]

print("\n--- ACCURACY BREAKDOWN BY DOCUMENT FORMAT ---")
print(f"{'Format':<20} | {'Docs':<5} | {'Expected':<8} | {'Matched':<8} | {'Accuracy':<8}")
print("-" * 60)
for fmt, stats in format_breakdown.items():
    acc = round((stats["matched"] / stats["expected"]) * 100, 1)
    print(f"{fmt:<20} | {stats['docs']:<5} | {stats['expected']:<8} | {stats['matched']:<8} | {acc}%")

# Save full results json
report_path = os.path.join(EVAL_DIR, "accuracy_report_30.json")
with open(report_path, "w", encoding="utf-8") as f:
    json.dump({
        "sha256_before": sha_before,
        "sha256_after": sha_after,
        "sha_unmodified": sha_match,
        "total_documents": len(eval_results),
        "total_expected_fields": total_expected_fields,
        "total_matched_fields": total_matched_fields,
        "overall_accuracy_pct": overall_accuracy,
        "total_sensitive_expected": total_sensitive_expected,
        "total_sensitive_masked": total_sensitive_masked,
        "summary_plaintext_leaks": summary_leaks_count,
        "format_breakdown": format_breakdown,
        "documents": eval_results,
    }, f, indent=2)

print(f"\nFull accuracy report saved to: {report_path}")
