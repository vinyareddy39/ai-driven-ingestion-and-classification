"""HTMX Human Review Interface and Training Data Export API."""

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from app.adapters.ecm import get_ecm_adapter
from app.core.security import mask_string, setup_secure_logging
from app.models.db import DocumentModel, ReviewTaskModel, get_db_session

logger = setup_secure_logging("ecm.api.review")
router = APIRouter(prefix="/review", tags=["Review UI"])

# In-memory storage for exported human-verified training pairs
_human_verified_training_records: List[Dict[str, Any]] = []


@router.get("", response_class=HTMLResponse)
def get_review_queue_page(request: Request):
    """Render HTMX Review Queue UI."""
    db = get_db_session()
    try:
        tasks = (
            db.query(ReviewTaskModel)
            .filter(ReviewTaskModel.status == "PENDING")
            .order_by(ReviewTaskModel.created_at.desc())
            .all()
        )

        rows_html = ""
        for t in tasks:
            conf_percent = int(t.confidence * 100)
            rows_html += f"""
            <tr id="task-{t.document_uid}">
                <td><code>{t.task_id}</code></td>
                <td><strong>{t.predicted_type}</strong></td>
                <td>
                    <div style="background:#e0e0e0;border-radius:4px;width:100px;display:inline-block;">
                        <div style="background:{'#4CAF50' if conf_percent>=90 else '#FF9800'};width:{conf_percent}%;height:14px;border-radius:4px;"></div>
                    </div>
                    {conf_percent}%
                </td>
                <td>{t.created_at.strftime('%Y-%m-%d %H:%M:%S') if t.created_at else ''}</td>
                <td>
                    <button class="btn btn-sm btn-primary"
                            hx-get="/review/{t.document_uid}"
                            hx-target="#detail-view"
                            hx-swap="innerHTML">Review</button>
                </td>
            </tr>
            """

        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>ECM Document Ingestion - Human Review Desk</title>
            <script src="https://unpkg.com/htmx.org@1.9.10"></script>
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
            <style>
                body {{ background: #f8f9fa; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
                .card {{ border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.08); }}
                .evidence-box {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 12px; font-family: monospace; font-size: 0.9em; }}
            </style>
        </head>
        <body class="p-4">
            <div class="container-fluid">
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <h2>ECM Human Review & Verification Console</h2>
                    <div>
                        <a href="/review/export/training_data.jsonl" class="btn btn-outline-success">Export Training JSONL</a>
                        <a href="/metrics" class="btn btn-outline-secondary">Prometheus Metrics</a>
                    </div>
                </div>
                <div class="row">
                    <div class="col-md-7">
                        <div class="card p-3 mb-4">
                            <h5>Pending Triage Queue ({len(tasks)} items)</h5>
                            <table class="table table-hover align-middle">
                                <thead>
                                    <tr>
                                        <th>Task ID</th>
                                        <th>Predicted Class</th>
                                        <th>Confidence</th>
                                        <th>Received At</th>
                                        <th>Action</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {rows_html if rows_html else '<tr><td colspan="5" class="text-center text-muted">No pending review tasks! All documents auto-accepted.</td></tr>'}
                                </tbody>
                            </table>
                        </div>
                    </div>
                    <div class="col-md-5">
                        <div class="card p-3" id="detail-view">
                            <div class="text-muted text-center p-4">Select an item from the queue to inspect and verify.</div>
                        </div>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)
    finally:
        db.close()


@router.get("/{document_uid}", response_class=HTMLResponse)
def get_document_review_detail(document_uid: str):
    """Render HTMX document verification panel."""
    db = get_db_session()
    try:
        doc = db.query(DocumentModel).filter(DocumentModel.uid == document_uid).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        extracted_fields = json.loads(doc.extracted_fields_json or "{}")
        pii_types = json.loads(doc.pii_types_json or "[]")
        evidence = mask_string(doc.extracted_fields_json or "")

        fields_form_inputs = ""
        for k, v in extracted_fields.items():
            fields_form_inputs += f"""
            <div class="mb-2">
                <label class="form-label small text-muted">{k}</label>
                <input type="text" name="field_{k}" class="form-control form-control-sm" value="{v}">
            </div>
            """

        detail_html = f"""
        <h5>Document Review: <code>{doc.file_name}</code></h5>
        <div class="mb-3">
            <span class="badge bg-primary">{doc.doc_type}</span>
            <span class="badge bg-secondary">Confidence: {doc.confidence:.2f}</span>
            <span class="badge {'bg-danger' if doc.pii_detected else 'bg-success'}">PII: {', '.join(pii_types) if pii_types else 'None'}</span>
        </div>
        <div class="mb-3">
            <label class="fw-bold small">Reasoning / Conflict Note:</label>
            <div class="evidence-box">{doc.decision_reason or 'Confidence below threshold; required validation'}</div>
        </div>
        <form hx-post="/review/{document_uid}/action" hx-target="#detail-view" hx-swap="innerHTML">
            <div class="mb-3">
                <label class="form-label fw-bold small">Corrected Document Type:</label>
                <select name="corrected_type" class="form-select form-select-sm">
                    <option value="{doc.doc_type}" selected>Keep Current ({doc.doc_type})</option>
                    <option value="invoice">Invoice</option>
                    <option value="contract">Contract</option>
                    <option value="kyc_form">KYC Form</option>
                    <option value="bank_statement">Bank Statement</option>
                    <option value="medical_report">Medical Report</option>
                    <option value="purchase_order">Purchase Order</option>
                    <option value="letter">Letter</option>
                    <option value="claim_form">Claim Form</option>
                    <option value="unknown">Unknown</option>
                </select>
            </div>
            <div class="mb-3">
                <label class="form-label fw-bold small">Extracted Field Values (Editable):</label>
                {fields_form_inputs if fields_form_inputs else '<p class="small text-muted">No schema fields extracted.</p>'}
            </div>
            <div class="mb-3">
                <label class="form-label fw-bold small">Reviewer Notes:</label>
                <textarea name="review_notes" class="form-control form-control-sm" rows="2" placeholder="Audit justification..."></textarea>
            </div>
            <input type="hidden" name="reviewer_id" value="reviewer-senior-1">
            <div class="d-flex gap-2">
                <button type="submit" name="action" value="CONFIRM" class="btn btn-success flex-fill">Confirm & Accept</button>
                <button type="submit" name="action" value="CORRECT" class="btn btn-warning flex-fill">Submit Corrections</button>
                <button type="submit" name="action" value="REJECT" class="btn btn-outline-danger">Reject</button>
            </div>
        </form>
        """
        return HTMLResponse(content=detail_html)
    finally:
        db.close()


def apply_review_decision(
    document_uid: str,
    action: str = "CONFIRM",
    reviewer_id: str = "reviewer-qa",
    corrected_type: Optional[str] = None,
    review_notes: str = "",
    corrected_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute review action (CONFIRM, CORRECT, REJECT) transactionally."""
    if corrected_fields is None:
        corrected_fields = {}

    db = get_db_session()
    try:
        doc = db.query(DocumentModel).filter(DocumentModel.uid == document_uid).first()
        task = db.query(ReviewTaskModel).filter(ReviewTaskModel.document_uid == document_uid).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        final_type = corrected_type if (action == "CORRECT" and corrected_type) else doc.doc_type
        doc.doc_type = final_type
        doc.reviewer_id = reviewer_id
        doc.review_notes = review_notes

        if action in ["CONFIRM", "CORRECT"]:
            doc.review_status = "human_verified"
            # Update human verified fields in FakeECM / Nuxeo
            ecm = get_ecm_adapter()
            ecm.update_metadata(doc.uid, corrected_fields, human_verified=True)
            if task:
                task.status = "COMPLETED"
                task.completed_at = datetime.now(timezone.utc)

            # Record training pair for model fine-tuning export
            _human_verified_training_records.append(
                {
                    "uid": doc.uid,
                    "sha256": doc.sha256,
                    "verified_type": final_type,
                    "verified_fields": corrected_fields,
                    "reviewer": reviewer_id,
                    "verified_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            logger.info(f"Human review committed for {doc.uid}: action={action}, verified_type={final_type}")
        else:
            doc.review_status = "rejected"
            if task:
                task.status = "REJECTED"
                task.completed_at = datetime.now(timezone.utc)

        db.commit()
        return {
            "status": "SUCCESS",
            "document_uid": document_uid,
            "action": action,
            "review_status": doc.review_status,
            "final_type": final_type,
        }
    finally:
        db.close()


@router.post("/{document_uid}/action", response_class=HTMLResponse)
async def process_review_action(document_uid: str, request: Request):
    """Process human confirmation or correction."""
    form_data = await request.form()
    action = form_data.get("action", "CONFIRM")
    reviewer_id = form_data.get("reviewer_id", "reviewer-qa")
    corrected_type = form_data.get("corrected_type")
    review_notes = form_data.get("review_notes", "")

    # Extract field corrections from form
    corrected_fields = {}
    for k, v in form_data.items():
        if k.startswith("field_"):
            field_name = k.replace("field_", "")
            corrected_fields[field_name] = v

    result = apply_review_decision(
        document_uid=document_uid,
        action=action,
        reviewer_id=reviewer_id,
        corrected_type=corrected_type,
        review_notes=review_notes,
        corrected_fields=corrected_fields,
    )

    return HTMLResponse(
        f"""
        <div class="alert alert-success">
            <h6>Document {document_uid[:8]} Updated!</h6>
            <p class="small mb-1">Action: <strong>{action}</strong> | Status: <strong>{result['review_status']}</strong></p>
            <p class="small text-muted mb-0">Changes saved to ECM as immutable human-verified metadata.</p>
        </div>
        """
    )


@router.get("/export/training_data.jsonl", response_class=PlainTextResponse)
def export_verified_training_jsonl():
    """Export human-verified corrections as labeled JSONL training data."""
    lines = [json.dumps(r) for r in _human_verified_training_records]
    return PlainTextResponse(content="\n".join(lines), media_type="application/jsonl")


@router.get("/api/tasks")
def get_review_tasks_json():
    """Return pending review tasks in JSON for the frontend."""
    db = get_db_session()
    try:
        tasks = (
            db.query(ReviewTaskModel)
            .filter(ReviewTaskModel.status == "PENDING")
            .order_by(ReviewTaskModel.created_at.desc())
            .all()
        )
        result = []
        for t in tasks:
            doc = db.query(DocumentModel).filter(DocumentModel.uid == t.document_uid).first()
            pii_types = json.loads(doc.pii_types_json or "[]") if doc else []
            pii_detected = doc.pii_detected if doc else False
            file_name = doc.file_name if doc else "document.pdf"
            decision_reason = doc.decision_reason if doc else ""

            result.append({
                "task_id": t.task_id,
                "document_uid": t.document_uid,
                "file_name": file_name,
                "predicted_type": t.predicted_type,
                "confidence": t.confidence,
                "pii_detected": pii_detected,
                "pii_types": pii_types,
                "decision_reason": decision_reason,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "status": t.status,
            })
        return result
    finally:
        db.close()


@router.get("/api/task/{document_uid}")
def get_review_task_detail_json(document_uid: str):
    """Return single review task detail in JSON for the frontend."""
    db = get_db_session()
    try:
        doc = db.query(DocumentModel).filter(DocumentModel.uid == document_uid).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        task = db.query(ReviewTaskModel).filter(ReviewTaskModel.document_uid == document_uid).first()

        extracted_fields = json.loads(doc.extracted_fields_json or "{}")
        field_confidences = json.loads(doc.field_confidences_json or "{}")
        pii_types = json.loads(doc.pii_types_json or "[]")
        pii_entities = json.loads(doc.pii_entities_json or "[]")

        return {
            "document_uid": doc.uid,
            "task_id": task.task_id if task else None,
            "file_name": doc.file_name,
            "sha256": doc.sha256,
            "doc_type": doc.doc_type,
            "confidence": doc.confidence,
            "review_status": doc.review_status,
            "retention_class": doc.retention_class,
            "acl": doc.acl,
            "decision_reason": doc.decision_reason,
            "pii_detected": doc.pii_detected,
            "pii_types": pii_types,
            "pii_entities": pii_entities,
            "extracted_fields": extracted_fields,
            "field_confidences": field_confidences,
            "evidence_text": task.evidence_text if task else "",
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        }
    finally:
        db.close()


@router.post("/api/task/{document_uid}/action")
def process_review_action_json(document_uid: str, payload: Dict[str, Any]):
    """Execute review action (CONFIRM, CORRECT, REJECT) via JSON payload."""
    action = payload.get("action", "CONFIRM")
    reviewer_id = payload.get("reviewer_id", "reviewer-qa")
    corrected_type = payload.get("corrected_type")
    review_notes = payload.get("review_notes", "")
    corrected_fields = payload.get("corrected_fields", {})

    result = apply_review_decision(
        document_uid=document_uid,
        action=action,
        reviewer_id=reviewer_id,
        corrected_type=corrected_type,
        review_notes=review_notes,
        corrected_fields=corrected_fields,
    )
    return result

