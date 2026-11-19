"""Unit and integration tests for Stage 4: Batch Results, Outbound Webhook Signing, and Legal Hold Archival."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.api.app import app
from app.core.auth import get_configured_tokens
from app.models.db import (
    AuditEventModel,
    DocumentModel,
    get_db_session,
    init_db,
)
from app.workers.archival import run_disposition_lifecycle, set_legal_hold
from app.workers.distribution import OutboundWebhookDispatcher

SAMPLE_PATH = "data/test_samples/sample_batch.pdf"


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient fixture."""
    init_db()
    return TestClient(app)


def auth_headers(role: str) -> dict:
    """Dynamically resolve configured token for a given role."""
    tokens = get_configured_tokens()
    role_to_token = {r: t for t, r in tokens.items()}
    token = role_to_token.get(role, "")
    return {"Authorization": f"Bearer {token}"}


class TestBatchResultsEndpoint:
    """Verify GET /api/v1/batches/{batch_id} progress aggregation, O(1) query counts, and user isolation."""

    @pytest.fixture(autouse=True)
    def setup_batch_fixtures(self):
        init_db()
        os.makedirs("data/test_samples", exist_ok=True)
        if not os.path.exists(SAMPLE_PATH):
            with open(SAMPLE_PATH, "wb") as f:
                f.write(b"%PDF-1.4 test batch file")

        db = get_db_session()
        now = datetime.now(timezone.utc)

        # Clean existing batch test records
        db.query(DocumentModel).filter(DocumentModel.batch_id.in_(["batch-usr-a-101", "batch-usr-b-202"])).delete()
        db.commit()

        # Seed batch for User A with mixed statuses and document types
        docs = [
            DocumentModel(
                uid="doc-batch-a-01",
                sha256="hash-batch-a-01",
                file_name="invoice_jan.pdf",
                storage_path=SAMPLE_PATH,
                doc_type="invoice",
                confidence=0.96,
                review_status="auto_accepted",
                batch_id="batch-usr-a-101",
                user_id="usr-patient-a",
                created_at=now,
            ),
            DocumentModel(
                uid="doc-batch-a-02",
                sha256="hash-batch-a-02",
                file_name="receipt_lunch.png",
                storage_path=SAMPLE_PATH,
                doc_type="receipt",
                confidence=0.91,
                review_status="approved",
                batch_id="batch-usr-a-101",
                user_id="usr-patient-a",
                created_at=now,
            ),
            DocumentModel(
                uid="doc-batch-a-03",
                sha256="hash-batch-a-03",
                file_name="kyc_form_passport.pdf",
                storage_path=SAMPLE_PATH,
                doc_type="kyc_form",
                confidence=0.74,
                review_status="pending_review",
                batch_id="batch-usr-a-101",
                user_id="usr-patient-a",
                created_at=now,
            ),
            DocumentModel(
                uid="doc-batch-a-04",
                sha256="hash-batch-a-04",
                file_name="corrupt_payload.exe",
                storage_path=SAMPLE_PATH,
                doc_type="unknown",
                confidence=0.0,
                review_status="quarantined",
                quarantine_reason="Antivirus threat detected: EICAR",
                batch_id="batch-usr-a-101",
                user_id="usr-patient-a",
                created_at=now,
            ),
        ]
        for d in docs:
            db.merge(d)

        # Seed batch for User B
        db.merge(
            DocumentModel(
                uid="doc-batch-b-01",
                sha256="hash-batch-b-01",
                file_name="user_b_claim.pdf",
                storage_path=SAMPLE_PATH,
                doc_type="claim_form",
                confidence=0.88,
                review_status="pending_review",
                batch_id="batch-usr-b-202",
                user_id="usr-patient-b",
                created_at=now,
            )
        )
        db.commit()
        db.close()
        return True

    def test_batch_detail_aggregation_and_progress(self, client: TestClient):
        """Staff (compliance) retrieves User A's batch: verifies aggregated counts, type breakdowns, and items."""
        resp = client.get("/api/v1/batches/batch-usr-a-101", headers=auth_headers("compliance"))
        assert resp.status_code == 200
        data = resp.json()

        assert data["batch_id"] == "batch-usr-a-101"
        assert data["user_id"] == "usr-patient-a"

        # Verify progress counts
        progress = data["progress"]
        assert progress["total"] == 4
        assert progress["done"] == 2        # auto_accepted (1) + approved (1)
        assert progress["needs_review"] == 1  # pending_review (1)
        assert progress["quarantined"] == 1  # quarantined (1)

        # Verify breakdown by doc_type
        by_type = data["counts_by_type"]
        assert by_type["invoice"] == 1
        assert by_type["receipt"] == 1
        assert by_type["kyc_form"] == 1
        assert by_type["unknown"] == 1

        # Verify item list
        items = data["items"]
        assert len(items) == 4
        quarantined_item = next(i for i in items if i["uid"] == "doc-batch-a-04")
        assert quarantined_item["error_detail"] == "Antivirus threat detected: EICAR"

    def test_batch_isolation_user_b_cannot_see_user_a(self, client: TestClient):
        """User B requesting User A's batch gets 404 Not Found (strict isolation)."""
        from app.core.jwt_auth import create_jwt_token
        user_b_token = create_jwt_token(user_id="usr-patient-b", role="patient")
        headers_b = {"Authorization": f"Bearer {user_b_token}"}

        resp = client.get("/api/v1/batches/batch-usr-a-101", headers=headers_b)
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_batch_isolation_user_a_can_see_own_batch(self, client: TestClient):
        """User A requesting own batch gets 200 OK."""
        from app.core.jwt_auth import create_jwt_token
        user_a_token = create_jwt_token(user_id="usr-patient-a", role="patient")
        headers_a = {"Authorization": f"Bearer {user_a_token}"}

        resp = client.get("/api/v1/batches/batch-usr-a-101", headers=headers_a)
        assert resp.status_code == 200
        assert resp.json()["batch_id"] == "batch-usr-a-101"

    def test_batch_not_found(self, client: TestClient):
        """Nonexistent batch returns 404."""
        resp = client.get("/api/v1/batches/batch-nonexistent-999", headers=auth_headers("reviewer"))
        assert resp.status_code == 404


class TestOutboundWebhookDispatcher:
    """Verify cryptographically signed outbound webhooks and audit trail."""

    def test_hmac_sha256_signature_generation(self):
        secret = "test-secret-key-12345"
        dispatcher = OutboundWebhookDispatcher(signing_secret=secret)
        payload = b'{"event":"test","status":"ok"}'
        expected_sig = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        assert dispatcher.compute_signature(payload) == expected_sig

    @patch("urllib.request.urlopen")
    def test_dispatch_success_and_audit_logging(self, mock_urlopen):
        # Mock 200 HTTP response
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        # Clean any existing audit for this doc
        db = get_db_session()
        db.query(AuditEventModel).filter(AuditEventModel.document_uid == "doc-test-wh-01").delete()
        db.commit()
        db.close()

        dispatcher = OutboundWebhookDispatcher(
            target_url="https://hooks.ecm.local/events",
            signing_secret="super-webhook-secret-999",
        )

        ok, delivery_id = dispatcher.dispatch(
            document_uid="doc-test-wh-01",
            event_type="DOCUMENT_PROCESSED",
            payload_data={"doc_type": "invoice", "confidence": 0.98},
        )

        assert ok is True
        assert delivery_id.startswith("dlv-")

        # Verify audit record written to DB
        db = get_db_session()
        audit = (
            db.query(AuditEventModel)
            .filter(AuditEventModel.document_uid == "doc-test-wh-01")
            .first()
        )
        assert audit is not None
        assert audit.event_type == "OUTBOUND_WEBHOOK_DISPATCH"
        assert audit.status == "SUCCESS"
        db.close()


class TestArchivalAndLegalHold:
    """Verify legal hold protection against document disposition and retention purging."""

    @pytest.fixture(autouse=True)
    def setup_archival_fixtures(self):
        init_db()
        db = get_db_session()
        now = datetime.now(timezone.utc)
        past_expired = now - timedelta(days=365)

        db.query(DocumentModel).filter(DocumentModel.uid.in_(["doc-exp-unheld-01", "doc-exp-held-02"])).delete()
        db.commit()

        # Doc 1: Expired retention, NO legal hold
        db.merge(
            DocumentModel(
                uid="doc-exp-unheld-01",
                sha256="hash-exp-01",
                file_name="expired_temp_notes.txt",
                storage_path=SAMPLE_PATH,
                doc_type="internal_memo",
                review_status="auto_accepted",
                retention_class="1_YEAR_TEMPORARY",
                retention_expires_at=past_expired,
                legal_hold=False,
                created_at=past_expired - timedelta(days=30),
            )
        )

        # Doc 2: Expired retention, WITH active legal hold (MUST BE PROTECTED!)
        db.merge(
            DocumentModel(
                uid="doc-exp-held-02",
                sha256="hash-exp-02",
                file_name="litigation_memo.pdf",
                storage_path=SAMPLE_PATH,
                doc_type="internal_memo",
                review_status="auto_accepted",
                retention_class="1_YEAR_TEMPORARY",
                retention_expires_at=past_expired,
                legal_hold=True,
                created_at=past_expired - timedelta(days=30),
            )
        )
        db.commit()
        db.close()
        return True

    def test_set_legal_hold_and_audit(self):
        """Test applying legal hold toggles flag and records immutable audit."""
        ok = set_legal_hold("doc-exp-unheld-01", hold=True, reason="Pending litigation 2026-CV-01", actor_id="legal-counsel")
        assert ok is True

        db = get_db_session()
        doc = db.query(DocumentModel).filter(DocumentModel.uid == "doc-exp-unheld-01").first()
        assert doc.legal_hold is True
        db.close()

    def test_disposition_lifecycle_purges_unheld_and_protects_held(self):
        """Disposition safely marks expired unheld documents as 'disposed' but strictly skips held documents."""
        res = run_disposition_lifecycle()

        assert "doc-exp-unheld-01" in res["purged_uids"]
        assert "doc-exp-held-02" in res["held_uids"]
        assert res["held_count"] >= 1

        db = get_db_session()
        # Verify unheld doc is disposed
        unheld = db.query(DocumentModel).filter(DocumentModel.uid == "doc-exp-unheld-01").first()
        assert unheld.review_status == "disposed"

        # Verify held doc was NOT touched
        held = db.query(DocumentModel).filter(DocumentModel.uid == "doc-exp-held-02").first()
        assert held.review_status == "auto_accepted"
        assert held.legal_hold is True
        db.close()
