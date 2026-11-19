"""Medication Reminder Notification Worker and Channel Adapters.

SAFETY GUARANTEES:
- Reminders must ONLY include the drug name, dose/instruction, and scheduled time.
- NEVER include patient name, email, raw prescription text, or tracking URLs in the notification body.
- Audit trail recorded for all dispatched notifications.
"""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

from sqlalchemy.orm import Session

from app.models.db import TimetableSlotModel, ReminderModel, ExtractedItemModel, AuditEventModel

logger = logging.getLogger("prescription_reminders")


class ReminderDeliveryChannel(ABC):
    """Abstract interface for pluggable reminder notification channels."""

    @abstractmethod
    def send(self, recipient_info: Dict[str, Any], payload: Dict[str, Any]) -> bool:
        """Send a single medication reminder."""
        pass


class LogReminderChannel(ReminderDeliveryChannel):
    """Safe structured log delivery channel.
    
    Logs only anonymized medication reminder events without PII or sensitive health data.
    """

    def __init__(self):
        self.delivered_messages: List[Dict[str, Any]] = []

    def send(self, recipient_info: Dict[str, Any], payload: Dict[str, Any]) -> bool:
        # Strictly verify payload safety
        assert "patient_name" not in payload, "PII Violation: patient_name in reminder payload"
        assert "url" not in payload, "Privacy Violation: URL in reminder payload"
        assert "raw_text" not in payload, "Privacy Violation: raw_text in reminder payload"

        msg = (
            f"[REMINDER] Slot {payload.get('slot_id')}: "
            f"Medication '{payload.get('drug_name')}' ({payload.get('dose')}) "
            f"scheduled for {payload.get('scheduled_at')}."
        )
        logger.info(msg)
        self.delivered_messages.append({
            "message": msg,
            "payload": payload,
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
        })
        return True


class StubSMTPReminderChannel(ReminderDeliveryChannel):
    """Stub SMTP delivery channel for testing email dispatches."""

    def __init__(self):
        self.sent_emails: List[Dict[str, Any]] = []

    def send(self, recipient_info: Dict[str, Any], payload: Dict[str, Any]) -> bool:
        # Strictly enforce safety
        safe_subject = "Medication Reminder"
        safe_body = (
            f"Reminder to take your scheduled dose:\n"
            f"Medication: {payload.get('drug_name')}\n"
            f"Dose: {payload.get('dose')}\n"
            f"Scheduled Time: {payload.get('scheduled_at')}\n"
        )
        self.sent_emails.append({
            "recipient": recipient_info.get("email", "anonymized@patient.local"),
            "subject": safe_subject,
            "body": safe_body,
            "payload": payload,
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
        })
        return True


def dispatch_due_reminders(
    db: Session,
    window_minutes: int = 60,
    channel: Optional[ReminderDeliveryChannel] = None,
    channel_name: str = "log",
    reference_time: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Query upcoming pending timetable slots and dispatch reminders.
    
    Guarantees:
    - Never reminds a slot more than once.
    - Only reminds pending slots.
    - Zero PII in dispatched notifications.
    """
    if channel is None:
        channel = LogReminderChannel()

    now = reference_time or datetime.now(timezone.utc)
    cutoff = now + timedelta(minutes=window_minutes)

    # Query pending slots in the time window [now - 15m, cutoff]
    lower_bound = now - timedelta(minutes=15)
    slots = db.query(TimetableSlotModel).filter(
        TimetableSlotModel.status == "pending",
        TimetableSlotModel.scheduled_at >= lower_bound,
        TimetableSlotModel.scheduled_at <= cutoff,
    ).all()

    dispatched = []

    for slot in slots:
        # Check if already reminded
        existing_reminder = db.query(ReminderModel).filter(
            ReminderModel.slot_id == slot.id
        ).first()
        if existing_reminder is not None:
            continue

        item = db.query(ExtractedItemModel).filter(ExtractedItemModel.id == slot.extracted_item_id).first()
        drug_name = item.drug_name if item else "Prescribed Medication"
        dose = item.dose if item else ""

        # Construct safe payload
        payload = {
            "slot_id": slot.id,
            "prescription_id": slot.prescription_id,
            "drug_name": drug_name,
            "dose": dose,
            "scheduled_at": slot.scheduled_at.isoformat(),
        }

        recipient_info = {
            "user_id": slot.user_id,
        }

        success = channel.send(recipient_info, payload)
        if success:
            reminder_record = ReminderModel(
                id=str(uuid.uuid4()),
                slot_id=slot.id,
                channel=channel_name,
                send_at=slot.scheduled_at,
                sent_at=datetime.now(timezone.utc),
            )
            db.add(reminder_record)

            audit_ev = AuditEventModel(
                event_id=f"audit-remind-{uuid.uuid4().hex[:12]}",
                document_uid=slot.prescription_id,
                sha256="",
                event_type="REMINDER_DISPATCHED",
                stage_name="reminders",
                status="SUCCESS",
                payload_json=f'{{"slot_id":"{slot.id}","channel":"{channel_name}","scheduled_at":"{slot.scheduled_at.isoformat()}"}}',
                created_at=datetime.now(timezone.utc),
            )
            db.add(audit_ev)
            dispatched.append(payload)

    db.commit()
    return dispatched
