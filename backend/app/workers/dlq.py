"""Dead-Letter Queue (DLQ) and Alerting Management."""

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
from app.adapters.queue import get_queue_adapter
from app.core.config import get_pipeline_config
from app.core.security import setup_secure_logging

logger = setup_secure_logging("ecm.dlq")

# Global in-memory alerts registry for testing and monitoring
_active_alerts: List[Dict[str, Any]] = []


class DeadLetterQueueHandler:
    """Handles failed stage messages, retries with backoff, and dead-letter routing."""

    def __init__(self):
        self.queue = get_queue_adapter()
        self.config = get_pipeline_config()
        self.dlq_name = self.config.queues.dlq_queue

    def handle_stage_failure(
        self,
        sha256_hash: str,
        stage_name: str,
        message_payload: Dict[str, Any],
        error_message: str,
    ) -> bool:
        """Handle failure: increment retry count or route to DLQ if max retries exceeded."""
        retries = message_payload.get("retries", 0) + 1
        message_payload["retries"] = retries
        message_payload["last_error"] = error_message
        message_payload["failed_stage"] = stage_name

        max_retries = self.config.pipeline.get("dlq_max_retries", 3)

        if retries <= max_retries:
            logger.warning(
                f"Retrying document {sha256_hash} stage {stage_name} (Attempt {retries}/{max_retries}): {error_message}"
            )
            # Re-enqueue to original queue with backoff metadata
            q_name = message_payload.get("queue_name", self.config.queues.live_queue)
            self.queue.push(q_name, message_payload)
            return True
        else:
            # Route to DLQ and trigger operational alert
            logger.error(
                f"DEAD-LETTER: Document {sha256_hash} exceeded max retries in stage {stage_name}. Moving to DLQ {self.dlq_name}"
            )
            self.queue.push(self.dlq_name, message_payload)
            self.trigger_alert(
                alert_type="STAGE_MAX_RETRIES_EXCEEDED",
                sha256=sha256_hash,
                stage=stage_name,
                error=error_message,
                payload=message_payload,
            )
            return False

    def trigger_alert(
        self,
        alert_type: str,
        sha256: str,
        stage: str,
        error: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit high-priority operational alert."""
        alert = {
            "alert_id": f"alert-{int(datetime.now(timezone.utc).timestamp())}-{sha256[:8]}",
            "alert_type": alert_type,
            "sha256": sha256,
            "stage": stage,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload or {},
        }
        _active_alerts.append(alert)
        logger.critical(f"ALERT TRIGGERED [{alert_type}]: {alert['alert_id']} - {error}")


def get_active_alerts() -> List[Dict[str, Any]]:
    return list(_active_alerts)


def clear_active_alerts() -> None:
    _active_alerts.clear()
