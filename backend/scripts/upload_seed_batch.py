import os
import sys
import time
import requests

BASE_URL = "http://127.0.0.1:8000"
EVAL_DIR = os.path.join(os.path.dirname(__file__), "..", "tests-data", "seeded_eval_30")

s = requests.Session()
login_res = s.post(
    f"{BASE_URL}/api/login",
    json={"email": "reviewer@ecm.local", "password": "Password123!"},
    timeout=10
)
if login_res.status_code != 200:
    print(f"Login failed: {login_res.status_code} {login_res.text}")
    sys.exit(1)

token = login_res.json()["token"]
headers = {"Authorization": f"Bearer {token}"}
print("Logged in successfully, token received.")

# Upload eval_01_form.pdf
filename = "eval_01_form.pdf"
fpath = os.path.join(EVAL_DIR, filename)
with open(fpath, "rb") as fp:
    res = s.post(
        f"{BASE_URL}/api/batches",
        files=[("files", (filename, fp, "application/pdf"))],
        headers=headers,
        timeout=60
    )
    print("Batch created:", res.status_code, res.json())
    batch_id = res.json()["id"]

# Poll for completion
for _ in range(30):
    time.sleep(1)
    b_res = s.get(f"{BASE_URL}/api/batches/{batch_id}", headers=headers)
    data = b_res.json()
    files = data.get("files", [])
    if files and files[0].get("stage") == "Done":
        print("Processing complete! File is Done.")
        print("Fields extracted:", len(files[0].get("fields", [])))
        break
    print(f"Waiting... stage: {files[0].get('stage') if files else 'unknown'}")
