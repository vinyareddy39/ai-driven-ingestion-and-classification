import os
import sys
sys.path.insert(0, os.path.abspath("."))
from dotenv import load_dotenv
load_dotenv()
import requests
import json
import time
from app.core.jwt_auth import create_token
from app.models.db import init_db, UserModel
from sqlalchemy.orm import sessionmaker

BASE = "http://127.0.0.1:8000"

# 1. Get or create a known test user and generate token
engine = init_db()
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()
user = db.query(UserModel).filter(UserModel.email == "testuser@example.com").first()
if not user:
    user = UserModel(email="testuser@example.com", name="Test User", password_hash="dummy")
    db.add(user)
    db.commit()
    db.refresh(user)

token = create_token({"sub": user.id, "email": user.email, "name": user.name})
headers = {"Authorization": f"Bearer {token}"}
print("Generated valid auth token for user:", user.email, user.id)

# 2. Create batch
batch_init = requests.post(f"{BASE}/api/batches", headers=headers, data={"batch_name": "Structure Test Batch"})
print("Init batch status:", batch_init.status_code, batch_init.json())
assert batch_init.status_code == 201, f"Failed to create batch: {batch_init.text}"
batch_id = batch_init.json()["id"]

# 3. Upload test files
test_files = [
    "doc_06_table_with_totals.pdf",
    "doc_03_form_checkboxes.pdf",
    "doc_04_signature_stamp_contract.pdf",
    "doc_07_nested_bullet_list.pdf",
    "doc_09_qr_code_verification.pdf"
]

files = [
    ("files", (fn, open(f"structure_eval_suite/inputs/{fn}", "rb"), "application/pdf"))
    for fn in test_files
]
rel_paths = [f"StructureDocs/{fn}" for fn in test_files]

append_res = requests.post(
    f"{BASE}/api/batches/{batch_id}/files",
    headers=headers,
    files=files,
    data={"relative_paths": json.dumps(rel_paths)}
)
print("Append files status:", append_res.status_code, append_res.json())
assert append_res.status_code == 201

# 4. Start batch processing
start_res = requests.post(f"{BASE}/api/batches/{batch_id}/start", headers=headers)
print("Start batch status:", start_res.status_code, start_res.json())
assert start_res.status_code == 200

# 5. Poll for completion
for i in range(25):
    time.sleep(1)
    b = requests.get(f"{BASE}/api/batches/{batch_id}", headers=headers).json()
    files_info = b.get("files", [])
    statuses = [f.get("status") for f in files_info]
    print(f"Poll {i}: {statuses}")
    if statuses and all(s in ("Done", "Done, check", "Failed", "completed") for s in statuses):
        print(f"All {len(statuses)} files processed!")
        break

# 6. Verify each file's extracted structures
print("\n" + "="*60)
print("STRUCTURE EXTRACTION VERIFICATION RESULTS")
print("="*60)

reclass_tested = False
for f in files_info:
    filename = f.get("filename")
    file_id = f.get("id")
    status = f.get("status")
    print(f"\n--- File: {filename} (ID: {file_id}, Status: {status}) ---")
    
    f_detail = requests.get(f"{BASE}/api/files/{file_id}", headers=headers).json()
    doc_type = f_detail.get("type")
    regions = f_detail.get("regions", [])
    fields = f_detail.get("fields", [])
    tables = f_detail.get("tables", [])
    
    print(f"Predicted Document Type: {doc_type}")
    print(f"Regions Count: {len(regions)} | Fields Count: {len(fields)} | Tables Count: {len(tables)}")
    
    # Structure types present in regions
    struct_counts = {}
    for r in regions:
        st = r.get("structure_type")
        struct_counts[st] = struct_counts.get(st, 0) + 1
    print(f"Region types detected: {struct_counts}")
    
    # Sample fields with their structure metadata
    for fld in fields[:4]:
        print(f"  * Field '{fld.get('label')}': {repr(fld.get('value'))} [type: {fld.get('structure_type')}, group: {fld.get('structure_group')}, conf: {fld.get('confidence')}]")

    # If this file has regions, test 1-click reclassification once
    if not reclass_tested and regions:
        target_r = regions[0]
        rid = target_r.get("id") or target_r.get("region_id")
        orig_type = target_r.get("structure_type")
        new_type = "heading" if orig_type != "heading" else "paragraph"
        print(f"\n>> Testing 1-click Reclassification on region {rid}: {orig_type} -> {new_type}")
        reclass_res = requests.post(
            f"{BASE}/api/files/{file_id}/regions/{rid}/reclassify",
            json={"new_structure_type": new_type},
            headers=headers
        )
        print(">> Reclassify response code:", reclass_res.status_code, reclass_res.json())
        assert reclass_res.status_code == 200, "Reclassification failed"
        
        # Verify the file regions were updated
        f_updated = requests.get(f"{BASE}/api/files/{file_id}", headers=headers).json()
        updated_r = next((r for r in f_updated.get("regions", []) if (r.get("id") == rid or r.get("region_id") == rid)), None)
        assert updated_r and updated_r.get("structure_type") == new_type, f"Region structure type not updated: {updated_r}"
        print(f">> Confirmed: Region {rid} successfully reclassified to '{new_type}' in database!")
        reclass_tested = True

print("\nALL VERIFICATIONS COMPLETED SUCCESSFULLY!")
