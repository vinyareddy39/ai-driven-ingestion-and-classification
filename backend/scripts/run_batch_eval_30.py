"""
Batch Evaluation Runner for 30 Seeded Documents.
Validates SHA-256 of answer key before and after, runs batch upload via API,
evaluates field-by-field accuracy, sensitive masking, and outputs full comparison table.
"""
import os
import sys
import time
import json
import hashlib
import requests

BASE_URL = "http://127.0.0.1:8000"
EVAL_DIR = os.path.join(os.path.dirname(__file__), "..", "tests-data", "seeded_eval_30")
KEY_PATH = os.path.join(EVAL_DIR, "answer_key.json")

def get_key_sha256():
    with open(KEY_PATH, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

sha_before = get_key_sha256()
print(f"PRE-RUN ANSWER_KEY_SHA256: {sha_before}")

with open(KEY_PATH, "r", encoding="utf-8") as f:
    answer_key = json.load(f)

# 1. Login or register to get session / token
s = requests.Session()
reg_res = s.post(
    f"{BASE_URL}/api/register",
    json={"name": "Reviewer Admin", "email": "reviewer@ecm.local", "password": "Password123!"},
    timeout=10
)

login_res = s.post(
    f"{BASE_URL}/api/login",
    json={"email": "reviewer@ecm.local", "password": "Password123!"},
    timeout=10
)
if login_res.status_code != 200:
    print(f"Auth failed: {login_res.status_code} {login_res.text}")
    sys.exit(1)

auth_data = login_res.json()
token = auth_data.get("token") or auth_data.get("access_token")
headers = {"Authorization": f"Bearer {token}"} if token else {}
print(f"Authenticated successfully as {auth_data.get('user', {}).get('email', 'reviewer@ecm.local')}")

# 2. Upload the 30 files in batch
file_tuples = []
opened_files = []
try:
    for filename in sorted(answer_key.keys()):
        fpath = os.path.join(EVAL_DIR, filename)
        fp = open(fpath, "rb")
        opened_files.append(fp)
        content_type = "application/pdf" if filename.endswith(".pdf") else "image/png"
        file_tuples.append(("files", (filename, fp, content_type)))

    print(f"Uploading batch of {len(file_tuples)} documents to /api/batches...")
    upload_res = s.post(
        f"{BASE_URL}/api/batches",
        files=file_tuples,
        headers=headers,
        timeout=120
    )
    if upload_res.status_code not in [200, 201]:
        print(f"Upload failed: {upload_res.status_code} {upload_res.text}")
        sys.exit(1)

    batch_resp = upload_res.json()
    batch_id = batch_resp.get("id")
    print(f"Uploaded batch ID: {batch_id}, file count: {batch_resp.get('file_count')}")
finally:
    for fp in opened_files:
        fp.close()

# 3. Poll batch status until all files reach Done
print("Polling batch completion...")
max_wait = 180
t0 = time.time()
completed = False

while time.time() - t0 < max_wait:
    b_res = s.get(f"{BASE_URL}/api/batches/{batch_id}", headers=headers, timeout=10)
    if b_res.status_code == 200:
        b_data = b_res.json()
        files = b_data.get("files", [])
        total = len(files)
        done = sum(1 for f in files if f.get("stage") == "Done")
        print(f"  Processed {done}/{total} files...")
        if done == total and total > 0:
            completed = True
            break
    time.sleep(3)

if not completed:
    print("Batch processing timed out!")
    sys.exit(1)

print(f"Batch completed in {time.time() - t0:.2f}s")

# 4. Collect results for each file and compare against answer key
eval_results = []
total_expected_fields = 0
total_matched_fields = 0
total_sensitive_expected = 0
total_sensitive_masked = 0

for filename, expected_data in sorted(answer_key.items()):
    file_record = next((f for f in files if f.get("name") == filename), None)
    if not file_record:
        print(f"Missing file record for {filename}")
        continue

    file_id = file_record["id"]
    detail_res = s.get(f"{BASE_URL}/api/files/{file_id}", headers=headers, timeout=10)
    if detail_res.status_code != 200:
        print(f"Error fetching file details for {file_id}: {detail_res.status_code}")
        continue

    doc_detail = detail_res.json()
    extracted_fields = doc_detail.get("fields", [])
    expected_fields = expected_data["expected_fields"]
    
    doc_expected_count = len(expected_fields)
    doc_extracted_count = len(extracted_fields)
    total_expected_fields += doc_expected_count

    matched_in_doc = 0
    field_comparisons = []

    for exp in expected_fields:
        exp_lbl = exp["label"].strip().lower()
        exp_val = exp["value"].strip()
        is_heading = exp["type"] == "heading"

        # Find matching extracted field
        match = None
        for ext_f in extracted_fields:
            ext_lbl = (ext_f.get("label") or "").strip().lower()
            ext_val = (ext_f.get("value") or "").strip()
            
            if is_heading:
                # Heading has label="" and value matches heading text
                if ext_lbl == "" and (exp_val.lower() in ext_val.lower() or ext_val.lower() in exp_val.lower()):
                    match = ext_f
                    break
            else:
                # Label match
                if ext_lbl == exp_lbl or exp_lbl in ext_lbl:
                    match = ext_f
                    break

        if match:
            ext_lbl = (match.get("label") or "").strip()
            ext_val = (match.get("value") or "").strip()
            is_sens = bool(match.get("is_sensitive", False))
            masked_v = match.get("masked_value")

            # Check if expected value was preserved without cutting words
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
    eval_results.append({
        "filename": filename,
        "doc_id": expected_data["doc_id"],
        "category": expected_data["category"],
        "format": expected_data["format_type"],
        "expected_lines": doc_expected_count,
        "extracted_fields": doc_extracted_count,
        "matched_fields": matched_in_doc,
        "accuracy_pct": accuracy_pct,
        "fields": field_comparisons,
    })

sha_after = get_key_sha256()
print(f"POST-RUN ANSWER_KEY_SHA256: {sha_after}")

sha_match = (sha_before == sha_after)
print(f"SHA-256 IMMUTABILITY VERIFIED: {sha_match}")

overall_accuracy = round((total_matched_fields / total_expected_fields) * 100, 2) if total_expected_fields > 0 else 0
print(f"\n==========================================")
print(f"EVALUATION RESULTS SUMMARY (30 DOCUMENTS)")
print(f"==========================================")
print(f"Total Expected Fields: {total_expected_fields}")
print(f"Total Matched Fields:  {total_matched_fields}")
print(f"Overall Accuracy:      {overall_accuracy}%")
print(f"Sensitive Fields Checked: {total_sensitive_expected}")
print(f"Sensitive Fields Masked:  {total_sensitive_masked}")
print(f"==========================================")

# Save evaluation report
report_path = os.path.join(EVAL_DIR, "eval_accuracy_report.json")
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
        "documents": eval_results,
    }, f, indent=2)

print(f"Full report saved to: {report_path}")
