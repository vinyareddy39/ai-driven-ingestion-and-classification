"""Pipeline orchestrator running stages sequentially with transactional idempotency."""

import argparse
import json
import time
from typing import Any, Dict, List, Optional
from app.adapters.ecm import get_ecm_adapter
from app.adapters.queue import get_queue_adapter
from app.adapters.storage import get_storage_adapter
from app.core.config import get_pipeline_config
from app.core.idempotency import get_idempotency_registry
from app.core.security import setup_secure_logging
from app.models.db import DocumentModel, get_db_session
from app.workers.dlq import DeadLetterQueueHandler
from app.workers.rate_limiter import TokenBucketRateLimiter
from app.workers.stages import (
    stage_audit_record,
    stage_classify,
    stage_decision_gate,
    stage_dedupe,
    stage_extract_fields,
    stage_index_search,
    stage_ocr,
    stage_pii_detect,
    stage_preprocess,
    stage_split_document,
    stage_virus_scan,
    stage_write_ecm,
)

logger = setup_secure_logging("ecm.pipeline")

# In-memory stage latency metrics for Prometheus observability
STAGE_LATENCY_METRICS: Dict[str, List[float]] = {
    "virus_scan": [],
    "dedupe": [],
    "preprocess": [],
    "ocr": [],
    "classify": [],
    "extract_fields": [],
    "pii_detect": [],
    "decision_gate": [],
    "ecm_write": [],
    "search_index": [],
    "audit": [],
}
PIPELINE_STATS = {
    "total_processed": 0,
    "auto_accepted": 0,
    "routed_to_review": 0,
    "quarantined": 0,
    "duplicates_linked": 0,
    "errors": 0,
}


def quarantine_document(
    uid: str,
    sha256_hash: str,
    file_name: str,
    storage_path: str,
    reason: str,
    batch_id: Optional[str] = None,
) -> None:
    """Quarantine corrupt, infected, or password-protected document."""
    db = get_db_session()
    try:
        doc = db.query(DocumentModel).filter(DocumentModel.uid == uid).first()
        if not doc:
            doc = DocumentModel(
                uid=uid,
                sha256=sha256_hash,
                file_name=file_name,
                storage_path=storage_path,
                doc_type="unknown",
                confidence=0.0,
                retention_class="QUARANTINE_HOLD",
                acl="RESTRICTED_SECURITY",
                target_workflow="SECURITY_INCIDENT_TRIAGE",
                review_status="quarantined",
                quarantine_reason=reason,
                decision_reason=reason,
                batch_id=batch_id,
            )
            db.add(doc)
        else:
            doc.review_status = "quarantined"
            doc.quarantine_reason = reason
            doc.decision_reason = reason
            if batch_id:
                doc.batch_id = batch_id
        db.commit()
    finally:
        db.close()

    dlq = DeadLetterQueueHandler()
    dlq.trigger_alert("DOCUMENT_QUARANTINED", sha256_hash, "preprocess", reason)
    PIPELINE_STATS["quarantined"] += 1
    logger.warning(f"Document {uid} ({sha256_hash}) QUARANTINED: {reason}")


def process_document_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute all pipeline stages for a document with transactional stage checkpoints."""
    uid = payload["uid"]
    sha256_hash = payload["sha256"]
    file_name = payload["file_name"]
    storage_path = payload.get("storage_path", "")
    is_reprocess = payload.get("is_reprocess", False)

    storage = get_storage_adapter()
    registry = get_idempotency_registry()
    dlq = DeadLetterQueueHandler()

    try:
        raw_bytes = storage.get(sha256_hash)
    except Exception as e:
        logger.error(f"Failed to fetch raw bytes for {sha256_hash}: {e}")
        dlq.handle_stage_failure(sha256_hash, "fetch_raw_storage", payload, str(e))
        PIPELINE_STATS["errors"] += 1
        return {"status": "FAILED", "error": str(e)}

    # 1. Stage: Virus Scan
    t0 = time.time()
    if not is_reprocess and not registry.is_stage_completed(sha256_hash, "virus_scan"):
        v_res = stage_virus_scan(sha256_hash, raw_bytes)
        STAGE_LATENCY_METRICS["virus_scan"].append(time.time() - t0)
        if v_res.get("status") == "INFECTED":
            registry.commit_stage(sha256_hash, "virus_scan", v_res)
            quarantine_document(uid, sha256_hash, file_name, storage_path, v_res["reason"], batch_id=payload.get("batch_id"))
            return {"status": "QUARANTINED", "reason": v_res["reason"]}
        registry.commit_stage(sha256_hash, "virus_scan", v_res)

    # 2. Stage: Dedupe
    t0 = time.time()
    if not is_reprocess:
        d_res = stage_dedupe(sha256_hash, current_uid=uid)
        STAGE_LATENCY_METRICS["dedupe"].append(time.time() - t0)
        if d_res.get("status") == "DUPLICATE_FOUND":
            # Exact duplicate found: create link reference, do not store copy
            ecm = get_ecm_adapter()
            canonical_rec = d_res["canonical_record"]
            link_rec = ecm.create_link(sha256_hash, canonical_rec, batch_id=payload.get("batch_id"), source_uid=uid)
            registry.commit_stage(sha256_hash, "dedupe", d_res)
            PIPELINE_STATS["duplicates_linked"] += 1
            PIPELINE_STATS["total_processed"] += 1
            logger.info(f"Deduplication: linked {uid} to canonical {d_res['canonical_uid']}")
            return {
                "status": "DUPLICATE_LINKED",
                "canonical_uid": d_res["canonical_uid"],
                "is_link": True,
            }

    # 3. Stage: Pre-process & Integrity Check
    t0 = time.time()
    p_res = registry.get_stage_result(sha256_hash, "preprocess")
    if not p_res:
        p_res = stage_preprocess(raw_bytes, file_name)
        STAGE_LATENCY_METRICS["preprocess"].append(time.time() - t0)
        if p_res.get("status") in ["CORRUPT", "PASSWORD_PROTECTED"]:
            registry.commit_stage(sha256_hash, "preprocess", p_res)
            quarantine_document(uid, sha256_hash, file_name, storage_path, p_res["reason"], batch_id=payload.get("batch_id"))
            return {"status": "QUARANTINED", "reason": p_res["reason"]}
        registry.commit_stage(sha256_hash, "preprocess", p_res)

    # 4. Stage: Split Multi-Document Files
    split_parts = stage_split_document(raw_bytes, file_name)
    target_bytes = split_parts[0][0]
    target_name = split_parts[0][1]

    # 5. Stage: OCR
    t0 = time.time()
    ocr_res = None if is_reprocess else registry.get_stage_result(sha256_hash, "ocr")
    if not ocr_res:
        ocr_res = stage_ocr(target_bytes, target_name)
        STAGE_LATENCY_METRICS["ocr"].append(time.time() - t0)
        registry.commit_stage(sha256_hash, "ocr", ocr_res)

    full_text = ocr_res["full_text"]

    # 6. Stage: Classify
    t0 = time.time()
    cls_res = None if is_reprocess else registry.get_stage_result(sha256_hash, "classify")
    if not cls_res:
        cls_res = stage_classify(full_text)
        STAGE_LATENCY_METRICS["classify"].append(time.time() - t0)
        registry.commit_stage(sha256_hash, "classify", cls_res)

    predicted_class = cls_res["predicted_class"]
    confidence = cls_res["confidence"]

    # 7. Stage: Extract Fields
    t0 = time.time()
    extracted_fields, field_confs, is_valid_schema = stage_extract_fields(full_text, predicted_class)
    if p_res and "page_condition" in p_res:
        extracted_fields["page_condition"] = p_res["page_condition"]
        field_confs["page_condition"] = 0.99
    STAGE_LATENCY_METRICS["extract_fields"].append(time.time() - t0)
    registry.commit_stage(
        sha256_hash,
        "extract_fields",
        {"fields": extracted_fields, "confidences": field_confs, "valid": is_valid_schema},
    )

    # 8. Stage: PII Detect
    t0 = time.time()
    pii_res = registry.get_stage_result(sha256_hash, "pii_detect")
    if not pii_res:
        pii_res = stage_pii_detect(full_text)
        STAGE_LATENCY_METRICS["pii_detect"].append(time.time() - t0)
        registry.commit_stage(sha256_hash, "pii_detect", pii_res)

    # 9. Stage: Decision Gate
    t0 = time.time()
    decision = stage_decision_gate(predicted_class, confidence, pii_res, extraction_valid=is_valid_schema)
    STAGE_LATENCY_METRICS["decision_gate"].append(time.time() - t0)
    registry.commit_stage(sha256_hash, "decision_gate", decision.model_dump())

    metadata_payload = {
        "file_name": file_name,
        "file_size": len(raw_bytes),
        "ocr_engine": ocr_res["engine_name"],
        "ocr_version": ocr_res["engine_version"],
        "classifier_model": cls_res["model_name"],
        "classifier_version": cls_res["model_version"],
        "extracted_fields": extracted_fields,
        "field_confidences": field_confs,
        "pii_detected": pii_res["pii_detected"],
        "pii_types": pii_res["pii_types"],
        "extracted_text_preview": full_text[:1000],
        "batch_id": payload.get("batch_id"),
        "user_id": payload.get("user_id"),
    }

    # 10. Stage: ECM Write
    t0 = time.time()
    ecm_record = stage_write_ecm(uid, sha256_hash, decision, metadata_payload, storage_path)
    STAGE_LATENCY_METRICS["ecm_write"].append(time.time() - t0)
    registry.commit_stage(sha256_hash, "ecm_write", {"ecm_id": ecm_record.ecm_id})

    # 11. Stage: Index in Search
    t0 = time.time()
    stage_index_search(uid, sha256_hash, decision, metadata_payload, full_text)
    STAGE_LATENCY_METRICS["search_index"].append(time.time() - t0)

    # 12. Stage: Audit Record
    t0 = time.time()
    audit_data = stage_audit_record(uid, sha256_hash, decision, metadata_payload)
    STAGE_LATENCY_METRICS["audit"].append(time.time() - t0)

    PIPELINE_STATS["total_processed"] += 1
    if decision.action == "AUTO_ACCEPT":
        PIPELINE_STATS["auto_accepted"] += 1
    elif decision.action == "ROUTE_TO_REVIEW":
        PIPELINE_STATS["routed_to_review"] += 1

    return {
        "status": "SUCCESS",
        "uid": uid,
        "sha256": sha256_hash,
        "decision": decision.model_dump(),
        "audit": audit_data.model_dump(),
        "ocr": ocr_res,
        "classification": cls_res,
    }


def run_pipeline_worker(queue_type: str = "live", max_items: Optional[int] = None) -> None:
    """Continuously poll queue and process documents."""
    cfg = get_pipeline_config()
    queue_name = cfg.queues.live_queue if queue_type == "live" else cfg.queues.bulk_queue
    queue = get_queue_adapter()
    rate_limiter = TokenBucketRateLimiter(rate_per_second=cfg.queues.bulk_rate_limit_per_second)

    logger.info(f"Starting pipeline worker on queue: {queue_name} (type={queue_type})")
    items_done = 0

    while True:
        if queue_type == "bulk":
            rate_limiter.wait_and_acquire(1.0)

        entry = queue.pop(queue_name, consumer_group=f"group-{queue_type}", timeout_ms=500)
        if entry is None:
            if max_items is not None and items_done >= max_items:
                break
            time.sleep(0.05)
            continue

        msg_id, payload = entry
        payload["queue_name"] = queue_name
        try:
            process_document_payload(payload)
            queue.ack(queue_name, f"group-{queue_type}", msg_id)
            items_done += 1
        except Exception as e:
            logger.error(f"Error processing item {msg_id}: {e}")
            dlq = DeadLetterQueueHandler()
            dlq.handle_stage_failure(payload.get("sha256", "unknown"), "worker_unhandled", payload, str(e))
            # Persist failure/quarantine to DocumentModel so batch progress tracks it accurately
            try:
                db_err = get_db_session()
                u_err = db_err.query(DocumentModel).filter(DocumentModel.uid == payload.get("uid")).first()
                if u_err:
                    u_err.review_status = "quarantined"
                    u_err.quarantine_reason = str(e)
                    u_err.decision_reason = f"Pipeline worker error: {str(e)}"
                    db_err.commit()
                db_err.close()
            except Exception:
                pass
            queue.ack(queue_name, f"group-{queue_type}", msg_id)

        if max_items is not None and items_done >= max_items:
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ECM Pipeline Worker")
    parser.add_argument("--queue", choices=["live", "bulk"], default="live", help="Queue to process")
    parser.add_argument("--max", type=int, default=None, help="Maximum items to process")
    args = parser.parse_args()
    run_pipeline_worker(queue_type=args.queue, max_items=args.max)
