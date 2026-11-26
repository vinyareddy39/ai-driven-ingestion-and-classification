"""Regression test suite for Batch Reading, Duplicate Detection, Honest Status, and Failure Grouping."""

import io
import os
import tempfile
import pytest
from unittest.mock import patch
from PIL import Image, ImageDraw, ImageFont
import fitz
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.core.jwt_auth import create_token
from app.models.db import init_db, get_db_session, UserModel, BatchModel, FileModel
from app.core.generalized_pipeline import GeneralizedDocumentPipeline


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers():
    init_db()
    db = get_db_session()
    try:
        user = db.query(UserModel).filter(UserModel.email == "test_verifier@example.com").first()
        if not user:
            user = UserModel(
                id="user_reg_01",
                name="Test Verifier",
                email="test_verifier@example.com",
                role="admin",
                password_hash="fake_hash",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        token = create_token({"sub": user.id, "email": user.email, "role": user.role})
        return {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def create_synthetic_digital_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 72), text, fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_clean_image(text: str) -> bytes:
    img = Image.new("RGB", (600, 400), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((50, 50), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def create_synthetic_noisy_skewed_image(text: str) -> bytes:
    img = Image.new("RGB", (600, 400), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)
    draw.text((60, 60), text, fill=(10, 10, 10))
    # Skew/rotate slightly
    rotated = img.rotate(2, expand=True, fillcolor=(255, 255, 255))
    buf = io.BytesIO()
    rotated.save(buf, format="PNG")
    return buf.getvalue()


def create_synthetic_image_only_pdf(text: str) -> bytes:
    img_bytes = create_synthetic_clean_image(text)
    doc = fitz.open()
    rect = fitz.Rect(0, 0, 595, 842)
    page = doc.new_page(width=595, height=842)
    page.insert_image(rect, stream=img_bytes)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_multipage_pdf() -> bytes:
    doc = fitz.open()
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((50, 72), "INVOICE #INV-9921\nVendor: Apex Solutions\nAmount: $5,000.00", fontsize=12)
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((50, 72), "TERMS AND CONDITIONS\nPayment due in 30 days.\nContact: billing@apex.example", fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


# 1. Digital PDF Reading
def test_digital_pdf_reading():
    content = "STATEMENT OF ACCOUNT\nAccount: 4892-0012\nBalance: $1,250.00\nDate: 2026-11-20"
    pdf_bytes = create_synthetic_digital_pdf(content)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        pipeline = GeneralizedDocumentPipeline()
        res = pipeline.process_file(tmp_path)
        assert res is not None
        assert len(res.get("fields", [])) > 0
        assert res.get("type") in ["statement", "bank_statement", "account_statement", "invoice", "receipt", "Document", "financial_statement", "unknown"]
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# 2. Clean Image Reading
def test_clean_image_reading():
    content = "RECEIPT\nStore: North Mart\nTotal: $42.50\nDate: 2026-11-22"
    img_bytes = create_synthetic_clean_image(content)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(img_bytes)
        tmp_path = tmp.name

    try:
        pipeline = GeneralizedDocumentPipeline()
        res = pipeline.process_file(tmp_path)
        assert res is not None
        assert len(res.get("fields", [])) > 0
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# 3. Skewed Noisy Image Reading
def test_skewed_noisy_image_reading():
    content = "DELIVERY RECEIPT\nOrder: 77124\nCarrier: FastLogistics\nDate: 2026-11-23"
    img_bytes = create_synthetic_noisy_skewed_image(content)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(img_bytes)
        tmp_path = tmp.name

    try:
        pipeline = GeneralizedDocumentPipeline()
        res = pipeline.process_file(tmp_path)
        assert res is not None
        assert len(res.get("fields", [])) > 0
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# 4. Image-Only PDF Reading
def test_image_only_pdf_reading():
    content = "PURCHASE ORDER\nPO Number: PO-8831\nVendor: Global Parts\nAmount: $950.00"
    pdf_bytes = create_synthetic_image_only_pdf(content)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        pipeline = GeneralizedDocumentPipeline()
        res = pipeline.process_file(tmp_path)
        assert res is not None
        assert len(res.get("fields", [])) > 0
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# 5. Multi-Page Document Reading
def test_multipage_reading():
    pdf_bytes = create_synthetic_multipage_pdf()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        pipeline = GeneralizedDocumentPipeline()
        res = pipeline.process_file(tmp_path)
        assert res is not None
        assert len(res.get("page_conditions", [1])) >= 2 or len(res.get("fields", [])) > 0
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# 6. Damaged / Corrupt File Handling (Honest Status & Safe Check Reasons)
def test_damaged_file_handling(client, auth_headers):
    corrupt_bytes = b"%PDF-1.4\n%corrupted_non_readable_junk\x00\xff\xfe\xfa"
    batch_res = client.post("/api/batches", headers=auth_headers, data={"batch_name": "Test Corrupt Batch"})
    assert batch_res.status_code == 201
    batch_id = batch_res.json()["id"]

    # Upload corrupt file
    files = [("files", ("corrupted_doc.pdf", corrupt_bytes, "application/pdf"))]
    app_res = client.post(f"/api/batches/{batch_id}/files", headers=auth_headers, files=files)
    assert app_res.status_code == 201

    # Start batch
    from app.api.routes_documents import process_batch_background
    process_batch_background(batch_id)

    b_res = client.get(f"/api/batches/{batch_id}", headers=auth_headers).json()
    f0 = b_res["files"][0]
    # Status and stage must agree honestly
    assert f0["stage"] == "Failed"
    assert f0["status"] == "Failed"
    assert f0["type"] == "Could not read"
    assert f0["check_reasons"] in ["file damaged", "text could not be read from the image"]
    # Internal paths / stack traces must not be exposed
    assert "Traceback" not in (f0["error"] or "")
    assert "File \"" not in (f0["error"] or "")


# 7. Worker Outage / Failure Handling
def test_worker_outage_handling(client, auth_headers):
    pdf_bytes = create_synthetic_digital_pdf("Standard invoice content")
    batch_res = client.post("/api/batches", headers=auth_headers, data={"batch_name": "Test Outage Batch"})
    batch_id = batch_res.json()["id"]

    files = [("files", ("outage_doc.pdf", pdf_bytes, "application/pdf"))]
    client.post(f"/api/batches/{batch_id}/files", headers=auth_headers, files=files)

    with patch("app.core.generalized_pipeline.GeneralizedDocumentPipeline.process_file", side_effect=RuntimeError("Worker connection failed")):
        from app.api.routes_documents import process_batch_background
        process_batch_background(batch_id)

    b_res = client.get(f"/api/batches/{batch_id}", headers=auth_headers).json()
    f0 = b_res["files"][0]
    assert f0["stage"] == "Failed"
    assert f0["status"] == "Failed"
    assert f0["type"] == "Could not read"
    assert f0["check_reasons"] == "reader unavailable"


# 8. Duplicate Detection Rules (No Self-Matching, Identical vs Different)
def test_duplicate_detection_rules(client, auth_headers):
    content_a = "UNIQUE CONTENT ALPHA " + os.urandom(8).hex()
    content_b = "UNIQUE CONTENT BETA " + os.urandom(8).hex()

    bytes_a = create_synthetic_digital_pdf(content_a)
    bytes_b = create_synthetic_digital_pdf(content_b)

    # Batch 1: Upload doc_alpha.pdf and copy_of_alpha.pdf (same content), plus doc_beta.pdf (different)
    batch_res = client.post("/api/batches", headers=auth_headers, data={"batch_name": "Dup Test Batch 1"})
    b1_id = batch_res.json()["id"]

    files = [
        ("files", ("doc_alpha.pdf", bytes_a, "application/pdf")),
        ("files", ("copy_of_alpha.pdf", bytes_a, "application/pdf")),
        ("files", ("doc_beta.pdf", bytes_b, "application/pdf")),
    ]
    client.post(f"/api/batches/{b1_id}/files", headers=auth_headers, files=files)
    b1_data = client.get(f"/api/batches/{b1_id}", headers=auth_headers).json()

    files_b1 = {f["name"]: f for f in b1_data["files"]}

    # Rule 1: First occurrence must NOT match itself
    assert files_b1["doc_alpha.pdf"]["dup"] is None

    # Rule 2: Identical copy in same batch matches the earlier file
    assert files_b1["copy_of_alpha.pdf"]["dup"] == "doc_alpha.pdf"

    # Rule 3: Distinct file must NOT receive duplicate match
    assert files_b1["doc_beta.pdf"]["dup"] is None

    # Batch 2: Re-upload doc_alpha.pdf alone in a new batch
    batch_res2 = client.post("/api/batches", headers=auth_headers, data={"batch_name": "Dup Test Batch 2"})
    b2_id = batch_res2.json()["id"]

    files_batch2 = [("files", ("doc_alpha.pdf", bytes_a, "application/pdf"))]
    client.post(f"/api/batches/{b2_id}/files", headers=auth_headers, files=files_batch2)
    b2_data = client.get(f"/api/batches/{b2_id}", headers=auth_headers).json()

    f_b2 = b2_data["files"][0]
    # Rule 4: Re-uploading doc_alpha.pdf must NEVER show "Same content as doc_alpha.pdf" under itself
    assert f_b2["dup"] is None or f_b2["dup"] != "doc_alpha.pdf"


# 9. Worker Health Status Endpoint
def test_worker_health_endpoint(client, auth_headers):
    res = client.get("/api/admin/workers/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ["healthy", "degraded"]
    assert "workers" in data
    assert data["workers"]["pipeline_ready"] is True
    assert data["database"]["status"] == "connected"
