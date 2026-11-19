"""Database models for documents, stages, audit trail, and human review tasks."""

from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session
from app.core.config import get_app_settings

Base = declarative_base()


class DocumentModel(Base):
    """Primary document and metadata storage record."""
    __tablename__ = "ecm_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(String(64), unique=True, index=True, nullable=False)
    sha256 = Column(String(64), index=True, nullable=False)
    file_name = Column(String(255), nullable=False)
    file_size = Column(Integer, default=0)
    mime_type = Column(String(100), default="application/octet-stream")
    storage_path = Column(String(500), nullable=False)
    doc_type = Column(String(50), default="unknown", index=True)
    confidence = Column(Float, default=0.0)
    retention_class = Column(String(100), default="")
    acl = Column(String(100), default="RESTRICTED_REVIEW")
    target_workflow = Column(String(100), default="")
    review_status = Column(String(50), default="pending", index=True)  # auto_accepted, pending_review, human_verified, quarantined, rejected
    is_link = Column(Boolean, default=False)
    linked_to_uid = Column(String(64), nullable=True)
    quarantine_reason = Column(String(255), nullable=True)

    extracted_fields_json = Column(Text, default="{}")
    human_verified_fields_json = Column(Text, default="{}")
    field_confidences_json = Column(Text, default="{}")
    pii_detected = Column(Boolean, default=False)
    pii_entities_json = Column(Text, default="[]")
    pii_types_json = Column(Text, default="[]")

    ocr_engine = Column(String(50), default="unknown")
    ocr_version = Column(String(50), default="1.0.0")
    classifier_model = Column(String(100), default="tfidf_logistic_regression")
    classifier_version = Column(String(50), default="v1.0")
    decision_reason = Column(String(500), default="")
    reviewer_id = Column(String(100), nullable=True)
    review_notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class StageExecutionModel(Base):
    """Atomic stage tracking for idempotency and failure recovery."""
    __tablename__ = "stage_executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sha256 = Column(String(64), index=True, nullable=False)
    stage_name = Column(String(64), index=True, nullable=False)
    status = Column(String(32), default="PENDING", index=True)  # PENDING, RUNNING, COMPLETED, FAILED
    retry_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    payload_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)


class AuditEventModel(Base):
    """Persistent audit log of all system transitions and human interactions."""
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(64), unique=True, index=True, nullable=False)
    document_uid = Column(String(64), index=True, nullable=False)
    sha256 = Column(String(64), index=True, nullable=False)
    event_type = Column(String(64), index=True, nullable=False)
    stage_name = Column(String(64), nullable=True)
    status = Column(String(32), default="SUCCESS")
    payload_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ReviewTaskModel(Base):
    """Human review task queue entries."""
    __tablename__ = "review_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), unique=True, index=True, nullable=False)
    document_uid = Column(String(64), unique=True, index=True, nullable=False)
    predicted_type = Column(String(50), nullable=False)
    confidence = Column(Float, default=0.0)
    evidence_text = Column(Text, default="")
    status = Column(String(32), default="PENDING", index=True)  # PENDING, IN_REVIEW, COMPLETED, REJECTED
    assigned_reviewer = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)


class ConfigHistoryModel(Base):
    """Persistent audit log of configuration threshold updates."""
    __tablename__ = "config_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    change_id = Column(String(64), unique=True, index=True, nullable=False)
    updated_by = Column(String(100), nullable=False)
    changes_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Patient Prescription & Timetable Data Models
# ---------------------------------------------------------------------------

class UserModel(Base):
    """User account record for patient and staff authentication."""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), default="patient", nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    disabled = Column(Boolean, default=False)


class PrescriptionModel(Base):
    """Patient prescription scan and job tracking record."""
    __tablename__ = "prescriptions"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    file_key = Column(String(255), index=True, nullable=False)
    status = Column(String(32), default="QUEUED", index=True, nullable=False)  # QUEUED, PROCESSING, NEEDS_REVIEW, CONFIRMED, FAILED
    model_version = Column(String(50), default="v1.0")
    ocr_engine = Column(String(50), default="HybridPyMuPDF-Tesseract")
    pii_detected = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ExtractedItemModel(Base):
    """Medication item extracted from a prescription."""
    __tablename__ = "extracted_items"

    id = Column(String(36), primary_key=True)
    prescription_id = Column(String(36), ForeignKey("prescriptions.id"), index=True, nullable=False)
    raw_text = Column(Text, default="")
    drug_name = Column(String(255), nullable=False)
    strength = Column(String(100), default="")
    dose = Column(String(100), default="")
    frequency = Column(String(100), default="")
    timing = Column(String(100), default="")
    duration_days = Column(Integer, nullable=True)
    schedule_rule = Column(String(255), default="")
    confidence_json = Column(Text, default="{}")
    verified_by_user = Column(Boolean, default=False, index=True)
    verified_at = Column(DateTime, nullable=True)


class TimetableSlotModel(Base):
    """Discrete scheduled dose slot for patient adherence tracking."""
    __tablename__ = "timetable_slots"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    prescription_id = Column(String(36), ForeignKey("prescriptions.id"), index=True, nullable=False)
    extracted_item_id = Column(String(36), ForeignKey("extracted_items.id"), index=True, nullable=False)
    scheduled_at = Column(DateTime, nullable=False, index=True)
    instruction = Column(String(255), default="")
    status = Column(String(32), default="pending", index=True)  # pending, taken, skipped
    status_changed_at = Column(DateTime, nullable=True)


class ReminderModel(Base):
    """Medication reminder notification dispatch record."""
    __tablename__ = "reminders"

    id = Column(String(36), primary_key=True)
    slot_id = Column(String(36), ForeignKey("timetable_slots.id"), index=True, nullable=False)
    channel = Column(String(32), default="email")
    send_at = Column(DateTime, nullable=False, index=True)
    sent_at = Column(DateTime, nullable=True)


# Database Engine and Session Factory
_engine = None
_SessionFactory = None


def get_db_engine():
    global _engine
    if _engine is None:
        settings = get_app_settings()
        db_url = settings.DATABASE_URL
        connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
        _engine = create_engine(db_url, connect_args=connect_args)
    return _engine


def init_db():
    """Create all tables in the database."""
    engine = get_db_engine()
    Base.metadata.create_all(engine)


def get_db_session():
    """Create a scoped SQLAlchemy session."""
    global _SessionFactory
    if _SessionFactory is None:
        engine = get_db_engine()
        _SessionFactory = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
    return _SessionFactory()
