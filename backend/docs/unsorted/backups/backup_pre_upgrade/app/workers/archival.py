"""Document Archival, Legal Hold Enforcement, and Disposition Engine."""

from datetime import datetime, timezone
import json
import logging
import os
from typing import Any, Dict, List, Optional
import uuid

from app.adapters.storage import get_storage_adapter
from app.models.db import AuditEventModel, DocumentModel, get_db_session

logger = logging.getLogger("ecm.archival")


class LegalHoldViolationError(Exception):
    """Raised when an operation attempts to dispose of a document under active legal hold."""
    pass


def set_legal_hold(
    document_uid: str,
    hold: bool,
    reason: str,
    actor_id: str,
) -> bool:
    """Apply or release a legal hold on a document, preventing disposition."""
    db = get_db_session()
    now = datetime.now(timezone.utc)
    try:
        doc = db.query(DocumentModel).filter(DocumentModel.uid == document_uid).first()
        if not doc:
            raise ValueError(f"Document '{document_uid}' not found")

        prev_hold = doc.legal_hold
        doc.legal_hold = hold

        audit = AuditEventModel(
            event_id=f"evt-{uuid.uuid4().hex[:12]}",
            document_uid=doc.uid,
            sha256=doc.sha256 or "",
            event_type="LEGAL_HOLD_MODIFIED",
            stage_name="archival",
            status="SUCCESS",
            payload_json=json.dumps({
                "actor_id": actor_id,
                "previous_hold": prev_hold,
                "new_hold": hold,
                "reason": reason,
            }),
            created_at=now,
        )
        db.add(audit)
        db.commit()
        logger.info(f"Document '{document_uid}' legal_hold set to {hold} by {actor_id}")
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run_disposition_lifecycle(
    as_of_time: Optional[datetime] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Identify expired documents past retention expiry and safely purge unheld files.
    
    INVARIANTS:
    - Any document with legal_hold == True MUST NOT be purged under any circumstance.
    - All disposition actions are immutably logged to the audit trail.
    """
    now = as_of_time or datetime.now(timezone.utc)
    db = get_db_session()
    storage = get_storage_adapter()

    try:
        # Find all documents past retention expiry
        candidates = (
            db.query(DocumentModel)
            .filter(
                DocumentModel.retention_expires_at != None,
                DocumentModel.retention_expires_at <= now,
                DocumentModel.review_status != "disposed",
            )
            .all()
        )

        purged_uids: List[str] = []
        held_uids: List[str] = []

        for doc in candidates:
            if doc.legal_hold:
                held_uids.append(doc.uid)
                continue

            if not dry_run:
                # 1. Delete physical storage file if present
                if doc.storage_path and os.path.exists(doc.storage_path):
                    try:
                        os.remove(doc.storage_path)
                    except Exception as e:
                        logger.warning(f"Could not remove physical file {doc.storage_path}: {e}")

                # 2. Mark review_status as 'disposed' and clear sensitive fields
                doc.review_status = "disposed"
                doc.extracted_fields_json = "{}"
                doc.human_verified_fields_json = "{}"

                # 3. Log disposition audit event
                audit = AuditEventModel(
                    event_id=f"evt-{uuid.uuid4().hex[:12]}",
                    document_uid=doc.uid,
                    sha256=doc.sha256 or "",
                    event_type="DOCUMENT_DISPOSITION",
                    stage_name="archival",
                    status="SUCCESS",
                    payload_json=json.dumps({
                        "retention_class": doc.retention_class,
                        "retention_expires_at": doc.retention_expires_at.isoformat() if doc.retention_expires_at else None,
                        "disposition_time": now.isoformat(),
                    }),
                    created_at=now,
                )
                db.add(audit)

            purged_uids.append(doc.uid)

        if not dry_run:
            db.commit()

        return {
            "dry_run": dry_run,
            "as_of": now.isoformat(),
            "eligible_count": len(candidates),
            "purged_count": len(purged_uids),
            "held_count": len(held_uids),
            "purged_uids": purged_uids,
            "held_uids": held_uids,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
