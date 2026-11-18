"""Contract tests asserting both FakeECM and NuxeoAdapter fulfill the ECMAdapter interface."""

import pytest
from app.adapters.ecm import FakeECM, NuxeoAdapter
from app.core.interfaces import ECMAdapter, ECMDocumentRecord


@pytest.fixture(params=[FakeECM, lambda: NuxeoAdapter(stub_mode=True)], ids=["FakeECM", "NuxeoAdapterStub"])
def ecm_adapter(request) -> ECMAdapter:
    """Fixture providing initialized ECM adapter instance."""
    inst = request.param()
    return inst


def test_contract_create_and_get_document(ecm_adapter: ECMAdapter):
    record = ECMDocumentRecord(
        ecm_id="",
        uid="contract-test-uid-001",
        sha256="contract_sha_001",
        doc_type="invoice",
        confidence=0.96,
        metadata={"file_name": "inv.pdf", "amount": 1200.0},
        retention_class="FINANCIAL_7_YEARS",
        acl="CONFIDENTIAL_FINANCE",
        target_workflow="AP_INVOICE_PROCESSING",
        review_status="auto_accepted",
    )

    created = ecm_adapter.create_document(record)
    assert created.ecm_id != ""

    fetched = ecm_adapter.get_document(created.ecm_id)
    assert fetched is not None
    assert fetched.doc_type == "invoice"
    assert fetched.confidence == 0.96
    assert fetched.retention_class == "FINANCIAL_7_YEARS"


def test_contract_find_by_hash(ecm_adapter: ECMAdapter):
    sha = "unique_hash_contract_999"
    record = ECMDocumentRecord(
        ecm_id="",
        uid="contract-uid-999",
        sha256=sha,
        doc_type="contract",
        confidence=0.94,
        metadata={"file_name": "contract.pdf"},
        retention_class="LEGAL_10_YEARS",
        acl="RESTRICTED_LEGAL",
        target_workflow="LEGAL_REVIEW",
        review_status="auto_accepted",
    )
    ecm_adapter.create_document(record)

    found = ecm_adapter.find_by_hash(sha)
    assert found is not None
    assert found.sha256 == sha
    assert found.doc_type == "contract"


def test_contract_create_link(ecm_adapter: ECMAdapter):
    target_rec = ECMDocumentRecord(
        ecm_id="target-ecm-01",
        uid="canonical-asset-100",
        sha256="canonical_hash_100",
        doc_type="bank_statement",
        confidence=0.97,
        retention_class="FINANCIAL_7_YEARS",
        acl="CONFIDENTIAL_FINANCE",
        target_workflow="TREASURY",
        review_status="auto_accepted",
        metadata={"file_name": "stmt.pdf"},
    )
    ecm_adapter.create_document(target_rec)

    new_duplicate_sha = "duplicate_hash_same_content"
    link = ecm_adapter.create_link(new_duplicate_sha, target_rec)
    assert link.is_link is True
    assert link.linked_to_id == target_rec.uid


def test_contract_update_metadata_human_verified(ecm_adapter: ECMAdapter):
    record = ECMDocumentRecord(
        ecm_id="",
        uid="contract-uid-human-01",
        sha256="sha_human_01",
        doc_type="unknown",
        confidence=0.62,
        retention_class="TEMP",
        acl="RESTRICTED_REVIEW",
        target_workflow="MANUAL_TRIAGE",
        review_status="pending_review",
    )
    created = ecm_adapter.create_document(record)

    updated = ecm_adapter.update_metadata(
        created.ecm_id,
        {"invoice_number": "INV-VERIFIED-100", "total_amount": 5000.0},
        human_verified=True,
    )
    assert updated.review_status == "human_verified"
    assert "invoice_number" in updated.human_verified_fields
