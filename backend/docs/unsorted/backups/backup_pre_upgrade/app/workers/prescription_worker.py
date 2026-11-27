"""Prescription Processing Background Worker.

Executes OCR, raw text line extraction, Presidio PII scanning,
grounded medication entity extraction, and transitions status to NEEDS_REVIEW.
Enforces idempotent re-runs without duplicate items and catches faults safely.
"""

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.adapters.ocr import get_ocr_engine
from app.adapters.pii import PresidioPIIDetector
from app.adapters.storage import get_storage_adapter
from app.models.db import (
    AuditEventModel,
    ExtractedItemModel,
    PrescriptionModel,
    get_db_session,
)
from app.workers.medication_extractor import MedicationExtractor

logger = logging.getLogger(__name__)


def process_prescription_job(prescription_id: str) -> bool:
    """Process a queued prescription asynchronously.

    Returns True if succeeded and transitioned to NEEDS_REVIEW,
    False if failed and transitioned to FAILED.
    """
    db = get_db_session()
    try:
        rx = db.query(PrescriptionModel).filter(PrescriptionModel.id == prescription_id).first()
        if not rx:
            logger.error("Prescription %s not found in database.", prescription_id)
            return False

        # Mark as processing
        rx.status = "PROCESSING"
        db.commit()

        storage = get_storage_adapter()
        file_bytes: Optional[bytes] = None

        # Fetch file bytes from storage adapter
        try:
            if storage.exists(rx.file_key):
                file_bytes = storage.get(rx.file_key)
            else:
                # Local filesystem fallback check if stored under data/storage/
                local_fallback = os.path.join(os.getcwd(), "data", "storage", rx.file_key)
                if os.path.exists(local_fallback):
                    with open(local_fallback, "rb") as f:
                        file_bytes = f.read()
                else:
                    raise FileNotFoundError(f"File key {rx.file_key} not found in storage.")
        except Exception as e:
            logger.error("Failed to retrieve file from storage for %s: %s", prescription_id, e)
            rx.status = "FAILED"
            rx.error_message = "Document storage read failure."
            db.commit()
            return False

        # Run OCR
        file_ext = rx.file_key.split(".")[-1].lower() if "." in rx.file_key else "pdf"
        ocr_engine = get_ocr_engine()
        try:
            ocr_result = ocr_engine.extract_text(file_bytes, file_ext)
            raw_text = ocr_result.full_text
        except Exception as e:
            logger.error("OCR execution failed for %s: %s", prescription_id, e)
            rx.status = "FAILED"
            rx.error_message = "OCR processing encountered an unrecoverable format error."
            db.commit()
            return False

        # Store extracted raw text
        rx.raw_text = raw_text

        # Run PII detection
        try:
            pii_detector = PresidioPIIDetector()
            detected_pii = pii_detector.detect(raw_text)
            rx.pii_detected = len(detected_pii) > 0
        except Exception as e:
            logger.warning("PII detection warning for %s: %s", prescription_id, e)
            rx.pii_detected = False

        # Run medication entity extraction
        extractor = MedicationExtractor()
        med_items = extractor.extract(raw_text)

        # Idempotency: Clean up any existing unconfirmed items from a previous run to prevent duplicates
        db.query(ExtractedItemModel).filter(
            ExtractedItemModel.prescription_id == rx.id,
            ExtractedItemModel.verified_by_user.is_(False),
        ).delete()

        # Insert extracted medication items
        for med in med_items:
            item_id = f"item-{uuid.uuid4().hex[:12]}"
            conf_payload = json.dumps(med.confidence)
            item_row = ExtractedItemModel(
                id=item_id,
                prescription_id=rx.id,
                raw_text=med.source_span,
                drug_name=med.drug_name,
                strength=med.strength,
                dose=med.dose,
                frequency=med.frequency,
                timing=med.timing,
                duration_days=med.duration_days,
                schedule_rule=med.schedule_rule,
                confidence_json=conf_payload,
                verified_by_user=False,
                verified_at=None,
            )
            db.add(item_row)

        # INVARIANT: Always transition to NEEDS_REVIEW (never auto-accept)
        rx.status = "NEEDS_REVIEW"
        rx.error_message = None

        # Record audit trail
        audit_ev = AuditEventModel(
            event_id=f"audit-rx-{uuid.uuid4().hex[:12]}",
            document_uid=rx.id,
            sha256=rx.sha256 or hashlib.sha256(file_bytes).hexdigest(),
            event_type="PRESCRIPTION_PROCESSED",
            stage_name="ocr_and_extraction",
            status="SUCCESS",
            payload_json=json.dumps({
                "prescription_id": rx.id,
                "user_id": rx.user_id,
                "items_extracted_count": len(med_items),
                "pii_detected": rx.pii_detected,
                "status": "NEEDS_REVIEW",
            }),
            created_at=datetime.now(timezone.utc),
        )
        db.add(audit_ev)
        db.commit()
        return True

    except Exception as e:
        logger.exception("Unexpected error in prescription worker for %s: %s", prescription_id, e)
        db.rollback()
        try:
            rx = db.query(PrescriptionModel).filter(PrescriptionModel.id == prescription_id).first()
            if rx:
                rx.status = "FAILED"
                rx.error_message = "Unexpected system processing error."
                db.commit()
        except Exception:
            pass
        return False
    finally:
        db.close()
