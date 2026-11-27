"""End-to-End API Batch Test and ZIP Export Verification."""

import csv
import io
import json
import logging
import os
import sys
sys.path.insert(0, os.path.abspath("."))
import time
import zipfile
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_verify")

API_BASE = "http://127.0.0.1:8000/api"
PROOF_DIR = os.path.abspath("data/proof_test_files")


def run_e2e():
    # 1. Login / Register
    logger.info("Authenticating test user...")
    test_email = f"verifier_{int(time.time())}@enterprise.com"
    test_pw = "Password123!"
    reg_resp = requests.post(
        f"{API_BASE}/register",
        json={"name": "Verifier Admin", "email": test_email, "password": test_pw},
    )
    assert reg_resp.status_code == 201, f"Registration failed: {reg_resp.text}"

    login_resp = requests.post(
        f"{API_BASE}/login",
        json={"email": test_email, "password": test_pw},
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"

    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    logger.info("Authenticated successfully as %s.", test_email)

    # 2. Test Unsupported File Rejection (Part 4, Point 2)
    logger.info("\n--- Testing Unsupported File Upload Rejection ---")
    unsupp_file = os.path.join(PROOF_DIR, "proof_10_unsupported.xyz")
    with open(unsupp_file, "rb") as f:
        res = requests.post(
            f"{API_BASE}/batches",
            headers=headers,
            files=[("files", ("proof_10_unsupported.xyz", f, "application/octet-stream"))],
        )
    logger.info("Upload status for .xyz: %d, Body: %s", res.status_code, res.text)
    assert res.status_code == 400
    assert "This file type isn't supported" in res.json()["detail"]
    logger.info("Unsupported type blocked at upload: PASS")

    # 3. Upload Batch of 20+ Mixed Files
    logger.info("\n--- Uploading 20+ Mixed File Batch ---")
    file_names = [
        "proof_01_notes.txt",
        "proof_02_clean_memo.pdf",
        "proof_03_scanned_receipt.pdf",
        "proof_04_financial_table.pdf",
        "proof_05_multipage_report.pdf",
        "proof_06_blank_page.pdf",
        "proof_07_empty_file.txt",
        "proof_08_damaged_cutoff.pdf",
        "proof_09_password_protected.pdf",
        "proof_11_comprehensive_sensitive.pdf",
        "proof_12_unplanned_astronomy_log.pdf",
    ] + [f"proof_{i}_document.pdf" for i in range(13, 23)]  # Total 21 files!

    files_payload = []
    open_handles = []
    for fn in file_names:
        fp = os.path.join(PROOF_DIR, fn)
        h = open(fp, "rb")
        open_handles.append(h)
        mime = "application/pdf" if fn.endswith(".pdf") else "text/plain"
        files_payload.append(("files", (fn, h, mime)))

    try:
        upload_res = requests.post(f"{API_BASE}/batches", headers=headers, files=files_payload)
        assert upload_res.status_code == 201, f"Batch upload failed: {upload_res.text}"
        batch_id = upload_res.json()["id"]
        logger.info("Batch created with ID: %s (%d files)", batch_id, len(file_names))
    finally:
        for h in open_handles:
            h.close()

    # 4. Poll Progress (Verify Neutral States and Progress Calculation)
    logger.info("\n--- Polling Processing Status ---")
    max_wait = 45
    start = time.time()
    finished = False
    locked_file_id = None
    batch_data = None

    while time.time() - start < max_wait:
        b_res = requests.get(f"{API_BASE}/batches/{batch_id}", headers=headers)
        assert b_res.status_code == 200
        batch_data = b_res.json()
        done_cnt = batch_data["done_count"]
        total_cnt = batch_data["file_count"]
        pct = batch_data["progress_pct"]
        
        # Verify Part 5, Point 3: percentage equals finished / total
        expected_pct = round((done_cnt / total_cnt) * 100) if total_cnt > 0 else 0
        assert pct == expected_pct, f"Progress pct mismatch: got {pct}, expected {expected_pct}"

        # Verify Neutral States: no raw errors, stage is Waiting/Still reading/Done
        for f in batch_data["files"]:
            assert f["stage"] in ["Waiting", "Still reading", "Done", "Failed"]
            assert "Rate limit" not in str(f["stage"])
            assert "HTTP" not in str(f["stage"])
            if f["name"] == "proof_09_password_protected.pdf":
                locked_file_id = f["id"]

        logger.info("Progress: %d/%d (%d%% complete)", done_cnt, total_cnt, pct)
        if done_cnt == total_cnt:
            finished = True
            break
        time.sleep(1.0)

    assert finished, "Batch did not finish processing in time!"
    logger.info("All files finished processing!")

    # Verify Special Error Outcomes
    file_map = {f["name"]: f for f in batch_data["files"]}
    
    empty_f = file_map["proof_07_empty_file.txt"]
    assert empty_f["error"] == "This file is empty.", f"Unexpected error on empty file: {empty_f['error']}"
    logger.info("Empty file verified: '%s'", empty_f["error"])

    damaged_f = file_map["proof_08_damaged_cutoff.pdf"]
    assert damaged_f["error"] == "This file looks damaged. Try uploading it again from the original.", f"Unexpected error on damaged file: {damaged_f['error']}"
    logger.info("Damaged file verified: '%s'", damaged_f["error"])

    locked_f = file_map["proof_09_password_protected.pdf"]
    assert locked_f["error"] == "This file is password protected.", f"Unexpected error on locked file: {locked_f['error']}"
    logger.info("Locked file verified: '%s'", locked_f["error"])

    # 5. Unlock the Password Protected File
    logger.info("\n--- Unlocking Password-Protected File ---")
    unlock_res = requests.post(
        f"{API_BASE}/files/{locked_file_id}/unlock",
        headers=headers,
        json={"password": "SecretPass123"},
    )
    assert unlock_res.status_code == 200, f"Unlock failed: {unlock_res.text}"
    logger.info("Unlock response: %s", unlock_res.json())

    # Check updated file details
    f_check = requests.get(f"{API_BASE}/files/{locked_file_id}", headers=headers).json()
    assert f_check["error"] is None
    assert len(f_check["fields"]) > 0
    logger.info("File successfully unlocked and %d details extracted!", len(f_check["fields"]))

    # 6. Verify ZIP Download and index.csv Structure
    logger.info("\n--- Downloading and Auditing ZIP Export ---")
    dl_res = requests.get(f"{API_BASE}/batches/{batch_id}/download", headers=headers)
    assert dl_res.status_code == 200
    zip_bytes = dl_res.content

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        file_list = zf.namelist()
        logger.info("ZIP contents: %s", [fn for fn in file_list if not fn.startswith("original_documents/")])
        assert "index.csv" in file_list
        assert "results.csv" in file_list
        assert "results.xlsx" in file_list

        index_csv_str = zf.read("index.csv").decode("utf-8-sig")
        reader = list(csv.reader(io.StringIO(index_csv_str)))
        header = reader[0]
        logger.info("index.csv Header columns count: %d", len(header))
        assert "File" in header
        assert "Document Type" in header
        assert "Sensitive Labels" in header
        assert "Status" in header

        # Check sensitive file row
        sens_row = next((r for r in reader[1:] if "proof_11_comprehensive_sensitive.pdf" in r[0]), None)
        assert sens_row is not None
        sens_labels_idx = header.index("Sensitive Labels")
        sens_labels_val = sens_row[sens_labels_idx]
        logger.info("Sensitive Labels listed in export: %s", sens_labels_val)
        assert "Aadhaar" in sens_labels_val or "PAN" in sens_labels_val or "Phone" in sens_labels_val

        # Verify sensitive value is present in full (not masked in export)
        joined_row = " ".join(sens_row)
        assert "3675 9834 6012" in joined_row, "Aadhaar value must be present in full in index.csv export!"
        logger.info("Aadhaar full value verified in index.csv export: PASS")

    logger.info("\nALL END-TO-END API & EXPORT VERIFICATIONS COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    run_e2e()
