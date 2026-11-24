"""Database models and connection handling.

Unified Data Layer supporting both:
1. Document Reader Application (UserModel, BatchModel, FileModel, FieldModel, CorrectionModel)
2. Asynchronous ECM Ingestion & Classification Pipeline (DocumentModel, StageExecutionModel,
   AuditEventModel, ReviewTaskModel, ConfigHistoryModel, PipelineJobModel)
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Optional

from cryptography.fernet import Fernet, InvalidToken
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
    event,
    inspect,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, relationship, scoped_session, sessionmaker

Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def gen_uuid() -> str:
    return str(uuid.uuid4())


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


# ---------------------------------------------------------------------------
# User & Batch Models
# ---------------------------------------------------------------------------
class UserModel(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(255), nullable=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), default="uploader", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    disabled = Column(Boolean, default=False)

    batches = relationship("BatchModel", back_populates="user", cascade="all, delete-orphan")
    corrections = relationship("CorrectionModel", back_populates="user", cascade="all, delete-orphan")


class BatchModel(Base):
    __tablename__ = "batches"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    batch_id = Column(String(64), index=True, nullable=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("UserModel", back_populates="batches")
    files = relationship("FileModel", back_populates="batch", cascade="all, delete-orphan", order_by="FileModel.created_at")


class FileModel(Base):
    __tablename__ = "files"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    batch_id = Column(String(36), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True)
    original_name = Column(String(512), nullable=False)
    stored_path = Column(String(1024), nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    cache_key = Column(String(128), index=True, nullable=True)
    stage_timings = Column(Text, nullable=True)
    status = Column(String(64), default="Waiting")
    stage = Column(String(64), default="Waiting")
    error = Column(Text, nullable=True)
    doc_type = Column(String(255), nullable=True)
    page_condition = Column(String(255), nullable=True)
    duplicate_of = Column(String(512), nullable=True)
    page_count = Column(Integer, default=1)
    provider_name = Column(String(64), nullable=True)
    model_name = Column(String(128), nullable=True)
    is_fallback = Column(Boolean, default=False)
    prompt_version = Column(String(32), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    batch = relationship("BatchModel", back_populates="files")
    fields = relationship("FieldModel", back_populates="file", cascade="all, delete-orphan", order_by="FieldModel.position")


class FieldModel(Base):
    __tablename__ = "fields"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    file_id = Column(String(36), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(255), nullable=False)
    value = Column(Text, nullable=False)
    original_value = Column(Text, nullable=False)
    confidence = Column(Float, default=1.0)
    source = Column(String(32), default="read")
    position = Column(Integer, default=0)
    page = Column(Integer, default=1)
    bbox = Column(Text, nullable=True)
    is_sensitive = Column(Boolean, default=False)

    file = relationship("FileModel", back_populates="fields")


class CorrectionModel(Base):
    __tablename__ = "corrections"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_type = Column(String(255), nullable=False)
    label = Column(String(255), nullable=False)
    original_value = Column(Text, nullable=False)
    corrected_value = Column(Text, nullable=False)
    layout_hint = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("UserModel", back_populates="corrections")


# ---------------------------------------------------------------------------
# ECM Ingest & Classification Pipeline Models
# ---------------------------------------------------------------------------
class DocumentModel(Base):
    """Primary document and metadata storage record in enterprise ECM."""
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


# ---------------------------------------------------------------------------
# Engine and Session Setup
# ---------------------------------------------------------------------------
_engine = None
_SessionFactory = None


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable SQLite WAL mode, normal synchronous, and 30s busy timeout for high concurrency."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()
    except Exception:
        pass


def get_db_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///./data/ecm_pipeline.db")


def init_db(db_url: str = None):
    global _engine, _SessionFactory
    if db_url is None:
        db_url = get_db_url()

    if db_url.startswith("sqlite:///"):
        path = db_url.replace("sqlite:///", "")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    connect_args = {"check_same_thread": False, "timeout": 30.0} if "sqlite" in db_url else {}
    _engine = create_engine(db_url, connect_args=connect_args)
    Base.metadata.create_all(bind=_engine)

    # Idempotent migrations for files and fields tables
    try:
        insp = inspect(_engine)
        if "files" in insp.get_table_names():
            existing_cols = [c["name"] for c in insp.get_columns("files")]
            with _engine.connect() as conn:
                columns_to_add = [
                    ("cache_key", "VARCHAR(128)"),
                    ("stage_timings", "TEXT"),
                    ("provider_name", "VARCHAR(64)"),
                    ("model_name", "VARCHAR(128)"),
                    ("is_fallback", "BOOLEAN DEFAULT 0"),
                    ("prompt_version", "VARCHAR(32)"),
                ]
                for col_name, col_type in columns_to_add:
                    if col_name not in existing_cols:
                        conn.execute(text(f"ALTER TABLE files ADD COLUMN {col_name} {col_type}"))
                conn.commit()

        if "batches" in insp.get_table_names():
            existing_batch_cols = [c["name"] for c in insp.get_columns("batches")]
            with _engine.connect() as conn:
                if "batch_id" not in existing_batch_cols:
                    conn.execute(text("ALTER TABLE batches ADD COLUMN batch_id VARCHAR(64)"))
                conn.commit()

        if "users" in insp.get_table_names():
            existing_user_cols = [c["name"] for c in insp.get_columns("users")]
            with _engine.connect() as conn:
                user_cols_to_add = [
                    ("role", "VARCHAR(32) DEFAULT 'uploader'"),
                    ("disabled", "BOOLEAN DEFAULT 0"),
                ]
                for col_name, col_type in user_cols_to_add:
                    if col_name not in existing_user_cols:
                        conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
                conn.commit()

        if "fields" in insp.get_table_names():
            existing_field_cols = [c["name"] for c in insp.get_columns("fields")]
            with _engine.connect() as conn:
                field_cols_to_add = [
                    ("page", "INTEGER DEFAULT 1"),
                    ("bbox", "TEXT"),
                    ("is_sensitive", "BOOLEAN DEFAULT 0"),
                ]
                for col_name, col_type in field_cols_to_add:
                    if col_name not in existing_field_cols:
                        conn.execute(text(f"ALTER TABLE fields ADD COLUMN {col_name} {col_type}"))
                conn.commit()
    except Exception:
        pass

    _SessionFactory = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=_engine))
    return _engine


def get_db_engine():
    global _engine
    if _engine is None:
        init_db()
    return _engine


def get_db_session():
    """Create or return a scoped SQLAlchemy session."""
    global _SessionFactory
    if _SessionFactory is None:
        init_db()
    return _SessionFactory()


def get_db() -> Generator:
    global _SessionFactory
    if _SessionFactory is None:
        init_db()
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()
