"""Outbound Webhook Dispatcher with HMAC-SHA256 Payload Signing and Audit Trail."""

import hashlib
import hmac
import json
import logging
import time
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from app.core.settings import get_app_settings
from app.models.db import AuditEventModel, get_db_session

logger = logging.getLogger("ecm.distribution")


class WebhookDeliveryError(Exception):
    """Raised when an outbound webhook delivery fails after maximum retries."""
    pass


class OutboundWebhookDispatcher:
    """Dispatches cryptographically signed webhooks to downstream external integrations."""

    def __init__(
        self,
        target_url: Optional[str] = None,
        signing_secret: Optional[str] = None,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ):
        settings = get_app_settings()
        self.target_url = target_url or settings.OUTBOUND_WEBHOOK_URL
        self.signing_secret = signing_secret or settings.WEBHOOK_SIGNING_SECRET
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    def compute_signature(self, payload_bytes: bytes) -> str:
        """Compute HMAC-SHA256 hex digest for binary payload."""
        secret_bytes = self.signing_secret.encode("utf-8")
        h = hmac.new(secret_bytes, payload_bytes, hashlib.sha256)
        return f"sha256={h.hexdigest()}"

    def dispatch(
        self,
        document_uid: str,
        event_type: str,
        payload_data: Dict[str, Any],
        url_override: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Sign and dispatch an event payload, recording audit logs."""
        url = url_override or self.target_url
        if not url:
            logger.info("Outbound webhook URL not configured; skipping dispatch.")
            return True, "SKIPPED_NO_URL"

        now = datetime.now(timezone.utc)
        delivery_id = f"dlv-{uuid.uuid4().hex[:12]}"
        
        envelope = {
            "delivery_id": delivery_id,
            "event_type": event_type,
            "document_uid": document_uid,
            "timestamp": now.isoformat(),
            "data": payload_data,
        }
        payload_bytes = json.dumps(envelope, sort_keys=True).encode("utf-8")
        signature = self.compute_signature(payload_bytes)

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ECM-Webhook-Dispatcher/1.0",
            "X-ECM-Delivery-ID": delivery_id,
            "X-ECM-Signature": signature,
        }

        last_error = ""
        success = False

        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(url, data=payload_bytes, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    if 200 <= resp.status < 300:
                        success = True
                        break
                    else:
                        last_error = f"HTTP {resp.status}"
            except Exception as e:
                last_error = str(e)

            if attempt < self.max_retries:
                sleep_time = self.backoff_factor * (2 ** (attempt - 1))
                time.sleep(sleep_time)

        # Audit delivery attempt (safe, scrubbed payload)
        self._record_audit_event(
            delivery_id=delivery_id,
            document_uid=document_uid,
            event_type=event_type,
            url=url,
            success=success,
            error_msg=last_error if not success else None,
            created_at=now,
        )

        if not success:
            logger.error(f"Failed to deliver webhook {delivery_id} to {url}: {last_error}")
            return False, last_error

        return True, delivery_id

    def _record_audit_event(
        self,
        delivery_id: str,
        document_uid: str,
        event_type: str,
        url: str,
        success: bool,
        error_msg: Optional[str],
        created_at: datetime,
    ) -> None:
        """Record outbound delivery audit entry with scrubbed metadata."""
        db = get_db_session()
        try:
            audit = AuditEventModel(
                event_id=f"evt-{uuid.uuid4().hex[:12]}",
                document_uid=document_uid,
                sha256="",
                event_type="OUTBOUND_WEBHOOK_DISPATCH",
                stage_name="distribution",
                status="SUCCESS" if success else "FAILED",
                payload_json=json.dumps({
                    "delivery_id": delivery_id,
                    "target_url": url,
                    "event_type": event_type,
                    "status": "DELIVERED" if success else "FAILED",
                    "error": error_msg,
                }),
                created_at=created_at,
            )
            db.add(audit)
            db.commit()
        except Exception as e:
            logger.warning(f"Could not write webhook audit event: {e}")
            db.rollback()
        finally:
            db.close()
