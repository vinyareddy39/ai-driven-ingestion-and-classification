"""End-to-end integration tests validating full document ingestion lifecycle."""

import hashlib
from pathlib import Path
import pytest
from app.adapters.ecm import get_ecm_adapter
from app.adapters.storage import get_storage_adapter
from app.models.db import DocumentModel, ReviewTaskModel, get_db_session
from app.workers.pipeline import process_document_payload

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "dataset"
TRAIN_DIR = DATA_DIR / "train"
SPECIAL_DIR = DATA_DIR / "special"


def test_full_flow_ingest_to_searchable_document():
    """Ingest a valid invoice through full pipeline: OCR -> Classify -> Fields -> PII -> Gate -> ECM -> Search."""
    import uuid
    from data.synthetic_generator import generate_invoice_content, render_pdf_document

    text, fields, pii = generate_invoice_content(99999)
    # Ensure fresh unique content
    text += f"\nUnique Processing Code: {uuid.uuid4().hex}"
    data = render_pdf_document(text)

    sha = hashlib.sha256(data).hexdigest()
    storage = get_storage_adapter()
    storage.save(sha, data)

    uid = f"integ-test-{sha[:10]}"
    payload = {
        "uid": uid,
        "sha256": sha,
        "file_name": "invoice_integ_unique.pdf",
        "storage_path": f"storage/{sha}",
        "is_reprocess": False,
    }

    result = process_document_payload(payload)
    assert result["status"] == "SUCCESS"
    assert result["decision"]["action"] in ["AUTO_ACCEPT", "ROUTE_TO_REVIEW"]

    # Assert document is recorded in ECM
    ecm = get_ecm_adapter()
    doc_record = ecm.get_document(uid)
    assert doc_record is not None
    assert doc_record.doc_type == "invoice"
    assert doc_record.retention_class == "FINANCIAL_7_YEARS"
    assert "invoice_number" in doc_record.metadata["extracted_fields"]

    # Assert 100% mandatory audit attributes are present
    audit = result["audit"]
    assert audit["ocrEngine"] != ""
    assert audit["ocrVersion"] != ""
    assert audit["classifierModel"] != ""
    assert audit["classifierVersion"] != ""
    assert audit["predictedType"] == "invoice"
    assert audit["reviewStatus"] != ""
    assert audit["processedAt"] != ""


def test_duplicate_creates_link_not_copy():
    """Assert duplicate file ingest creates lightweight reference link instead of copying asset."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        fitz.Point(50, 80),
        "MASTER CONTRACT AGREEMENT\nContract ID: CNT-DUPE-TEST-001\nParty One: Alpha Corp\nParty Two: Beta Corp",
    )
    data = doc.tobytes()
    doc.close()

    sha = hashlib.sha256(data).hexdigest()
    storage = get_storage_adapter()
    storage.save(sha, data)

    # 1. Process canonical document
    canonical_uid = f"canonical-{sha[:10]}"
    p1 = {
        "uid": canonical_uid,
        "sha256": sha,
        "file_name": "contract_original.pdf",
        "storage_path": f"storage/{sha}",
        "is_reprocess": False,
    }
    r1 = process_document_payload(p1)
    assert r1["status"] == "SUCCESS"

    # 2. Ingest duplicate file
    duplicate_uid = f"duplicate-{sha[:10]}"
    p2 = {
        "uid": duplicate_uid,
        "sha256": sha,
        "file_name": "contract_duplicate.pdf",
        "storage_path": f"storage/{sha}",
        "is_reprocess": False,
    }
    r2 = process_document_payload(p2)
    assert r2["status"] == "DUPLICATE_LINKED"
    assert r2["is_link"] is True
    assert r2["canonical_uid"] == canonical_uid


def test_corrupt_and_password_protected_files_quarantined():
    """Assert corrupted and password-protected files are quarantined with alert notification."""
    # Corrupt test
    corrupt_path = SPECIAL_DIR / "special_corrupt.pdf"
    with open(corrupt_path, "rb") as f:
        data = f.read()
    sha_c = hashlib.sha256(data).hexdigest()
    get_storage_adapter().save(sha_c, data)

    # Clean previous record if exists in test DB copy
    db = get_db_session()
    db.query(DocumentModel).filter(DocumentModel.sha256 == sha_c).delete()
    db.commit()
    db.close()

    p_corrupt = {
        "uid": f"corrupt-{sha_c[:8]}",
        "sha256": sha_c,
        "file_name": "special_corrupt.pdf",
        "storage_path": f"storage/{sha_c}",
        "is_reprocess": False,
    }
    res_c = process_document_payload(p_corrupt)
    assert res_c["status"] == "QUARANTINED"
    assert "Corrupt" in res_c["reason"]

    # Password-protected test
    pwd_path = SPECIAL_DIR / "special_password_protected.pdf"
    with open(pwd_path, "rb") as f:
        pwd_data = f.read()
    sha_p = hashlib.sha256(pwd_data).hexdigest()
    get_storage_adapter().save(sha_p, pwd_data)

    db = get_db_session()
    db.query(DocumentModel).filter(DocumentModel.sha256 == sha_p).delete()
    db.commit()
    db.close()

    p_pwd = {
        "uid": f"pwd-{sha_p[:8]}",
        "sha256": sha_p,
        "file_name": "special_password_protected.pdf",
        "storage_path": f"storage/{sha_p}",
        "is_reprocess": False,
    }
    res_p = process_document_payload(p_pwd)
    assert res_p["status"] == "QUARANTINED"
    assert "password-protected" in res_p["reason"]


def test_conflict_routes_to_review_with_stricter_acl():
    """Assert classifier/PII conflict routes to review queue with RESTRICTED_REVIEW ACL."""
    import uuid
    from data.synthetic_generator import render_pdf_document

    conflict_text = f"""
============================================================
              FORMAL LETTER OF CORRESPONDENCE
============================================================
From: Corporate Communications Division, Global Enterprise Inc.
To: Valued Stakeholder Johnathan Doe
Date: 2026-03-01
Subject: Formal Stakeholder Letter Regarding Annual Corporate Policies

Dear Valued Stakeholder,

We are writing to officially provide you with this formal letter of correspondence
regarding our updated annual enterprise policies and shareholder governance guidelines.

Please review the attached terms and keep this letter for your correspondence records.
For identity verification under corporate compliance requirements:
Primary SSN on Record: 987-65-4321
Passport Identifier: P88776655
Medical License Reference: MD-445566
Unique Tracking Code: {uuid.uuid4().hex}

Should you have any questions regarding this correspondence, please reply to this letter.

Sincerely,
Corporate Secretarial Office
Global Enterprise Inc.
"""
    data = render_pdf_document(conflict_text)
    sha = hashlib.sha256(data).hexdigest()
    get_storage_adapter().save(sha, data)

    p = {
        "uid": f"conflict-{sha[:8]}",
        "sha256": sha,
        "file_name": "special_conflict_unique.pdf",
        "storage_path": f"storage/{sha}",
        "is_reprocess": False,
    }
    res = process_document_payload(p)
    assert res["status"] == "SUCCESS"
    decision = res["decision"]
    assert decision["action"] == "ROUTE_TO_REVIEW"
    assert decision["acl"] == "RESTRICTED_REVIEW"
    assert "Conflict" in decision["reason"]


def test_unknown_routes_to_review():
    """Assert document classified as unknown is never auto-accepted and routes to review."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        fitz.Point(50, 80),
        "MISCELLANEOUS EXPERIMENTAL NOTES\nUnstructured random text without any standard transactional layout.\nExperimental poetry and cooking recipes.",
    )
    data = doc.tobytes()
    doc.close()

    sha = hashlib.sha256(data).hexdigest()
    get_storage_adapter().save(sha, data)

    p = {
        "uid": f"unknown-{sha[:8]}",
        "sha256": sha,
        "file_name": "unknown_unique.pdf",
        "storage_path": f"storage/{sha}",
        "is_reprocess": False,
    }
    res = process_document_payload(p)
    assert res["status"] == "SUCCESS"
    assert res["decision"]["action"] == "ROUTE_TO_REVIEW"
    assert res["decision"]["review_status"] == "pending_review"
