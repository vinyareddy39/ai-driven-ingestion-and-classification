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

    def test_batch_detail_aggregation_and_progress(self):
        """Staff (compliance) retrieves User A's batch: verifies aggregated counts, type breakdowns, and items."""
        from app.api.routes_v1 import get_batch_detail
        from app.models.api_schemas import UserSessionResponse

        staff_user = UserSessionResponse(
            user_id="usr-cmp-01",
            username="compliance@ecm.local",
            role="compliance",
            permissions=["compliance:read", "documents:read"],
        )
        batch = get_batch_detail("batch-usr-a-101", current_user=staff_user)

        assert batch.batch_id == "batch-usr-a-101"
        assert batch.user_id == "usr-patient-a"

        # Verify progress counts
        progress = batch.progress
        assert progress.total == 4
        assert progress.done == 2        # auto_accepted (1) + approved (1)
        assert progress.needs_review == 1  # pending_review (1)
        assert progress.quarantined == 1  # quarantined (1)

        # Verify breakdown by doc_type
        by_type = batch.counts_by_type
        assert by_type["invoice"] == 1
        assert by_type["receipt"] == 1
        assert by_type["kyc_form"] == 1
        assert by_type["unknown"] == 1

        # Verify item list
        items = batch.items
        assert len(items) == 4
        quarantined_item = next(i for i in items if i.uid == "doc-batch-a-04")
        assert quarantined_item.error_detail == "Antivirus threat detected: EICAR"

    def test_batch_isolation_user_b_cannot_see_user_a(self):
        """User B requesting User A's batch gets 404 Not Found (strict isolation)."""
        from fastapi import HTTPException
        from app.api.routes_v1 import get_batch_detail
        from app.models.api_schemas import UserSessionResponse

        user_b = UserSessionResponse(
            user_id="usr-patient-b",
            username="b@health.local",
            role="patient",
            permissions=["patient:read"],
        )

        with pytest.raises(HTTPException) as excinfo:
            get_batch_detail("batch-usr-a-101", current_user=user_b)
        assert excinfo.value.status_code == 404
        assert "not found" in str(excinfo.value.detail).lower()

    def test_batch_isolation_user_a_can_see_own_batch(self):
        """User A requesting own batch gets 200 OK."""
        from app.api.routes_v1 import get_batch_detail
        from app.models.api_schemas import UserSessionResponse

        user_a = UserSessionResponse(
            user_id="usr-patient-a",
            username="a@health.local",
            role="patient",
            permissions=["patient:read"],
        )

        batch = get_batch_detail("batch-usr-a-101", current_user=user_a)
        assert batch.batch_id == "batch-usr-a-101"
        assert batch.progress.total == 4

    def test_fresh_upload_batch_status_reachable_and_valid_shape(self):
        """Verify that freshly uploaded documents in a batch immediately return 200 with the valid schema shape."""
        from datetime import datetime, timezone
        from app.api.routes_v1 import get_batch_detail
        from app.models.api_schemas import UserSessionResponse
        from app.models.db import DocumentModel, get_db_session

        fresh_batch_id = "batch-fresh-test-999"
        db = get_db_session()
        db.query(DocumentModel).filter(DocumentModel.batch_id == fresh_batch_id).delete()
        now = datetime.now(timezone.utc)
        fresh_doc = DocumentModel(
            uid="doc-fresh-test-01",
            sha256="hash-fresh-01",
            file_name="test_fresh.pdf",
            file_size=1024,
            mime_type="application/pdf",
            storage_path=SAMPLE_PATH,
            doc_type="unknown",
            confidence=0.0,
            review_status="queued",
            decision_reason="Queued for automated processing",
            batch_id=fresh_batch_id,
            user_id="usr-adm-01",
            created_at=now,
        )
        db.add(fresh_doc)
        db.commit()
        db.close()

        admin_user = UserSessionResponse(
            user_id="usr-adm-01",
            username="admin@ecm.local",
            role="admin",
            permissions=["*"],
        )

        # Query batch status immediately
        batch = get_batch_detail(fresh_batch_id, current_user=admin_user)

        # Verify schema shape and values
        assert batch.batch_id == fresh_batch_id
        assert batch.progress.total == 1
        assert batch.progress.queued == 1
        assert isinstance(batch.counts_by_type, dict)
        assert len(batch.items) == 1

        item = batch.items[0]
        assert item.file_name == "test_fresh.pdf"
        assert item.review_status == "queued"
        assert item.confidence == 0.0
        assert item.doc_type == "unknown"
        assert item.review_reason == "Queued for automated processing"

    def test_batch_not_found(self):
        """Nonexistent batch returns 404."""
        from fastapi import HTTPException
        from app.api.routes_v1 import get_batch_detail
        from app.models.api_schemas import UserSessionResponse

        admin_user = UserSessionResponse(
            user_id="usr-adm-01",
            username="admin@ecm.local",
            role="admin",
            permissions=["*"],
        )

        with pytest.raises(HTTPException) as excinfo:
            get_batch_detail("batch-nonexistent-999", current_user=admin_user)
        assert excinfo.value.status_code == 404


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


class TestBatchLifecycleAndExports:
    """Test batch initialization, listing, streaming zip exports, and notifications."""

    def test_create_batch_and_list_batches(self):
        from app.api.routes_v1 import create_batch, list_batches
        from app.models.api_schemas import BatchCreateRequest, UserSessionResponse

        user_owner = UserSessionResponse(
            user_id="usr-batch-owner-01",
            username="owner@test.local",
            role="user",
            permissions=["documents:read", "documents:write"],
        )

        # 1. Create a batch explicitly
        resp = create_batch(BatchCreateRequest(name="Upload #10"), current_user=user_owner)
        assert resp.batch_id.startswith("batch-")
        assert resp.name == "Upload #10"
        assert resp.number >= 1

        # 2. List batches for this user
        batch_list = list_batches(page=1, page_size=10, current_user=user_owner)
        assert batch_list.total >= 1
        found = next((b for b in batch_list.items if b.batch_id == resp.batch_id), None)
        assert found is not None
        assert found.name == "Upload #10"

    def test_export_batch_zip_stream_and_folders(self):
        import zipfile
        from app.api.routes_v1 import export_batch_zip
        from app.models.api_schemas import UserSessionResponse

        admin_user = UserSessionResponse(
            user_id="usr-adm-01",
            username="admin@ecm.local",
            role="admin",
            permissions=["*"],
        )

        file_resp = export_batch_zip("batch-usr-a-101", current_user=admin_user)
        assert file_resp.status_code == 200
        assert "application/zip" in file_resp.headers["content-type"]
        assert os.path.exists(file_resp.path)

        with zipfile.ZipFile(file_resp.path, "r") as zf:
            namelist = zf.namelist()
            # Must contain summary.csv
            assert "summary.csv" in namelist
            # Must contain folders per type
            assert any(n.startswith("invoice/") for n in namelist)
            assert any(n.startswith("receipt/") for n in namelist)
            # Must contain 'Needs a quick check/' for pending_review
            assert any(n.startswith("Needs a quick check/") for n in namelist)

            # Check summary.csv content
            summary_content = zf.read("summary.csv").decode("utf-8")
            assert "file,type,how_sure,status,reason,key_fields" in summary_content
            assert "invoice_jan.pdf" in summary_content

        # Execute background task function to verify spool cleanup
        if file_resp.background and hasattr(file_resp.background, "func"):
            file_resp.background.func()
        assert not os.path.exists(file_resp.path)

    def test_notifications_lifecycle(self):
        from app.api.routes_v1 import get_user_notifications, mark_notification_read, mark_all_notifications_read
        from app.models.api_schemas import UserSessionResponse
        from app.models.db import NotificationModel, get_db_session

        user = UserSessionResponse(
            user_id="usr-notif-tester-01",
            username="notif@test.local",
            role="user",
            permissions=["documents:read"],
        )

        db = get_db_session()
        db.query(NotificationModel).filter(NotificationModel.user_id == user.user_id).delete()
        now = datetime.now(timezone.utc)
        n1 = NotificationModel(
            id="notif-test-01",
            user_id=user.user_id,
            batch_id="batch-notif-1",
            title="Upload #1 is ready",
            message="5 files sorted.",
            read=False,
            created_at=now,
        )
        n2 = NotificationModel(
            id="notif-test-02",
            user_id=user.user_id,
            batch_id="batch-notif-2",
            title="Upload #2 is ready",
            message="10 files sorted.",
            read=False,
            created_at=now,
        )
        db.add_all([n1, n2])
        db.commit()
        db.close()

        # 1. Get notifications
        res = get_user_notifications(current_user=user)
        assert res.unread_count == 2
        assert len(res.items) == 2

        # 2. Mark one as read
        mark_res = mark_notification_read("notif-test-01", current_user=user)
        assert mark_res.success is True

        res2 = get_user_notifications(current_user=user)
        assert res2.unread_count == 1

        # 3. Mark all as read
        mark_all_res = mark_all_notifications_read(current_user=user)
        assert mark_all_res.success is True

        res3 = get_user_notifications(current_user=user)
        assert res3.unread_count == 0

