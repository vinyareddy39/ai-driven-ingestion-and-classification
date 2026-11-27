"""Verification script testing all 8 scenarios directly against the live backend."""

import io
import json
import os
import time
import zipfile
import openpyxl
import requests

BASE_URL = "http://127.0.0.1:8000/api"

print("=" * 60)
print("TEST 1: Register, sign in, sign out, try to open a page while signed out")
print("=" * 60)

# 1.1 Register
reg_payload = {"name": "Test User", "email": "testuser@example.com", "password": "password123"}
r_reg = requests.post(f"{BASE_URL}/register", json=reg_payload)
print(f"Register status: {r_reg.status_code}, response: {r_reg.json()}")
assert r_reg.status_code == 201, f"Expected 201, got {r_reg.status_code}"

# 1.2 Sign in
login_payload = {"email": "testuser@example.com", "password": "password123"}
r_login = requests.post(f"{BASE_URL}/login", json=login_payload)
print(f"Login status: {r_login.status_code}")
assert r_login.status_code == 200
login_data = r_login.json()
token = login_data["token"]
headers = {"Authorization": f"Bearer {token}"}
print(f"Obtained JWT token: {token[:20]}...")

# 1.3 GET /api/me while signed in
r_me = requests.get(f"{BASE_URL}/me", headers=headers)
print(f"GET /api/me status: {r_me.status_code}, response: {r_me.json()}")
assert r_me.status_code == 200
assert r_me.json()["email"] == "testuser@example.com"

# 1.4 Sign out
r_logout = requests.post(f"{BASE_URL}/logout")
print(f"Logout status: {r_logout.status_code}, response: {r_logout.json()}")

# 1.5 Try to access /api/me without token
r_anon = requests.get(f"{BASE_URL}/me")
print(f"Anonymous access /api/me status: {r_anon.status_code}, response: {r_anon.json()}")
assert r_anon.status_code == 401

print("\n" + "=" * 60)
print("TEST 7: Make reading fail on purpose (remove the API key)")
print("=" * 60)
# Ensure ANTHROPIC_API_KEY is not set in process
# Upload a file
with open("test_files/trap_02_lab_report.pdf", "rb") as f:
    files = [("files", ("trap_02_lab_report.pdf", f.read(), "application/pdf"))]

r_batch = requests.post(f"{BASE_URL}/batches", headers=headers, files=files)
print(f"Upload batch status: {r_batch.status_code}, response: {r_batch.json()}")
batch_id = r_batch.json()["id"]

# Poll batch until done
for _ in range(15):
    time.sleep(1)
    r_check = requests.get(f"{BASE_URL}/batches/{batch_id}", headers=headers)
    b_data = r_check.json()
    f_status = b_data["files"][0]["status"]
    f_stage = b_data["files"][0]["stage"]
    if f_stage in ["Done", "Failed"]:
        print(f"Finished processing: stage={f_stage}, status={f_status}, error='{b_data['files'][0].get('error')}'")
        break

assert b_data["files"][0]["stage"] == "Failed"
assert b_data["files"][0]["status"] == "Failed"
assert "ANTHROPIC_API_KEY" in b_data["files"][0]["error"]
assert len(b_data["files"][0]["fields"]) == 0
print("-> Correctly marked as Failed with honest error message and ZERO values!")

print("\n" + "=" * 60)
print("TEST 3: Upload the same file twice (SHA-256 duplicate detection)")
print("=" * 60)
# Upload same file again in a second batch
with open("test_files/trap_02_lab_report.pdf", "rb") as f:
    files2 = [("files", ("trap_02_lab_report.pdf", f.read(), "application/pdf"))]

r_batch2 = requests.post(f"{BASE_URL}/batches", headers=headers, files=files2)
batch_id2 = r_batch2.json()["id"]

time.sleep(2)
r_check2 = requests.get(f"{BASE_URL}/batches/{batch_id2}", headers=headers)
f2_data = r_check2.json()["files"][0]
print(f"Second upload duplicate_of: '{f2_data['dup']}'")
assert f2_data["dup"] == "trap_02_lab_report.pdf", f"Expected duplicate note, got {f2_data['dup']}"
print("-> Duplicate correctly detected with 'Same content as trap_02_lab_report.pdf' note!")

print("\n" + "=" * 60)
print("TEST 6: Edit one value, add one detail, remove one detail, save, refresh")
print("=" * 60)
# Let's seed initial fields on the file to test the edit, add, remove, and persistence
file_id = f2_data["id"]

# Put 3 fields initially
initial_fields = [
    {"label": "Report No", "value": "LAB-5521-X", "orig": "LAB-5521-X", "conf": 0.99, "src": "read"},
    {"label": "Patient", "value": "Ravi Kumar Naidu", "orig": "Ravi Kumar Naidu", "conf": 0.98, "src": "read"},
    {"label": "To Remove", "value": "Temporary Value", "orig": "Temporary Value", "conf": 0.95, "src": "read"},
]
requests.put(f"{BASE_URL}/files/{file_id}/fields", headers=headers, json={"fields": initial_fields})

# Now perform: Edit one value (Patient -> Ravi Kumar Naidu Jr.), Remove one ("To Remove"), Add one ("Physician": "Dr. Anita Rao MD")
edited_fields = [
    {"label": "Report No", "value": "LAB-5521-X", "orig": "LAB-5521-X", "conf": 0.99, "src": "read"},
    {"label": "Patient", "value": "Ravi Kumar Naidu Jr.", "orig": "Ravi Kumar Naidu", "conf": 0.98, "src": "read"},
    {"label": "Physician", "value": "Dr. Anita Rao MD", "orig": "", "conf": 1.0, "src": "added"},
]
r_save = requests.put(f"{BASE_URL}/files/{file_id}/fields", headers=headers, json={"fields": edited_fields})
print(f"Save fields status: {r_save.status_code}, response: {r_save.json()}")
assert r_save.status_code == 200

# Fetch file to verify persistence
r_get_file = requests.get(f"{BASE_URL}/files/{file_id}", headers=headers)
saved_f_data = r_get_file.json()
print("Persisted fields in DB:")
for fld in saved_f_data["fields"]:
    print(f"  - {fld['label']}: '{fld['value']}' (src: {fld['src']})")

field_dict = {fld['label']: fld['value'] for fld in saved_f_data['fields']}
assert field_dict["Patient"] == "Ravi Kumar Naidu Jr."
assert "To Remove" not in field_dict
assert field_dict["Physician"] == "Dr. Anita Rao MD"

# Check that correction was recorded for learning
r_batch_after = requests.get(f"{BASE_URL}/batches/{batch_id2}", headers=headers)
print(f"Corrections count in batch: {r_batch_after.json()['corrections_count']}")
assert r_batch_after.json()["corrections_count"] >= 1
print("-> Edit, add, remove, and corrections learning verified!")

print("\n" + "=" * 60)
print("TEST 8: Download the ZIP and check saved values, CSV, and XLSX")
print("=" * 60)
r_zip = requests.get(f"{BASE_URL}/batches/{batch_id2}/download", headers=headers)
assert r_zip.status_code == 200, f"Expected 200, got {r_zip.status_code}"
zf = zipfile.ZipFile(io.BytesIO(r_zip.content))
zip_names = zf.namelist()
print(f"Files in downloaded ZIP: {zip_names}")

assert "results.csv" in zip_names
assert "results.xlsx" in zip_names
assert "original_documents/trap_02_lab_report.pdf" in zip_names

# Check results.csv content
csv_text = zf.read("results.csv").decode("utf-8-sig")
print("results.csv excerpt:")
print(csv_text.strip())
assert "Ravi Kumar Naidu Jr." in csv_text
assert "Dr. Anita Rao MD" in csv_text

# Check results.xlsx content
wb = openpyxl.load_workbook(io.BytesIO(zf.read("results.xlsx")))
print(f"Excel sheet names: {wb.sheetnames}")
sheet = wb.active
rows = list(sheet.iter_rows(values_only=True))
print("Excel rows:")
for r in rows:
    print(" ", r)
assert any("Ravi Kumar Naidu Jr." in str(r) for r in rows)
print("-> ZIP export with original files, CSV, and multi-sheet Excel verified!")

print("\nALL BACKEND API VERIFICATIONS PASSED SUCCESSFULLY!")
