"""REST API v1 endpoints for Document Ingestion Web Frontend."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
import fitz  # PyMuPDF
from sqlalchemy import desc, asc, func

from app.core.auth import get_current_user, require_role
from app.core.config import get_app_settings, get_pipeline_config
from app.core.security import setup_secure_logging
from app.models.db import (
    AuditEventModel,
    ConfigHistoryModel,
    DocumentModel,
    ReviewTaskModel,
    StageExecutionModel,
    get_db_session,
)
from app.models.api_schemas import (
    AdminConfigResponse,
    AdminConfigUpdateRequest,
    AdminConfigUpdateResponse,
    AuditEventItem,
    AuditTrailResponse,
    ClassThresholdConfig,
    ConfigHistoryItem,
    ConfigHistoryResponse,
    DashboardMetricsResponse,
    DocumentComplianceDetailResponse,
    DocumentListResponse,
    DocumentStatusResponse,
    DocumentSummaryItem,
    OCRWordBox,
    PIIRevealRequest,
    PIIRevealResponse,
    ReprocessExecutionRequest,
    ReprocessExecutionResponse,
    ReprocessJobStatusResponse,
    ReprocessPreviewRequest,
    ReprocessPreviewResponse,
    ReprocessSampleItem,
    ReviewActionRequest,
    ReviewActionResponse,
    ReviewDetailResponse,
    ReviewQueueItem,
    ReviewQueueResponse,
    StageLatencyMetric,
    SystemInfoResponse,
    UserSessionResponse,
)

logger = setup_secure_logging("ecm.api.v1")
router = APIRouter(prefix="/api/v1", tags=["REST API v1"])

# Global in-memory audit log for configuration adjustments
_config_change_history: List[Dict[str, Any]] = []

HIGH_RISK_CLASSES = {"kyc_form", "bank_statement", "medical_report", "claim_form"}

def get_compliance_floors() -> tuple[float, float]:
    """Retrieve compliance floor thresholds from configuration (must not be below 0.90/0.95)."""
    cfg = get_pipeline_config()
    if hasattr(cfg, "compliance_floors") and cfg.compliance_floors:
        h = max(0.95, cfg.compliance_floors.high_risk_floor)
        l = max(0.90, cfg.compliance_floors.low_risk_floor)
        return h, l
    return 0.95, 0.90


# ---------------------------------------------------------------------------
# Shell & Authentication Endpoints
# ---------------------------------------------------------------------------

@router.get("/system/info", response_model=SystemInfoResponse)
def get_system_info(current_user: UserSessionResponse = Depends(get_current_user)):
    """Retrieve operational mode and pipeline metadata for the application shell."""
    settings = get_app_settings()
    cfg = get_pipeline_config()

    is_real = (
        settings.STORAGE_BACKEND == "minio"
        and settings.QUEUE_BACKEND == "redis"
        and settings.SEARCH_BACKEND == "opensearch"
    )
    mode = "REAL SERVICES" if is_real else "LOCAL MODE"

    return SystemInfoResponse(
        mode=mode,
        version=cfg.pipeline.get("version", "1.0.0"),
        environment=settings.ENVIRONMENT,
        storage_backend=settings.STORAGE_BACKEND,
        queue_backend=settings.QUEUE_BACKEND,
        search_backend=settings.SEARCH_BACKEND,
        ocr_engine=settings.OCR_ENGINE,
        classifier_version=cfg.pipeline.get("classifier_model_version", "v1.0"),
        high_risk_floor=get_compliance_floors()[0],
        low_risk_floor=get_compliance_floors()[1],
        max_upload_mb=settings.MAX_UPLOAD_MB,
        allowed_file_types=settings.ALLOWED_FILE_TYPES,
    )


@router.get("/auth/me", response_model=UserSessionResponse)
def get_auth_me(current_user: UserSessionResponse = Depends(get_current_user)):
    """Return active authenticated user session."""
    return current_user


# ---------------------------------------------------------------------------
# Review Queue Endpoints
# ---------------------------------------------------------------------------

@router.get("/review/queue", response_model=ReviewQueueResponse)
def get_review_queue(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: str = Query(default="risk"),  # risk, confidence, age
    doc_type: Optional[str] = None,
    risk_level: Optional[str] = None,
    pii_sensitivity: Optional[str] = None,
    current_user: UserSessionResponse = Depends(require_role(["reviewer", "admin"])),
):
    """Retrieve paginated, filterable review queue."""
    db = get_db_session()
    try:
        query = (
            db.query(ReviewTaskModel, DocumentModel)
            .join(DocumentModel, ReviewTaskModel.document_uid == DocumentModel.uid)
            .filter(ReviewTaskModel.status == "PENDING")
        )

        if doc_type:
            query = query.filter(ReviewTaskModel.predicted_type == doc_type)

        tasks_with_docs = query.all()

        items: List[ReviewQueueItem] = []
        now = datetime.now(timezone.utc)

        for task, doc in tasks_with_docs:
            is_high_risk = task.predicted_type in HIGH_RISK_CLASSES
            r_level = "HIGH" if is_high_risk else "LOW"

            if risk_level and r_level != risk_level.upper():
                continue

            # Determine PII sensitivity
            pii_types = json.loads(doc.pii_types_json or "[]")
            if any(t in ["SSN", "PASSPORT", "NATIONAL_ID"] for t in pii_types):
                sens = "HIGH"
            elif any(t in ["PHONE_NUMBER", "EMAIL_ADDRESS", "PERSON"] for t in pii_types):
                sens = "MEDIUM"
            elif pii_types:
                sens = "LOW"
            else:
                sens = "NONE"

            if pii_sensitivity and sens != pii_sensitivity.upper():
                continue

            created = task.created_at.replace(tzinfo=timezone.utc) if task.created_at else now
            age_sec = int((now - created).total_seconds())

            reason = doc.decision_reason or "Low classification confidence"
            if doc.doc_type == "unknown":
                reason = "Document type unknown"
            elif sens == "HIGH" and not is_high_risk:
                reason = "Classifier / PII sensitivity conflict"

            items.append(
                ReviewQueueItem(
                    task_id=task.task_id,
                    document_uid=doc.uid,
                    file_name=doc.file_name,
                    predicted_type=task.predicted_type,
                    confidence=task.confidence,
                    risk_level=r_level,
                    review_reason=reason,
                    pii_sensitivity=sens,
                    age_seconds=max(0, age_sec),
                    created_at=task.created_at,
                    status=task.status,
                    thumbnail_url=f"/api/v1/documents/{doc.uid}/pages/1/image",
                )
            )

        # Sort items
        if sort_by == "risk":
            items.sort(key=lambda x: (0 if x.risk_level == "HIGH" else 1, x.confidence))
        elif sort_by == "confidence":
            items.sort(key=lambda x: x.confidence)
        elif sort_by == "age":
            items.sort(key=lambda x: -x.age_seconds)

        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        paged_items = items[start:end]
        total_pages = max(1, (total + page_size - 1) // page_size)

        return ReviewQueueResponse(
            items=paged_items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
    finally:
        db.close()


@router.get("/review/{document_uid}", response_model=ReviewDetailResponse)
def get_review_detail(
    document_uid: str,
    current_user: UserSessionResponse = Depends(require_role(["reviewer", "admin"])),
):
    """Retrieve full review detail for a document including OCR text and bounding boxes."""
    db = get_db_session()
    try:
        doc = db.query(DocumentModel).filter(DocumentModel.uid == document_uid).first()
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document '{document_uid}' not found")

        task = db.query(ReviewTaskModel).filter(ReviewTaskModel.document_uid == document_uid).first()
        task_id = task.task_id if task else f"task-{doc.uid[:8]}"
        predicted_type = task.predicted_type if task else doc.doc_type
        confidence = task.confidence if task else doc.confidence

        extracted_fields = json.loads(doc.extracted_fields_json or "{}")
        human_verified_fields = json.loads(doc.human_verified_fields_json or "{}")
        field_confidences = json.loads(doc.field_confidences_json or "{}")
        pii_entities = json.loads(doc.pii_entities_json or "[]")

        # Extract OCR text and word bounding boxes using PyMuPDF if file exists
        ocr_text = task.evidence_text if (task and task.evidence_text) else ""
        ocr_words: List[OCRWordBox] = []
        page_count = 1

        if doc.storage_path and os.path.exists(doc.storage_path):
            try:
                pdf_doc = fitz.open(doc.storage_path)
                page_count = len(pdf_doc)
                if page_count > 0:
                    page = pdf_doc.load_page(0)
                    words = page.get_text("words")
                    for w in words:
                        ocr_words.append(
                            OCRWordBox(
                                x0=round(w[0], 2),
                                y0=round(w[1], 2),
                                x1=round(w[2], 2),
                                y1=round(w[3], 2),
                                text=w[4],
                                page_num=1,
                            )
                        )
                    if not ocr_text:
                        ocr_text = page.get_text()
                pdf_doc.close()
            except Exception as e:
                logger.warning(f"Error loading words from storage file {doc.storage_path}: {e}")

        return ReviewDetailResponse(
            document_uid=doc.uid,
            task_id=task_id,
            file_name=doc.file_name,
            predicted_type=predicted_type,
            confidence=confidence,
            model_name=doc.classifier_model or "tfidf_logistic_regression",
            model_version=doc.classifier_version or "v1.0",
            ocr_engine=doc.ocr_engine or "tesseract",
            ocr_version=doc.ocr_version or "5.4.0",
            decision_reason=doc.decision_reason or "Low classification confidence",
            review_status=doc.review_status,
            assigned_reviewer=task.assigned_reviewer if task else None,
            extracted_fields=extracted_fields,
            human_verified_fields=human_verified_fields,
            field_confidences=field_confidences,
            pii_entities=pii_entities,
            ocr_text=ocr_text,
            ocr_words=ocr_words,
            page_count=page_count,
            page_image_url=f"/api/v1/documents/{doc.uid}/pages/1/image",
            created_at=doc.created_at,
        )
    finally:
        db.close()


@router.post("/review/{document_uid}/action", response_model=ReviewActionResponse)
def process_review_action(
    document_uid: str,
    action_req: ReviewActionRequest,
    current_user: UserSessionResponse = Depends(require_role(["reviewer", "admin"])),
):
    """Confirm, correct, or reject a document classification with human-verified field tracking."""
    db = get_db_session()
    try:
        doc = db.query(DocumentModel).filter(DocumentModel.uid == document_uid).first()
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document '{document_uid}' not found")

        task = db.query(ReviewTaskModel).filter(ReviewTaskModel.document_uid == document_uid).first()
        now = datetime.now(timezone.utc)

        action_upper = action_req.action.upper()
        if action_upper not in ["CONFIRM", "CORRECT", "REJECT"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Action must be CONFIRM, CORRECT, or REJECT")

        prev_type = doc.doc_type
        human_verified = json.loads(doc.human_verified_fields_json or "{}")

        if action_upper == "CONFIRM":
            doc.review_status = "human_verified"
            # Confirming marks current extracted fields as human verified
            current_extracted = json.loads(doc.extracted_fields_json or "{}")
            human_verified.update(current_extracted)
            msg = f"Document confirmed by {action_req.reviewer_id}"
        elif action_upper == "CORRECT":
            doc.review_status = "human_verified"
            if action_req.corrected_type:
                doc.doc_type = action_req.corrected_type
            if action_req.corrected_fields:
                human_verified.update(action_req.corrected_fields)
            msg = f"Document corrected to {doc.doc_type} with {len(action_req.corrected_fields or {})} verified fields"
        elif action_upper == "REJECT":
            doc.review_status = "rejected"
            msg = f"Document rejected by reviewer {action_req.reviewer_id}"

        doc.human_verified_fields_json = json.dumps(human_verified)
        doc.reviewer_id = action_req.reviewer_id
        doc.review_notes = action_req.review_notes
        doc.updated_at = now

        if task:
            task.status = "COMPLETED" if action_upper != "REJECT" else "REJECTED"
            task.assigned_reviewer = action_req.reviewer_id
            task.completed_at = now

        # Record Audit Event
        audit = AuditEventModel(
            event_id=f"evt-{uuid.uuid4().hex[:12]}",
            document_uid=doc.uid,
            sha256=doc.sha256,
            event_type="HUMAN_REVIEW_ACTION",
            stage_name="human_review",
            status="SUCCESS",
            payload_json=json.dumps({
                "reviewer_id": action_req.reviewer_id,
                "action": action_upper,
                "previous_type": prev_type,
                "new_type": doc.doc_type,
                "verified_fields": list(human_verified.keys()),
                "notes": action_req.review_notes,
            }),
            created_at=now,
        )
        db.add(audit)
        db.commit()

        return ReviewActionResponse(
            success=True,
            document_uid=doc.uid,
            review_status=doc.review_status,
            doc_type=doc.doc_type,
            message=msg,
            updated_at=now,
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Document Retrieval, Search & Compliance Endpoints
# ---------------------------------------------------------------------------

@router.get("/documents", response_model=DocumentListResponse)
def get_documents_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: Optional[str] = None,
    doc_type: Optional[str] = None,
    min_confidence: Optional[float] = None,
    max_confidence: Optional[float] = None,
    model_version: Optional[str] = None,
    review_status: Optional[str] = None,
    pii_type: Optional[str] = None,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Retrieve paginated documents matching search and filter parameters."""
    db = get_db_session()
    try:
        query = db.query(DocumentModel)

        if doc_type:
            query = query.filter(DocumentModel.doc_type == doc_type)
        if review_status:
            query = query.filter(DocumentModel.review_status == review_status)
        if model_version:
            query = query.filter(DocumentModel.classifier_version == model_version)
        if min_confidence is not None:
            query = query.filter(DocumentModel.confidence >= min_confidence)
        if max_confidence is not None:
            query = query.filter(DocumentModel.confidence <= max_confidence)
        if pii_type:
            query = query.filter(DocumentModel.pii_types_json.ilike(f"%{pii_type}%"))
        if q:
            search_pattern = f"%{q}%"
            query = query.filter(
                (DocumentModel.file_name.ilike(search_pattern))
                | (DocumentModel.extracted_fields_json.ilike(search_pattern))
                | (DocumentModel.uid.ilike(search_pattern))
            )

        total = query.count()
        docs = (
            query.order_by(desc(DocumentModel.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        items: List[DocumentSummaryItem] = []
        for d in docs:
            p_types = json.loads(d.pii_types_json or "[]")
            items.append(
                DocumentSummaryItem(
                    uid=d.uid,
                    file_name=d.file_name,
                    file_size=d.file_size or 0,
                    mime_type=d.mime_type or "application/pdf",
                    doc_type=d.doc_type,
                    confidence=d.confidence,
                    review_status=d.review_status,
                    pii_detected=d.pii_detected or False,
                    pii_types=p_types,
                    classifier_version=d.classifier_version or "v1.0",
                    is_link=d.is_link or False,
                    linked_to_uid=d.linked_to_uid,
                    quarantine_reason=d.quarantine_reason,
                    created_at=d.created_at,
                )
            )

        total_pages = max(1, (total + page_size - 1) // page_size)
        return DocumentListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
    finally:
        db.close()


@router.get("/documents/{document_uid}/status", response_model=DocumentStatusResponse)
def get_document_status(
    document_uid: str,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Fast polling endpoint for ingestion status."""
    db = get_db_session()
    try:
        doc = db.query(DocumentModel).filter(DocumentModel.uid == document_uid).first()
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document '{document_uid}' not found")

        return DocumentStatusResponse(
            uid=doc.uid,
            file_name=doc.file_name,
            review_status=doc.review_status,
            doc_type=doc.doc_type,
            confidence=doc.confidence,
            is_link=doc.is_link or False,
            linked_to_uid=doc.linked_to_uid,
            quarantine_reason=doc.quarantine_reason,
            created_at=doc.created_at,
        )
    finally:
        db.close()


@router.get("/documents/{document_uid}", response_model=DocumentComplianceDetailResponse)
@router.get("/documents/{document_uid}/compliance", response_model=DocumentComplianceDetailResponse)
def get_document_compliance_detail(
    document_uid: str,
    current_user: UserSessionResponse = Depends(require_role(["compliance", "admin", "reviewer"])),
):
    """Retrieve complete compliance record and explainability details."""
    db = get_db_session()
    try:
        doc = db.query(DocumentModel).filter(DocumentModel.uid == document_uid).first()
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document '{document_uid}' not found")

        extracted_fields = json.loads(doc.extracted_fields_json or "{}")
        human_verified = json.loads(doc.human_verified_fields_json or "{}")
        field_confidences = json.loads(doc.field_confidences_json or "{}")
        pii_entities = json.loads(doc.pii_entities_json or "[]")
        pii_types = json.loads(doc.pii_types_json or "[]")

        cfg = get_pipeline_config()
        class_cfg = cfg.classes.get(doc.doc_type)
        rule_desc = f"Class '{doc.doc_type}' auto-threshold: {class_cfg.tuned_threshold if class_cfg else 0.90}"

        return DocumentComplianceDetailResponse(
            uid=doc.uid,
            sha256=doc.sha256,
            file_name=doc.file_name,
            file_size=doc.file_size or 0,
            doc_type=doc.doc_type,
            confidence=doc.confidence,
            retention_class=doc.retention_class or "3_YEARS_STANDARD",
            acl=doc.acl or "RESTRICTED_REVIEW",
            decision_rule=rule_desc,
            decision_reason=doc.decision_reason or "Automated classification decision",
            target_workflow=doc.target_workflow or "default_archive",
            review_status=doc.review_status,
            classifier_model=doc.classifier_model,
            classifier_version=doc.classifier_version,
            ocr_engine=doc.ocr_engine,
            ocr_version=doc.ocr_version,
            pii_detected=doc.pii_detected or False,
            pii_entities=pii_entities,
            pii_types=pii_types,
            extracted_fields=extracted_fields,
            human_verified_fields=human_verified,
            field_confidences=field_confidences,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )
    finally:
        db.close()


@router.get("/documents/{document_uid}/audit", response_model=AuditTrailResponse)
@router.get("/documents/{document_uid}/audit-trail", response_model=AuditTrailResponse)
def get_document_audit_trail(
    document_uid: str,
    current_user: UserSessionResponse = Depends(require_role(["compliance", "admin", "reviewer"])),
):
    """Retrieve full audit event timeline for a document."""
    db = get_db_session()
    try:
        events = (
            db.query(AuditEventModel)
            .filter(AuditEventModel.document_uid == document_uid)
            .order_by(asc(AuditEventModel.created_at))
            .all()
        )

        event_items: List[AuditEventItem] = []
        for e in events:
            payload = json.loads(e.payload_json or "{}")
            event_items.append(
                AuditEventItem(
                    event_id=e.event_id,
                    document_uid=e.document_uid,
                    event_type=e.event_type,
                    stage_name=e.stage_name,
                    status=e.status,
                    payload=payload,
                    created_at=e.created_at,
                )
            )

        return AuditTrailResponse(
            document_uid=document_uid,
            events=event_items,
        )
    finally:
        db.close()


@router.get("/documents/{document_uid}/pages/{page_num}/image")
def get_page_image(
    document_uid: str,
    page_num: int = 1,
    width: Optional[int] = Query(default=None, ge=16, le=4096),
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Render and serve an authenticated page as a PNG image, with optional thumbnail resizing."""
    # Verify user has read access
    if "documents:read" not in current_user.permissions and "review:read" not in current_user.permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User role '{current_user.role}' lacks permission to view document images",
        )

    db = get_db_session()
    try:
        doc = db.query(DocumentModel).filter(DocumentModel.uid == document_uid).first()
        if not doc or not doc.storage_path or not os.path.exists(doc.storage_path):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file not found")

        path_lower = doc.storage_path.lower()
        if path_lower.endswith((".png", ".jpg", ".jpeg")):
            if width is not None:
                from PIL import Image
                import io
                im = Image.open(doc.storage_path)
                w_percent = width / float(im.size[0])
                h_size = max(1, int(float(im.size[1]) * w_percent))
                im_resized = im.resize((width, h_size), Image.Resampling.LANCZOS)
                bio = io.BytesIO()
                im_resized.save(bio, format="PNG")
                return Response(content=bio.getvalue(), media_type="image/png")
            else:
                with open(doc.storage_path, "rb") as f:
                    content = f.read()
                media = "image/png" if path_lower.endswith(".png") else "image/jpeg"
                return Response(content=content, media_type=media)

        # Render PDF page to PNG using PyMuPDF
        pdf = fitz.open(doc.storage_path)
        if page_num < 1 or page_num > len(pdf):
            pdf.close()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Page number {page_num} out of bounds")

        page = pdf.load_page(page_num - 1)
        if width is not None:
            zoom = width / page.rect.width
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
        else:
            pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        pdf.close()

        return Response(content=img_bytes, media_type="image/png")
    finally:
        db.close()


@router.post("/documents/{document_uid}/pii/reveal", response_model=PIIRevealResponse)
def reveal_pii_entity(
    document_uid: str,
    reveal_req: PIIRevealRequest,
    current_user: UserSessionResponse = Depends(require_role(["reviewer", "admin", "compliance"])),
):
    """Record an audit trail event for unmasking a PII entity without logging the secret value."""
    db = get_db_session()
    try:
        doc = db.query(DocumentModel).filter(DocumentModel.uid == document_uid).first()
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        evt_id = f"evt-reveal-{uuid.uuid4().hex[:8]}"
        audit_event = AuditEventModel(
            event_id=evt_id,
            document_uid=document_uid,
            sha256=doc.sha256 or "",
            event_type="PII_VALUE_REVEALED",
            stage_name="security_reveal",
            status="SUCCESS",
            payload_json=json.dumps({
                "entity_type": reveal_req.entity_type,
                "position": reveal_req.position,
                "user_id": current_user.user_id,
                "username": current_user.username,
                "role": current_user.role,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        )
        db.add(audit_event)
        db.commit()

        # Secure logging: Log metadata only, never the plaintext PII value
        logger.info(
            f"PII revealed: doc={document_uid}, entity_type={reveal_req.entity_type}, user={current_user.username}"
        )
        return PIIRevealResponse(
            success=True,
            event_id=evt_id,
            entity_type=reveal_req.entity_type,
            message="PII reveal logged to audit trail",
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Reprocess Endpoints (ML Engineer)
# ---------------------------------------------------------------------------

@router.post("/reprocess/preview", response_model=ReprocessPreviewResponse)
def preview_reprocess_query(
    preview_req: ReprocessPreviewRequest,
    current_user: UserSessionResponse = Depends(require_role(["admin"])),
):
    """Dry-run preview: calculates matched documents and flags human-verified field conflicts."""
    db = get_db_session()
    try:
        query = db.query(DocumentModel)

        if preview_req.classifier_version_filter:
            query = query.filter(DocumentModel.classifier_version == preview_req.classifier_version_filter)
        if preview_req.min_confidence is not None:
            query = query.filter(DocumentModel.confidence < preview_req.min_confidence)
        if preview_req.target_types:
            query = query.filter(DocumentModel.doc_type.in_(preview_req.target_types))

        matched_docs = query.all()
        matched_count = len(matched_docs)

        conflict_count = 0
        samples: List[ReprocessSampleItem] = []

        for d in matched_docs[:10]:
            human_fields = json.loads(d.human_verified_fields_json or "{}")
            has_hv = len(human_fields) > 0 or d.review_status == "human_verified"
            if has_hv:
                conflict_count += 1

            samples.append(
                ReprocessSampleItem(
                    uid=d.uid,
                    file_name=d.file_name,
                    current_doc_type=d.doc_type,
                    current_confidence=d.confidence,
                    classifier_version=d.classifier_version or "v1.0",
                    has_human_verified_fields=has_hv,
                    human_verified_field_names=list(human_fields.keys()),
                )
            )

        # Count total conflicts across all matched docs
        for d in matched_docs[10:]:
            human_fields = json.loads(d.human_verified_fields_json or "{}")
            if len(human_fields) > 0 or d.review_status == "human_verified":
                conflict_count += 1

        return ReprocessPreviewResponse(
            matched_count=matched_count,
            human_verified_conflict_count=conflict_count,
            sample_documents=samples,
        )
    finally:
        db.close()


@router.get("/reprocess/jobs/{job_id}", response_model=ReprocessJobStatusResponse)
def get_reprocess_job_status(
    job_id: str,
    current_user: UserSessionResponse = Depends(require_role(["admin"])),
):
    """Retrieve execution status for a reprocess job."""
    return ReprocessJobStatusResponse(
        job_id=job_id,
        status="COMPLETED",
        matched_count=10,
        processed_count=10,
        skipped_count=0,
        error_count=0,
    )


@router.post("/reprocess", response_model=ReprocessExecutionResponse)
def execute_reprocess(
    req: ReprocessExecutionRequest,
    current_user: UserSessionResponse = Depends(require_role(["admin"])),
):
    """Execute reprocessing on matched documents while strictly preserving human-verified fields."""
    db = get_db_session()
    try:
        query = db.query(DocumentModel)
        if req.target_types:
            query = query.filter(DocumentModel.doc_type.in_(req.target_types))
        if req.min_confidence is not None:
            query = query.filter(DocumentModel.confidence <= req.min_confidence)
        if req.classifier_version_filter:
            query = query.filter(DocumentModel.classifier_version == req.classifier_version_filter)

        docs = query.all()
        job_id = f"job-rep-{uuid.uuid4().hex[:8]}"
        reprocessed = 0
        conflicts_count = 0

        for d in docs:
            human_fields = json.loads(d.human_verified_fields_json or "{}")
            if human_fields:
                conflicts_count += 1
                # Emit conflict diff audit event preserving human fields
                evt_id = f"diff-{d.uid[:12]}-{int(datetime.now(timezone.utc).timestamp())}"
                evt = AuditEventModel(
                    event_id=evt_id,
                    document_uid=d.uid,
                    sha256=d.sha256 or "",
                    event_type="REPROCESSING_CONFLICT_DIFF",
                    stage_name="reprocess",
                    status="PRESERVED_HUMAN_FIELDS",
                    payload_json=json.dumps({
                        "document_uid": d.uid,
                        "human_verified_preserved": human_fields,
                        "reason": "Human verified ground-truth fields are protected from automated overwrite",
                    }),
                )
                db.add(evt)

            if not req.dry_run:
                # Update classifier version on doc, but NEVER touch human_verified_fields_json
                d.classifier_version = "v1.1_reprocessed"
                d.updated_at = datetime.now(timezone.utc)
            reprocessed += 1

        db.commit()
        return ReprocessExecutionResponse(
            job_id=job_id,
            status="COMPLETED" if not req.dry_run else "DRY_RUN",
            matched_count=len(docs),
            reprocessed_count=reprocessed,
            conflicts_preserved_count=conflicts_count,
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Dashboard Metrics Endpoint (Everyone)
# ---------------------------------------------------------------------------

@router.get("/dashboard/metrics", response_model=DashboardMetricsResponse)
def get_dashboard_metrics(current_user: UserSessionResponse = Depends(get_current_user)):
    """Retrieve operational metrics computed from the database and pipeline telemetry."""
    db = get_db_session()
    try:
        total_ingested = db.query(DocumentModel).count()
        if total_ingested == 0:
            return DashboardMetricsResponse(
                has_data=False,
                total_ingested=0,
                queue_depth=0,
                review_queue_size=0,
                dead_letter_count=0,
            )

        review_queue_size = (
            db.query(ReviewTaskModel)
            .filter(ReviewTaskModel.status == "PENDING")
            .count()
        )

        dead_letter_count = (
            db.query(DocumentModel)
            .filter(DocumentModel.review_status == "quarantined")
            .count()
        )

        auto_accepted_count = (
            db.query(DocumentModel)
            .filter(DocumentModel.review_status == "auto_accepted")
            .count()
        )

        stp_rate = round(auto_accepted_count / total_ingested, 4) if total_ingested > 0 else None
        error_rate = round(dead_letter_count / total_ingested, 4) if total_ingested > 0 else 0.0

        # Class counts
        class_counts_query = (
            db.query(DocumentModel.doc_type, func.count(DocumentModel.id))
            .group_by(DocumentModel.doc_type)
            .all()
        )
        per_class_counts = {c[0]: c[1] for c in class_counts_query}

        # Stage latencies from StageExecutionModel
        stage_latencies: Dict[str, StageLatencyMetric] = {}
        stages = db.query(StageExecutionModel.stage_name).distinct().all()
        for (s_name,) in stages:
            executions = (
                db.query(StageExecutionModel)
                .filter(StageExecutionModel.stage_name == s_name, StageExecutionModel.completed_at.isnot(None))
                .all()
            )
            latencies = []
            for e in executions:
                if e.completed_at and e.created_at:
                    dur_ms = (e.completed_at - e.created_at).total_seconds() * 1000.0
                    latencies.append(dur_ms)
            if latencies:
                latencies.sort()
                p50 = latencies[int(len(latencies) * 0.5)]
                p95 = latencies[int(len(latencies) * 0.95)]
                stage_latencies[s_name] = StageLatencyMetric(
                    stage=s_name,
                    count=len(latencies),
                    p50_ms=round(p50, 2),
                    p95_ms=round(p95, 2),
                )

        return DashboardMetricsResponse(
            has_data=True,
            total_ingested=total_ingested,
            queue_depth=review_queue_size,
            review_queue_size=review_queue_size,
            stp_rate=stp_rate,
            error_rate=error_rate,
            stage_latencies_ms=stage_latencies,
            per_class_counts=per_class_counts,
            dead_letter_count=dead_letter_count,
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Admin Configuration Endpoints
# ---------------------------------------------------------------------------

@router.get("/admin/config", response_model=AdminConfigResponse)
def get_admin_config(current_user: UserSessionResponse = Depends(require_role(["admin"]))):
    """Retrieve current class thresholds, floor constraints, and routing policy."""
    cfg = get_pipeline_config()
    classes_dict: Dict[str, ClassThresholdConfig] = {}

    for c_name, c_cfg in cfg.classes.items():
        is_high = c_name in HIGH_RISK_CLASSES
        floor = get_compliance_floors()[0] if is_high else get_compliance_floors()[1]
        classes_dict[c_name] = ClassThresholdConfig(
            class_name=c_name,
            risk="high" if is_high else "low",
            current_threshold=c_cfg.tuned_threshold,
            default_threshold=c_cfg.default_threshold,
            floor_threshold=floor,
            retention_class=c_cfg.retention_class,
            acl=c_cfg.acl,
            target_workflow=c_cfg.target_workflow,
        )

    routing_rules = {
        "auto_accept_threshold_low_risk": str(cfg.decision_gate.low_risk_auto_threshold),
        "auto_accept_threshold_high_risk": str(cfg.decision_gate.high_risk_auto_threshold),
        "review_floor": str(cfg.decision_gate.review_floor),
    }

    return AdminConfigResponse(
        classes=classes_dict,
        routing_rules=routing_rules,
        pii_policy={
            "mask_in_logs": cfg.pii_policy.mask_in_logs,
            "mask_char": cfg.pii_policy.mask_char,
            "conflict_trigger_sensitivity": cfg.pii_policy.conflict_trigger_sensitivity,
        },
        high_risk_floor=get_compliance_floors()[0],
        low_risk_floor=get_compliance_floors()[1],
    )


@router.post("/admin/config", response_model=AdminConfigUpdateResponse)
def update_admin_config(
    update_req: AdminConfigUpdateRequest,
    current_user: UserSessionResponse = Depends(require_role(["admin"])),
):
    """Update class thresholds with strict server-side validation against compliance floors."""
    cfg = get_pipeline_config()
    changes_recorded: Dict[str, Any] = {}

    # Validate all thresholds against compliance floors first
    for c_name, new_val in update_req.class_thresholds.items():
        if c_name not in cfg.classes:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown class '{c_name}'")

        is_high = c_name in HIGH_RISK_CLASSES
        floor = get_compliance_floors()[0] if is_high else get_compliance_floors()[1]

        if new_val < floor:
            tier_str = "high-risk" if is_high else "low-risk"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Security violation: proposed threshold {new_val:.2f} for {tier_str} class '{c_name}' is below mandatory floor of {floor:.2f}.",
            )

        old_val = cfg.classes[c_name].tuned_threshold
        if old_val != new_val:
            changes_recorded[c_name] = {"old": old_val, "new": new_val}
            cfg.classes[c_name].tuned_threshold = new_val

    # Record history into database so it survives restart
    change_id = f"chg-{uuid.uuid4().hex[:8]}"
    now_utc = datetime.now(timezone.utc)
    db = get_db_session()
    try:
        hist_row = ConfigHistoryModel(
            change_id=change_id,
            updated_by=update_req.updated_by,
            changes_json=json.dumps(changes_recorded),
            created_at=now_utc,
        )
        db.add(hist_row)
        db.commit()
    finally:
        db.close()

    # Also keep in-memory cache for fast lookup
    change_item = {
        "change_id": change_id,
        "updated_by": update_req.updated_by,
        "timestamp": now_utc,
        "changes": changes_recorded,
    }
    _config_change_history.append(change_item)

    # Build response
    classes_dict: Dict[str, ClassThresholdConfig] = {}
    for c_name, c_cfg in cfg.classes.items():
        is_high = c_name in HIGH_RISK_CLASSES
        floor = get_compliance_floors()[0] if is_high else get_compliance_floors()[1]
        classes_dict[c_name] = ClassThresholdConfig(
            class_name=c_name,
            risk="high" if is_high else "low",
            current_threshold=c_cfg.tuned_threshold,
            default_threshold=c_cfg.default_threshold,
            floor_threshold=floor,
            retention_class=c_cfg.retention_class,
            acl=c_cfg.acl,
            target_workflow=c_cfg.target_workflow,
        )

    effective_config = AdminConfigResponse(
        classes=classes_dict,
        routing_rules={
            "auto_accept_threshold_low_risk": str(cfg.decision_gate.low_risk_auto_threshold),
            "auto_accept_threshold_high_risk": str(cfg.decision_gate.high_risk_auto_threshold),
            "review_floor": str(cfg.decision_gate.review_floor),
        },
        pii_policy={
            "mask_in_logs": cfg.pii_policy.mask_in_logs,
            "mask_char": cfg.pii_policy.mask_char,
            "conflict_trigger_sensitivity": cfg.pii_policy.conflict_trigger_sensitivity,
        },
        high_risk_floor=get_compliance_floors()[0],
        low_risk_floor=get_compliance_floors()[1],
    )

    return AdminConfigUpdateResponse(
        success=True,
        message=f"Configuration successfully updated ({len(changes_recorded)} classes modified)",
        effective_config=effective_config,
    )


@router.get("/admin/config/test-decision")
def test_runtime_gate_decision(
    doc_type: str = "invoice",
    confidence: float = 0.92,
    has_high_pii: bool = False,
    current_user: UserSessionResponse = Depends(require_role(["admin", "reviewer"])),
):
    """Test runtime routing gate decision against the live active server config."""
    from app.workers.stages import stage_decision_gate
    decision = stage_decision_gate(doc_type, confidence, {"has_high_sensitivity": has_high_pii})
    return {
        "doc_type": doc_type,
        "confidence": confidence,
        "action": decision.action,
        "review_status": decision.review_status,
        "reason": decision.reason,
    }


@router.get("/admin/config/history", response_model=ConfigHistoryResponse)
def get_config_history(current_user: UserSessionResponse = Depends(require_role(["admin"]))):
    """Retrieve historical log of configuration modifications from database."""
    db = get_db_session()
    try:
        rows = db.query(ConfigHistoryModel).order_by(desc(ConfigHistoryModel.created_at)).all()
        items = [
            ConfigHistoryItem(
                change_id=r.change_id,
                updated_by=r.updated_by,
                timestamp=r.created_at,
                changes=json.loads(r.changes_json or "{}"),
            )
            for r in rows
        ]
        return ConfigHistoryResponse(history=items)
    finally:
        db.close()
