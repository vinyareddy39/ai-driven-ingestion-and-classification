import os
import json
import time
import requests
from pathlib import Path
from collections import defaultdict, Counter

TUNNEL_URL = "https://pirates-minimize-participant-hub.trycloudflare.com"
TOKEN = "3WNO2zIz4d8j1xoqM9PNiQXf1p-GKV6gxPI8Mi5L0wE"
BATCH_ID = f"batch-80-eval-{int(time.time())}"

headers = {
    "Authorization": f"Bearer {TOKEN}",
}

dataset_dir = Path("data/dataset/val_v3")
classes = [
    "invoice",
    "receipt" if (dataset_dir / "v3_receipt_0001.pdf").exists() else "purchase_order",
    "bank_statement",
    "medical_report",
    "kyc_form",
    "contract",
    "claim_form",
    "letter",
]

# Collect 10 files per class
selected_files = []
ground_truth = {}

for cls in classes:
    files = sorted(list(dataset_dir.glob(f"v3_{cls}_*.pdf")))[:10]
    for f in files:
        selected_files.append(f)
        ground_truth[f.name] = cls

print(f"Selected {len(selected_files)} files across {len(classes)} classes.")

# Upload all 80 files in one batch
print(f"\nUploading 80 files as one batch ({BATCH_ID}) to live server...")
upload_success = 0
for i, fpath in enumerate(selected_files):
    with open(fpath, "rb") as fp:
        resp = requests.post(
            f"{TUNNEL_URL}/ingest?batch_id={BATCH_ID}",
            headers=headers,
            files={"file": (fpath.name, fp, "application/pdf")}
        )
        if resp.status_code == 202:
            upload_success += 1
    if (i + 1) % 20 == 0:
        print(f"  Uploaded {i + 1}/80 files...")

print(f"Successfully uploaded {upload_success}/80 files.")

# Poll until batch processing completes
print("\nWaiting for batch processing to complete...")
start_time = time.time()
final_status = None

while time.time() - start_time < 90:
    res = requests.get(f"{TUNNEL_URL}/api/v1/batches/{BATCH_ID}", headers=headers)
    if res.status_code == 200:
        data = res.json()
        prog = data["progress"]
        queued = prog.get("queued", 0)
        processing = prog.get("processing", 0)
        total = prog.get("total", 0)
        done = prog.get("done", 0)
        needs_review = prog.get("needs_review", 0)
        quarantined = prog.get("quarantined", 0)

        print(f"  [Status] Total: {total} | Done: {done} | Review: {needs_review} | Queued: {queued} | Processing: {processing}")
        if queued == 0 and processing == 0 and (done + needs_review + quarantined) >= total:
            final_status = data
            break
    time.sleep(2)

if not final_status:
    print("Timed out waiting for batch, fetching current state...")
    final_status = requests.get(f"{TUNNEL_URL}/api/v1/batches/{BATCH_ID}", headers=headers).json()

# Compute matches against ground_truth
items = final_status.get("items", [])
type_matches = Counter()
type_totals = Counter()
review_routed = 0

for item in items:
    fname = item["file_name"]
    pred_type = item["doc_type"]
    gt_type = ground_truth.get(fname, "unknown")
    type_totals[gt_type] += 1
    if pred_type == gt_type:
        type_matches[gt_type] += 1
    if item["review_status"] == "pending_review":
        review_routed += 1

print("\n" + "=" * 60)
print("LOCAL MODE - BATCH INGESTION 80-FILE EVALUATION REPORT")
print("=" * 60)
print(f"Batch ID: {BATCH_ID}")
print(f"Total Processed: {len(items)}")
print(f"Progress Breakdown: {json.dumps(final_status.get('progress', {}), indent=2)}")
print(f"Counts By Type: {json.dumps(final_status.get('counts_by_type', {}), indent=2)}")
print("\nGround Truth Match Breakdown (Files per type matching ground_truth):")
for gt_cls in sorted(type_totals.keys()):
    matched = type_matches[gt_cls]
    tot = type_totals[gt_cls]
    acc = (matched / tot) * 100 if tot > 0 else 0
    print(f"  {gt_cls:<18}: {matched}/{tot} matched ({acc:.1f}%)")

print(f"\nTotal Files Routed to Review: {review_routed}")
print(f"Total Files Auto-Accepted: {final_status.get('progress', {}).get('done', 0)}")
print("=" * 60)
