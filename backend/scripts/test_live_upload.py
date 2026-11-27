import requests
import json
import uuid

BASE = "http://127.0.0.1:8000"

# 1. Register a unique test user
unique_id = str(uuid.uuid4())[:8]
email = f"test_{unique_id}@example.com"
password = "password123"

reg_res = requests.post(f"{BASE}/api/register", json={"name": f"Tester {unique_id}", "email": email, "password": password})
print("Register status:", reg_res.status_code, reg_res.json())

# 2. Login
login_res = requests.post(f"{BASE}/api/login", json={"email": email, "password": password})
print("Login status:", login_res.status_code)
token = login_res.json().get("token")
headers = {"Authorization": f"Bearer {token}"}
print("Authenticated successfully:", bool(token))

# 3. Create batch (init)
batch_init = requests.post(f"{BASE}/api/batches", headers=headers, data={"batch_name": "Live Upload Test Batch"})
print("Init batch status:", batch_init.status_code, batch_init.json())
batch_id = batch_init.json()["id"]

# 4. Append files to batch
files = [
    ("files", ("b_01.pdf", b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 300 300]/Parent 2 0 R>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000056 00000 n\n0000000111 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n180\n%%EOF", "application/pdf")),
    ("files", ("b_02.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82", "image/png")),
]
rel_paths = ["Invoices/b_01.pdf", "Receipts/b_02.png"]
append_res = requests.post(
    f"{BASE}/api/batches/{batch_id}/files",
    headers=headers,
    files=files,
    data={"relative_paths": json.dumps(rel_paths)}
)
print("Append files status:", append_res.status_code, append_res.json())
assert append_res.status_code == 201, f"Expected 201, got {append_res.status_code}"

# 5. Start batch processing
start_res = requests.post(f"{BASE}/api/batches/{batch_id}/start", headers=headers)
print("Start batch status:", start_res.status_code, start_res.json())
assert start_res.status_code == 200

# 6. Fetch batch details
batch_get = requests.get(f"{BASE}/api/batches/{batch_id}", headers=headers)
print("Get batch status:", batch_get.status_code)
files_in_batch = batch_get.json()["files"]
print(f"Files saved successfully ({len(files_in_batch)}):", [f["name"] for f in files_in_batch])
print("SUCCESS: Full upload flow completed without any 500 error!")
