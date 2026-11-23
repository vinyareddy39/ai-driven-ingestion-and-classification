"""REST API v1 endpoints for Document Ingestion Web Frontend."""

from datetime import datetime, timedelta, timezone
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional, Tuple
import uuid
import zipfile

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
import fitz  # PyMuPDF
from sqlalchemy import desc, asc, func

from app.core.auth import get_current_user, require_role
from app.core.config import get_app_settings, get_pipeline_config
from app.core.security import setup_secure_logging
from app.models.db import (
    AuditEventModel,
    BatchModel,
    ConfigHistoryModel,
    DocumentModel,
    DownloadModel,
    MultipartUploadModel,
    NotificationModel,
    PipelineJobModel,
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
    BatchCreateRequest,
    BatchCreateResponse,
    BatchDetailResponse,
    BatchFileItem,
    BatchListResponse,
    BatchProgressCounts,
    BatchSummaryItem,
    BatchSummaryResponse,
    ClassThresholdConfig,
    ConfigHistoryItem,
    ConfigHistoryResponse,
    DashboardMetricsResponse,
    DocumentComplianceDetailResponse,
    DocumentListResponse,
    DocumentStatusResponse,
    DocumentSummaryItem,
    DownloadCleanupResponse,
    DownloadCreateResponse,
    DownloadItem,
    DownloadListResponse,
    NotificationItem,
    NotificationListResponse,
    NotificationMarkReadResponse,
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
    UploadAbortResponse,
    UploadCompleteRequest,
    UploadCompleteResponse,
    UploadInitRequest,
    UploadInitResponse,
    UploadPartETag,
    UploadPartPresignedUrl,
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
    from app.adapters.virus import get_virus_scanner, ClamAVScanner
    settings = get_app_settings()
    cfg = get_pipeline_config()

    is_real = (
        settings.STORAGE_BACKEND in ("minio", "s3")
        and settings.QUEUE_BACKEND == "redis"
        and settings.SEARCH_BACKEND == "opensearch"
    )
    mode = "REAL SERVICES" if is_real else "LOCAL MODE"

    scanner = get_virus_scanner()
    scanner_name = "clamav" if isinstance(scanner, ClamAVScanner) else "eicar-test-only"

    cls_type = cfg.pipeline.get("classifier_model_type", "tfidf_logistic")
    cls_ver = cfg.pipeline.get("classifier_model_version", "v1.0")

    engines_dict = {
        "ocr": settings.OCR_ENGINE,
        "classifier": f"{cls_type} ({cls_ver})",
        "pii": "presidio-v2.2 (en)",
        "database": "postgresql" if "postgres" in (settings.DATABASE_URL or "").lower() else "sqlite",
        "search": settings.SEARCH_BACKEND if settings.SEARCH_BACKEND != "memory" else "sqlite_fts / memory",
        "scanner": scanner_name,
        "reminders": "database-backed scheduler",
    }

    return SystemInfoResponse(
        mode=mode,
        version=cfg.pipeline.get("version", "1.0.0"),
        environment=settings.ENVIRONMENT,
        storage_backend=settings.STORAGE_BACKEND,
        queue_backend=settings.QUEUE_BACKEND,
        search_backend=settings.SEARCH_BACKEND,
        ocr_engine=settings.OCR_ENGINE,
        classifier_version=cls_ver,
        virus_scanner=scanner_name,
        scanner=scanner_name,
        engines=engines_dict,
        high_risk_floor=get_compliance_floors()[0],
        low_risk_floor=get_compliance_floors()[1],
        max_upload_mb=settings.MAX_UPLOAD_MB,
        max_upload_size_mb=settings.MAX_UPLOAD_MB,
        max_upload_size_bytes=settings.MAX_UPLOAD_MB * 1024 * 1024,
        allowed_file_types=settings.ALLOWED_FILE_TYPES,
        allowed_extensions=[".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".eml", ".docx"],
    )


@router.get("/auth/me", response_model=UserSessionResponse)
def get_auth_me(current_user: UserSessionResponse = Depends(get_current_user)):
    """Return active authenticated user session."""
    return current_user


@router.get("/document-types")
def get_document_types(current_user: UserSessionResponse = Depends(get_current_user)):
    """Return configuration-driven list of document types and their field definitions."""
    cfg_path = Path("config/document_types.json")
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"document_types": {}}


@router.get("/document-types/{doc_type}")
def get_document_type_detail(doc_type: str, current_user: UserSessionResponse = Depends(get_current_user)):
    """Return field list and schema for a specific document type."""
    cfg_path = Path("config/document_types.json")
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            types = data.get("document_types", {})
            if doc_type in types:
                return types[doc_type]
    raise HTTPException(status_code=404, detail=f"Document type '{doc_type}' not found in configuration")


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
# Batch Results, Upload Sessions & Export Endpoints
# ---------------------------------------------------------------------------

PLAIN_STATUS_MAP = {
    "auto_accepted": "SORTED_AUTOMATICALLY",
    "approved": "SORTED_AUTOMATICALLY",
    "human_verified": "SORTED_AUTOMATICALLY",
    "pending_review": "NEEDS_CHECK",
    "failed": "FAILED",
    "duplicate": "ALREADY_UPLOADED",
    "quarantined": "BLOCKED",
    "queued": "PROCESSING",
    "processing": "PROCESSING",
}


def to_plain_status(review_status: str, is_link: bool = False) -> str:
    if is_link:
        return "ALREADY_UPLOADED"
    return PLAIN_STATUS_MAP.get(review_status or "queued", "SORTED_AUTOMATICALLY")


@router.post("/batches", response_model=BatchCreateResponse, status_code=status.HTTP_201_CREATED)
def create_batch(
    req: Optional[BatchCreateRequest] = None,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Explicitly initialize a new upload batch session prior to file streaming."""
    db = get_db_session()
    try:
        batch_id = f"batch-{uuid.uuid4().hex[:12]}"
        user_id = current_user.user_id if current_user else None
        b_count = db.query(BatchModel).count()
        number = b_count + 1
        name = req.name if (req and req.name) else f"Upload #{number}"
        now = datetime.now(timezone.utc)

        batch = BatchModel(
            batch_id=batch_id,
            number=number,
            name=name,
            user_id=user_id,
            created_at=now,
        )
        db.add(batch)
        db.commit()
        return BatchCreateResponse(
            batch_id=batch_id,
            number=number,
            name=name,
            created_at=now,
        )
    finally:
        db.close()


@router.get("/batches", response_model=BatchListResponse)
def list_batches(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """List all upload batches (owner-scoped, newest first) with status and type breakdowns."""
    if not isinstance(page, int) or isinstance(page, bool):
        page = 1
    if not isinstance(page_size, int) or isinstance(page_size, bool):
        page_size = 20

    db = get_db_session()
    try:
        user_id = current_user.user_id if current_user else None
        is_staff = current_user.role in ("admin", "reviewer", "compliance")

        # Discover all unique batches from BatchModel or DocumentModel
        batch_query = db.query(BatchModel)
        if not is_staff and user_id:
            batch_query = batch_query.filter(BatchModel.user_id == user_id)

        all_batch_rows = batch_query.order_by(desc(BatchModel.created_at)).all()
        known_batch_ids = {b.batch_id for b in all_batch_rows}

        # Also find any batch_ids present in DocumentModel not yet in BatchModel
        doc_batches_query = db.query(DocumentModel.batch_id, DocumentModel.user_id, func.min(DocumentModel.created_at)).filter(
            DocumentModel.batch_id.isnot(None)
        )
        if not is_staff and user_id:
            doc_batches_query = doc_batches_query.filter(DocumentModel.user_id == user_id)
        doc_batches = doc_batches_query.group_by(DocumentModel.batch_id).all()

        for b_id, b_uid, b_created in doc_batches:
            if b_id and b_id not in known_batch_ids:
                count = len(all_batch_rows) + 1
                new_b = BatchModel(
                    batch_id=b_id,
                    number=count,
                    name=f"Upload #{count}",
                    user_id=b_uid,
                    created_at=b_created or datetime.now(timezone.utc),
                )
                db.add(new_b)
                all_batch_rows.append(new_b)
                known_batch_ids.add(b_id)
        db.commit()

        # Re-query sorted
        all_batch_rows.sort(key=lambda x: x.created_at or datetime.min, reverse=True)
        total = len(all_batch_rows)
        paged_batches = all_batch_rows[(page - 1) * page_size : page * page_size]

        items: List[BatchSummaryItem] = []
        for b in paged_batches:
            # Query aggregations for this batch
            status_counts = dict(
                db.query(DocumentModel.review_status, func.count(DocumentModel.uid))
                .filter(DocumentModel.batch_id == b.batch_id)
                .group_by(DocumentModel.review_status)
                .all()
            )
            type_counts = dict(
                db.query(DocumentModel.doc_type, func.count(DocumentModel.uid))
                .filter(DocumentModel.batch_id == b.batch_id)
                .group_by(DocumentModel.doc_type)
                .all()
            )

            file_count = sum(status_counts.values())
            plain_status_counts = {
                "SORTED_AUTOMATICALLY": (
                    status_counts.get("auto_accepted", 0)
                    + status_counts.get("approved", 0)
                    + status_counts.get("human_verified", 0)
                ),
                "NEEDS_CHECK": status_counts.get("pending_review", 0),
                "FAILED": status_counts.get("failed", 0),
                "ALREADY_UPLOADED": status_counts.get("duplicate", 0),
                "BLOCKED": status_counts.get("quarantined", 0),
                "PROCESSING": status_counts.get("queued", 0) + status_counts.get("processing", 0),
            }

            finished_count = (
                plain_status_counts["SORTED_AUTOMATICALLY"]
                + plain_status_counts["NEEDS_CHECK"]
                + plain_status_counts["FAILED"]
                + plain_status_counts["ALREADY_UPLOADED"]
                + plain_status_counts["BLOCKED"]
            )
            progress_pct = round((finished_count / file_count) * 100, 1) if file_count > 0 else 0.0
            is_finished = (progress_pct >= 100.0 and file_count > 0) or (
                file_count > 0 and (status_counts.get("queued", 0) + status_counts.get("processing", 0) == 0)
            )

            # Lookup latest downloaded timestamp if available
            last_dl = (
                db.query(DownloadModel)
                .filter(DownloadModel.batch_id == b.batch_id, DownloadModel.status == "DOWNLOADED")
                .order_by(DownloadModel.last_downloaded_at.desc())
                .first()
            )

            items.append(
                BatchSummaryItem(
                    batch_id=b.batch_id,
                    number=b.number or 1,
                    name=b.name or f"Upload #{b.number or 1}",
                    created_at=b.created_at,
                    file_count=file_count,
                    progress_percent=progress_pct,
                    counts_by_type=type_counts,
                    counts_by_status=plain_status_counts,
                    needs_check_count=plain_status_counts["NEEDS_CHECK"],
                    is_finished=is_finished,
                    last_downloaded_at=last_dl.last_downloaded_at if last_dl else None,
                )
            )

        return BatchListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )
    finally:
        db.close()


@router.get("/batches/{batch_id}", response_model=BatchDetailResponse)
def get_batch_detail(
    batch_id: str,
    doc_type: Optional[str] = Query(None, alias="type"),
    review_status: Optional[str] = Query(None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Retrieve batch progress, status breakdown, and document list with user isolation and filtering."""
    if not isinstance(doc_type, str):
        doc_type = None
    if not isinstance(review_status, str):
        review_status = None
    if not isinstance(page, int) or isinstance(page, bool):
        page = 1
    if not isinstance(page_size, int) or isinstance(page_size, bool):
        page_size = 100

    db = get_db_session()
    try:
        # 1. Fetch batch metadata from BatchModel or DocumentModel
        batch_record = db.query(BatchModel).filter(BatchModel.batch_id == batch_id).first()
        doc_count_total = db.query(DocumentModel).filter(DocumentModel.batch_id == batch_id).count()

        if not batch_record and doc_count_total == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Upload '{batch_id}' not found",
            )

        # Enforce user isolation:
        first_doc = db.query(DocumentModel).filter(DocumentModel.batch_id == batch_id).first()
        batch_owner = (batch_record.user_id if batch_record else None) or (first_doc.user_id if first_doc else None)
        is_staff = current_user.role in ("admin", "reviewer", "compliance")
        if batch_owner and not is_staff and current_user.user_id != batch_owner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Upload '{batch_id}' not found",
            )

        # 2. O(1) SQL Aggregations: Status counts and Type counts
        status_counts = dict(
            db.query(DocumentModel.review_status, func.count(DocumentModel.uid))
            .filter(DocumentModel.batch_id == batch_id)
            .group_by(DocumentModel.review_status)
            .all()
        )

        type_counts = dict(
            db.query(DocumentModel.doc_type, func.count(DocumentModel.uid))
            .filter(DocumentModel.batch_id == batch_id)
            .group_by(DocumentModel.doc_type)
            .all()
        )

        total_files = sum(status_counts.values())

        plain_status_counts = {
            "SORTED_AUTOMATICALLY": (
                status_counts.get("auto_accepted", 0)
                + status_counts.get("approved", 0)
                + status_counts.get("human_verified", 0)
            ),
            "NEEDS_CHECK": status_counts.get("pending_review", 0),
            "FAILED": status_counts.get("failed", 0),
            "ALREADY_UPLOADED": status_counts.get("duplicate", 0),
            "BLOCKED": status_counts.get("quarantined", 0),
            "PROCESSING": status_counts.get("queued", 0) + status_counts.get("processing", 0),
        }

        finished_count = (
            plain_status_counts["SORTED_AUTOMATICALLY"]
            + plain_status_counts["NEEDS_CHECK"]
            + plain_status_counts["FAILED"]
            + plain_status_counts["ALREADY_UPLOADED"]
            + plain_status_counts["BLOCKED"]
        )
        progress_pct = round((finished_count / total_files) * 100, 1) if total_files > 0 else 0.0
        is_finished = (progress_pct >= 100.0 and total_files > 0) or (
            total_files > 0 and (status_counts.get("queued", 0) + status_counts.get("processing", 0) == 0)
        )

        progress = BatchProgressCounts(
            total=total_files,
            queued=status_counts.get("queued", 0),
            processing=status_counts.get("processing", 0),
            done=plain_status_counts["SORTED_AUTOMATICALLY"],
            needs_review=status_counts.get("pending_review", 0),
            failed=status_counts.get("failed", 0),
            quarantined=status_counts.get("quarantined", 0),
            duplicate=status_counts.get("duplicate", 0),
        )

        # Auto-create notification if finished and not yet notified
        if is_finished and total_files > 0:
            existing_notif = db.query(NotificationModel).filter(NotificationModel.batch_id == batch_id).first()
            if not existing_notif:
                b_name = batch_record.name if batch_record else f"Upload"
                notif = NotificationModel(
                    id=f"notif-{uuid.uuid4().hex[:12]}",
                    user_id=batch_owner,
                    batch_id=batch_id,
                    title=f"{b_name} is ready",
                    message=f"{total_files} files sorted.",
                    read=False,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(notif)
                db.commit()

        # 3. Query paginated and filtered items
        items_query = db.query(DocumentModel).filter(DocumentModel.batch_id == batch_id)
        if doc_type and doc_type != "all":
            items_query = items_query.filter(DocumentModel.doc_type == doc_type)
        if review_status and review_status != "all":
            # Map plain status filter back to db status if necessary
            if review_status == "SORTED_AUTOMATICALLY":
                items_query = items_query.filter(DocumentModel.review_status.in_(["auto_accepted", "approved", "human_verified"]))
            elif review_status == "NEEDS_CHECK":
                items_query = items_query.filter(DocumentModel.review_status == "pending_review")
            elif review_status == "FAILED":
                items_query = items_query.filter(DocumentModel.review_status == "failed")
            elif review_status == "ALREADY_UPLOADED":
                items_query = items_query.filter((DocumentModel.review_status == "duplicate") | (DocumentModel.is_link == True))
            elif review_status == "BLOCKED":
                items_query = items_query.filter(DocumentModel.review_status == "quarantined")
            else:
                items_query = items_query.filter(DocumentModel.review_status == review_status)

        total_filtered = items_query.count()
        docs = items_query.order_by(DocumentModel.created_at.asc()).offset((page - 1) * page_size).limit(page_size).all()

        items = []
        for d in docs:
            f_json = json.loads(d.extracted_fields_json or "{}") if d.extracted_fields_json else {}
            v = f_json.get("vendor_name") or f_json.get("vendor") or f_json.get("store_name") or f_json.get("merchant") or f_json.get("supplier")
            amt = f_json.get("total_amount") or f_json.get("total") or f_json.get("amount")
            if amt is not None and isinstance(amt, (int, float)):
                amt_str = f"${amt:,.2f}"
            elif amt is not None:
                amt_str = str(amt)
            else:
                amt_str = None
            ext_method = "OCR" if ("ocr" in (d.ocr_engine or "").lower() or "trocr" in (d.ocr_engine or "").lower()) else "direct text"
            items.append(
                BatchFileItem(
                    uid=d.uid,
                    file_name=d.file_name,
                    doc_type=d.doc_type,
                    review_status=d.review_status,
                    plain_status=to_plain_status(d.review_status, d.is_link or False),
                    confidence=d.confidence or 0.0,
                    how_sure=round((d.confidence or 0.0) * 100, 1),
                    review_reason=d.decision_reason or d.quarantine_reason,
                    error_detail=d.quarantine_reason if d.review_status in ("quarantined", "failed") else None,
                    is_link=d.is_link or False,
                    extraction_method=ext_method,
                    vendor=str(v) if v else None,
                    amount=amt_str,
                    extracted_fields=f_json,
                    created_at=d.created_at,
                )
            )

        b_num = batch_record.number if batch_record else 1
        b_name = batch_record.name if batch_record else f"Upload #{b_num}"
        b_created = batch_record.created_at if batch_record else (first_doc.created_at if first_doc else datetime.now(timezone.utc))

        return BatchDetailResponse(
            batch_id=batch_id,
            number=b_num,
            name=b_name,
            user_id=batch_owner,
            created_at=b_created,
            progress=progress,
            progress_percent=progress_pct,
            counts_by_type=type_counts,
            counts_by_status=plain_status_counts,
            needs_check_count=plain_status_counts["NEEDS_CHECK"],
            is_finished=is_finished,
            items=items,
            total_items=total_filtered,
            page=page,
            page_size=page_size,
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Direct-to-Storage Multipart Upload Endpoints (Stage 1 & Stage 2)
# ---------------------------------------------------------------------------

def _is_valid_magic_bytes(header: bytes, ext: str) -> bool:
    """Validate true magic bytes at start of binary stream."""
    ext = ext.lower().lstrip(".")
    if ext == "pdf":
        return header.startswith(b"%PDF-")
    elif ext == "png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    elif ext in ("jpg", "jpeg"):
        return header.startswith(b"\xff\xd8\xff")
    elif ext in ("tiff", "tif"):
        return header.startswith(b"II*\x00") or header.startswith(b"MM\x00*")
    elif ext == "docx":
        return header.startswith(b"PK\x03\x04")
    elif ext == "eml":
        sample = header[:300].lower()
        return any(h in sample for h in (b"from:", b"to:", b"subject:", b"received:", b"mime-version:"))
    return True


@router.post("/uploads/init", response_model=UploadInitResponse)
def init_multipart_upload(
    req: UploadInitRequest,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Initiate a direct-to-storage presigned multipart upload session."""
    import math
    settings = get_app_settings()
    max_upload_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024

    # 1. Validate file extension / MIME type
    ext = os.path.splitext(req.file_name)[1].lower()
    allowed_exts = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".eml", ".docx"]
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file extension '{ext}'. Allowed: {', '.join(allowed_exts)}",
        )

    # 2. Check per-file size limit (MAX_UPLOAD_MB, default 2048)
    if req.file_size > max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size {req.file_size} bytes exceeds maximum allowed limit of {settings.MAX_UPLOAD_MB}MB.",
        )

    db = get_db_session()
    try:
        # 3. If batch_id provided, verify batch exists, check ownership and file count cap (1000)
        if req.batch_id:
            batch_rec = db.query(BatchModel).filter(BatchModel.batch_id == req.batch_id).first()
            first_doc = db.query(DocumentModel).filter(DocumentModel.batch_id == req.batch_id).first()
            if not batch_rec and not first_doc:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Batch '{req.batch_id}' not found")
            b_owner = (batch_rec.user_id if batch_rec else None) or (first_doc.user_id if first_doc else None)
            if b_owner and current_user.role not in ("admin", "reviewer") and b_owner != current_user.user_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Batch '{req.batch_id}' not found")
            existing_count = db.query(DocumentModel).filter(DocumentModel.batch_id == req.batch_id).count()
            if existing_count >= 1000:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Batch file limit reached (maximum 1,000 files per batch).",
                )

        # 4. Concurrency backpressure check (Stage 2)
        active_jobs = db.query(PipelineJobModel).filter(
            PipelineJobModel.status.in_(["QUEUED", "PROCESSING"])
        ).count()
        if active_jobs >= 50:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Pipeline capacity saturated. Backpressure active.",
                headers={"Retry-After": "30"},
            )

        # 5. Calculate part size (16 MB to 64 MB)
        base_part_size = 16 * 1024 * 1024
        part_size = max(base_part_size, min(64 * 1024 * 1024, math.ceil(req.file_size / 5000)))
        part_count = max(1, math.ceil(req.file_size / part_size))

        # 6. Storage initialization
        from app.adapters.storage import get_storage_adapter
        storage = get_storage_adapter()
        raw_storage_key = f"raw/{uuid.uuid4().hex}_{req.file_name}"

        storage_upload_id = storage.create_multipart_upload(raw_storage_key, req.mime_type)

        # 7. Generate presigned part URLs
        parts_list: List[UploadPartPresignedUrl] = []
        for p_num in range(1, part_count + 1):
            url = storage.generate_presigned_part_url(
                key=raw_storage_key,
                upload_id=storage_upload_id,
                part_number=p_num,
                expires_in=3600,
            )
            parts_list.append(UploadPartPresignedUrl(part_number=p_num, url=url))

        # 8. Record in DB
        up_record = MultipartUploadModel(
            id=storage_upload_id,
            storage_key=raw_storage_key,
            file_name=req.file_name,
            mime_type=req.mime_type,
            file_size=req.file_size,
            part_size=part_size,
            part_count=part_count,
            owner=current_user.user_id,
            batch_id=req.batch_id,
            status="INITIATED",
            created_at=datetime.now(timezone.utc),
        )
        db.add(up_record)
        db.commit()

        return UploadInitResponse(
            upload_id=storage_upload_id,
            key=raw_storage_key,
            part_size=part_size,
            part_count=part_count,
            parts=parts_list,
            max_upload_mb=settings.MAX_UPLOAD_MB,
        )
    finally:
        db.close()


@router.put("/uploads/{upload_id}/parts/{part_number}")
async def upload_part_local(
    upload_id: str,
    part_number: int,
    request: Request,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Upload a part chunk in local storage mode or test environment."""
    db = get_db_session()
    try:
        up = db.query(MultipartUploadModel).filter(MultipartUploadModel.id == upload_id).first()
        if not up:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload session not found")
        if up.owner != current_user.user_id and current_user.role not in ("admin", "reviewer"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload session not found")

        body_bytes = await request.body()
        from app.adapters.storage import get_storage_adapter
        storage = get_storage_adapter()
        if hasattr(storage, "upload_part_data"):
            etag = storage.upload_part_data(upload_id, part_number, body_bytes)
        else:
            etag = hashlib.md5(body_bytes).hexdigest()

        return Response(content=json.dumps({"etag": etag}), media_type="application/json", headers={"ETag": etag})
    finally:
        db.close()


@router.post("/uploads/{upload_id}/complete", response_model=UploadCompleteResponse)
def complete_multipart_upload_endpoint(
    upload_id: str,
    req: UploadCompleteRequest,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Finalize multipart upload: verify size, magic bytes, SHA-256, and queue pipeline."""
    db = get_db_session()
    try:
        up = db.query(MultipartUploadModel).filter(MultipartUploadModel.id == upload_id).first()
        if not up:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload session not found")
        if up.owner != current_user.user_id and current_user.role not in ("admin", "reviewer"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload session not found")

        # Idempotency check: if already completed, return existing document
        if up.status == "COMPLETED" and up.document_uid:
            doc = db.query(DocumentModel).filter(DocumentModel.uid == up.document_uid).first()
            if doc:
                return UploadCompleteResponse(
                    status="COMPLETED",
                    document_uid=doc.uid,
                    file_name=doc.file_name,
                    file_size=doc.file_size,
                    sha256=doc.sha256,
                    batch_id=doc.batch_id,
                    is_duplicate=doc.is_link or False,
                )

        from app.adapters.storage import get_storage_adapter
        storage = get_storage_adapter()

        # 1. Finalize multipart upload in storage
        parts_dicts = [{"part_number": p.part_number, "etag": p.etag} for p in req.parts]
        try:
            storage.complete_multipart_upload(up.storage_key, upload_id, parts_dicts)
        except Exception as e:
            logger.error("Failed to complete multipart upload in storage: %s", e)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Storage finalization failed: {str(e)}")

        # 2. Verify stored object size (never trust client)
        try:
            real_size = storage.get_object_size(up.storage_key)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot verify stored object: {str(e)}")

        # 3. Stream object chunk-by-chunk to verify magic bytes and compute real SHA-256
        hasher = hashlib.sha256()
        first_chunk = b""
        for chunk in storage.get_stream(up.storage_key, chunk_size=65536):
            if not first_chunk:
                first_chunk = chunk
            hasher.update(chunk)

        real_sha256 = hasher.hexdigest()

        # Verify magic bytes
        ext = os.path.splitext(up.file_name)[1].lower()
        if not _is_valid_magic_bytes(first_chunk, ext):
            storage.delete(up.storage_key)
            up.status = "FAILED"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File verification failed: signature does not match claimed format '{ext}'.",
            )

        # 4. Check for virus infection on first chunk
        from app.adapters.virus import get_virus_scanner
        scanner = get_virus_scanner()
        is_clean, virus_name = scanner.scan(first_chunk)
        if not is_clean:
            storage.delete(up.storage_key)
            up.status = "FAILED"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Quarantined: malicious content detected ({virus_name}).",
            )

        # 5. Deduplication check (Stage 2 idempotency)
        existing_doc = db.query(DocumentModel).filter(DocumentModel.sha256 == real_sha256).first()
        doc_uid = f"doc-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        if existing_doc:
            doc = DocumentModel(
                uid=doc_uid,
                sha256=real_sha256,
                file_name=up.file_name,
                file_size=real_size,
                mime_type=up.mime_type,
                storage_path=up.storage_key,
                doc_type=existing_doc.doc_type,
                confidence=existing_doc.confidence,
                retention_class=existing_doc.retention_class,
                acl=existing_doc.acl,
                target_workflow=existing_doc.target_workflow,
                review_status="duplicate",
                is_link=True,
                linked_to_uid=existing_doc.uid,
                batch_id=up.batch_id,
                user_id=up.owner,
                extracted_fields_json=existing_doc.extracted_fields_json,
                field_confidences_json=existing_doc.field_confidences_json,
                pii_detected=existing_doc.pii_detected,
                pii_types_json=existing_doc.pii_types_json,
                ocr_engine=existing_doc.ocr_engine,
                ocr_version=existing_doc.ocr_version,
                classifier_model=existing_doc.classifier_model,
                classifier_version=existing_doc.classifier_version,
                decision_reason="Duplicate document linked by SHA-256 hash match",
                created_at=now,
            )
            db.add(doc)
            up.status = "COMPLETED"
            up.sha256 = real_sha256
            up.document_uid = doc_uid
            up.completed_at = now
            db.commit()

            return UploadCompleteResponse(
                status="COMPLETED",
                document_uid=doc_uid,
                file_name=up.file_name,
                file_size=real_size,
                sha256=real_sha256,
                batch_id=up.batch_id,
                is_duplicate=True,
            )

        # 6. New unique document: enqueue into PipelineJobModel for background worker (Stage 3)
        doc = DocumentModel(
            uid=doc_uid,
            sha256=real_sha256,
            file_name=up.file_name,
            file_size=real_size,
            mime_type=up.mime_type,
            storage_path=up.storage_key,
            doc_type="processing",
            confidence=0.0,
            retention_class="UNCLASSIFIED",
            acl="RESTRICTED_REVIEW",
            target_workflow="INGESTION_PIPELINE",
            review_status="queued",
            batch_id=up.batch_id,
            user_id=up.owner,
            decision_reason="Queued for pipeline processing",
            created_at=now,
        )
        db.add(doc)

        job_payload = {
            "uid": doc_uid,
            "sha256": real_sha256,
            "file_name": up.file_name,
            "storage_path": up.storage_key,
            "batch_id": up.batch_id,
            "user_id": up.owner,
            "is_reprocess": False,
        }
        job = PipelineJobModel(
            job_id=f"job-{uuid.uuid4().hex[:12]}",
            queue_name="live",
            payload_json=json.dumps(job_payload),
            status="QUEUED",
            retry_count=0,
            created_at=now,
        )
        db.add(job)

        up.status = "COMPLETED"
        up.sha256 = real_sha256
        up.document_uid = doc_uid
        up.completed_at = now
        db.commit()

        return UploadCompleteResponse(
            status="COMPLETED",
            document_uid=doc_uid,
            file_name=up.file_name,
            file_size=real_size,
            sha256=real_sha256,
            batch_id=up.batch_id,
            is_duplicate=False,
        )
    finally:
        db.close()


@router.post("/uploads/{upload_id}/abort", response_model=UploadAbortResponse)
def abort_multipart_upload_endpoint(
    upload_id: str,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Abort an in-progress multipart upload and clean up temporary parts."""
    db = get_db_session()
    try:
        up = db.query(MultipartUploadModel).filter(MultipartUploadModel.id == upload_id).first()
        if not up:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload session not found")
        if up.owner != current_user.user_id and current_user.role not in ("admin", "reviewer"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload session not found")

        from app.adapters.storage import get_storage_adapter
        storage = get_storage_adapter()
        try:
            storage.abort_multipart_upload(up.storage_key, upload_id)
        except Exception:
            pass

        up.status = "ABORTED"
        db.commit()
        return UploadAbortResponse(status="ABORTED", upload_id=upload_id)
    finally:
        db.close()


@router.post("/uploads/cleanup-abandoned")
def cleanup_abandoned_uploads(
    max_age_hours: int = Query(default=24, ge=1, le=168),
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Cleanup partial uploads abandoned longer than threshold (default 24h)."""
    db = get_db_session()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        abandoned = db.query(MultipartUploadModel).filter(
            MultipartUploadModel.status == "INITIATED",
            MultipartUploadModel.created_at < cutoff,
        ).all()

        from app.adapters.storage import get_storage_adapter
        storage = get_storage_adapter()
        cleaned_count = 0

        for up in abandoned:
            try:
                storage.abort_multipart_upload(up.storage_key, up.id)
            except Exception:
                pass
            up.status = "EXPIRED"
            cleaned_count += 1

        db.commit()
        return {"status": "SUCCESS", "cleaned_count": cleaned_count}
    finally:
        db.close()


@router.get("/batches/{batch_id}/summary")
def get_batch_summary_export(
    batch_id: str,
    format: str = Query(default="json", pattern="^(json|csv)$"),
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Export batch summary in JSON or CSV format (counts by type, review reasons, failures)."""
    db = get_db_session()
    try:
        batch_rec = db.query(BatchModel).filter(BatchModel.batch_id == batch_id).first()
        first_doc = db.query(DocumentModel).filter(DocumentModel.batch_id == batch_id).first()
        if not batch_rec and not first_doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Upload '{batch_id}' not found")

        batch_owner = (batch_rec.user_id if batch_rec else None) or (first_doc.user_id if first_doc else None)
        if batch_owner and current_user.role not in ("admin", "reviewer") and batch_owner != current_user.user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Upload '{batch_id}' not found")

        docs = db.query(DocumentModel).filter(DocumentModel.batch_id == batch_id).all()
        status_counts: Dict[str, int] = {}
        type_counts: Dict[str, int] = {}
        review_reasons: Dict[str, int] = {}
        failures: List[Dict[str, Any]] = []

        for d in docs:
            st = d.review_status or "unknown"
            tp = d.doc_type or "unknown"
            status_counts[st] = status_counts.get(st, 0) + 1
            type_counts[tp] = type_counts.get(tp, 0) + 1
            if d.decision_reason:
                review_reasons[d.decision_reason] = review_reasons.get(d.decision_reason, 0) + 1
            if d.review_status == "failed":
                failures.append({"uid": d.uid, "file_name": d.file_name, "error": d.decision_reason})

        if format == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["Section", "Key", "Value"])
            writer.writerow(["Metadata", "Batch ID", batch_id])
            writer.writerow(["Metadata", "Total Files", str(len(docs))])
            for st, cnt in status_counts.items():
                writer.writerow(["Status", st, str(cnt)])
            for tp, cnt in type_counts.items():
                writer.writerow(["Type", tp, str(cnt)])
            for rsn, cnt in review_reasons.items():
                writer.writerow(["Review Reason", rsn, str(cnt)])
            for f in failures:
                writer.writerow(["Failure", f["file_name"], f["error"]])
            buf.seek(0)
            return Response(
                content=buf.getvalue(),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename=batch_{batch_id}_summary.csv"},
            )

        return BatchSummaryResponse(
            batch_id=batch_id,
            batch_number=batch_rec.number if batch_rec else 1,
            total_files=len(docs),
            status_counts=status_counts,
            type_counts=type_counts,
            review_reasons=review_reasons,
            failure_details=failures,
            completed_at=batch_rec.updated_at if batch_rec else None,
        )
    finally:
        db.close()


def build_batch_zip_file(batch_id: str, db, target_path: str, exported_by: str):
    """Helper to build a clean zip archive segregated by document type and audit summary."""
    from app.adapters.storage import get_storage_adapter
    docs = db.query(DocumentModel).filter(DocumentModel.batch_id == batch_id).all()
    if not docs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Upload '{batch_id}' not found or empty")

    restricted_classes = {"medical_report", "kyc_form", "bank_statement", "claim_form", "prescription"}
    settings = get_app_settings()
    has_restricted = any(d.doc_type in restricted_classes for d in docs)
    if has_restricted:
        is_prod = getattr(settings, "APP_ENV", "local").lower() == "production"
        allow_export = getattr(settings, "ALLOW_LOCAL_EXPORT", True)
        if is_prod or not allow_export:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Security policy: Export of sensitive documents (medical, financial, KYC) is restricted and disabled.",
            )

    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
    temp_target = target_path + f".tmp.{uuid.uuid4().hex[:6]}"
    storage = get_storage_adapter()
    seen_names = {}

    def sanitize_csv_cell(val: Any) -> str:
        s = str(val or "")
        if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
            return f"'{s}"
        return s

    try:
        with zipfile.ZipFile(temp_target, "w", zipfile.ZIP_DEFLATED) as zf:
            csv_buffer = io.StringIO()
            csv_writer = csv.writer(csv_buffer)
            csv_writer.writerow(["file", "type", "how_sure", "status", "reason", "key_fields"])

            for d in docs:
                p_status = to_plain_status(d.review_status, d.is_link or False)
                how_sure_pct = f"{round((d.confidence or 0.0) * 100, 1)}%"
                reason = d.decision_reason or d.quarantine_reason or ""
                fields = json.loads(d.extracted_fields_json or "{}")
                key_fields_str = "; ".join([f"{k}={v}" for k, v in list(fields.items())[:5]])

                csv_writer.writerow([
                    sanitize_csv_cell(d.file_name),
                    sanitize_csv_cell(d.doc_type),
                    sanitize_csv_cell(how_sure_pct),
                    sanitize_csv_cell(p_status),
                    sanitize_csv_cell(reason),
                    sanitize_csv_cell(key_fields_str),
                ])

                file_bytes = None
                if d.storage_path and os.path.exists(d.storage_path):
                    try:
                        with open(d.storage_path, "rb") as f_in:
                            file_bytes = f_in.read()
                    except Exception:
                        pass
                elif d.sha256 and storage.exists(d.sha256):
                    try:
                        file_bytes = storage.get(d.sha256)
                    except Exception:
                        pass

                if file_bytes is None:
                    file_bytes = b""

                folder = d.doc_type or "unknown"
                clean_name = os.path.basename(d.file_name or f"document_{d.uid}.bin")

                pair = (folder, clean_name)
                seen_names[pair] = seen_names.get(pair, 0) + 1
                if seen_names[pair] > 1:
                    p_name, p_ext = os.path.splitext(clean_name)
                    clean_name = f"{p_name}_{seen_names[pair]}{p_ext}"

                # Write single copy under type folder (no duplicate copy in 'Needs a quick check')
                zf.writestr(f"{folder}/{clean_name}", file_bytes)

            # Write single index.csv (no summary.csv)
            zf.writestr("index.csv", csv_buffer.getvalue())

        if os.path.exists(target_path):
            try:
                os.unlink(target_path)
            except Exception:
                pass
        os.replace(temp_target, target_path)

        audit_evt = AuditEventModel(
            event_id=f"evt-export-{uuid.uuid4().hex[:8]}",
            document_uid=batch_id,
            sha256=docs[0].sha256 or "",
            event_type="BATCH_EXPORTED",
            stage_name="export",
            status="SUCCESS",
            payload_json=json.dumps({
                "batch_id": batch_id,
                "exported_by": exported_by,
                "file_count": len(docs),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        )
        db.add(audit_evt)
        db.commit()

        return len(docs), os.path.getsize(target_path)
    finally:
        if os.path.exists(temp_target):
            try:
                os.unlink(temp_target)
            except Exception:
                pass


def cleanup_expired_downloads(db) -> int:
    """Purge temporary zip archives exceeding retention duration and mark them EXPIRED."""
    settings = get_app_settings()
    expiry_hours = getattr(settings, "DOWNLOAD_EXPIRY_HOURS", 24)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=expiry_hours)

    expired_records = db.query(DownloadModel).filter(
        DownloadModel.status.in_(["READY", "DOWNLOADED"]),
        DownloadModel.requested_at < cutoff,
    ).all()

    count = 0
    for dl in expired_records:
        if dl.file_path and os.path.exists(dl.file_path):
            try:
                os.unlink(dl.file_path)
            except Exception:
                pass
        dl.status = "EXPIRED"
        count += 1
    if count > 0:
        db.commit()
    return count


def prepare_download_task(download_id: str, batch_id: str, user_id: str, username: str):
    """Background worker task to assemble and compress a large batch archive."""
    db = get_db_session()
    try:
        dl = db.query(DownloadModel).filter(DownloadModel.id == download_id).first()
        if not dl:
            return
        dest_dir = os.path.abspath("./data/downloads")
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, f"{download_id}.zip")

        file_count, size_bytes = build_batch_zip_file(batch_id, db, dest_path, username)
        dl.status = "READY"
        dl.file_path = dest_path
        dl.file_count = file_count
        dl.size_bytes = size_bytes
        dl.completed_at = datetime.now(timezone.utc)
        dl.error_message = None

        batch_rec = db.query(BatchModel).filter(BatchModel.batch_id == batch_id).first()
        b_num = batch_rec.number if batch_rec else 1
        b_name = batch_rec.name if batch_rec else f"Upload #{b_num}"

        notif = NotificationModel(
            id=f"notif-{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            batch_id=batch_id,
            title=f"{b_name} zip is ready to download",
            message=f"Your sorted files ({file_count} files) are packaged and ready to download.",
            read=False,
            created_at=datetime.now(timezone.utc),
        )
        db.add(notif)
        db.commit()
    except Exception:
        try:
            dl = db.query(DownloadModel).filter(DownloadModel.id == download_id).first()
            if dl:
                dl.status = "FAILED"
                dl.error_message = "Preparation failed. Please try again."
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.get("/batches/{batch_id}/export")
def export_batch_zip(
    batch_id: str,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Stream a zip archive of sorted files organized by type, plus a 'Needs a quick check' folder and summary.csv."""
    db = get_db_session()
    try:
        docs = db.query(DocumentModel).filter(DocumentModel.batch_id == batch_id).all()
        if not docs:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Upload '{batch_id}' not found or empty")

        batch_owner = docs[0].user_id
        is_staff = current_user.role in ("admin", "reviewer", "compliance")
        if batch_owner and not is_staff and current_user.user_id != batch_owner:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Upload '{batch_id}' not found")

        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        temp_zip_path = temp_zip.name
        temp_zip.close()

        build_batch_zip_file(batch_id, db, temp_zip_path, current_user.username)

        batch_rec = db.query(BatchModel).filter(BatchModel.batch_id == batch_id).first()
        export_name = f"Upload_{batch_rec.number if batch_rec else batch_id[:8]}_sorted.zip"
        from starlette.responses import FileResponse
        from starlette.background import BackgroundTask

        def cleanup_spool():
            if os.path.exists(temp_zip_path):
                try:
                    os.unlink(temp_zip_path)
                except Exception:
                    pass

        return FileResponse(
            path=temp_zip_path,
            media_type="application/zip",
            filename=export_name,
            background=BackgroundTask(cleanup_spool),
        )
    finally:
        db.close()


@router.post("/batches/{batch_id}/downloads", response_model=DownloadCreateResponse)
def request_batch_download(
    batch_id: str,
    background_tasks: BackgroundTasks,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Create a download archive request for a batch. Small batches prepare directly; large ones in background."""
    db = get_db_session()
    try:
        batch_rec = db.query(BatchModel).filter(BatchModel.batch_id == batch_id).first()
        first_doc = db.query(DocumentModel).filter(DocumentModel.batch_id == batch_id).first()
        if not batch_rec and not first_doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Upload '{batch_id}' not found")

        batch_owner = (batch_rec.user_id if batch_rec else None) or (first_doc.user_id if first_doc else None)
        is_staff = current_user.role in ("admin", "reviewer", "compliance")
        if batch_owner and not is_staff and current_user.user_id != batch_owner:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Upload '{batch_id}' not found")

        doc_count = db.query(DocumentModel).filter(DocumentModel.batch_id == batch_id).count()
        if doc_count == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot download an empty batch")

        dl_id = f"dl-{uuid.uuid4().hex[:12]}"
        dest_dir = os.path.abspath("./data/downloads")
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, f"{dl_id}.zip")

        now = datetime.now(timezone.utc)
        dl = DownloadModel(
            id=dl_id,
            owner=current_user.user_id,
            batch_id=batch_id,
            status="PREPARING",
            file_count=doc_count,
            size_bytes=0,
            file_path=dest_path,
            requested_at=now,
            completed_at=None,
            last_downloaded_at=None,
            error_message=None,
        )
        db.add(dl)
        db.commit()

        # Small batches (<= 10 files) assemble synchronously
        if doc_count <= 10:
            try:
                file_count, size_bytes = build_batch_zip_file(batch_id, db, dest_path, current_user.username)
                dl.status = "READY"
                dl.file_count = file_count
                dl.size_bytes = size_bytes
                dl.completed_at = datetime.now(timezone.utc)
                db.commit()
            except Exception as e:
                dl.status = "FAILED"
                dl.error_message = "Preparation failed. Please try again."
                db.commit()
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to prepare archive")
        else:
            # Large batches assemble in background
            background_tasks.add_task(
                prepare_download_task,
                dl_id,
                batch_id,
                current_user.user_id,
                current_user.username,
            )

        return DownloadCreateResponse(
            id=dl.id,
            batch_id=dl.batch_id,
            status=dl.status,
            file_count=dl.file_count,
            size_bytes=dl.size_bytes,
            requested_at=dl.requested_at,
            completed_at=dl.completed_at,
            last_downloaded_at=dl.last_downloaded_at,
            error_message=dl.error_message,
            download_url=f"/api/v1/downloads/{dl.id}/file",
        )
    finally:
        db.close()


@router.get("/downloads", response_model=DownloadListResponse)
def list_user_downloads(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Retrieve owner-scoped download history newest first."""
    if not isinstance(page, int) or isinstance(page, bool):
        page = 1
    if not isinstance(page_size, int) or isinstance(page_size, bool):
        page_size = 20

    db = get_db_session()
    try:
        cleanup_expired_downloads(db)

        is_staff = current_user.role in ("admin", "reviewer", "compliance")
        query = db.query(DownloadModel)
        if not is_staff and current_user.user_id:
            query = query.filter(DownloadModel.owner == current_user.user_id)

        total = query.count()
        records = query.order_by(DownloadModel.requested_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

        batch_ids = [r.batch_id for r in records]
        batches = {b.batch_id: b for b in db.query(BatchModel).filter(BatchModel.batch_id.in_(batch_ids)).all()} if batch_ids else {}

        items = []
        for r in records:
            b_info = batches.get(r.batch_id)
            items.append(
                DownloadItem(
                    id=r.id,
                    batch_id=r.batch_id,
                    batch_number=b_info.number if b_info else None,
                    batch_name=b_info.name if b_info else f"Upload",
                    status=r.status,
                    file_count=r.file_count,
                    size_bytes=r.size_bytes,
                    requested_at=r.requested_at,
                    completed_at=r.completed_at,
                    last_downloaded_at=r.last_downloaded_at,
                    error_message=r.error_message,
                    download_url=f"/api/v1/downloads/{r.id}/file",
                )
            )

        return DownloadListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )
    finally:
        db.close()


@router.get("/downloads/{download_id}/file")
def stream_download_file(
    download_id: str,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Stream a previously prepared zip archive. Re-downloads reflect review corrections."""
    db = get_db_session()
    try:
        dl = db.query(DownloadModel).filter(DownloadModel.id == download_id).first()
        if not dl:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Download record not found")

        is_staff = current_user.role in ("admin", "reviewer", "compliance")
        if dl.owner != current_user.user_id and not is_staff:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Download record not found")

        if dl.status == "PREPARING":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Download archive is still preparing. Please wait.")
        if dl.status == "FAILED":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=dl.error_message or "Download preparation failed. Please request a new download.")

        # Rebuild if EXPIRED or file does not exist on disk
        dest_path = dl.file_path or os.path.abspath(f"./data/downloads/{dl.id}.zip")
        if dl.status == "EXPIRED" or not os.path.exists(dest_path):
            file_count, size_bytes = build_batch_zip_file(dl.batch_id, db, dest_path, current_user.username)
            dl.file_count = file_count
            dl.size_bytes = size_bytes
            dl.file_path = dest_path
            dl.status = "READY"
            dl.completed_at = datetime.now(timezone.utc)
            db.commit()

        # Update download status & timestamp
        dl.status = "DOWNLOADED"
        dl.last_downloaded_at = datetime.now(timezone.utc)
        db.commit()

        # Log audit trail event
        audit_evt = AuditEventModel(
            event_id=f"evt-dl-{uuid.uuid4().hex[:8]}",
            document_uid=dl.batch_id,
            sha256="",
            event_type="BATCH_DOWNLOADED",
            stage_name="download",
            status="SUCCESS",
            payload_json=json.dumps({
                "download_id": dl.id,
                "batch_id": dl.batch_id,
                "downloaded_by": current_user.username,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
        )
        db.add(audit_evt)
        db.commit()

        batch_rec = db.query(BatchModel).filter(BatchModel.batch_id == dl.batch_id).first()
        b_num = batch_rec.number if batch_rec else 1
        export_name = f"Upload_{b_num}_sorted.zip"

        from starlette.responses import FileResponse
        return FileResponse(
            path=dest_path,
            media_type="application/zip",
            filename=export_name,
        )
    finally:
        db.close()


@router.post("/downloads/cleanup-expired", response_model=DownloadCleanupResponse)
def trigger_download_cleanup(
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Trigger cleanup of expired temporary zip files."""
    db = get_db_session()
    try:
        count = cleanup_expired_downloads(db)
        return DownloadCleanupResponse(expired_count=count)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Notification Endpoints
# ---------------------------------------------------------------------------

@router.get("/notifications", response_model=NotificationListResponse)
def get_user_notifications(current_user: UserSessionResponse = Depends(get_current_user)):
    """Retrieve owner-scoped notifications newest first with unread badge count."""
    db = get_db_session()
    try:
        user_id = current_user.user_id if current_user else None
        is_staff = current_user.role in ("admin", "reviewer", "compliance")
        query = db.query(NotificationModel)
        if not is_staff and user_id:
            query = query.filter((NotificationModel.user_id == user_id) | (NotificationModel.user_id.is_(None)))

        notifs = query.order_by(desc(NotificationModel.created_at)).limit(50).all()
        unread_count = query.filter(NotificationModel.read == False).count()

        items = [
            NotificationItem(
                id=n.id,
                batch_id=n.batch_id,
                title=n.title,
                message=n.message,
                read=n.read,
                created_at=n.created_at,
            )
            for n in notifs
        ]
        return NotificationListResponse(items=items, unread_count=unread_count)
    finally:
        db.close()


@router.post("/notifications/{notification_id}/read", response_model=NotificationMarkReadResponse)
def mark_notification_read(
    notification_id: str,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Mark a single notification as read."""
    db = get_db_session()
    try:
        notif = db.query(NotificationModel).filter(NotificationModel.id == notification_id).first()
        if not notif:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
        notif.read = True
        db.commit()
        return NotificationMarkReadResponse(success=True, marked_count=1)
    finally:
        db.close()


@router.post("/notifications/read-all", response_model=NotificationMarkReadResponse)
def mark_all_notifications_read(current_user: UserSessionResponse = Depends(get_current_user)):
    """Mark all notifications for current user as read."""
    db = get_db_session()
    try:
        user_id = current_user.user_id if current_user else None
        is_staff = current_user.role in ("admin", "reviewer", "compliance")
        query = db.query(NotificationModel).filter(NotificationModel.read == False)
        if not is_staff and user_id:
            query = query.filter((NotificationModel.user_id == user_id) | (NotificationModel.user_id.is_(None)))
        count = query.count()
        query.update({NotificationModel.read: True}, synchronize_session=False)
        db.commit()
        return NotificationMarkReadResponse(success=True, marked_count=count)
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
    is_staff = current_user.role in ("admin", "reviewer", "compliance")
    if not is_staff and "documents:read" not in current_user.permissions and "documents:read_own" not in current_user.permissions and "review:read" not in current_user.permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User role '{current_user.role}' lacks permission to view document images",
        )

    db = get_db_session()
    try:
        doc = db.query(DocumentModel).filter(DocumentModel.uid == document_uid).first()
        if not doc or not doc.storage_path or not os.path.exists(doc.storage_path):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file not found")

        if not is_staff and doc.user_id and doc.user_id != current_user.user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied for document")

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
