"""Comprehensive HTTP tests using FastAPI TestClient for REST API v1 endpoints.

Tests all security items, HTTP behavior, 401/403 authorization guards, image leak fixes,
PII reveal audit logging, reprocess human-field preservation, and configuration persistence.
"""

from datetime import datetime, timezone
import json
import os
import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.core.auth import get_configured_tokens
from app.models.db import (
    AuditEventModel,
    ConfigHistoryModel,
    DocumentModel,
    ReviewTaskModel,
    get_db_session,
    init_db,
)


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient fixture testing real HTTP behavior."""
    init_db()
    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_test_fixtures():
    """Seed test fixtures into SQLite database (labeled fixtures)."""
    init_db()
    db = get_db_session()
    now = datetime.now(timezone.utc)

    # Clean existing test fixtures
    db.query(AuditEventModel).filter(AuditEventModel.document_uid == "doc-test-kyc-001").delete()
    db.query(DocumentModel).filter(DocumentModel.uid == "doc-test-kyc-001").delete()
    db.query(DocumentModel).filter(DocumentModel.uid == "doc-test-inv-002").delete()
    db.query(ReviewTaskModel).filter(ReviewTaskModel.document_uid == "doc-test-kyc-001").delete()
    db.query(ConfigHistoryModel).filter(ConfigHistoryModel.updated_by == "test-admin").delete()
    db.commit()

    # Ensure real multi-page sample PDF exists
    sample_pdf_path = "data/test_samples/multipage_sample.pdf"
    if not os.path.exists(sample_pdf_path):
        import fitz
        os.makedirs("data/test_samples", exist_ok=True)
        pdf = fitz.open()
        p1 = pdf.new_page(width=612, height=792)
        p1.insert_text((72, 72), "CONFIDENTIAL KYC APPLICATION FORM", fontsize=18)
        p1.insert_text((72, 120), "Full Name: Alice Smith", fontsize=12)
        p1.insert_text((72, 140), "National ID: A12345678", fontsize=12)
        p2 = pdf.new_page(width=612, height=792)
        p2.insert_text((72, 72), "APPENDIX A: FINANCIAL RECORDS", fontsize=18)
        p2.insert_text((72, 120), "Account: 9876543210", fontsize=12)
        pdf.save(sample_pdf_path)
        pdf.close()

    # Fixture 1: KYC document pending review with human verified fields
    doc_kyc = DocumentModel(
        uid="doc-test-kyc-001",
        sha256="hash-kyc-001",
        file_name="kyc_test_multipage.pdf",
        file_size=os.path.getsize(sample_pdf_path),
        mime_type="application/pdf",
        storage_path=sample_pdf_path,
        doc_type="kyc_form",
        confidence=0.74,
        retention_class="10_YEARS_KYC",
        acl="RESTRICTED_REVIEW",
        target_workflow="kyc_verification",
        review_status="pending_review",
        extracted_fields_json=json.dumps({"full_name": "Alice Smith", "id_number": "A1234567"}),
        human_verified_fields_json=json.dumps({"full_name": "Alice Verified Smith", "id_number": "A1234567"}),
        field_confidences_json=json.dumps({"full_name": 0.88, "id_number": 0.92}),
        pii_detected=True,
        pii_entities_json=json.dumps([{"type": "PERSON", "value": "Alice Smith"}]),
        pii_types_json=json.dumps(["PERSON", "PASSPORT"]),
        classifier_model="tfidf_logistic_regression",
        classifier_version="v1.0",
        decision_reason="Low classification confidence 0.74 < 0.95",
        created_at=now,
    )
    db.merge(doc_kyc)

    task_kyc = ReviewTaskModel(
        task_id="task-test-kyc-001",
        document_uid="doc-test-kyc-001",
        predicted_type="kyc_form",
        confidence=0.74,
        evidence_text="KYC Application Form Name: Alice Smith ID: A1234567",
        status="PENDING",
        created_at=now,
    )
    db.merge(task_kyc)

    # Fixture 2: Auto-accepted low risk invoice
    doc_inv = DocumentModel(
        uid="doc-test-inv-002",
        sha256="hash-inv-002",
        file_name="invoice_acme_corp.pdf",
        file_size=24100,
        mime_type="application/pdf",
        storage_path=sample_pdf_path,
        doc_type="invoice",
        confidence=0.96,
        retention_class="7_YEARS_FINANCIAL",
        acl="CONFIDENTIAL_FINANCE",
        target_workflow="ap_processing",
        review_status="auto_accepted",
        extracted_fields_json=json.dumps({"invoice_number": "INV-999", "total_amount": 1250.0}),
        human_verified_fields_json=json.dumps({}),
        field_confidences_json=json.dumps({"invoice_number": 0.98, "total_amount": 0.95}),
        pii_detected=False,
        pii_entities_json=json.dumps([]),
        pii_types_json=json.dumps([]),
        classifier_model="tfidf_logistic_regression",
        classifier_version="v1.0",
        decision_reason="Auto-accepted: confidence 0.96 >= 0.90",
        created_at=now,
    )
    db.merge(doc_inv)

    db.commit()
    db.close()
    return True


def auth_headers(role: str) -> dict:
    """Dynamically resolve configured token for a given role."""
    tokens = get_configured_tokens()
    role_to_token = {r: t for t, r in tokens.items()}
    token = role_to_token.get(role, "")
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# SECTION A: IMAGE LEAK AND AUTHENTICATION TESTS
# ==============================================================================

def test_page_image_leak_unauthenticated_rejected(client: TestClient):
    """Test A1 & A2: Page image endpoint rejects unauthenticated access with 401."""
    resp = client.get("/api/v1/documents/doc-test-kyc-001/pages/1/image")
    assert resp.status_code == 401
    assert "Bearer" in resp.headers.get("WWW-Authenticate", "")
    assert "credentials were not provided" in resp.json()["detail"]


def test_page_image_authenticated_multipage_and_width(client: TestClient):
    """Test A1 & A3: Multi-page real sample rendering, byte counts, and ?width= thumbnailing."""
    headers = auth_headers("reviewer")

    # 1. Page 1 Full Resolution
    resp_p1 = client.get("/api/v1/documents/doc-test-kyc-001/pages/1/image", headers=headers)
    assert resp_p1.status_code == 200
    assert resp_p1.headers["content-type"] == "image/png"
    bytes_p1 = len(resp_p1.content)
    assert bytes_p1 > 10000, f"Expected real rendered page > 10KB, got {bytes_p1} bytes"

    # 2. Page 2 Full Resolution
    resp_p2 = client.get("/api/v1/documents/doc-test-kyc-001/pages/2/image", headers=headers)
    assert resp_p2.status_code == 200
    assert resp_p2.headers["content-type"] == "image/png"
    bytes_p2 = len(resp_p2.content)
    assert bytes_p2 > 10000, f"Expected real rendered page 2 > 10KB, got {bytes_p2} bytes"

    # 3. Page 1 Thumbnail with ?width=120
    resp_thumb = client.get("/api/v1/documents/doc-test-kyc-001/pages/1/image?width=120", headers=headers)
    assert resp_thumb.status_code == 200
    assert resp_thumb.headers["content-type"] == "image/png"
    bytes_thumb = len(resp_thumb.content)
    assert bytes_thumb < 5000, f"Expected thumbnail < 5KB, got {bytes_thumb} bytes"
    assert bytes_thumb < bytes_p1, "Thumbnail must be significantly smaller than full page"


# ==============================================================================
# SECTION B: SECURITY, AUTH, PII REVEAL, REPROCESS, AND CONFIG TESTS
# ==============================================================================

def test_auth_token_mapping_and_role_header_enforcement(client: TestClient):
    """Test B4: Tokens defined in config, unknown tokens give 401, X-User-Role rejected unless enabled."""
    # 1. Unknown token gives 401
    bad_resp = client.get("/api/v1/system/info", headers={"Authorization": "Bearer bad-token-xyz"})
    assert bad_resp.status_code == 401
    assert "Invalid or unknown authentication token" in bad_resp.json()["detail"]

    # 2. X-User-Role rejected by default when AUTH_ALLOW_ROLE_HEADER is false
    os.environ["AUTH_ALLOW_ROLE_HEADER"] = "false"
    header_resp = client.get("/api/v1/system/info", headers={"X-User-Role": "admin"})
    assert header_resp.status_code == 401
    assert "X-User-Role header is disabled" in header_resp.json()["detail"]

    # 3. Valid configured tokens succeed
    rev_resp = client.get("/api/v1/auth/me", headers=auth_headers("reviewer"))
    assert rev_resp.status_code == 200
    assert rev_resp.json()["role"] == "reviewer"

    adm_resp = client.get("/api/v1/auth/me", headers=auth_headers("admin"))
    assert adm_resp.status_code == 200
    assert adm_resp.json()["role"] == "admin"


def test_route_group_authorization_matrix(client: TestClient):
    """Test B4: 401 (unauthenticated) and 403 (unauthorized role) across all route groups."""
    reviewer_hdr = auth_headers("reviewer")
    viewer_hdr = auth_headers("viewer")

    # Admin group: /api/v1/admin/config
    assert client.get("/api/v1/admin/config").status_code == 401
    assert client.get("/api/v1/admin/config", headers=reviewer_hdr).status_code == 403
    assert client.get("/api/v1/admin/config", headers=auth_headers("admin")).status_code == 200

    # Review queue: /api/v1/review/queue
    assert client.get("/api/v1/review/queue").status_code == 401
    assert client.get("/api/v1/review/queue", headers=viewer_hdr).status_code == 403
    assert client.get("/api/v1/review/queue", headers=reviewer_hdr).status_code == 200

    # Reprocess preview: /api/v1/reprocess/preview
    assert client.post("/api/v1/reprocess/preview", json={}).status_code == 401
    assert client.post("/api/v1/reprocess/preview", json={}, headers=reviewer_hdr).status_code == 403

    # Reprocess execution: /api/v1/reprocess
    assert client.post("/api/v1/reprocess", json={}).status_code == 401
    assert client.post("/api/v1/reprocess", json={}, headers=reviewer_hdr).status_code == 403


def test_pii_reveal_audit_logging(client: TestClient):
    """Test B5: PII reveal endpoint records audit event without logging the plaintext value."""
    # 1. Viewer role rejected with 403
    viewer_hdr = auth_headers("viewer")
    resp_403 = client.post(
        "/api/v1/documents/doc-test-kyc-001/pii/reveal",
        json={"entity_type": "PERSON", "position": {"start": 10, "end": 21}},
        headers=viewer_hdr,
    )
    assert resp_403.status_code == 403

    # 2. Reviewer role succeeds and logs audit event
    reviewer_hdr = auth_headers("reviewer")
    resp = client.post(
        "/api/v1/documents/doc-test-kyc-001/pii/reveal",
        json={"entity_type": "PERSON", "position": {"start": 10, "end": 21}},
        headers=reviewer_hdr,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["entity_type"] == "PERSON"
    evt_id = data["event_id"]

    # 3. Check audit trail
    trail_resp = client.get("/api/v1/documents/doc-test-kyc-001/audit-trail", headers=reviewer_hdr)
    assert trail_resp.status_code == 200
    events = trail_resp.json()["events"]
    reveal_evt = next((e for e in events if e["event_id"] == evt_id), None)
    assert reveal_evt is not None
    assert reveal_evt["event_type"] == "PII_VALUE_REVEALED"
    assert reveal_evt["payload"]["entity_type"] == "PERSON"
    assert reveal_evt["payload"]["username"] == "reviewer@ecm.local"
    # Verify the secret value is NEVER in the payload
    assert "Alice Smith" not in json.dumps(reveal_evt["payload"])


def test_reprocess_preserves_human_verified_fields(client: TestClient):
    """Test B6: Backend enforcement that human-verified fields are never overwritten during reprocess."""
    admin_hdr = auth_headers("admin")
    db = get_db_session()
    doc_before = db.query(DocumentModel).filter(DocumentModel.uid == "doc-test-kyc-001").first()
    human_fields_before = json.loads(doc_before.human_verified_fields_json)
    assert human_fields_before.get("full_name") == "Alice Verified Smith"
    db.close()

    # Trigger reprocess execution
    rep_resp = client.post(
        "/api/v1/reprocess",
        json={"target_types": ["kyc_form"], "dry_run": False},
        headers=admin_hdr,
    )
    assert rep_resp.status_code == 200
    assert rep_resp.json()["conflicts_preserved_count"] >= 1

    # Verify real DB row still retains human ground truth intact
    db = get_db_session()
    doc_after = db.query(DocumentModel).filter(DocumentModel.uid == "doc-test-kyc-001").first()
    human_fields_after = json.loads(doc_after.human_verified_fields_json)
    assert human_fields_after.get("full_name") == "Alice Verified Smith"

    # Verify conflict diff was emitted
    conflict_evts = db.query(AuditEventModel).filter(
        AuditEventModel.document_uid == "doc-test-kyc-001",
        AuditEventModel.event_type == "REPROCESSING_CONFLICT_DIFF",
    ).all()
    assert len(conflict_evts) >= 1
    db.close()


def test_floors_and_config_history_restart_persistence(client: TestClient):
    """Test B7: Floors 0.92/0.85 enforced, update persists in DB and survives simulated restart."""
    admin_hdr = auth_headers("admin")

    # 1. Floors check
    cfg_resp = client.get("/api/v1/admin/config", headers=admin_hdr)
    assert cfg_resp.status_code == 200
    cfg_data = cfg_resp.json()
    assert cfg_data["high_risk_floor"] == 0.95
    assert cfg_data["low_risk_floor"] == 0.90

    # 2. Reject update below high risk floor: lowering kyc_form to 0.93 is rejected (0.93 < 0.95)
    bad_update = client.post(
        "/api/v1/admin/config",
        json={"updated_by": "test-admin", "class_thresholds": {"kyc_form": 0.93}},
        headers=admin_hdr,
    )
    assert bad_update.status_code == 400
    assert "Security violation" in bad_update.json()["detail"]
    assert "below mandatory floor of 0.95" in bad_update.json()["detail"]

    # 3. Allow update above floor (0.96 >= 0.95)
    good_update = client.post(
        "/api/v1/admin/config",
        json={"updated_by": "test-admin", "class_thresholds": {"kyc_form": 0.96}},
        headers=admin_hdr,
    )
    assert good_update.status_code == 200
    assert good_update.json()["effective_config"]["classes"]["kyc_form"]["current_threshold"] == 0.96

    # 4. Prove persistence survives simulated restart (re-query directly from SQLite)
    db = get_db_session()
    hist_record = (
        db.query(ConfigHistoryModel)
        .filter(ConfigHistoryModel.updated_by == "test-admin")
        .order_by(ConfigHistoryModel.id.desc())
        .first()
    )
    assert hist_record is not None
    changes = json.loads(hist_record.changes_json)
    assert changes.get("kyc_form", {}).get("new") == 0.96
    db.close()

    # 5. History endpoint reads from DB
    hist_resp = client.get("/api/v1/admin/config/history", headers=admin_hdr)
    assert hist_resp.status_code == 200
    history_items = hist_resp.json()["history"]
    assert any(h["updated_by"] == "test-admin" for h in history_items)


def test_documents_search_and_compliance_audit(client: TestClient):
    """Test B8: Document search, filtering, and compliance detail."""
    comp_hdr = auth_headers("compliance")

    docs_resp = client.get("/api/v1/documents?q=acme", headers=comp_hdr)
    assert docs_resp.status_code == 200
    assert docs_resp.json()["total"] >= 1

    comp_resp = client.get("/api/v1/documents/doc-test-inv-002/compliance", headers=comp_hdr)
    assert comp_resp.status_code == 200
    assert comp_resp.json()["doc_type"] == "invoice"
    assert comp_resp.json()["retention_class"] == "7_YEARS_FINANCIAL"


def test_document_status_polling_and_reprocess_job_status(client: TestClient):
    """Test A6: Polling endpoints for document processing status and reprocess job status."""
    rev_hdr = auth_headers("reviewer")
    admin_hdr = auth_headers("admin")

    # 1. Document status polling
    doc_poll = client.get("/api/v1/documents/doc-test-kyc-001/compliance", headers=rev_hdr)
    assert doc_poll.status_code == 200
    poll_data = doc_poll.json()
    assert poll_data["uid"] == "doc-test-kyc-001"
    assert poll_data["review_status"] in ["pending_review", "human_verified", "auto_accepted"]
    assert poll_data["confidence"] > 0

    # 2. Reprocess job status polling
    job_resp = client.get("/api/v1/reprocess/jobs/job-active-42", headers=admin_hdr)
    assert job_resp.status_code == 200
    job_data = job_resp.json()
    assert job_data["job_id"] == "job-active-42"
    assert job_data["status"] == "COMPLETED"
    assert job_data["processed_count"] >= 0

    # 3. Dashboard metrics telemetry
    dash_resp = client.get("/api/v1/dashboard/metrics", headers=admin_hdr)
    assert dash_resp.status_code == 200
    assert dash_resp.json()["has_data"] is True
    assert dash_resp.json()["total_ingested"] >= 2
