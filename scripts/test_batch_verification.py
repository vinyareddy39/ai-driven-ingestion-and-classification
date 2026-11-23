import requests
import json
import time

TUNNEL_URL = "https://dicke-visitor-cluster-calculated.trycloudflare.com"
TOKEN = "3WNO2zIz4d8j1xoqM9PNiQXf1p-GKV6gxPI8Mi5L0wE"
BATCH_ID = f"batch-test-{int(time.time())}"

headers = {
    "Authorization": f"Bearer {TOKEN}",
}

print(f"=== Testing batch upload for {BATCH_ID} ===")

# Create 3 valid synthetic files (invoice, receipt, contract text in valid PDFs)
import fitz # PyMuPDF

def make_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text, fontsize=12)
    b = doc.tobytes()
    doc.close()
    return b

pdf1 = make_pdf("TAX INVOICE\nInvoice Number: INV-2026-9901\nTotal Amount: $1,450.00\nDate: 2026-11-19\nVendor: Global Tech Supplies")
pdf2 = make_pdf("RECEIPT OF PAYMENT\nReceipt Number: REC-8821\nAmount Paid: $42.50\nMerchant: Starbucks Coffee\nDate: 2026-11-19")
pdf3 = make_pdf("MUTUAL NON-DISCLOSURE AGREEMENT\nThis Contract is entered into by and between Party A and Party B on 2026-11-19.")

files = [
    ("invoice_9901.pdf", pdf1),
    ("receipt_8821.pdf", pdf2),
    ("nda_contract.pdf", pdf3),
]

for fname, data in files:
    resp = requests.post(
        f"{TUNNEL_URL}/ingest?batch_id={BATCH_ID}",
        headers=headers,
        files={"file": (fname, data, "application/pdf")}
    )
    print(f"Ingest {fname} -> HTTP {resp.status_code}: {resp.json().get('status')} (uid={resp.json().get('uid')})")

print("\n--- Immediate GET /api/v1/batches/{batch_id} ---")
r0 = requests.get(f"{TUNNEL_URL}/api/v1/batches/{BATCH_ID}", headers=headers)
print(f"HTTP {r0.status_code}")
print(json.dumps(r0.json(), indent=2))

print("\nWaiting 4 seconds for processing...")
time.sleep(4)

print("\n--- After Processing GET /api/v1/batches/{batch_id} ---")
r1 = requests.get(f"{TUNNEL_URL}/api/v1/batches/{BATCH_ID}", headers=headers)
print(f"HTTP {r1.status_code}")
print(json.dumps(r1.json(), indent=2))
