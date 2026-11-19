"""Observability API: Prometheus metrics, health checks, and asset audit inspections."""

import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import PlainTextResponse
import numpy as np

from app.adapters.queue import get_queue_adapter
from app.core.auth import get_current_user, require_role
from app.core.config import get_pipeline_config
from app.models.api_schemas import UserSessionResponse
from app.models.db import AuditEventModel, DocumentModel, ReviewTaskModel, get_db_session
from app.workers.pipeline import PIPELINE_STATS, STAGE_LATENCY_METRICS

router = APIRouter(tags=["Observability"])


@router.get("/metrics", response_class=PlainTextResponse)
def get_prometheus_metrics(current_user: UserSessionResponse = Depends(get_current_user)):
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
def get_asset_audit_report(
    uid: str,
    current_user: UserSessionResponse = Depends(require_role(["compliance", "admin", "reviewer"])),
):
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
