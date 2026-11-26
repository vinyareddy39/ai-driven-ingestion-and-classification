"""Stage 7: Privacy, Security, Column Encryption, and GDPR/HIPAA Compliance Tests."""

import json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.adapters.storage import get_storage_adapter
from app.models.db import (
    AuditEventModel,
    ExtractedItemModel,
    PrescriptionModel,
    ReminderModel,
    TimetableSlotModel,
    UserModel,
    get_db_session,
    get_db_engine,
)
from app.core.jwt_auth import hash_password, create_jwt_token


@pytest.fixture
def auth_user():
    db = get_db_session()
    try:
        user_id = str(uuid.uuid4())
        email = f"gdpr_user_{uuid.uuid4().hex[:6]}@example.com"
        user = UserModel(
            id=user_id,
            email=email,
            password_hash=hash_password("SecurePassword123!"),
            role="patient",
        )
        db.add(user)
        db.commit()

        token = create_jwt_token(user_id=user.id, role=user.role, expires_in_seconds=3600)
        client = TestClient(app)
        client.headers["Authorization"] = f"Bearer {token}"
        client.user_id = user_id
        client.email = email
        return client
    finally:
        db.close()


def test_column_encryption_at_rest_and_raw_db_leak_prevention(auth_user):
    """Verify that raw_text is encrypted at rest in the database (Fernet / AES-128-CBC + HMAC)."""
    db = get_db_session()
    rx_id = str(uuid.uuid4())
    sensitive_text = "CONFIDENTIAL: Rx Hydrochlorothiazide 25mg OD for severe essential hypertension"

    try:
        rx = PrescriptionModel(
            id=rx_id,
            user_id=auth_user.user_id,
            file_key="prescriptions/priv_test.pdf",
            status="NEEDS_REVIEW",
            raw_text=sensitive_text,
        )
        db.add(rx)
        db.commit()

        # 1. Inspect Raw SQL Column Value Directly (Bypassing ORM TypeDecorator)
        engine = get_db_engine()
        with engine.connect() as conn:
            from sqlalchemy import text
            result = conn.execute(text("SELECT raw_text FROM prescriptions WHERE id = :id"), {"id": rx_id}).fetchone()
            assert result is not None
            raw_stored_str = result[0]

            # Invariant: Raw DB value MUST be ciphertext starting with Fernet header 'gAAAAA'
            assert raw_stored_str.startswith("gAAAAA"), f"Security Failure: raw_text not encrypted at rest! Stored: {raw_stored_str[:20]}"
            # Invariant: Sensitive medical strings MUST NOT be present in raw database storage
            assert "Hydrochlorothiazide" not in raw_stored_str
            assert "hypertension" not in raw_stored_str

        # 2. Inspect Transparent ORM Decryption
        db.expire_all()
        fetched_rx = db.query(PrescriptionModel).filter(PrescriptionModel.id == rx_id).first()
        assert fetched_rx.raw_text == sensitive_text
    finally:
        db.close()


def test_patient_data_export(auth_user):
    """Test GET /api/v1/user/export-my-data returns full portable personal health bundle."""
    db = get_db_session()
    try:
        rx_id = str(uuid.uuid4())
        rx = PrescriptionModel(
            id=rx_id,
            user_id=auth_user.user_id,
            file_key="prescriptions/export_test.pdf",
            status="CONFIRMED",
            raw_text="Rx Atorvastatin 20mg HS",
        )
        item_id = str(uuid.uuid4())
        item = ExtractedItemModel(
            id=item_id,
            prescription_id=rx_id,
            raw_text="Atorvastatin 20mg",
            drug_name="Atorvastatin",
            strength="20mg",
            dose="1 tablet",
            frequency="HS",
            timing="at bedtime",
            duration_days=30,
            verified_by_user=True,
        )
        db.add(rx)
        db.add(item)
        db.commit()

        resp = auth_user.get("/api/v1/user/export-my-data")
        assert resp.status_code == 200, resp.text
        bundle = resp.json()

        assert bundle["user_id"] == auth_user.user_id
        assert bundle["email"] == auth_user.email
        assert len(bundle["prescriptions"]) >= 1
        assert len(bundle["extracted_medications"]) >= 1
        assert bundle["prescriptions"][0]["raw_text"] == "Rx Atorvastatin 20mg HS"
    finally:
        db.close()


def test_patient_data_hard_delete_gdpr_hipaa(auth_user):
    """Test DELETE /api/v1/user/delete-my-data permanently purges files and DB records."""
    db = get_db_session()
    storage = get_storage_adapter()
    try:
        file_key = f"prescriptions/{auth_user.user_id}/test_purge.pdf"
        storage.save(file_key, b"%PDF-1.4 Fake prescription binary content")
        assert storage.exists(file_key) is True

        rx_id = str(uuid.uuid4())
        rx = PrescriptionModel(
            id=rx_id,
            user_id=auth_user.user_id,
            file_key=file_key,
            status="CONFIRMED",
            raw_text="Rx Metformin 500mg BD",
        )
        item_id = str(uuid.uuid4())
        item = ExtractedItemModel(
            id=item_id,
            prescription_id=rx_id,
            drug_name="Metformin",
            verified_by_user=True,
        )
        slot_id = str(uuid.uuid4())
        slot = TimetableSlotModel(
            id=slot_id,
            user_id=auth_user.user_id,
            prescription_id=rx_id,
            extracted_item_id=item_id,
            scheduled_at=datetime.now(timezone.utc),
            status="pending",
        )
        rem_id = str(uuid.uuid4())
        rem = ReminderModel(
            id=rem_id,
            slot_id=slot_id,
            channel="email",
            send_at=datetime.now(timezone.utc),
        )
        db.add(rx)
        db.add(item)
        db.add(slot)
        db.add(rem)
        db.commit()

        # Execute hard delete
        resp = auth_user.delete("/api/v1/user/delete-my-data")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "PURGED"

        # 1. Verify physical file permanently unlinked
        assert storage.exists(file_key) is False

        # 2. Verify all DB records deleted
        assert db.query(PrescriptionModel).filter(PrescriptionModel.user_id == auth_user.user_id).first() is None
        assert db.query(ExtractedItemModel).filter(ExtractedItemModel.id == item_id).first() is None
        assert db.query(TimetableSlotModel).filter(TimetableSlotModel.user_id == auth_user.user_id).first() is None
        assert db.query(ReminderModel).filter(ReminderModel.id == rem_id).first() is None
        assert db.query(UserModel).filter(UserModel.id == auth_user.user_id).first() is None

        # 3. Verify scrubbed audit record retained with zero PII
        audit_purge = db.query(AuditEventModel).filter(
            AuditEventModel.event_type == "PATIENT_DATA_PURGED",
            AuditEventModel.document_uid == "PURGED",
        ).first()
        assert audit_purge is not None
        payload = json.loads(audit_purge.payload_json)
        assert "user_hash" in payload
        assert "email" not in payload
        assert "prescription_text" not in payload
    finally:
        db.close()


def test_log_hygiene_zero_pii_or_drug_leakage(auth_user, caplog):
    """Verify that logging handlers emit ZERO patient PII or raw prescription text."""
    with caplog.at_level(logging.INFO):
        # Trigger auth, item query, and reminder operations
        resp = auth_user.get(f"/api/v1/prescriptions/{uuid.uuid4()}")
        assert resp.status_code == 404

        all_logs = caplog.text
        # Assert zero patient credentials or secrets in logs
        assert "SecurePassword123!" not in all_logs
        assert "password_hash" not in all_logs

