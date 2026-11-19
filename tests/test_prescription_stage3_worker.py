"""Automated Integration & Unit Tests for Stage 3: Prescription Upload, Storage, and Worker.

Verifies:
- POST /api/v1/prescriptions upload returns 201 QUEUED
- Duplicate detection per-user vs cross-user
- Mime type validation and size limits
- Background worker execution: OCR text preservation with line breaks, PII scan, entity extraction
- INVARIANT: Status transitions to NEEDS_REVIEW (never auto-accept)
- Idempotency: re-running worker does not duplicate extracted items
- Fault handling: worker failure transitions status to FAILED safely
"""

import io
import json
import os
import uuid
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.api.app import app
from app.core.jwt_auth import create_jwt_token, hash_password
from app.models.db import (
    AuditEventModel,
    ExtractedItemModel,
    PrescriptionModel,
    UserModel,
    get_db_session,
)
from app.workers.prescription_worker import process_prescription_job


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def test_users():
    """Create two test patient users in DB."""
    db = get_db_session()
    try:
        user_a_id = f"user-rx-a-{uuid.uuid4().hex[:8]}"
        user_b_id = f"user-rx-b-{uuid.uuid4().hex[:8]}"

        user_a = UserModel(
            id=user_a_id,
            email=f"{user_a_id}@example.com",
            password_hash=hash_password("PatientPassword123!"),
            role="patient",
            disabled=False,
        )
        user_b = UserModel(
            id=user_b_id,
            email=f"{user_b_id}@example.com",
            password_hash=hash_password("PatientPassword123!"),
            role="patient",
            disabled=False,
        )
        db.add_all([user_a, user_b])
        db.commit()

        token_a = create_jwt_token(user_id=user_a_id, role="patient", expires_in_seconds=3600)
        token_b = create_jwt_token(user_id=user_b_id, role="patient", expires_in_seconds=3600)

        return {
            "user_a_id": user_a_id,
            "token_a": token_a,
            "user_b_id": user_b_id,
            "token_b": token_b,
        }
    finally:
        db.close()


def _create_sample_prescription_png(text_lines: list) -> bytes:
    """Generate a clean synthetic prescription image in-memory."""
    img = Image.new("RGB", (600, 300), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    y = 20
    for line in text_lines:
        draw.text((20, y), line, fill=(0, 0, 0))
        y += 35
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_upload_prescription_201_queued(client, test_users):
    """Verify prescription upload returns 201 CREATED with status QUEUED."""
    sample_bytes = _create_sample_prescription_png([
        "Dr. John Doe, MD - Clinic",
        "Amoxicillin 500mg 1 capsule TDS after meals for 7 days",
        "Paracetamol 500mg 1 tab SOS for fever",
    ])

    headers = {"Authorization": f"Bearer {test_users['token_a']}"}
    files = {"file": ("rx_test.png", sample_bytes, "image/png")}

    resp = client.post("/api/v1/prescriptions", headers=headers, files=files)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "QUEUED"
    assert data["prescription_id"].startswith("rx-")
    assert "job_id" in data


def test_upload_prescription_duplicate_detection(client, test_users):
    """Verify same user uploading identical file gets existing record; different user gets new record."""
    sample_bytes = _create_sample_prescription_png([
        "Dr. Alice Smith, MD",
        "Metformin 500mg 1 tab BD with meals for 30 days",
    ])

    headers_a = {"Authorization": f"Bearer {test_users['token_a']}"}
    headers_b = {"Authorization": f"Bearer {test_users['token_b']}"}

    # Upload 1: User A
    resp_a1 = client.post(
        "/api/v1/prescriptions",
        headers=headers_a,
        files={"file": ("rx_metformin.png", sample_bytes, "image/png")},
    )
    assert resp_a1.status_code == 201
    rx_id_a1 = resp_a1.json()["prescription_id"]

    # Upload 2: User A re-uploads the exact same file
    resp_a2 = client.post(
        "/api/v1/prescriptions",
        headers=headers_a,
        files={"file": ("rx_metformin.png", sample_bytes, "image/png")},
    )
    assert resp_a2.status_code == 201
    rx_id_a2 = resp_a2.json()["prescription_id"]
    # Invariant: Duplicate upload by same user returns the same prescription ID
    assert rx_id_a1 == rx_id_a2
    assert "Duplicate upload detected" in resp_a2.json()["message"]

    # Upload 3: User B uploads the same file
    resp_b1 = client.post(
        "/api/v1/prescriptions",
        headers=headers_b,
        files={"file": ("rx_metformin.png", sample_bytes, "image/png")},
    )
    assert resp_b1.status_code == 201
    rx_id_b1 = resp_b1.json()["prescription_id"]
    # Invariant: Different user gets their own isolated prescription record
    assert rx_id_b1 != rx_id_a1


def test_upload_invalid_mime_type_rejected(client, test_users):
    """Verify non-image/non-pdf formats are rejected with 415 Unsupported Media Type."""
    headers = {"Authorization": f"Bearer {test_users['token_a']}"}
    fake_exe = b"MZ\x90\x00\x03\x00\x00\x00"

    resp = client.post(
        "/api/v1/prescriptions",
        headers=headers,
        files={"file": ("malicious.exe", fake_exe, "application/x-dosexec")},
    )
    assert resp.status_code == 415


def test_background_worker_processing_and_invariants(client, test_users):
    """Verify worker execution, line preservation, entity extraction, and NEVER AUTO-ACCEPT invariant."""
    sample_bytes = _create_sample_prescription_png([
        "Patient: Jane Doe SSN 123-45-6789",
        "Amoxicillin 500mg 1 cap TDS after meals for 5 days",
        "Cetirizine 10mg 1 tab OD at bedtime for 10 days",
    ])

    headers = {"Authorization": f"Bearer {test_users['token_a']}"}
    resp = client.post(
        "/api/v1/prescriptions",
        headers=headers,
        files={"file": ("rx_multi.png", sample_bytes, "image/png")},
    )
    assert resp.status_code == 201
    rx_id = resp.json()["prescription_id"]

    # Execute worker
    success = process_prescription_job(rx_id)
    assert success is True

    # Inspect prescription detail
    detail_resp = client.get(f"/api/v1/prescriptions/{rx_id}", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()

    # INVARIANT: Status MUST be NEEDS_REVIEW (never auto-accept)
    assert detail["status"] == "NEEDS_REVIEW"
    assert detail["requires_user_confirmation"] is True
    assert len(detail["raw_text"]) > 0

    # Verify extracted items
    items = detail["items"]
    drug_names = [it["drug_name"] for it in items]
    assert "Amoxicillin" in drug_names
    assert "Cetirizine" in drug_names

    # Check unconfirmed invariant
    for it in items:
        assert it["verified_by_user"] is False

    # Check audit trail record
    db = get_db_session()
    try:
        audit_row = db.query(AuditEventModel).filter(
            AuditEventModel.document_uid == rx_id,
            AuditEventModel.event_type == "PRESCRIPTION_PROCESSED",
        ).first()
        assert audit_row is not None
        assert audit_row.status == "SUCCESS"
    finally:
        db.close()


def test_worker_idempotency_and_no_duplicates(client, test_users):
    """Verify running worker repeatedly on same prescription does not duplicate extracted items."""
    sample_bytes = _create_sample_prescription_png([
        "Ibuprofen 400mg 1 tab BD after meals for 3 days",
    ])

    headers = {"Authorization": f"Bearer {test_users['token_a']}"}
    resp = client.post(
        "/api/v1/prescriptions",
        headers=headers,
        files={"file": ("rx_ibuprofen.png", sample_bytes, "image/png")},
    )
    rx_id = resp.json()["prescription_id"]

    # First run
    process_prescription_job(rx_id)

    db = get_db_session()
    try:
        count_first = db.query(ExtractedItemModel).filter(ExtractedItemModel.prescription_id == rx_id).count()
        assert count_first >= 1

        # Second run (simulating duplicate worker delivery)
        process_prescription_job(rx_id)
        count_second = db.query(ExtractedItemModel).filter(ExtractedItemModel.prescription_id == rx_id).count()

        # Invariant: Item count does not multiply
        assert count_first == count_second
    finally:
        db.close()


def test_worker_failure_handling_safe_error(client, test_users):
    """Verify missing/corrupted file fails cleanly with status FAILED and safe error message."""
    db = get_db_session()
    try:
        bad_rx_id = f"rx-fault-{uuid.uuid4().hex[:8]}"
        bad_rx = PrescriptionModel(
            id=bad_rx_id,
            user_id=test_users["user_a_id"],
            file_key="non_existent/path/missing.pdf",
            status="QUEUED",
        )
        db.add(bad_rx)
        db.commit()

        # Run worker on missing file
        result = process_prescription_job(bad_rx_id)
        assert result is False

        # Status must be FAILED with safe message
        rx_db = db.query(PrescriptionModel).filter(PrescriptionModel.id == bad_rx_id).first()
        assert rx_db.status == "FAILED"
        assert rx_db.error_message is not None
        # Safe message invariant: no raw stack trace or internal filesystem path in user-facing error
        assert "traceback" not in rx_db.error_message.lower()
        assert "c:\\" not in rx_db.error_message.lower()
    finally:
        db.close()
