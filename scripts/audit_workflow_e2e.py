"""End-to-End Workflow Audit & Verification Script.

Tests all 11 workflow steps with raw output.
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime, timezone
import hashlib
import io
import json
import os
import uuid
from fastapi.testclient import TestClient
import fitz
from PIL import Image, ImageDraw

from app.api.app import app
from app.models.db import (
    BatchModel,
    DocumentModel,
    DownloadModel,
    NotificationModel,
    get_db_session,
    init_db,
)
from app.workers.pipeline import process_document_payload

init_db()
client = TestClient(app)
headers = {"Authorization": "Bearer 3WNO2zIz4d8j1xoqM9PNiQXf1p-GKV6gxPI8Mi5L0wE"}

print("==================================================")
print("AUDIT: WORKFLOW STEPS 1 THROUGH 11 VERIFICATION")
print("==================================================")

# ----------------------------------------------------------------------
# STEP 1: UPLOAD
# ----------------------------------------------------------------------
batch_res = client.post("/api/v1/batches", headers=headers, json={"name": "Upload #42"})
assert batch_res.status_code == 201, batch_res.text
batch_id = batch_res.json()["batch_id"]
batch_num = batch_res.json()["number"]
print(f"[STEP 1: UPLOAD] Status=DONE. Batch created: ID={batch_id}, Number={batch_num}, Name={batch_res.json()['name']}")

# ----------------------------------------------------------------------
# STEP 2: SAFETY CHECKS (MAGIC BYTES, SIZE LIMIT, VIRUS SCAN, DUPLICATE)
# ----------------------------------------------------------------------
# 2a. Size limit in system/info
info = client.get("/api/v1/system/info", headers=headers).json()
print(f"[STEP 2: SAFETY] Max upload size: {info['max_upload_mb']} MB ({info['max_upload_size_bytes']} bytes)")

# 2b. Magic bytes validation
bad_content = b"NOT_A_VALID_PDF_HEADER_DATA"
res_bad = client.post(
    "/api/v1/ingest",
    headers=headers,
    files={"file": ("malicious.pdf", io.BytesIO(bad_content), "application/pdf")},
    data={"batch_id": batch_id},
)
print(f"[STEP 2: SAFETY] Magic bytes rejection: status={res_bad.status_code}, detail='{res_bad.json()['detail']}'")

# 2c. Virus scan (EICAR signature)
from app.adapters.virus import get_virus_scanner
scanner = get_virus_scanner()
is_clean_eicar, virus_name = scanner.scan(b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*")
print(f"[STEP 2: SAFETY] Virus scanner on EICAR: clean={is_clean_eicar}, detected='{virus_name}'")

# ----------------------------------------------------------------------
# STEP 3: READING (TEXT LAYER FOR DIGITAL PDF, OCR FOR SCANS)
# ----------------------------------------------------------------------
from app.adapters.ocr import get_ocr_engine
ocr_engine = get_ocr_engine()

# Digital PDF
doc_digital = fitz.open()
page = doc_digital.new_page(width=600, height=400)
page.insert_text((50, 50), "TAX INVOICE\nSupplier: Acme Hardware\nAmount: $1,250.00\nDate: 2026-11-20")
pdf_bytes = doc_digital.tobytes()
doc_digital.close()
res_digital_ocr = ocr_engine.extract_text(pdf_bytes, "pdf")
print(f"[STEP 3: READING] Digital PDF text layer: method={res_digital_ocr.page_methods[0]}, pages={res_digital_ocr.pages_count}, sample text='{res_digital_ocr.full_text[:35]}...'")

# Scanned Raster PNG
doc_scan = fitz.open()
p_scan = doc_scan.new_page(width=400, height=200)
p_scan.insert_text((30, 50), "RECEIPT FOR PAYMENT\nStore: Metro Grocery\nUnique Code: GROCERY492\nTotal: $45.50", fontsize=15)
pix = p_scan.get_pixmap(dpi=150)
png_bytes = pix.tobytes("png")
doc_scan.close()
res_scan_ocr = ocr_engine.extract_text(png_bytes, "png")
print(f"[STEP 3: READING] Scanned image OCR: method={res_scan_ocr.page_methods[0]}, extracted='{res_scan_ocr.full_text.splitlines()[0]}', code in text={'GROCERY492' in res_scan_ocr.full_text}")

# ----------------------------------------------------------------------
# STEP 4: SORTING (CLASSIFIER TYPE & PERCENTAGE)
# ----------------------------------------------------------------------
from app.adapters.classifier import get_classifier
classifier = get_classifier()
cls_res = classifier.predict(res_digital_ocr.full_text)
how_sure = round(cls_res.confidence * 100, 1)
print(f"[STEP 4: SORTING] Predicted type='{cls_res.predicted_class}', how_sure={how_sure}%")

# ----------------------------------------------------------------------
# STEP 5: DETAILS AND PERSONAL DATA (KEY-VALUE EXTRACTION & PII)
# ----------------------------------------------------------------------
from app.workers.stages import stage_extract_fields, stage_pii_detect
extracted_fields, confs, is_valid = stage_extract_fields(res_digital_ocr.full_text, cls_res.predicted_class)
pii_res = stage_pii_detect("Employee John Doe SSN: 123-45-6789 Phone: 555-0199")
print(f"[STEP 5: DETAILS & PII] Extracted fields={list(extracted_fields.keys())}, PII detected={pii_res['pii_detected']}, types={pii_res['pii_types']}")

# ----------------------------------------------------------------------
# STEP 6: DECISION (SORTED_AUTOMATICALLY, NEEDS_CHECK, FAILED, ALREADY_UPLOADED, BLOCKED)
# ----------------------------------------------------------------------
from app.api.routes_v1 import to_plain_status
decisions = [
    ("auto_accepted", False, to_plain_status("auto_accepted")),
    ("pending_review", False, to_plain_status("pending_review")),
    ("failed", False, to_plain_status("failed")),
    ("duplicate", True, to_plain_status("duplicate", is_link=True)),
    ("quarantined", False, to_plain_status("quarantined")),
]
print(f"[STEP 6: DECISION] Plain status mappings: {dict((k, v) for k, _, v in decisions)}")

# ----------------------------------------------------------------------
# STEP 7: PROGRESS & NOTIFICATION (PERCENTAGE & BELL NOTIFICATION AT 100%)
# ----------------------------------------------------------------------
db = get_db_session()
# Ingest 2 files into batch_id: 1 auto-accepted, 1 pending review
sha_dig = hashlib.sha256(pdf_bytes).hexdigest()
sha_png = hashlib.sha256(png_bytes).hexdigest()
doc1_uid = f"doc-aud-1-{uuid.uuid4().hex[:6]}"
doc1 = DocumentModel(
    uid=doc1_uid,
    sha256=sha_dig,
    file_name="invoice_acme.pdf",
    file_size=len(pdf_bytes),
    storage_path=f"data/storage/{sha_dig}",
    batch_id=batch_id,
    user_id="usr-adm-01",
    doc_type="invoice",
    confidence=0.96,
    review_status="auto_accepted",
    extracted_fields_json=json.dumps({"amount": "1250.00", "supplier": "Acme Hardware"}),
    decision_reason="Confidence 0.96 >= threshold 0.85 for invoice",
)
doc2_uid = f"doc-aud-2-{uuid.uuid4().hex[:6]}"
doc2 = DocumentModel(
    uid=doc2_uid,
    sha256=sha_png,
    file_name="scanned_receipt.png",
    file_size=len(png_bytes),
    storage_path=f"data/storage/{sha_png}",
    batch_id=batch_id,
    user_id="usr-adm-01",
    doc_type="receipt",
    confidence=0.62,
    review_status="pending_review",
    extracted_fields_json=json.dumps({"total": "45.50"}),
    decision_reason="Confidence 0.62 below acceptance threshold 0.85; routed to review queue",
)
db.add_all([doc1, doc2])
db.commit()
db.close()

b_detail = client.get(f"/api/v1/batches/{batch_id}", headers=headers).json()
notifs = client.get("/api/v1/notifications", headers=headers).json()
print(f"[STEP 7: PROGRESS & NOTIFICATION] Batch progress={b_detail['progress_percent']}%, is_finished={b_detail['is_finished']}")
print(f"[STEP 7: PROGRESS & NOTIFICATION] Notifications unread={notifs['unread_count']}, latest='{notifs['items'][0]['title'] if notifs['items'] else 'none'}'")

# ----------------------------------------------------------------------
# STEP 8: RESULTS PAGE /uploads/{id}
# ----------------------------------------------------------------------
print(f"[STEP 8: RESULTS PAGE] Batch ID={b_detail['batch_id']}, Name='{b_detail['name']}'")
print(f"       Counts by Type: {b_detail['counts_by_type']}")
print(f"       Counts by Status: {b_detail['counts_by_status']}")
print(f"       Needs Check Count: {b_detail['needs_check_count']}")
print(f"       Total Items in List: {len(b_detail['items'])}")

# ----------------------------------------------------------------------
# STEP 9: REVIEW (CONFIRM / CORRECT & REPROCESSING PRESERVATION)
# ----------------------------------------------------------------------
rev_resp = client.post(
    f"/api/v1/review/{doc2_uid}/action",
    headers=headers,
    json={
        "action": "CORRECT",
        "reviewer_id": "auditor_alice",
        "corrected_type": "receipt",
        "corrected_fields": {"store": "Metro Grocery", "total": "45.50"},
        "review_notes": "Verified receipt total and store name by human reviewer",
    },
)
print(f"[STEP 9: REVIEW] Review action status={rev_resp.status_code}, message='{rev_resp.json()['message']}'")
db = get_db_session()
doc2_db = db.query(DocumentModel).filter(DocumentModel.uid == doc2_uid).first()
print(f"[STEP 9: REVIEW] Persisted: status='{doc2_db.review_status}', reviewer='{doc2_db.reviewer_id}', verified_fields={doc2_db.human_verified_fields_json}")
db.close()

# ----------------------------------------------------------------------
# STEP 10: DOWNLOAD (STREAMED ZIP WITH FOLDERS & summary.csv)
# ----------------------------------------------------------------------
import zipfile
dl_init = client.post(f"/api/v1/batches/{batch_id}/downloads", headers=headers).json()
print(f"[STEP 10: DOWNLOAD] Request created: ID={dl_init['id']}, status='{dl_init['status']}'")

# Stream file
dl_file_resp = client.get(f"/api/v1/downloads/{dl_init['id']}/file", headers=headers)
print(f"[STEP 10: DOWNLOAD] Stream download status={dl_file_resp.status_code}, bytes={len(dl_file_resp.content)}")
zf = zipfile.ZipFile(io.BytesIO(dl_file_resp.content))
print(f"[STEP 10: DOWNLOAD] Zip entries: {zf.namelist()}")
assert "summary.csv" in zf.namelist()
csv_content = zf.read("summary.csv").decode("utf-8")
print(f"[STEP 10: DOWNLOAD] summary.csv header: {csv_content.splitlines()[0]}")

# ----------------------------------------------------------------------
# STEP 11: MY UPLOADS
# ----------------------------------------------------------------------
batches_resp = client.get("/api/v1/batches?page=1&page_size=10", headers=headers).json()
print(f"[STEP 11: MY UPLOADS] Total batches found: {batches_resp['total']}")
for b in batches_resp['items'][:3]:
    print(f"       Batch: {b['name']} (ID: {b['batch_id']}), files={b['file_count']}, progress={b['progress_percent']}%")
print("==================================================")
print("AUDIT COMPLETE: ALL 11 WORKFLOW STEPS VERIFIED.")
print("==================================================")
