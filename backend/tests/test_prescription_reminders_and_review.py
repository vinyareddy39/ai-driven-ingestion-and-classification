"""Tests for Stage 6: Reminders, Review Loop, and Batch Reprocessing with Invariant Protection."""

import json
import os
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.models.db import (
    AuditEventModel,
    ExtractedItemModel,
    PrescriptionModel,
    ReminderModel,
    TimetableSlotModel,
    UserModel,
    get_db_session,
)
from app.core.jwt_auth import hash_password, create_jwt_token
from app.workers.reminders import (
    LogReminderChannel,
    StubSMTPReminderChannel,
    dispatch_due_reminders,
)


@pytest.fixture
def auth_client():
    client = TestClient(app)
    db = get_db_session()
    try:
        user_id = str(uuid.uuid4())
        user = UserModel(
            id=user_id,
            email=f"stage6_user_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("SecurePassword123!"),
            role="patient",
        )
        db.add(user)
        db.commit()

        token = create_jwt_token(user_id=user.id, role=user.role, expires_in_seconds=3600)
        client.headers["Authorization"] = f"Bearer {token}"
        client.user_id = user_id
        return client
    finally:
        db.close()


def test_user_item_correction_and_training_export(auth_client):
    """Test user manual correction of medication field, verifying DB update and JSONL export."""
    db = get_db_session()
    try:
        rx_id = str(uuid.uuid4())
        rx = PrescriptionModel(
            id=rx_id,
            user_id=auth_client.user_id,
            file_key="prescriptions/test.pdf",
            sha256="fake_sha256_stage6",
            status="NEEDS_REVIEW",
            raw_text="Rx Amoxicillin 250mg TDS x 5 days",
        )
        item_id = str(uuid.uuid4())
        item = ExtractedItemModel(
            id=item_id,
            prescription_id=rx_id,
            raw_text="Amoxicillin 250mg TDS",
            drug_name="Amoxicillin",
            strength="250mg",
            dose="1 capsule",
            frequency="TDS",
            timing="after food",
            duration_days=5,
            schedule_rule="8am,2pm,8pm",
            verified_by_user=False,
        )
        db.add(rx)
        db.add(item)
        db.commit()

        corrections_path = os.path.join("data", "prescription_corrections.jsonl")
        initial_lines = 0
        if os.path.exists(corrections_path):
            with open(corrections_path, "r", encoding="utf-8") as f:
                initial_lines = len(f.readlines())

        # Correct dose and strength via PATCH
        resp = auth_client.patch(
            f"/api/v1/prescriptions/{rx_id}/items/{item_id}",
            json={
                "strength": "500mg",
                "dose": "500mg",
                "verified_by_user": True,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["strength"] == "500mg"
        assert data["dose"] == "500mg"
        assert data["verified_by_user"] is True

        # Verify DB persisted
        db.refresh(item)
        assert item.strength == "500mg"
        assert item.verified_by_user is True

        # Verify corrections file appended
        assert os.path.exists(corrections_path)
        with open(corrections_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == initial_lines + 1
        last_rec = json.loads(lines[-1])
        assert last_rec["item_id"] == item_id
        assert last_rec["corrected_fields"]["strength"] == "500mg"
        assert last_rec["verified_by_user"] is True
        # Safety invariant: no user personal name or email logged
        assert "patient_name" not in last_rec
        assert "user_id" not in last_rec

        # Verify audit trail
        audit_rec = db.query(AuditEventModel).filter(
            AuditEventModel.document_uid == rx_id,
            AuditEventModel.event_type == "ITEM_CORRECTED",
        ).first()
        assert audit_rec is not None
    finally:
        db.close()


def test_batch_reprocessing_preserves_verified_items(auth_client):
    """Test that batch reprocessing NEVER overwrites user-verified items."""
    db = get_db_session()
    try:
        rx_id = str(uuid.uuid4())
        rx = PrescriptionModel(
            id=rx_id,
            user_id=auth_client.user_id,
            file_key="prescriptions/test.pdf",
            sha256="fake_sha256_stage6_reprocess",
            status="NEEDS_REVIEW",
            raw_text="Rx Metformin 500mg BD after food x 30 days\nRx Paracetamol 650mg TDS x 3 days",
            model_version="v1.0",
        )
        # Item 1: User-verified and corrected
        item1_id = str(uuid.uuid4())
        item1 = ExtractedItemModel(
            id=item1_id,
            prescription_id=rx_id,
            raw_text="Metformin 500mg BD",
            drug_name="Metformin",
            strength="500mg",
            dose="Custom 1000mg User Dose",
            frequency="BD",
            timing="after food",
            duration_days=30,
            verified_by_user=True,  # PROTECTED
        )
        # Item 2: Unverified
        item2_id = str(uuid.uuid4())
        item2 = ExtractedItemModel(
            id=item2_id,
            prescription_id=rx_id,
            raw_text="Paracetamol 650mg TDS",
            drug_name="Paracetamol",
            strength="650mg",
            dose="650mg",
            frequency="TDS",
            timing="after food",
            duration_days=3,
            verified_by_user=False,  # Can be reprocessed
        )
        db.add(rx)
        db.add(item1)
        db.add(item2)
        db.commit()

        # 1. Test Dry-Run Mode
        dry_run_resp = auth_client.post(
            "/api/v1/prescriptions/reprocess",
            json={
                "prescription_ids": [rx_id],
                "dry_run": True,
            },
        )
        assert dry_run_resp.status_code == 200, dry_run_resp.text
        dry_data = dry_run_resp.json()
        assert dry_data["dry_run"] is True
        res = dry_data["results"][0]
        assert res["items_preserved"] == 1
        actions = {d["action"] for d in res["diffs"]}
        assert "preserved" in actions

        # Verify DB untouched after dry run
        db.refresh(rx)
        assert rx.model_version == "v1.0"
        db.refresh(item1)
        assert item1.dose == "Custom 1000mg User Dose"

        # 2. Test Live Reprocess
        live_resp = auth_client.post(
            "/api/v1/prescriptions/reprocess",
            json={
                "prescription_ids": [rx_id],
                "dry_run": False,
            },
        )
        assert live_resp.status_code == 200, live_resp.text
        live_data = live_resp.json()
        assert live_data["dry_run"] is False

        # Invariant Verification: Item 1 MUST still exist and be intact
        db.refresh(rx)
        assert rx.model_version == "v2.0-batch-reprocessed"

        persisted_item1 = db.query(ExtractedItemModel).filter(ExtractedItemModel.id == item1_id).first()
        assert persisted_item1 is not None, "Violation: User-verified item was deleted during reprocessing!"
        assert persisted_item1.dose == "Custom 1000mg User Dose", "Violation: User-verified item was altered!"
        assert persisted_item1.verified_by_user is True

        # Audit event check
        audit_reprocess = db.query(AuditEventModel).filter(
            AuditEventModel.document_uid == rx_id,
            AuditEventModel.event_type == "PRESCRIPTION_REPROCESSED",
        ).first()
        assert audit_reprocess is not None
    finally:
        db.close()


def test_reminder_scheduler_and_safe_payloads(auth_client):
    """Test reminder dispatch: safe payloads, zero PII, and non-duplicate delivery."""
    db = get_db_session()
    try:
        rx_id = str(uuid.uuid4())
        rx = PrescriptionModel(
            id=rx_id,
            user_id=auth_client.user_id,
            file_key="prescriptions/test.pdf",
            status="CONFIRMED",
        )
        item_id = str(uuid.uuid4())
        item = ExtractedItemModel(
            id=item_id,
            prescription_id=rx_id,
            raw_text="Amoxicillin 500mg",
            drug_name="Amoxicillin",
            strength="500mg",
            dose="500mg capsule",
            verified_by_user=True,
        )
        # Slot scheduled 20 minutes in future
        now = datetime.now(timezone.utc)
        slot_time = now + timedelta(minutes=20)
        slot_id = str(uuid.uuid4())
        slot = TimetableSlotModel(
            id=slot_id,
            user_id=auth_client.user_id,
            prescription_id=rx_id,
            extracted_item_id=item_id,
            scheduled_at=slot_time,
            instruction="Take 500mg capsule after food",
            status="pending",
        )
        db.add(rx)
        db.add(item)
        db.add(slot)
        db.commit()

        # Dispatch reminders via LogReminderChannel
        log_channel = LogReminderChannel()
        dispatched = dispatch_due_reminders(
            db,
            window_minutes=60,
            channel=log_channel,
            reference_time=now,
        )
        assert len(dispatched) == 1
        d_slot = dispatched[0]
        assert d_slot["slot_id"] == slot_id
        assert d_slot["drug_name"] == "Amoxicillin"
        assert d_slot["dose"] == "500mg capsule"
        # Safety invariant checks
        assert "patient_name" not in d_slot
        assert "patient_email" not in d_slot
        assert "raw_text" not in d_slot
        assert "url" not in d_slot

        # Verify ReminderModel row created
        reminder_row = db.query(ReminderModel).filter(ReminderModel.slot_id == slot_id).first()
        assert reminder_row is not None
        assert reminder_row.sent_at is not None

        # Verify idempotency: calling dispatch again produces 0 additional reminders
        second_dispatch = dispatch_due_reminders(
            db,
            window_minutes=60,
            channel=log_channel,
            reference_time=now,
        )
        assert len(second_dispatch) == 0

        # Test StubSMTPReminderChannel
        smtp_channel = StubSMTPReminderChannel()
        smtp_slot_id = str(uuid.uuid4())
        smtp_slot = TimetableSlotModel(
            id=smtp_slot_id,
            user_id=auth_client.user_id,
            prescription_id=rx_id,
            extracted_item_id=item_id,
            scheduled_at=now + timedelta(minutes=10),
            instruction="Take 500mg capsule",
            status="pending",
        )
        db.add(smtp_slot)
        db.commit()

        smtp_dispatched = dispatch_due_reminders(
            db,
            window_minutes=30,
            channel=smtp_channel,
            channel_name="smtp",
            reference_time=now,
        )
        assert len(smtp_dispatched) == 1
        assert len(smtp_channel.sent_emails) == 1
        email_msg = smtp_channel.sent_emails[0]
        assert "Amoxicillin" in email_msg["body"]
        assert "500mg" in email_msg["body"]
        assert "patient_name" not in email_msg["payload"]
    finally:
        db.close()
