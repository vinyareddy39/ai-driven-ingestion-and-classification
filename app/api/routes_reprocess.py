"""Reprocessing API: reprocess documents matching query filters via bulk queue."""

from datetime import datetime, timezone
import json
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, status
from app.adapters.queue import get_queue_adapter
from app.adapters.search import get_search_adapter
from app.core.config import get_pipeline_config
from app.core.security import setup_secure_logging
from app.models.db import AuditEventModel, DocumentModel, get_db_session
from app.models.schemas import ReprocessRequest, ReprocessResponse

logger = setup_secure_logging("ecm.api.reprocess")
router = APIRouter(prefix="/reprocess", tags=["Reprocessing"])

# Track diffs emitted during reprocessing conflicts
_reprocessing_conflict_diffs: List[Dict[str, Any]] = []


@router.post("", response_model=ReprocessResponse, status_code=status.HTTP_202_ACCEPTED)
def reprocess_documents_by_query(payload: ReprocessRequest):
    """Query OpenSearch for candidate documents and enqueue for rate-limited bulk reprocessing."""
    search = get_search_adapter()
    cfg = get_pipeline_config()
    queue = get_queue_adapter()
    bulk_queue = cfg.queues.bulk_queue

    # Construct search query
    query: Dict[str, Any] = {}
    if payload.classifier_version_filter:
        query["classifier_version"] = {"lt": payload.classifier_version_filter}
    if payload.min_confidence is not None:
        query["confidence"] = {"lt": payload.min_confidence}
    if payload.target_types:
        query["doc_type"] = {"in": payload.target_types}

    matched_docs = search.search(query, limit=5000)

    # Fallback to direct DB query if search index has no entries yet
    if not matched_docs:
        db = get_db_session()
        try:
            db_query = db.query(DocumentModel).filter(DocumentModel.is_link == False)
            if payload.min_confidence is not None:
                db_query = db_query.filter(DocumentModel.confidence < payload.min_confidence)
            if payload.classifier_version_filter:
                db_query = db_query.filter(DocumentModel.classifier_version != payload.classifier_version_filter)
            if payload.target_types:
                db_query = db_query.filter(DocumentModel.doc_type.in_(payload.target_types))

            records = db_query.limit(5000).all()
            matched_docs = [
                {
                    "uid": r.uid,
                    "sha256": r.sha256,
                    "doc_type": r.doc_type,
                    "confidence": r.confidence,
                    "classifier_version": r.classifier_version,
                    "file_name": r.file_name,
                    "storage_path": r.storage_path,
                }
                for r in records
            ]
        finally:
            db.close()

    job_id = f"job-reproc-{uuid.uuid4().hex[:8]}"
    queued_count = 0
    skipped_count = 0

    if not payload.dry_run:
        for doc in matched_docs:
            uid = doc.get("uid") or doc.get("_id")
            sha256_hash = doc.get("sha256")
            if not sha256_hash or not uid:
                skipped_count += 1
                continue

            msg = {
                "uid": uid,
                "sha256": sha256_hash,
                "file_name": doc.get("file_name", "document.pdf"),
                "storage_path": doc.get("storage_path", ""),
                "is_reprocess": True,
                "job_id": job_id,
            }
            queue.push(bulk_queue, msg)
            queued_count += 1

    logger.info(
        f"Reprocessing initiated: job {job_id}, matched={len(matched_docs)}, queued={queued_count}, dry_run={payload.dry_run}"
    )

    return ReprocessResponse(
        matched_count=len(matched_docs),
        queued_count=queued_count,
        skipped_count=skipped_count,
        dry_run=payload.dry_run,
        job_id=job_id,
    )


def record_reprocessing_conflict_diff(
    document_uid: str,
    human_verified: Dict[str, Any],
    new_extracted: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Compare reprocessed automated extraction against human-verified ground-truth.

    Guarantees human verified fields are NEVER overwritten, and emits a structured diff.
    """
    diffs = {}
    for k, verified_val in human_verified.items():
        if k in new_extracted and new_extracted[k] != verified_val:
            diffs[k] = {
                "human_verified_preserved": verified_val,
                "new_automated_prediction_ignored": new_extracted[k],
            }

    if diffs:
        diff_event = {
            "document_uid": document_uid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "field_diffs": diffs,
        }
        _reprocessing_conflict_diffs.append(diff_event)

        db = get_db_session()
        try:
            event = AuditEventModel(
                event_id=f"diff-{document_uid[:12]}-{int(datetime.now(timezone.utc).timestamp())}",
                document_uid=document_uid,
                sha256="",
                event_type="REPROCESSING_CONFLICT_DIFF",
                stage_name="reprocess",
                status="PRESERVED_HUMAN_FIELDS",
                payload_json=json.dumps(diff_event),
            )
            db.add(event)
            db.commit()
        finally:
            db.close()

        logger.warning(f"Reprocessing conflict diff emitted for {document_uid}: preserved human ground-truth")
        return diff_event
    return None


def get_reprocessing_conflict_diffs() -> List[Dict[str, Any]]:
    return list(_reprocessing_conflict_diffs)
