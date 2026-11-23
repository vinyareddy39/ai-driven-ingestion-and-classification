"""Database models for documents, stages, audit trail, and human review tasks."""

import os
from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session
from cryptography.fernet import Fernet, InvalidToken
from app.core.config import get_app_settings

Base = declarative_base()

# ---------------------------------------------------------------------------
# Column-Level Health Data Encryption at Rest (Fernet / AES-128-CBC + HMAC)
# ---------------------------------------------------------------------------

_fernet_instance = None


def get_fernet_cipher() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        import base64
        import hashlib
        raw_key = os.getenv("ENCRYPTION_KEY") or os.getenv("DATA_ENCRYPTION_KEY")
        if not raw_key:
            import secrets
            raw_key = secrets.token_urlsafe(32)
            os.environ["ENCRYPTION_KEY"] = raw_key
        try:
            key_str = raw_key if isinstance(raw_key, str) else raw_key.decode("utf-8")
            decoded = base64.urlsafe_b64decode(key_str.encode("utf-8"))
            if len(decoded) == 32:
                key_bytes = key_str.encode("utf-8")
            else:
                key_bytes = base64.urlsafe_b64encode(hashlib.sha256(key_str.encode("utf-8")).digest())
        except Exception:
            key_bytes = base64.urlsafe_b64encode(hashlib.sha256(str(raw_key).encode("utf-8")).digest())
        _fernet_instance = Fernet(key_bytes)
    return _fernet_instance


class EncryptedText(TypeDecorator):
    """Transparent column-level encryption for sensitive health text at rest."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not value:
            return ""
        cipher = get_fernet_cipher()
        return cipher.encrypt(value.encode("utf-8")).decode("utf-8")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if not value:
            return ""
        if value.startswith("gAAAAA"):
            try:
                cipher = get_fernet_cipher()
                return cipher.decrypt(value.encode("utf-8")).decode("utf-8")
            except (InvalidToken, Exception):
                return value
        return value



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

    # Enterprise Batch, Ownership, and Retention extensions
    batch_id = Column(String(64), index=True, nullable=True)
    user_id = Column(String(36), ForeignKey("users.id"), index=True, nullable=True)
    legal_hold = Column(Boolean, default=False, index=True)
    retention_expires_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index("idx_doc_model_conf", "classifier_version", "confidence"),
        Index("idx_doc_batch_status", "batch_id", "review_status"),
    )


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
    name = Column(String(100), nullable=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), default="uploader", nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    disabled = Column(Boolean, default=False)


class RevokedTokenModel(Base):
    """Revoked stateless authentication tokens list for logout enforcement."""
    __tablename__ = "revoked_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(String(36), nullable=True)
    expires_at = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class PrescriptionModel(Base):
    """Patient prescription scan and job tracking record."""
    __tablename__ = "prescriptions"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    file_key = Column(String(255), index=True, nullable=False)
    sha256 = Column(String(64), index=True, nullable=True)
    status = Column(String(32), default="QUEUED", index=True, nullable=False)  # QUEUED, PROCESSING, NEEDS_REVIEW, CONFIRMED, FAILED
    raw_text = Column(EncryptedText, nullable=True)
    error_message = Column(String(255), nullable=True)
    model_version = Column(String(50), default="v1.0")
    ocr_engine = Column(String(50), default="HybridPyMuPDF-Tesseract")
    pii_detected = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ExtractedItemModel(Base):
    """Medication item extracted from a prescription."""
    __tablename__ = "extracted_items"

    id = Column(String(36), primary_key=True)
    prescription_id = Column(String(36), ForeignKey("prescriptions.id"), index=True, nullable=False)
    raw_text = Column(EncryptedText, default="")
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


class PipelineJobModel(Base):
    """Persistent job queue model surviving process restarts across PostgreSQL and SQLite."""
    __tablename__ = "pipeline_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(64), unique=True, index=True, nullable=False)
    queue_name = Column(String(64), index=True, nullable=False)
    payload_json = Column(Text, nullable=False)
    status = Column(String(32), default="QUEUED", index=True, nullable=False)  # QUEUED, PROCESSING, COMPLETED, FAILED
    retry_count = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    claimed_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class BatchModel(Base):
    """Enterprise batch upload session record."""
    __tablename__ = "batches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(64), unique=True, index=True, nullable=False)
    number = Column(Integer, default=1, index=True, nullable=False)
    name = Column(String(100), nullable=True)
    user_id = Column(String(36), index=True, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class NotificationModel(Base):
    """User notifications for completed batches and system events."""
    __tablename__ = "notifications"

    id = Column(String(64), primary_key=True)
    user_id = Column(String(36), index=True, nullable=True)
    batch_id = Column(String(64), index=True, nullable=True)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    read = Column(Boolean, default=False, index=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class DownloadModel(Base):
    """User requested batch export archive record and download tracker."""
    __tablename__ = "downloads"

    id = Column(String(64), primary_key=True)
    owner = Column(String(36), index=True, nullable=False)
    batch_id = Column(String(64), index=True, nullable=False)
    status = Column(String(32), default="PREPARING", index=True, nullable=False)  # PREPARING, READY, DOWNLOADED, FAILED, EXPIRED
    file_count = Column(Integer, default=0, nullable=False)
    size_bytes = Column(Integer, default=0, nullable=False)
    file_path = Column(String(500), nullable=True)
    requested_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = Column(DateTime, nullable=True)
    last_downloaded_at = Column(DateTime, nullable=True)
    error_message = Column(String(500), nullable=True)


class MultipartUploadModel(Base):
    """Multipart file upload sessions for large files (direct-to-storage / R2 / S3)."""
    __tablename__ = "multipart_uploads"

    id = Column(String(64), primary_key=True)  # upload_id or uuid
    storage_key = Column(String(255), nullable=False)
    file_name = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    part_size = Column(Integer, nullable=False)
    part_count = Column(Integer, nullable=False)
    owner = Column(String(100), nullable=False, index=True)
    batch_id = Column(String(64), nullable=True, index=True)
    status = Column(String(32), default="INITIATED", index=True)  # INITIATED, COMPLETED, ABORTED, EXPIRED
    sha256 = Column(String(64), nullable=True, index=True)
    document_uid = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime, nullable=True)



# Database Engine and Session Factory
_engine = None
_SessionFactory = None


def get_db_engine():
    global _engine
    if _engine is None:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            settings = get_app_settings()
            db_url = settings.DATABASE_URL
        connect_args = {"check_same_thread": False, "timeout": 30.0} if "sqlite" in db_url else {}
        _engine = create_engine(db_url, connect_args=connect_args)
        if "sqlite" in db_url:
            from sqlalchemy import event

            @event.listens_for(_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()
    return _engine


def init_db():
    """Create all tables in the database."""
    engine = get_db_engine()
    Base.metadata.create_all(engine)
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE pipeline_jobs ADD COLUMN claimed_at TIMESTAMP"))
            conn.commit()
    except Exception:
        pass
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN name VARCHAR(100)"))
            conn.commit()
    except Exception:
        pass


def get_db_session():
    """Create a scoped SQLAlchemy session."""
    global _SessionFactory
    if _SessionFactory is None:
        engine = get_db_engine()
        _SessionFactory = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
    return _SessionFactory()
