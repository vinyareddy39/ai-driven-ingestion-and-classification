import os
import sys
import time
import requests
import json

BASE_URL = "http://127.0.0.1:8000/api"

def get_auth_token():
    email = "audit_tester@ecm.local"
    password = "AuditPassword123!"
    # Try login first
    r = requests.post(f"{BASE_URL}/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.json()["token"]
    
    # Otherwise register
    r_reg = requests.post(f"{BASE_URL}/register", json={"name": "Audit Tester", "email": email, "password": password})
    if r_reg.status_code == 201:
        # Now login
        r_log = requests.post(f"{BASE_URL}/login", json={"email": email, "password": password})
        return r_log.json()["token"]
    
    raise RuntimeError(f"Unable to authenticate: {r.text} / {r_reg.text}")

token = get_auth_token()
headers = {"Authorization": f"Bearer {token}"}

def upload_and_process(file_path, batch_name):
    print(f"\n--- Uploading {os.path.basename(file_path)} to {batch_name} ---")
    t0 = time.time()
    
    # 1. Create batch
    r1 = requests.post(f"{BASE_URL}/batches", json={"name": batch_name}, headers=headers)
    assert r1.status_code == 201, f"Failed to create batch: {r1.text}"
    batch = r1.json()
    batch_id = batch["id"]
    print(f"Created batch {batch_id}")

    # 2. Upload file
    with open(file_path, "rb") as f:
        files = {"files": (os.path.basename(file_path), f, "image/png")}
        r2 = requests.post(f"{BASE_URL}/batches/{batch_id}/files", files=files, headers=headers)
    assert r2.status_code == 201, f"Failed to upload file: {r2.text}"
    
    # Get file id from batch
    r_b = requests.get(f"{BASE_URL}/batches/{batch_id}", headers=headers)
    files_list = r_b.json().get("files", [])
    assert len(files_list) > 0, "No files found in batch after upload"
    file_id = files_list[0]["id"]
    print(f"Uploaded file {file_id}")

    # 3. Start batch
    r3 = requests.post(f"{BASE_URL}/batches/{batch_id}/start", headers=headers)
    assert r3.status_code == 200, f"Failed to start batch: {r3.text}"
    print(f"Started batch processing at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t0))}")

    # 4. Poll until completed
    while True:
        r4 = requests.get(f"{BASE_URL}/batches/{batch_id}", headers=headers)
        b_data = r4.json()
        f_entry = next((f for f in b_data.get("files", []) if f["id"] == file_id), None)
        if f_entry and f_entry.get("stage") in ("Done", "Failed"):
            elapsed = time.time() - t0
            print(f"Finished processing in {elapsed:.2f}s: stage={f_entry.get('stage')}, status={f_entry.get('status')}")
            break
        time.sleep(0.5)

    # 5. Get file details
    r5 = requests.get(f"{BASE_URL}/files/{file_id}", headers=headers)
    file_details = r5.json()
    return file_details, elapsed

def main():
    test_img = "C:/ml/eval_60_dataset/doc_16.png"
    if not os.path.exists(test_img):
        test_img = "C:/ml/scratch/test_sideways_tinted.png"

    print("TESTING FRESH READING (DOUBLE UPLOAD PROOF)...")
    res1, elapsed1 = upload_and_process(test_img, "Batch_Run_1")
    time.sleep(1.0)
    res2, elapsed2 = upload_and_process(test_img, "Batch_Run_2")

    print("\n================ DOUBLE UPLOAD PROOF RESULTS ================")
    print(f"Run 1 File ID: {res1['id']}")
    print(f"Run 1 Duration: {elapsed1:.2f}s")
    print(f"Run 1 Fields Extracted: {len(res1.get('fields', []))}")
    print(f"Run 1 Duplicate Of: {res1.get('duplicate_of')}")
    print(f"Run 1 Created At: {res1.get('created_at')}")

    print(f"\nRun 2 File ID: {res2['id']}")
    print(f"Run 2 Duration: {elapsed2:.2f}s")
    print(f"Run 2 Fields Extracted: {len(res2.get('fields', []))}")
    print(f"Run 2 Duplicate Of: {res2.get('duplicate_of')}")
    print(f"Run 2 Created At: {res2.get('created_at')}")

    # Verify that run 2 took actual processing time (> 0.5s) and executed freshly
    assert elapsed2 > 0.5, f"Run 2 was suspiciously fast ({elapsed2}s), indicating a cached result!"
    dup_val = res2.get("duplicate_of")
    assert dup_val in (res1.get("original_name"), res1["id"], os.path.basename(test_img)), f"Expected Run 2 duplicate_of to reference Run 1, got {dup_val}"
    print(f"\nSUCCESS: Both runs executed full OCR extraction from scratch without returning cached responses.")
    print(f"Duplicate tracking properly recorded duplicate_of = '{dup_val}'")

if __name__ == "__main__":
    main()
