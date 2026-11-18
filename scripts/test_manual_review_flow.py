"""End-to-End manual verification of review UI and core workflows:
1. Upload clean invoice -> auto-accept with type, confidence, fields.
2. Upload blurry or unknown file -> lands in review queue.
3. Upload the same invoice twice -> links to first, not create a copy.
4. Correct one document in the review UI, then check that the field is marked human-verified.
5. Open any asset and confirm it shows the model name, version, and confidence.
"""

import json
import asyncio
from pathlib import Path
from starlette.requests import Request
from starlette.datastructures import FormData

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.routes_ingest import ingest_file_bytes
from app.api.routes_review import get_review_queue_page, get_document_review_detail, process_review_action
from app.adapters.ecm import get_ecm_adapter
from app.adapters.queue import get_queue_adapter
from app.core.config import get_pipeline_config
from app.models.db import DocumentModel, ReviewTaskModel, get_db_session, init_db
from app.workers.pipeline import process_document_payload
from data.synthetic_generator import render_scanned_pdf

def run_manual_check():
    print("=" * 80)
    print("MANUAL CHECK OF THE REVIEW UI & INGESTION FLOWS")
    print("=" * 80)
    init_db()
    cfg = get_pipeline_config()
    queue = get_queue_adapter()
    db = get_db_session()

    # --------------------------------------------------------------------------
    # 1. Upload one clean invoice. It should auto-accept with a type, confidence, and fields.
    # --------------------------------------------------------------------------
    print("\n--- 1. Upload Clean Invoice ---")
    invoice_text = (
        "============================================================\n"
        "                    COMMERCIAL INVOICE\n"
        "============================================================\n"
        "Vendor Name: Apex Global Logistics\n"
        "Vendor Tax ID (EIN): 12-3456789\n"
        "Billed To: Johnathan Doe\n"
        "Invoice Number: INV-20269999\n"
        "Invoice Date: 2026-03-15\n"
        "Payment Terms: Net 30\n\n"
        "DESCRIPTION OF CHARGES:\n"
        "Enterprise IT Implementation Services         $4500.00\n"
        "------------------------------------------------------------\n"
        "Balance Due: $4500.00\n"
        "Please remit payment within 30 days.\n"
    )
    invoice_pdf = render_scanned_pdf(invoice_text)
    ingest_res1 = ingest_file_bytes(invoice_pdf, "clean_invoice_01.pdf")
    print(f"Ingest Result: UID={ingest_res1.uid}, SHA256={ingest_res1.sha256[:16]}..., Status={ingest_res1.status}")
    
    # Process through pipeline
    item1 = queue.pop(cfg.queues.live_queue)[1]
    proc1 = process_document_payload(item1)
    uid1 = item1["uid"]
    
    db.expire_all()
    doc1 = db.query(DocumentModel).filter(DocumentModel.uid == uid1).first()
    print(f"Pipeline Process Status: {proc1.get('status')}")
    print(f"ECM Document State:      Type={doc1.doc_type}, Confidence={doc1.confidence:.4f}, ReviewStatus={doc1.review_status}")
    print(f"Extracted Fields:        {doc1.extracted_fields_json}")
    assert doc1.doc_type == "invoice", f"Expected invoice, got {doc1.doc_type}"
    assert doc1.confidence >= 0.90, f"Expected confidence >= 0.90, got {doc1.confidence}"
    assert doc1.review_status == "auto_accepted", f"Expected auto_accepted, got {doc1.review_status}"
    print("Verdict Step 1: PASS (Clean invoice auto-accepted with confidence & fields)")

    # --------------------------------------------------------------------------
    # 2. Upload a blurry or unknown file. It should land in the review queue.
    # --------------------------------------------------------------------------
    print("\n--- 2. Upload Blurry / Unknown File ---")
    unknown_text = (
        "DEPARTMENT OF BOTANICAL RESEARCH\n"
        "Photosynthesis laboratory notes for Phase 3\n"
        "Specimen: Arabidopsis thaliana\n"
        "Observations: Chlorophyll fluorescence steady at 450nm.\n"
    )
    unknown_pdf = render_scanned_pdf(unknown_text, degradation_type="blur")
    ingest_res2 = ingest_file_bytes(unknown_pdf, "botanical_notes.pdf")
    print(f"Ingest Result: UID={ingest_res2.uid}, Status={ingest_res2.status}")
    
    item2 = queue.pop(cfg.queues.live_queue)[1]
    proc2 = process_document_payload(item2)
    uid2 = item2["uid"]
    
    db.expire_all()
    doc2 = db.query(DocumentModel).filter(DocumentModel.uid == uid2).first()
    task2 = db.query(ReviewTaskModel).filter(ReviewTaskModel.document_uid == uid2).first()
    print(f"Pipeline Process Status: {proc2.get('status')}")
    print(f"ECM Document State:      Type={doc2.doc_type}, Confidence={doc2.confidence:.4f}, ReviewStatus={doc2.review_status}")
    print(f"Decision Reason:         {doc2.decision_reason}")
    print(f"Review Task in Queue:    Task ID={task2.task_id if task2 else None}, Status={task2.status if task2 else None}")
    assert doc2.review_status == "pending_review", f"Expected pending_review, got {doc2.review_status}"
    assert task2 is not None and task2.status == "PENDING", "Expected pending task in review queue"
    print("Verdict Step 2: PASS (Unknown file routed to review queue)")

    # --------------------------------------------------------------------------
    # 3. Upload the same invoice twice. The second should link to the first, not create a copy.
    # --------------------------------------------------------------------------
    print("\n--- 3. Upload Duplicate Invoice ---")
    ingest_res3 = ingest_file_bytes(invoice_pdf, "clean_invoice_01_duplicate.pdf")
    item3 = queue.pop(cfg.queues.live_queue)[1]
    proc3 = process_document_payload(item3)
    uid3 = item3["uid"]
    
    db.expire_all()
    doc3 = db.query(DocumentModel).filter(DocumentModel.uid == uid3).first()
    print(f"Pipeline Process Status: {proc3.get('status')}")
    print(f"Duplicate Linked UID:    {proc3.get('canonical_uid')}")
    print(f"Original Document UID:   {uid1}")
    assert proc3.get("status") == "DUPLICATE_LINKED", f"Expected DUPLICATE_LINKED, got {proc3.get('status')}"
    assert proc3.get("canonical_uid") == uid1, f"Expected canonical_uid={uid1}, got {proc3.get('canonical_uid')}"
    print("Verdict Step 3: PASS (Duplicate linked to original document, no copy created)")

    # --------------------------------------------------------------------------
    # 4. Correct one document in the review UI, then check that the field is marked human-verified.
    # --------------------------------------------------------------------------
    print("\n--- 4. Correct Document in Review UI ---")
    # A. Render Review Queue Page (GET /review)
    req_queue = Request({"type": "http"})
    res_queue = get_review_queue_page(req_queue)
    print(f"GET /review Page: Status={res_queue.status_code}, HTML length={len(res_queue.body)}")
    assert res_queue.status_code == 200
    assert f"task-{uid2}" in res_queue.body.decode()

    # B. Render Document Detail Review Panel (GET /review/{uid})
    res_detail = get_document_review_detail(uid2)
    print(f"GET /review/{uid2} Panel: Status={res_detail.status_code}")
    assert res_detail.status_code == 200

    # C. Submit Correction (POST /review/{uid}/action)
    class FakeFormRequest:
        async def form(self):
            return {
                "action": "CORRECT",
                "reviewer_id": "qa-lead-auditor",
                "corrected_type": "contract",
                "review_notes": "Re-classified from unknown to contract following clinical examination agreement review",
                "field_contract_id": "CNT-OVERRIDE-8888",
                "field_effective_date": "2026-03-20"
            }
            
    res_action = asyncio.run(process_review_action(uid2, FakeFormRequest()))
    print(f"POST /review/{uid2}/action: Status={res_action.status_code}")
    assert res_action.status_code == 200

    # Verify DB and ECM state
    db.expire_all()
    doc_after = db.query(DocumentModel).filter(DocumentModel.uid == uid2).first()
    print(f"Updated Review Status:   {doc_after.review_status}")
    print(f"Updated Doc Type:        {doc_after.doc_type}")
    print(f"Reviewer ID:             {doc_after.reviewer_id}")
    assert doc_after.review_status == "human_verified"
    assert doc_after.doc_type == "contract"

    ecm = get_ecm_adapter()
    ecm_rec = ecm.get(uid2)
    print(f"ECM Metadata Record:     human_verified={ecm_rec.metadata.get('human_verified')}")
    print(f"ECM Corrected Fields:    contract_id={ecm_rec.metadata.get('contract_id')}, effective_date={ecm_rec.metadata.get('effective_date')}")
    assert ecm_rec.metadata.get("human_verified") is True
    print("Verdict Step 4: PASS (Field corrected in review UI and marked human_verified in ECM)")

    # --------------------------------------------------------------------------
    # 5. Open any asset and confirm it shows the model name, version, and confidence.
    # --------------------------------------------------------------------------
    print("\n--- 5. Audit Trail Completeness Check ---")
    doc_audit = db.query(DocumentModel).filter(DocumentModel.uid == uid1).first()
    print(f"Inspecting Asset:        UID={doc_audit.uid}")
    print(f"Model Name:              {doc_audit.classifier_model}")
    print(f"Model Version:           {doc_audit.classifier_version}")
    print(f"Confidence:              {doc_audit.confidence:.4f}")
    print(f"Review Status:           {doc_audit.review_status}")
    print(f"OCR Engine / Version:    {doc_audit.ocr_engine} / {doc_audit.ocr_version}")
    assert doc_audit.classifier_model is not None and len(doc_audit.classifier_model) > 0
    assert doc_audit.classifier_version is not None and len(doc_audit.classifier_version) > 0
    assert doc_audit.confidence is not None and doc_audit.confidence > 0.0
    assert doc_audit.review_status is not None
    print("Verdict Step 5: PASS (Asset carries model name, version, confidence, and review status)")

    db.close()
    print("\n" + "=" * 80)
    print("MANUAL CHECK COMPLETE: ALL 5 STEPS VERIFIED & PASSED")
    print("=" * 80)

if __name__ == "__main__":
    run_manual_check()
