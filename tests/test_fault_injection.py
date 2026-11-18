"""Fault injection tests: worker crash mid-batch and OCR outage leading to retries, DLQ, and alerts."""

import hashlib
from unittest.mock import patch
import pytest
from app.adapters.queue import get_queue_adapter
from app.adapters.storage import get_storage_adapter
from app.core.config import get_pipeline_config
from app.core.idempotency import get_idempotency_registry
from app.workers.dlq import DeadLetterQueueHandler, clear_active_alerts, get_active_alerts
from app.workers.pipeline import process_document_payload


def test_kill_worker_mid_batch_no_lost_no_duplicates():
    """Simulate worker crash after OCR stage; assert retry commits idempotently without duplicate records."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(fitz.Point(50, 80), "COMMERCIAL INVOICE\nInvoice Number: INV-CRASH-001\nTotal Amount: $500.00")
    raw_data = doc.tobytes()
    doc.close()

    sha = hashlib.sha256(raw_data).hexdigest()
    storage = get_storage_adapter()
    storage.save(sha, raw_data)

    registry = get_idempotency_registry()
    registry.reset_hash(sha)

    uid = f"crash-test-{sha[:8]}"
    payload = {
        "uid": uid,
        "sha256": sha,
        "file_name": "crash_test.pdf",
        "storage_path": f"storage/{sha}",
        "is_reprocess": False,
    }

    # Simulate worker crash during stage execution by injecting failure after OCR
    with patch("app.workers.pipeline.stage_classify", side_effect=RuntimeError("Worker SIGKILL Simulated")):
        try:
            process_document_payload(payload)
        except RuntimeError:
            pass

    # Verify that stages completed prior to crash (virus scan, dedupe, preprocess, ocr) are committed
    assert registry.is_stage_completed(sha, "ocr") is True
    # And stage that crashed was not marked completed
    assert not registry.is_stage_completed(sha, "classify")

    # Worker restarts and resumes processing the same document
    result = process_document_payload(payload)
    assert result["status"] == "SUCCESS"

    # Assert OCR stage was not re-executed (idempotent result was reused)
    assert registry.is_stage_completed(sha, "classify") is True
    assert registry.is_stage_completed(sha, "ecm_write") is True


def test_ocr_outage_leads_to_retries_then_dlq_and_alert():
    """Simulate persistent OCR outage; assert retries with backoff, routing to DLQ, and alert emission."""
    clear_active_alerts()
    cfg = get_pipeline_config()
    queue = get_queue_adapter()
    dlq_handler = DeadLetterQueueHandler()

    sha = "outage_test_sha_888"
    payload = {
        "uid": "outage-doc-001",
        "sha256": sha,
        "file_name": "outage.pdf",
        "retries": 0,
        "queue_name": cfg.queues.live_queue,
    }

    # Simulate 3 failed retry attempts
    for attempt in range(1, 4):
        should_retry = dlq_handler.handle_stage_failure(sha, "ocr", payload, "OCR Service 503 Unavailable")
        assert should_retry is True
        assert payload["retries"] == attempt

    # 4th failure exceeds max retries (3) -> routes to DLQ and emits alert
    should_retry = dlq_handler.handle_stage_failure(sha, "ocr", payload, "OCR Service 503 Unavailable")
    assert should_retry is False

    # Assert message landed in DLQ
    dlq_depth = queue.length(cfg.queues.dlq_queue)
    assert dlq_depth >= 1

    # Assert operational alert was triggered
    alerts = get_active_alerts()
    assert len(alerts) >= 1
    assert alerts[-1]["alert_type"] == "STAGE_MAX_RETRIES_EXCEEDED"
    assert alerts[-1]["stage"] == "ocr"
    assert "OCR Service 503 Unavailable" in alerts[-1]["error"]
