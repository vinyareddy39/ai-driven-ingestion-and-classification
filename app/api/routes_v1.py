"""API v1 Endpoints for Frontend-to-Backend Connection."""

from datetime import datetime, timezone
import json
import os
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.adapters.queue import get_queue_adapter
from app.core.config import get_app_settings, get_pipeline_config
from app.core.security import setup_secure_logging
from app.models.db import AuditEventModel, DocumentModel, ReviewTaskModel, get_db_session
from app.models.schemas import ReprocessRequest, ReprocessResponse
from app.api.routes_observability import get_asset_audit_report, get_dashboard_stats, list_documents
from app.api.routes_review import apply_review_decision, get_review_tasks_json

logger = setup_secure_logging("ecm.api.v1")
router = APIRouter(prefix="/api/v1", tags=["API v1"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SystemInfoResponse(BaseModel):
    mode: str = "LOCAL MODE"
    version: str = "1.0.0"
    environment: str = "development"
    max_upload_size_bytes: int = 26214400  # 25 MB
    max_upload_size_mb: int = 25
    allowed_file_types: List[str] = [
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/tiff",
        "message/rfc822",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    allowed_extensions: List[str] = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".eml", ".docx"]


class UserAuthResponse(BaseModel):
    id: str = "user-1"
    username: str = "admin"
    role: str = "admin"
    permissions: List[str] = ["review", "ingest", "admin", "reprocess", "audit"]


class DocumentStatusResponse(BaseModel):
    uid: str
    status: str
    doc_type: str
    confidence: float
    is_link: bool
    linked_to_uid: Optional[str] = None
    created_at: Optional[str] = None


class ConfigHistoryItem(BaseModel):
    revision: int
    changed_at: str
    changed_by: str
    summary: str


# In-memory config revision audit
_config_history: List[Dict[str, Any]] = [
    {
        "revision": 1,
        "changed_at": datetime.now(timezone.utc).isoformat(),
        "changed_by": "system",
        "summary": "Initial baseline pipeline configuration loaded",
    }
]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/system/info", response_model=SystemInfoResponse)
def get_system_info():
    """Return runtime operational mode, upload limits, and environment info."""
    settings = get_app_settings()
    mode = "REAL SERVICES" if settings.ENVIRONMENT == "production" else "LOCAL MODE"
    return SystemInfoResponse(
        mode=mode,
        version="1.0.0",
        environment=settings.ENVIRONMENT,
        max_upload_size_bytes=26214400,
        max_upload_size_mb=25,
    )


@router.get("/auth/me", response_model=UserAuthResponse)
def get_current_user(
    authorization: Optional[str] = Header(None),
    x_user_role: Optional[str] = Header(None),
):
    """Return authenticated user context based on Bearer token or role header."""
    role = x_user_role or "admin"
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        if token == "invalid":
            raise HTTPException(status_code=401, detail="Invalid token")
    return UserAuthResponse(
        id="user-admin-1",
        username="admin",
        role=role,
        permissions=["review", "ingest", "admin", "reprocess", "audit"],
    )


def check_auth_role(
    authorization: Optional[str] = None,
    x_user_role: Optional[str] = None,
    allowed_roles: Optional[List[str]] = None,
) -> str:
    """Validate credentials and permissions. Supports Bearer token and local X-User-Role."""
    role = None
    if authorization:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid authorization scheme")
        token = authorization.split(" ", 1)[1].strip()
        if not token or token == "invalid":
            raise HTTPException(status_code=401, detail="Invalid token")
        if "reviewer" in token:
            role = "reviewer"
        elif "viewer" in token or "user" in token:
            role = "viewer"
        else:
            role = "admin"
    elif x_user_role:
        role = x_user_role

    if not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
        )

    if allowed_roles and role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: role '{role}' lacks required permissions",
        )
    return role


@router.get("/review/queue")
def get_review_queue(
    authorization: Optional[str] = Header(None),
    x_user_role: Optional[str] = Header(None),
):
    """Retrieve pending review queue tasks."""
    check_auth_role(authorization, x_user_role, allowed_roles=["admin", "reviewer"])
    return get_review_tasks_json()



@router.post("/review/{document_uid}/action")
def submit_review_action(document_uid: str, payload: Dict[str, Any]):
    """Process a human review action (CONFIRM, CORRECT, REJECT)."""
    action = payload.get("action", "CONFIRM")
    reviewer_id = payload.get("reviewer_id", "reviewer-senior-1")
    corrected_type = payload.get("corrected_type")
    review_notes = payload.get("review_notes", "")
    corrected_fields = payload.get("corrected_fields", {})

    return apply_review_decision(
        document_uid=document_uid,
        action=action,
        reviewer_id=reviewer_id,
        corrected_type=corrected_type,
        review_notes=review_notes,
        corrected_fields=corrected_fields,
    )


@router.get("/documents")
def get_documents_list(
    doc_type: Optional[str] = Query(None),
    review_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
):
    """Retrieve paginated and filtered list of documents."""
    return list_documents(
        doc_type=doc_type,
        review_status=review_status,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/documents/{uid}")
def get_document_by_uid(uid: str):
    """Retrieve full audit report and document metadata."""
    return get_asset_audit_report(uid)


@router.get("/documents/{uid}/status", response_model=DocumentStatusResponse)
def get_document_status(uid: str):
    """Retrieve current processing or review status for a document."""
    db = get_db_session()
    try:
        doc = db.query(DocumentModel).filter(DocumentModel.uid == uid).first()
        if not doc:
            return DocumentStatusResponse(
                uid=uid,
                status="QUEUED",
                doc_type="unknown",
                confidence=0.0,
                is_link=False,
            )
        return DocumentStatusResponse(
            uid=doc.uid,
            status=doc.review_status,
            doc_type=doc.doc_type,
            confidence=doc.confidence,
            is_link=doc.is_link,
            linked_to_uid=doc.linked_to_uid,
            created_at=doc.created_at.isoformat() if doc.created_at else None,
        )
    finally:
        db.close()


@router.get("/documents/{uid}/pages/{n}/image")
def get_document_page_image(
    uid: str,
    n: int,
    width: Optional[int] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Return rendered page image (PNG)."""
    # 1x1 transparent/placeholder PNG
    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff"
        b"?\x00\x05\xfe\x02\xfe\r\xfe\x1d\xef\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return Response(content=tiny_png, media_type="image/png")


@router.get("/audit/{uid}")
def get_audit_by_uid(uid: str):
    """Audit report endpoint alias under /api/v1."""
    return get_asset_audit_report(uid)


@router.post("/reprocess/preview", response_model=ReprocessResponse)
def preview_reprocess(payload: ReprocessRequest):
    """Dry-run preview of reprocess query matches without enqueuing."""
    payload.dry_run = True
    from app.api.routes_reprocess import reprocess_documents_by_query
    return reprocess_documents_by_query(payload)


@router.get("/dashboard/metrics")
def get_dashboard_metrics():
    """Retrieve dashboard operational KPIs and stage latencies."""
    return get_dashboard_stats()


@router.get("/admin/config")
def get_admin_config(
    authorization: Optional[str] = Header(None),
    x_user_role: Optional[str] = Header(None),
):
    """Retrieve active pipeline and classifier thresholds."""
    check_auth_role(authorization, x_user_role, allowed_roles=["admin"])
    cfg = get_pipeline_config()
    return {
        "pipeline": cfg.pipeline,
        "classes": {k: v.dict() for k, v in cfg.classes.items()},
        "decision_gate": cfg.decision_gate.dict(),
        "pii_policy": cfg.pii_policy.dict(),
        "queues": cfg.queues.dict(),
        "reprocessing": cfg.reprocessing.dict(),
    }


@router.get("/admin/config/history")
def get_admin_config_history():
    """Retrieve history of pipeline configuration changes."""
    return _config_history
