import requests
import json
import time

TUNNEL_URL = "https://gregory-file-refer-species.trycloudflare.com"
TOKEN = "3WNO2zIz4d8j1xoqM9PNiQXf1p-GKV6gxPI8Mi5L0wE"
BATCH_ID = f"batch-synth-{int(time.time())}"

headers = {
    "Authorization": f"Bearer {TOKEN}",
}

print(f"=== STEP 1.1: Uploading 3 synthetic files in batch {BATCH_ID} via {TUNNEL_URL} ===")
files_data = [
    ("file_1.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"),
    ("file_2.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"),
    ("file_3.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"),
]

upload_responses = []
for fname, content in files_data:
    resp = requests.post(
        f"{TUNNEL_URL}/ingest?batch_id={BATCH_ID}",
        headers=headers,
        files={"file": (fname, content, "image/png")}
    )
    print(f"POST /ingest?batch_id={BATCH_ID} -> Status: {resp.status_code}, Body: {resp.text}")
    upload_responses.append(resp)

print("\n=== STEP 1.2: Calling GET /api/v1/batches/{id} immediately after upload ===")
batch_url = f"{TUNNEL_URL}/api/v1/batches/{BATCH_ID}"
batch_resp = requests.get(batch_url, headers=headers)
print(f"Request URL: {batch_url}")
print(f"Request Method: GET")
print(f"Status Code: {batch_resp.status_code}")
print(f"Response Headers: {dict(batch_resp.headers)}")
print(f"Response Body: {batch_resp.text}")

print("\nWaiting 3 seconds for pipeline worker...")
time.sleep(3)
batch_resp2 = requests.get(batch_url, headers=headers)
print(f"After 3s -> Status Code: {batch_resp2.status_code}, Response Body: {batch_resp2.text}")
