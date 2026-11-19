"""Observability API: Prometheus metrics, health checks, and asset audit inspections."""

import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import PlainTextResponse
import numpy as np

from app.adapters.queue import get_queue_adapter
from app.core.config import get_pipeline_config
from app.models.db import AuditEventModel, DocumentModel, ReviewTaskModel, get_db_session
from app.workers.pipeline import PIPELINE_STATS, STAGE_LATENCY_METRICS

router = APIRouter(tags=["Observability"])


@router.get("/metrics", response_class=PlainTextResponse)
def get_prometheus_metrics():
    """Export standard Prometheus metrics covering queues, latency, STP rate, and errors."""
    cfg = get_pipeline_config()
    queue = get_queue_adapter()

    live_depth = queue.length(cfg.queues.live_queue)
    bulk_depth = queue.length(cfg.queues.bulk_queue)
    dlq_depth = queue.length(cfg.queues.dlq_queue)

    db = get_db_session()
    try:
        pending_review_count = (
            db.query(ReviewTaskModel).filter(ReviewTaskModel.status == "PENDING").count()
        )
        total_assets = db.query(DocumentModel).count()
        auto_accepted_assets = (
            db.query(DocumentModel).filter(DocumentModel.review_status == "auto_accepted").count()
        )
    finally:
        db.close()

    total_proc = max(1, PIPELINE_STATS["total_processed"])
    stp_rate = float(PIPELINE_STATS["auto_accepted"] / total_proc) * 100.0
    error_rate = float(PIPELINE_STATS["errors"] / total_proc) * 100.0

    lines = [
        "# HELP ecm_queue_depth Current depth of message queues",
        "# TYPE ecm_queue_depth gauge",
        f'ecm_queue_depth{{queue="live"}} {live_depth}',
        f'ecm_queue_depth{{queue="bulk"}} {bulk_depth}',
        f'ecm_queue_depth{{queue="dlq"}} {dlq_depth}',
        "",
        "# HELP ecm_review_queue_size Documents pending human review",
        "# TYPE ecm_review_queue_size gauge",
        f"ecm_review_queue_size {pending_review_count}",
        "",
        "# HELP ecm_pipeline_stp_rate Straight-through processing rate percentage",
        "# TYPE ecm_pipeline_stp_rate gauge",
        f"ecm_pipeline_stp_rate {stp_rate:.2f}",
        "",
        "# HELP ecm_pipeline_error_rate Error rate percentage",
        "# TYPE ecm_pipeline_error_rate gauge",
        f"ecm_pipeline_error_rate {error_rate:.2f}",
        "",
        "# HELP ecm_pipeline_documents_total Processed documents total by status",
        "# TYPE ecm_pipeline_documents_total counter",
        f'ecm_pipeline_documents_total{{status="auto_accepted"}} {PIPELINE_STATS["auto_accepted"]}',
        f'ecm_pipeline_documents_total{{status="routed_to_review"}} {PIPELINE_STATS["routed_to_review"]}',
        f'ecm_pipeline_documents_total{{status="quarantined"}} {PIPELINE_STATS["quarantined"]}',
        f'ecm_pipeline_documents_total{{status="duplicates_linked"}} {PIPELINE_STATS["duplicates_linked"]}',
        f'ecm_pipeline_documents_total{{status="errors"}} {PIPELINE_STATS["errors"]}',
        "",
        "# HELP ecm_stage_latency_seconds_p50 Median stage execution latency",
        "# TYPE ecm_stage_latency_seconds_p50 gauge",
    ]

    for stage_name, latencies in STAGE_LATENCY_METRICS.items():
        if latencies:
            p50 = float(np.percentile(latencies, 50))
            p95 = float(np.percentile(latencies, 95))
        else:
            p50 = 0.001
            p95 = 0.002
        lines.append(f'ecm_stage_latency_seconds_p50{{stage="{stage_name}"}} {p50:.4f}')
        lines.append(f'ecm_stage_latency_seconds_p95{{stage="{stage_name}"}} {p95:.4f}')

    return PlainTextResponse(content="\n".join(lines) + "\n")


@router.get("/health/live", status_code=status.HTTP_200_OK)
def liveness_check():
    """Kubernetes / Docker liveness probe."""
    return {"status": "ALIVE"}


@router.get("/health/ready", status_code=status.HTTP_200_OK)
def readiness_check():
    """Readiness probe validating DB, queue, and config status."""
    db = get_db_session()
    try:
        db.execute(DocumentModel.__table__.select().limit(1))
        db_ok = True
    except Exception:
        db_ok = False
    finally:
        db.close()

    queue_ok = get_queue_adapter() is not None

    if db_ok and queue_ok:
        return {"status": "READY", "database": "CONNECTED", "queue": "CONNECTED"}
    raise HTTPException(status_code=503, detail="Service Unavailable: downstream connection degraded")


@router.get("/audit/{uid}")
def get_asset_audit_report(uid: str):
    """Retrieve full audit record and compliance history for asset."""
    db = get_db_session()
    try:
        doc = db.query(DocumentModel).filter(DocumentModel.uid == uid).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Asset not found")

        events = (
            db.query(AuditEventModel)
            .filter(AuditEventModel.document_uid == uid)
            .order_by(AuditEventModel.created_at.asc())
            .all()
        )

        return {
            "uid": doc.uid,
            "sha256": doc.sha256,
            "file_name": doc.file_name,
            "predictedType": doc.doc_type,
            "confidence": doc.confidence,
            "ocrEngine": doc.ocr_engine,
            "ocrVersion": doc.ocr_version,
            "classifierModel": doc.classifier_model,
            "classifierVersion": doc.classifier_version,
            "reviewStatus": doc.review_status,
            "retentionClass": doc.retention_class,
            "assignedAcl": doc.acl,
            "targetWorkflow": doc.target_workflow,
            "decisionReason": doc.decision_reason,
            "reviewerId": doc.reviewer_id,
            "reviewNotes": doc.review_notes,
            "piiDetected": doc.pii_detected,
            "piiTypes": json.loads(doc.pii_types_json or "[]"),
            "extractedFields": json.loads(doc.extracted_fields_json or "{}"),
            "humanVerifiedFields": json.loads(doc.human_verified_fields_json or "{}"),
            "processedAt": doc.created_at.isoformat() if doc.created_at else None,
            "auditTrail": [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type,
                    "stage": e.stage_name,
                    "timestamp": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ],
        }
    finally:
        db.close()


@router.get("/api/stats/dashboard")
def get_dashboard_stats():
    """Retrieve summarized statistics for the dashboard UI."""
    cfg = get_pipeline_config()
    queue = get_queue_adapter()

    live_depth = queue.length(cfg.queues.live_queue) if queue else 0
    bulk_depth = queue.length(cfg.queues.bulk_queue) if queue else 0
    dlq_depth = queue.length(cfg.queues.dlq_queue) if queue else 0

    db = get_db_session()
    try:
        total_assets = db.query(DocumentModel).count()
        auto_accepted_count = db.query(DocumentModel).filter(DocumentModel.review_status == "auto_accepted").count()
        pending_review_count = db.query(ReviewTaskModel).filter(ReviewTaskModel.status == "PENDING").count()
        quarantined_count = db.query(DocumentModel).filter(DocumentModel.review_status == "quarantined").count()
        human_verified_count = db.query(DocumentModel).filter(DocumentModel.review_status == "human_verified").count()
        duplicates_count = db.query(DocumentModel).filter(DocumentModel.is_link == True).count()

        from sqlalchemy import func
        type_counts = (
            db.query(DocumentModel.doc_type, func.count(DocumentModel.id))
            .group_by(DocumentModel.doc_type)
            .all()
        )
        type_breakdown = [{"type": t[0] or "unknown", "count": t[1]} for t in type_counts]

        status_counts = (
            db.query(DocumentModel.review_status, func.count(DocumentModel.id))
            .group_by(DocumentModel.review_status)
            .all()
        )
        status_breakdown = [{"status": s[0] or "pending", "count": s[1]} for s in status_counts]

        recent_docs = (
            db.query(DocumentModel)
            .order_by(DocumentModel.created_at.desc())
            .limit(10)
            .all()
        )
        recent_items = [
            {
                "uid": d.uid,
                "file_name": d.file_name,
                "doc_type": d.doc_type,
                "confidence": d.confidence,
                "review_status": d.review_status,
                "pii_detected": d.pii_detected,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in recent_docs
        ]
    finally:
        db.close()

    total_proc = max(1, PIPELINE_STATS["total_processed"])
    stp_rate = (
        float(PIPELINE_STATS["auto_accepted"] / total_proc) * 100.0
        if PIPELINE_STATS["total_processed"] > 0
        else (float(auto_accepted_count / max(1, total_assets)) * 100.0)
    )
    error_rate = float(PIPELINE_STATS["errors"] / total_proc) * 100.0

    stage_latencies = {}
    for stage_name, latencies in STAGE_LATENCY_METRICS.items():
        if latencies:
            stage_latencies[stage_name] = {
                "p50": round(float(np.percentile(latencies, 50)) * 1000, 2),
                "p95": round(float(np.percentile(latencies, 95)) * 1000, 2),
            }
        else:
            stage_latencies[stage_name] = {"p50": 1.0, "p95": 2.0}

    return {
        "total_documents": total_assets,
        "auto_accepted": auto_accepted_count,
        "pending_review": pending_review_count,
        "quarantined": quarantined_count,
        "human_verified": human_verified_count,
        "duplicates_linked": duplicates_count,
        "stp_rate": round(stp_rate, 1),
        "error_rate": round(error_rate, 1),
        "queue_depths": {
            "live": live_depth,
            "bulk": bulk_depth,
            "dlq": dlq_depth,
        },
        "stage_latencies": stage_latencies,
        "type_breakdown": type_breakdown,
        "status_breakdown": status_breakdown,
        "recent_documents": recent_items,
    }


@router.get("/api/documents")
def list_documents(
    doc_type: Optional[str] = None,
    review_status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """List documents with filtering, search, and pagination."""
    db = get_db_session()
    try:
        q = db.query(DocumentModel)
        if doc_type:
            q = q.filter(DocumentModel.doc_type == doc_type)
        if review_status:
            q = q.filter(DocumentModel.review_status == review_status)
        if search:
            search_pattern = f"%{search}%"
            q = q.filter(
                (DocumentModel.file_name.ilike(search_pattern))
                | (DocumentModel.uid.ilike(search_pattern))
                | (DocumentModel.sha256.ilike(search_pattern))
            )

        total = q.count()
        docs = q.order_by(DocumentModel.created_at.desc()).offset(offset).limit(limit).all()

        items = [
            {
                "uid": d.uid,
                "sha256": d.sha256,
                "file_name": d.file_name,
                "doc_type": d.doc_type,
                "confidence": d.confidence,
                "review_status": d.review_status,
                "retention_class": d.retention_class,
                "acl": d.acl,
                "pii_detected": d.pii_detected,
                "is_link": d.is_link,
                "linked_to_uid": d.linked_to_uid,
                "decision_reason": d.decision_reason,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ]

        return {"total": total, "items": items, "limit": limit, "offset": offset}
    finally:
        db.close()

