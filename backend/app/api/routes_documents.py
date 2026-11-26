"""Batch upload, progress tracking, dynamic results, field editing, learning corrections,

and ZIP download endpoints.

ZERO DEFAULTS:
- Columns are generated dynamically from the union of extracted labels in that group.
- Exact values preserved: no case conversion, comma preservation.
- Real duplicate tracking (SHA-256) with full re-reading and 'Same content as...' note.
- Real ZIP download containing original files, CSV, and multi-sheet Excel (.xlsx).
"""

import csv
import io
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("routes_documents")

import openpyxl
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.jwt_auth import get_current_user
from app.models.db import (
    BatchModel,
    CorrectionModel,
    FieldModel,
    FileModel,
    UserModel,
    get_db,
    init_db,
)
from app.workers.vision_pipeline import (
    extract_document_vision,
    extract_embedded_text,
    extract_document_text_llm,
    cross_check_confidence,
    deskew_and_clean,
    detect_page_condition,
    render_first_page_image,
    render_page_to_png_bytes,
)
from app.core.providers import (
    PROMPT_VERSION,
    get_fallback_orchestrator,
)
from app.core.sensitivity import evaluate_document_sensitivity
from app.core.preprocessing import load_document_pages, preprocess_image
from app.core.generalized_pipeline import GeneralizedDocumentPipeline
from app.core.learned_registry import LearnedRegistry
from app.core.comprehensive_extractor import (
    UniversalDocumentReader,
    PasswordProtectedException,
    EmptyFileException,
    DamagedFileException,
    ExtractedDetail,
    ExtractionResult,
)

SUPPORTED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp",
    ".txt", ".csv", ".docx", ".xlsx", ".eml"
}

_persistent_worker_loop: Optional[asyncio.AbstractEventLoop] = None
_persistent_worker_thread: Optional[threading.Thread] = None
_loop_init_lock = threading.Lock()


def get_persistent_worker_loop() -> asyncio.AbstractEventLoop:
    """Return a single persistent worker event loop for all background document processing."""
    global _persistent_worker_loop, _persistent_worker_thread
    if _persistent_worker_loop is None or not _persistent_worker_loop.is_running():
        with _loop_init_lock:
            if _persistent_worker_loop is None or not _persistent_worker_loop.is_running():
                _persistent_worker_loop = asyncio.new_event_loop()
                def _loop_runner():
                    asyncio.set_event_loop(_persistent_worker_loop)
                    _persistent_worker_loop.run_forever()
                _persistent_worker_thread = threading.Thread(
                    target=_loop_runner, daemon=True, name="PersistentWorkerLoop"
                )
                _persistent_worker_thread.start()
    return _persistent_worker_loop

router = APIRouter(prefix="/api", tags=["batches"])

STORAGE_DIR = os.path.abspath("data/storage")
DOWNLOADS_DIR = os.path.abspath("data/downloads")
os.makedirs(STORAGE_DIR, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class FieldPayload(BaseModel):
    label: str
    value: str
    orig: Optional[str] = None
    orig_label: Optional[str] = None
    conf: Optional[float] = 1.0
    val_conf: Optional[float] = None
    lbl_conf: Optional[float] = None
    src: Optional[str] = "read"
    page: Optional[int] = 1
    bbox: Optional[Any] = None
    is_sensitive: Optional[bool] = False
    is_edited: Optional[bool] = False
    structure_type: Optional[str] = "label_value_pair"
    structure_group: Optional[str] = "fields"
    structure_confidence: Optional[float] = 1.0
    region_id: Optional[str] = None
    reason: Optional[str] = ""
    suggested_label: Optional[str] = ""
    hint: Optional[str] = ""


class ReclassifyRegionRequest(BaseModel):
    new_structure_type: str


class UnlockFileRequest(BaseModel):
    password: str


class UpdateFieldsRequest(BaseModel):
    fields: List[FieldPayload]


def compute_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def compute_cache_key(sha256: str, user_id: Optional[str] = None) -> str:
    """User-scoped cache key = sha256 + prompt_version + user_id."""
    raw = f"{sha256}:{PROMPT_VERSION}:{user_id or 'anon'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_sqlite_write_lock = threading.RLock()


def safe_commit(db_session, max_retries=6):
    """Safely commit database transaction with exponential backoff on SQLite busy locks."""
    for attempt in range(max_retries):
        try:
            db_session.commit()
            return
        except Exception as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                time.sleep(0.15 * (2 ** attempt))
                continue
            raise


def process_file_background(file_id: str, db_url: Optional[str] = None, force_fresh: bool = False):
    """Background worker processing a single document through Speed-First async pipeline."""
    import base64
    import cv2
    import fitz
    from sqlalchemy.orm import sessionmaker

    engine = init_db(db_url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    db = SessionLocal()
    db.autoflush = False

    t0 = time.perf_counter()
    hash_ms = 0.0
    text_check_ms = 0.0
    render_ms = 0.0
    deskew_ms = 0.0
    model_ms = 0.0
    db_write_ms = 0.0

    f = None
    try:
        f = db.query(FileModel).filter(FileModel.id == file_id).first()
        if not f:
            return

        batch = db.query(BatchModel).filter(BatchModel.id == f.batch_id).first()
        user_id = batch.user_id if batch else None

        # 0. User-Scoped Cache Key: sha256 + prompt_version + user_id (scoped per user, never shared across users)
        t_h = time.perf_counter()
        cache_key = compute_cache_key(f.sha256, user_id=user_id)
        f.cache_key = cache_key
        hash_ms = round((time.perf_counter() - t_h) * 1000, 2)

        # Point 6: Every upload is read again from scratch. Nothing is skipped by cache or filename.
        # If identical content (SHA-256), mark "Same content as <earlier file>" note, but still read again.
        if user_id:
            earlier_dup = (
                db.query(FileModel)
                .join(BatchModel, BatchModel.id == FileModel.batch_id)
                .filter(
                    FileModel.sha256 == f.sha256,
                    BatchModel.user_id == user_id,
                    FileModel.id != f.id,
                    FileModel.created_at < f.created_at,
                    FileModel.original_name != f.original_name,
                )
                .order_by(FileModel.created_at.asc())
                .first()
            )
            if earlier_dup:
                f.duplicate_of = earlier_dup.original_name
                logger.info(f"Identical content detected for {f.original_name} (same content as {earlier_dup.original_name}). Reading again from scratch.")
            elif f.duplicate_of == f.original_name:
                f.duplicate_of = None

        queue_wait_ms = 0.0
        if f.created_at:
            now_utc = datetime.now(timezone.utc)
            created = f.created_at if f.created_at.tzinfo else f.created_at.replace(tzinfo=timezone.utc)
            queue_wait_ms = max(0.0, round((now_utc - created).total_seconds() * 1000, 2))

        with _sqlite_write_lock:
            f.started_at = datetime.now(timezone.utc)
            f.stage = "Still reading"
            f.status = "Still reading"
            safe_commit(db)

        # 1. Multi-Format Universal Document Reading & Generalized Pipeline Processing
        t_read = time.perf_counter()
        MAX_RETRIES = 3
        pipe_res = None
        error_category = None
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                pipeline_engine = GeneralizedDocumentPipeline()
                pipe_res = pipeline_engine.process_file(f.stored_path)
                break
            except PasswordProtectedException:
                error_category = "password"
                last_error = "This file is password protected."
                break
            except EmptyFileException:
                error_category = "empty"
                last_error = "This file is empty."
                break
            except DamagedFileException:
                error_category = "damaged"
                last_error = "file damaged"
                break
            except Exception as e:
                logger.error(f"Error reading file {file_id} (attempt {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                last_error = str(e)
                err_lower = str(e).lower()
                if "ocr" in err_lower or "image" in err_lower or "decode" in err_lower or "pixmap" in err_lower:
                    error_category = "image_ocr"
                elif "worker" in err_lower or "model" in err_lower or "unavailable" in err_lower or "pipeline" in err_lower:
                    error_category = "reader_unavailable"
                elif "corrupt" in err_lower or "damaged" in err_lower or "cannot open" in err_lower:
                    error_category = "damaged"
                else:
                    error_category = "image_ocr" if f.original_name.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.webp')) else "reader_unavailable"

                if attempt < MAX_RETRIES:
                    with _sqlite_write_lock:
                        f.stage = "Still reading"
                        f.status = f"Retrying ({attempt}/{MAX_RETRIES})"
                        f.check_reasons = f"Reading attempt {attempt} failed, retrying ({attempt}/{MAX_RETRIES})..."
                        safe_commit(db)
                    time.sleep(0.3)

        if pipe_res is None:
            clean_reason = "text could not be read from the image"
            if error_category == "password":
                clean_reason = "password protected file"
            elif error_category == "empty":
                clean_reason = "file is empty"
            elif error_category == "damaged":
                clean_reason = "file damaged"
            elif error_category == "reader_unavailable":
                clean_reason = "reader unavailable"
            elif error_category == "image_ocr":
                clean_reason = "text could not be read from the image"

            with _sqlite_write_lock:
                f.stage = "Failed"
                f.status = "Failed"
                f.doc_type = "Could not read"
                f.error = clean_reason
                f.check_reasons = clean_reason
                f.finished_at = datetime.now(timezone.utc)
                safe_commit(db)
            logger.info(f"File {f.original_name} failed reading: {clean_reason}")
            return

        f.page_count = len(pipe_res.get("page_conditions", [1])) or 1
        f.doc_type = pipe_res.get("type", "Document")
        f.page_condition = pipe_res.get("page_quality", "clean")
        f.document_summary = pipe_res.get("summary")
        f.tags = json.dumps(pipe_res.get("tags", []))
        f.raw_text_by_page = json.dumps(pipe_res.get("raw_text_by_page", {}))
        f.tables_data = json.dumps(pipe_res.get("tables", []))
        f.regions_data = json.dumps(pipe_res.get("regions", []))
        f.pipeline_version = pipe_res.get("pipeline_version", "2.3.0")
        f.registry_version = pipe_res.get("registry_version", "2.3.0")

        extracted_fields = pipe_res.get("fields", [])

        # Sort fields: labelled rows first, unlabelled rows below them
        sorted_details = sorted(
            extracted_fields,
            key=lambda d: (1 if not (d.get("label") and d.get("label").strip()) else 0, d.get("page", 1))
        )

        new_fields = []
        for pos, d in enumerate(sorted_details):
            meta_dict = {
                "value_confidence": d.get("value_confidence", d.get("confidence", 1.0)),
                "label_confidence": d.get("label_confidence"),
                "structure_type": d.get("structure_type", "label_value_pair"),
                "structure_group": d.get("structure_group", "fields"),
                "structure_confidence": d.get("structure_confidence", 1.0),
                "region_id": d.get("region_id"),
                "reason": d.get("reason", ""),
                "suggested_label": d.get("suggested_label", ""),
                "alternatives": d.get("alternatives", []),
                "hint": d.get("hint", ""),
                "grounding_span": d.get("grounding_span"),
                "split_suggestion": d.get("split_suggestion"),
                "in_more_details": d.get("in_more_details", False),
                "is_promoted": d.get("is_promoted", True),
            }
            new_fields.append(FieldModel(
                file_id=f.id,
                label=d.get("label", ""),
                original_label=d.get("original_label", d.get("label", "")),
                value=d.get("value", ""),
                original_value=d.get("original_value", d.get("value", "")),
                confidence=float(d.get("confidence", 1.0)),
                source=d.get("source", "document"),
                position=pos,
                page=d.get("page", 1),
                bbox=json.dumps(d.get("bbox")) if d.get("bbox") else None,
                is_sensitive=bool(d.get("is_sensitive", False)),
                detector_tag=d.get("detector_tag"),
                meta_info=json.dumps(meta_dict),
            ))

        final_status = "Done, check" if pipe_res.get("needs_review") else "Done"
        final_reasons = "; ".join(pipe_res.get("review_reasons", [])) if pipe_res.get("review_reasons") else None
        if final_status == "Done, check" and not final_reasons:
            final_reasons = "Low confidence details require verification"

        total_ms = round((time.perf_counter() - t0) * 1000, 2)

        # Generate page 1 PNG preview bytes and store in Postgres preview_data
        try:
            if not f.preview_data and os.path.exists(f.stored_path):
                import base64
                p_bytes = render_page_to_png_bytes(f.stored_path, page_num=1, dpi=120)
                if p_bytes:
                    f.preview_data = base64.b64encode(p_bytes).decode('ascii')
        except Exception as pe:
            logger.warning(f"Could not generate preview_data for {f.original_name}: {pe}")

        with _sqlite_write_lock:
            db.query(FieldModel).filter(FieldModel.file_id == f.id).delete()
            db.add_all(new_fields)
            f.stage = "Done"
            f.status = final_status
            f.error = None
            f.check_reasons = final_reasons
            f.finished_at = datetime.now(timezone.utc)
            f.stage_timings = json.dumps({
                "queue_wait_ms": queue_wait_ms,
                "total_ms": total_ms,
                "provider": "generalized_pipeline",
                "details_count": len(new_fields),
                "sensitive_count": sum(1 for x in new_fields if x.is_sensitive),
            })
            safe_commit(db)

        # Ephemeral storage cleanup: delete local temporary file after processing
        from app.core.config import get_app_settings
        app_settings = get_app_settings()
        if getattr(app_settings, "DELETE_UPLOAD_AFTER_PROCESSING", True):
            if os.path.exists(f.stored_path):
                try:
                    os.remove(f.stored_path)
                    logger.debug(f"Purged ephemeral file from disk: {f.stored_path}")
                except Exception as de:
                    logger.debug(f"Could not remove temporary uploaded file {f.stored_path}: {de}")

        sens_count = sum(1 for x in new_fields if x.is_sensitive)
        logger.info(f"File {f.original_name} completed in {total_ms}ms: {len(new_fields)} details ({sens_count} sensitive).")

    except Exception as e:
        logger.error(f"Error processing file {file_id}: {e}", exc_info=True)
        if f:
            f.stage = "Failed"
            f.status = "Failed"
            f.doc_type = "Could not read"
            f.error = "reader unavailable"
            f.check_reasons = "reader unavailable"
            f.finished_at = datetime.now(timezone.utc)
            try:
                safe_commit(db)
            except Exception:
                pass
    finally:
        db.close()


def process_batch_background(batch_id: str):
    """Process files in a batch concurrently with worker pool for high speed."""
    import concurrent.futures
    import time
    from sqlalchemy.orm import sessionmaker

    engine = init_db()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        files = db.query(FileModel).filter(FileModel.batch_id == batch_id).all()
        file_ids = [f.id for f in files]
    finally:
        db.close()

    if not file_ids:
        return

    # Blazing speed: 4 parallel workers across hybrid fast text / vision pipeline
    workers = 4

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = []
        for fid in file_ids:
            # Check cancellation before dispatching
            check_db = SessionLocal()
            try:
                b_exists = check_db.query(BatchModel).filter(BatchModel.id == batch_id).first()
                if not b_exists:
                    break
            finally:
                check_db.close()

            futures.append(executor.submit(process_file_background, fid))
            # Minimal 0.2s stagger between worker thread dispatches
            time.sleep(0.2)

        concurrent.futures.wait(futures)


@router.post("/batches", status_code=status.HTTP_201_CREATED)
def create_batch(
    files: Optional[List[UploadFile]] = File(None),
    relative_paths: Optional[str] = Form(None),
    batch_name: Optional[str] = Form(None),
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        os.makedirs(STORAGE_DIR, exist_ok=True)
        rel_list: List[str] = []
        rel_dict: Dict[str, str] = {}
        if relative_paths:
            try:
                parsed = json.loads(relative_paths)
                if isinstance(parsed, list):
                    rel_list = [str(x) for x in parsed]
                elif isinstance(parsed, dict):
                    rel_dict = {str(k): str(v) for k, v in parsed.items()}
            except Exception:
                rel_list = []
                rel_dict = {}

        b_name = batch_name or (f"Batch · {len(files)} files" if files else "New Batch")
        batch = BatchModel(user_id=user.id, name=b_name)
        db.add(batch)
        safe_commit(db)
        db.refresh(batch)

        if not files:
            return {
                "id": batch.id,
                "name": batch.name,
                "file_count": 0,
                "created_at": batch.created_at.isoformat() if batch.created_at else None,
            }

        saved_files = []
        max_upload_bytes = int(os.getenv("MAX_UPLOAD_MB", "200")) * 1024 * 1024
        for idx, upload in enumerate(files):
            filename = upload.filename or ""
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            file_bytes = upload.file.read()
            if len(file_bytes) > max_upload_bytes:
                max_mb = max_upload_bytes // (1024 * 1024)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File '{filename}' exceeds maximum allowed upload size limit of {max_mb} MB.",
                )
            sha256 = compute_sha256(file_bytes)

            clean_original_name = re.sub(r"\.\.+", "", os.path.basename(filename or safe_filename)).lstrip("._") or "document.pdf"

            earlier_in_batch = next((sf for sf in saved_files if sf.sha256 == sha256), None)
            if earlier_in_batch:
                dup_name = earlier_in_batch.original_name
            else:
                dup_file = (
                    db.query(FileModel)
                    .join(BatchModel, BatchModel.id == FileModel.batch_id)
                    .filter(
                        FileModel.sha256 == sha256,
                        BatchModel.user_id == user.id,
                        FileModel.original_name != clean_original_name,
                    )
                    .order_by(FileModel.created_at.asc())
                    .first()
                )
                dup_name = dup_file.original_name if dup_file else None

            safe_filename = re.sub(r"[^a-zA-Z0-9_.-]", "_", upload.filename or "doc")
            file_id = str(uuid.uuid4())
            stored_path = os.path.join(STORAGE_DIR, f"{file_id}_{safe_filename}")
            with open(stored_path, "wb") as f_out:
                f_out.write(file_bytes)

            if idx < len(rel_list):
                rel_path = rel_list[idx]
            elif filename in rel_dict:
                rel_path = rel_dict[filename]
            elif safe_filename in rel_dict:
                rel_path = rel_dict[safe_filename]
            else:
                rel_path = filename

            file_record = FileModel(
                id=file_id,
                batch_id=batch.id,
                original_name=clean_original_name,
                relative_path=rel_path,
                stored_path=stored_path,
                sha256=sha256,
                status="Waiting",
                stage="Waiting",
                duplicate_of=dup_name,
            )
            db.add(file_record)
            saved_files.append(file_record)

        safe_commit(db)

        if saved_files:
            thread = threading.Thread(target=process_batch_background, args=(batch.id,), daemon=True)
            thread.start()

        return {
            "id": batch.id,
            "name": batch.name,
            "file_count": len(saved_files),
            "created_at": batch.created_at.isoformat() if batch.created_at else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating batch: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create batch: {str(e)}")


@router.post("/batches/{batch_id}/files", status_code=status.HTTP_201_CREATED)
def append_files_to_batch(
    batch_id: str,
    files: List[UploadFile] = File(...),
    relative_paths: Optional[str] = Form(None),
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        os.makedirs(STORAGE_DIR, exist_ok=True)
        batch = db.query(BatchModel).filter(BatchModel.id == batch_id, BatchModel.user_id == user.id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")

        rel_list: List[str] = []
        rel_dict: Dict[str, str] = {}
        if relative_paths:
            try:
                parsed = json.loads(relative_paths)
                if isinstance(parsed, list):
                    rel_list = [str(x) for x in parsed]
                elif isinstance(parsed, dict):
                    rel_dict = {str(k): str(v) for k, v in parsed.items()}
            except Exception:
                rel_list = []
                rel_dict = {}

        saved_files = []
        max_upload_bytes = int(os.getenv("MAX_UPLOAD_MB", "200")) * 1024 * 1024
        for idx, upload in enumerate(files):
            filename = upload.filename or ""
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            file_bytes = upload.file.read()
            if len(file_bytes) > max_upload_bytes:
                max_mb = max_upload_bytes // (1024 * 1024)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File '{filename}' exceeds maximum allowed upload size limit of {max_mb} MB.",
                )
            sha256 = compute_sha256(file_bytes)

            clean_original_name = re.sub(r"\.\.+", "", os.path.basename(filename or safe_filename)).lstrip("._") or "document.pdf"

            earlier_in_batch = next((sf for sf in saved_files if sf.sha256 == sha256), None)
            if earlier_in_batch:
                dup_name = earlier_in_batch.original_name
            else:
                dup_file = (
                    db.query(FileModel)
                    .join(BatchModel, BatchModel.id == FileModel.batch_id)
                    .filter(
                        FileModel.sha256 == sha256,
                        BatchModel.user_id == user.id,
                        FileModel.original_name != clean_original_name,
                    )
                    .order_by(FileModel.created_at.asc())
                    .first()
                )
                dup_name = dup_file.original_name if dup_file else None

            safe_filename = re.sub(r"[^a-zA-Z0-9_.-]", "_", upload.filename or "doc")
            file_id = str(uuid.uuid4())
            stored_path = os.path.join(STORAGE_DIR, f"{file_id}_{safe_filename}")
            with open(stored_path, "wb") as f_out:
                f_out.write(file_bytes)

            if idx < len(rel_list):
                rel_path = rel_list[idx]
            elif filename in rel_dict:
                rel_path = rel_dict[filename]
            elif safe_filename in rel_dict:
                rel_path = rel_dict[safe_filename]
            else:
                rel_path = filename

            file_record = FileModel(
                id=file_id,
                batch_id=batch.id,
                original_name=clean_original_name,
                relative_path=rel_path,
                stored_path=stored_path,
                sha256=sha256,
                status="Waiting",
                stage="Waiting",
                duplicate_of=dup_name,
            )
            db.add(file_record)
            saved_files.append(file_record)

        safe_commit(db)

        total_count = db.query(FileModel).filter(FileModel.batch_id == batch.id).count()
        batch.name = f"Batch · {total_count} files"
        safe_commit(db)

        return {
            "batch_id": batch.id,
            "added_count": len(saved_files),
            "total_count": total_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error appending files to batch {batch_id}: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to append files: {str(e)}")


@router.post("/batches/{batch_id}/start")
def start_batch_processing(
    batch_id: str,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch = db.query(BatchModel).filter(BatchModel.id == batch_id, BatchModel.user_id == user.id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    thread = threading.Thread(target=process_batch_background, args=(batch.id,), daemon=True)
    thread.start()
    return {"message": "Processing started", "batch_id": batch.id}


@router.get("/batches")
def list_batches(
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batches = (
        db.query(BatchModel)
        .filter(BatchModel.user_id == user.id)
        .order_by(BatchModel.created_at.desc())
        .all()
    )

    result = []
    for b in batches:
        total = len(b.files)
        done = sum(1 for f in b.files if f.stage == "Done")
        failed = sum(1 for f in b.files if f.stage == "Failed")
        result.append({
            "id": b.id,
            "name": b.name,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "file_count": total,
            "done_count": done,
            "failed_count": failed,
        })
    return result


@router.get("/batches/{batch_id}")
def get_batch(
    batch_id: str,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch = (
        db.query(BatchModel)
        .filter(BatchModel.id == batch_id, BatchModel.user_id == user.id)
        .first()
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    corrections_count = (
        db.query(CorrectionModel).filter(CorrectionModel.user_id == user.id).count()
    )

    total_files = len(batch.files)
    done_files = sum(1 for f in batch.files if f.stage == "Done")
    failed_files = sum(1 for f in batch.files if f.stage == "Failed")

    # Part 5, Point 3: The percentage must equal finished files divided by total files.
    pct = round((done_files / total_files * 100)) if total_files > 0 else 0

    files_data = []
    all_latencies = []
    batch_retries = 0
    batch_429s = 0

    for f in batch.files:
        fields_data = []
        for fld in f.fields:
            meta = {}
            if getattr(fld, "meta_info", None):
                try:
                    meta = json.loads(fld.meta_info)
                except Exception:
                    meta = {}
            lbl_c = meta.get("label_confidence")
            if lbl_c is None and (not fld.label or not fld.label.strip()):
                lbl_c = None
            elif lbl_c is None:
                lbl_c = 0.90
            fields_data.append({
                "id": fld.id,
                "label": fld.label,
                "orig_label": getattr(fld, "original_label", None) or fld.label,
                "value": fld.value,
                "orig": fld.original_value,
                "conf": fld.confidence,
                "val_conf": meta.get("value_confidence", fld.confidence),
                "lbl_conf": lbl_c,
                "structure_type": meta.get("structure_type", "label_value_pair"),
                "structure_group": meta.get("structure_group", "fields"),
                "structure_confidence": meta.get("structure_confidence", 1.0),
                "region_id": meta.get("region_id"),
                "src": fld.source,
                "page": fld.page or 1,
                "bbox": json.loads(fld.bbox) if fld.bbox else None,
                "is_sensitive": bool(fld.is_sensitive),
                "detector_tag": getattr(fld, "detector_tag", None),
                "is_unlabelled": not bool(fld.label and fld.label.strip()),
                "is_edited": bool(getattr(fld, "is_edited", False) or fld.source == "edited"),
                "reason": meta.get("reason", ""),
                "suggested_label": meta.get("suggested_label", ""),
                "alternatives": meta.get("alternatives", []),
                "hint": meta.get("hint", ""),
                "grounding_span": meta.get("grounding_span"),
                "split_suggestion": meta.get("split_suggestion"),
                "in_more_details": meta.get("in_more_details", False),
                "is_promoted": meta.get("is_promoted", True),
            })
        
        timings_dict = {}
        if f.stage_timings:
            try:
                timings_dict = json.loads(f.stage_timings)
                if "total_ms" in timings_dict and timings_dict["total_ms"] > 0:
                    all_latencies.append(timings_dict["total_ms"])
                batch_retries += timings_dict.get("retries", 0)
                batch_429s += timings_dict.get("count_429", 0)
            except Exception:
                pass

        clean_err = f.error
        if clean_err:
            cl = clean_err.lower()
            if "password" in cl:
                clean_err = "password protected file"
            elif "empty" in cl:
                clean_err = "file is empty"
            elif "damaged" in cl or "corrupt" in cl:
                clean_err = "file damaged"
            elif "ocr" in cl or "image" in cl or "text could not be read" in cl:
                clean_err = "text could not be read from the image"
            elif "reader" in cl or "unavailable" in cl or "worker" in cl:
                clean_err = "reader unavailable"

        # Status and message must agree: "Done" only when reading succeeded.
        clean_status = f.status
        clean_stage = f.stage
        if clean_status in ["Failed", "Damaged", "Empty", "Locked"]:
            clean_stage = "Failed"
            clean_status = "Failed"
        elif clean_stage == "Failed":
            clean_status = "Failed"
        elif clean_stage == "Done":
            clean_status = clean_status if clean_status in ["Done", "Done, check", "Needs check"] else "Done"
        else:
            clean_stage = "Waiting" if clean_stage == "Waiting" else "Still reading"

        # Check reasons: never empty when check or failure is needed
        check_reasons = getattr(f, "check_reasons", None) or clean_err
        if clean_status in ["Done, check", "Needs check"] and not check_reasons:
            check_reasons = "Low confidence details require verification"
        elif clean_status == "Failed" and not check_reasons:
            check_reasons = clean_err or "Reading failed"
        elif clean_status == "Done":
            check_reasons = None

        # Grouping: Failed files must not be grouped under a normal document type.
        doc_type_val = f.doc_type
        if clean_stage == "Failed" or clean_status == "Failed" or not doc_type_val:
            doc_type_val = "Could not read"

        # Never match a file with itself or show dup of own name
        dup_val = f.duplicate_of
        if dup_val == f.original_name:
            dup_val = None

        tags_list = []
        if getattr(f, "tags", None):
            try:
                tags_list = json.loads(f.tags)
            except Exception:
                tags_list = []

        raw_text_dict = {}
        if getattr(f, "raw_text_by_page", None):
            try:
                raw_text_dict = json.loads(f.raw_text_by_page)
            except Exception:
                raw_text_dict = {}

        files_data.append({
            "id": f.id,
            "name": f.original_name,
            "relative_path": f.relative_path or f.original_name,
            "type": doc_type_val,
            "cond": f.page_condition or "clean",
            "dup": dup_val,
            "status": clean_status,
            "stage": clean_stage,
            "error": clean_err,
            "check_reasons": check_reasons,
            "document_summary": getattr(f, "document_summary", None),
            "tags": tags_list,
            "raw_text_by_page": raw_text_dict,
            "pipeline_version": getattr(f, "pipeline_version", "2.3.0"),
            "registry_version": getattr(f, "registry_version", "2.3.0"),
            "provider": f.provider_name or timings_dict.get("provider", "local_ocr"),
            "model": f.model_name or timings_dict.get("model", "default"),
            "is_fallback": f.is_fallback or timings_dict.get("is_fallback", False),
            "timings": timings_dict,
            "fields": fields_data,
            "tables": json.loads(f.tables_data) if getattr(f, "tables_data", None) else [],
            "regions": json.loads(f.regions_data) if getattr(f, "regions_data", None) else [],
        })

    # Summary calculations (p50, p95, total time, 429s, retries, failures)
    p50_ms = 0.0
    p95_ms = 0.0
    if all_latencies:
        all_latencies.sort()
        n = len(all_latencies)
        p50_idx = int(0.50 * (n - 1))
        p95_idx = int(0.95 * (n - 1))
        p50_ms = round(all_latencies[p50_idx], 2)
        p95_ms = round(all_latencies[p95_idx], 2)

    total_batch_time_ms = 0.0
    if batch.created_at:
        finished_times = [f.finished_at for f in batch.files if f.finished_at]
        if finished_times:
            latest_finish = max(finished_times)
            b_created = batch.created_at if batch.created_at.tzinfo else batch.created_at.replace(tzinfo=timezone.utc)
            l_finish = latest_finish if latest_finish.tzinfo else latest_finish.replace(tzinfo=timezone.utc)
            total_batch_time_ms = max(0.0, round((l_finish - b_created).total_seconds() * 1000, 2))
        else:
            total_batch_time_ms = sum(all_latencies)

    batch_summary = {
        "total_time_ms": total_batch_time_ms,
        "p50_ms": p50_ms,
        "p95_ms": p95_ms,
        "count_429": batch_429s,
        "retries": batch_retries,
        "failures": failed_files,
        "files_processed": len(all_latencies),
    }

    return {
        "id": batch.id,
        "name": batch.name,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "file_count": total_files,
        "done_count": done_files,
        "failed_count": failed_files,
        "progress_pct": pct,
        "corrections_count": corrections_count,
        "summary": batch_summary,
        "files": files_data,
    }


@router.get("/files/{file_id}")
def get_file(
    file_id: str,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    f = (
        db.query(FileModel)
        .join(BatchModel, BatchModel.id == FileModel.batch_id)
        .filter(FileModel.id == file_id, BatchModel.user_id == user.id)
        .first()
    )
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    fields_data = []
    for fld in f.fields:
        meta = {}
        if getattr(fld, "meta_info", None):
            try:
                meta = json.loads(fld.meta_info)
            except Exception:
                meta = {}
        lbl_c = meta.get("label_confidence")
        if lbl_c is None and (not fld.label or not fld.label.strip()):
            lbl_c = None
        elif lbl_c is None:
            lbl_c = 0.90
        fields_data.append({
            "id": fld.id,
            "label": fld.label,
            "orig_label": getattr(fld, "original_label", None) or fld.label,
            "value": fld.value,
            "orig": fld.original_value,
            "conf": fld.confidence,
            "val_conf": meta.get("value_confidence", fld.confidence),
            "lbl_conf": lbl_c,
            "structure_type": meta.get("structure_type", "label_value_pair"),
            "structure_group": meta.get("structure_group", "fields"),
            "structure_confidence": meta.get("structure_confidence", 1.0),
            "region_id": meta.get("region_id"),
            "src": fld.source,
            "page": fld.page or 1,
            "bbox": json.loads(fld.bbox) if fld.bbox else None,
            "is_sensitive": bool(fld.is_sensitive),
            "detector_tag": getattr(fld, "detector_tag", None),
            "is_unlabelled": not bool(fld.label and fld.label.strip()),
            "is_edited": bool(getattr(fld, "is_edited", False) or fld.source == "edited"),
            "reason": meta.get("reason", ""),
            "suggested_label": meta.get("suggested_label", ""),
            "alternatives": meta.get("alternatives", []),
            "hint": meta.get("hint", ""),
            "grounding_span": meta.get("grounding_span"),
            "split_suggestion": meta.get("split_suggestion"),
            "in_more_details": meta.get("in_more_details", False),
            "is_promoted": meta.get("is_promoted", True),
        })

    clean_stage = f.stage
    clean_status = f.status
    if clean_status in ["Failed", "Damaged", "Empty", "Locked"]:
        clean_stage = "Failed"
        clean_status = "Failed"
    elif clean_stage == "Failed":
        clean_status = "Failed"
    elif clean_stage == "Done":
        clean_status = clean_status if clean_status in ["Done", "Done, check", "Needs check"] else "Done"
    else:
        clean_stage = "Waiting" if clean_stage == "Waiting" else "Still reading"

    check_reasons = getattr(f, "check_reasons", None) or f.error
    if clean_status in ["Done, check", "Needs check"] and not check_reasons:
        check_reasons = "Low confidence details require verification"
    elif clean_status == "Failed" and not check_reasons:
        check_reasons = f.error or "Reading failed"
    elif clean_status == "Done":
        check_reasons = None

    doc_type_val = f.doc_type
    if clean_stage == "Failed" or clean_status == "Failed" or not doc_type_val:
        doc_type_val = "Could not read"

    dup_val = f.duplicate_of
    if dup_val == f.original_name:
        dup_val = None

    return {
        "id": f.id,
        "batch_id": f.batch_id,
        "name": f.original_name,
        "relative_path": f.relative_path or f.original_name,
        "type": doc_type_val,
        "cond": f.page_condition or "clean",
        "dup": dup_val,
        "status": clean_status,
        "stage": clean_stage,
        "error": f.error,
        "check_reasons": check_reasons,
        "fields": fields_data,
        "tables": json.loads(f.tables_data) if getattr(f, "tables_data", None) else [],
        "regions": json.loads(f.regions_data) if getattr(f, "regions_data", None) else [],
    }


@router.get("/admin/workers/health")
@router.get("/health/workers")
def get_workers_health(db: Session = Depends(get_db)):
    """Worker and pipeline health status for admin/status dashboard."""
    pipeline_ok = True
    ocr_status = "ready"
    try:
        from app.core.generalized_pipeline import GeneralizedDocumentPipeline
        pipeline_ok = True
    except Exception as e:
        pipeline_ok = False
        ocr_status = f"unavailable: {str(e)}"

    waiting_count = db.query(FileModel).filter(FileModel.stage.in_(["Waiting", "Still reading"])).count()
    external_ai_enabled = os.getenv("ENABLE_EXTERNAL_AI", "false").lower() in ("true", "1")
    return {
        "status": "healthy" if pipeline_ok else "degraded",
        "external_ai_enabled": external_ai_enabled,
        "external_ai_warning": "WARNING: External AI is enabled. Document content, extracted text and images may be transmitted to third-party APIs (Google Gemini, Groq, Anthropic)." if external_ai_enabled else None,
        "workers": {
            "status": "running",
            "active_tasks": waiting_count,
            "max_workers": 4,
            "pipeline_ready": pipeline_ok,
            "ocr_status": ocr_status,
            "pdf_reader": "PyMuPDF",
        },
        "database": {
            "status": "connected",
            "type": "sqlite",
        }
    }


@router.get("/label-suggestions")
def get_label_suggestions(
    doc_type: Optional[str] = Query(None),
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return field label suggestions from taxonomy config and human review history."""
    suggestions: List[str] = []
    seen = set()

    def add_sug(text_val: Optional[str]):
        if not text_val:
            return
        clean = text_val.strip()
        if not clean or clean.startswith("Unlabelled") or clean == "(no label)":
            return
        if clean.lower() not in seen:
            seen.add(clean.lower())
            suggestions.append(clean)

    # 1. Config taxonomy field concepts
    doc_type_lower = (doc_type or "").lower().strip()
    taxonomy_path = os.path.abspath("config/taxonomy.yaml")
    if os.path.exists(taxonomy_path):
        try:
            import yaml
            with open(taxonomy_path, "r", encoding="utf-8") as f_tax:
                tax_data = yaml.safe_load(f_tax) or {}
                tax = tax_data.get("taxonomy", {})
                
                # Priority 1: Current doc_type field concepts
                if doc_type_lower in tax:
                    for c in tax[doc_type_lower].get("field_concepts", []):
                        add_sug(c.replace("_", " ").title())
                
                # Priority 2: Other document types field concepts
                for t_name, t_val in tax.items():
                    if t_name != doc_type_lower:
                        for c in t_val.get("field_concepts", []):
                            add_sug(c.replace("_", " ").title())
        except Exception as e:
            logger.warning(f"Failed to load taxonomy for label suggestions: {e}")

    # Priority 3: Labels from corrections table (previous user feedback/edits)
    try:
        corr_records = (
            db.query(CorrectionModel.new_label, CorrectionModel.label)
            .filter((CorrectionModel.new_label.isnot(None)) | (CorrectionModel.label.isnot(None)))
            .all()
        )
        for rec in corr_records:
            add_sug(rec[0])
            add_sug(rec[1])
    except Exception as e:
        logger.warning(f"Error reading corrections for suggestions: {e}")

    # Priority 4: Existing fields from other reviewed files
    try:
        distinct_fields = (
            db.query(FieldModel.label)
            .filter(FieldModel.label.isnot(None), FieldModel.label != "")
            .distinct()
            .all()
        )
        for (f_lbl,) in distinct_fields:
            add_sug(f_lbl)
    except Exception as e:
        logger.warning(f"Error reading field labels for suggestions: {e}")

    return {"suggestions": suggestions}


@router.put("/files/{file_id}/fields")
def update_file_fields(
    file_id: str,
    payload: UpdateFieldsRequest,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    f = (
        db.query(FileModel)
        .join(BatchModel, BatchModel.id == FileModel.batch_id)
        .filter(FileModel.id == file_id, BatchModel.user_id == user.id)
        .first()
    )
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    # Part 3: Prevent duplicate labels in one document unless the schema allows a list
    seen_labels = set()
    list_allowed_labels = {"line_items", "items", "notes", "entries", "diagnoses", "medications", "procedures"}
    for item in payload.fields:
        lbl_clean = item.label.strip().lower()
        if not lbl_clean:
            continue
        is_list = lbl_clean.endswith("[]") or lbl_clean.endswith("_list") or lbl_clean in list_allowed_labels
        if not is_list and lbl_clean in seen_labels:
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate label '{item.label.strip()}' is not allowed in this document unless defined as a list."
            )
        seen_labels.add(lbl_clean)

    # Record corrections for learning
    existing_fields = {fld.label: fld.original_value for fld in f.fields}

    # Delete old fields
    db.query(FieldModel).filter(FieldModel.file_id == f.id).delete()

    # Part 3: Sort fields so rows with no label sort below labelled rows
    sorted_items = sorted(
        payload.fields,
        key=lambda x: (1 if not x.label.strip() else 0, x.page or 1)
    )

    has_low_conf = False
    has_unlabelled = False
    for pos, item in enumerate(sorted_items):
        lbl = item.label.strip()
        val = item.value.strip()
        orig_lbl = (item.orig_label if item.orig_label is not None else lbl).strip()
        orig_val = (item.orig if item.orig is not None else val).strip()
        src = item.src or "read"
        conf = item.conf if item.conf is not None else 1.0

        if not lbl and not val:
            continue

        if not lbl and val:
            has_unlabelled = True

        # Detect edit: either label or value changed, or was marked edited
        is_edited = (lbl != orig_lbl) or (val != orig_val) or (src == "edited") or bool(item.is_edited)
        if is_edited and src != "added":
            src = "edited"
        elif not is_edited and src == "edited":
            src = "read"

        if conf < 0.85:
            has_low_conf = True

        meta_dict = {
            "value_confidence": item.val_conf if item.val_conf is not None else conf,
            "label_confidence": item.lbl_conf,
            "structure_type": getattr(item, "structure_type", "label_value_pair") or "label_value_pair",
            "structure_group": getattr(item, "structure_group", "fields") or "fields",
            "structure_confidence": getattr(item, "structure_confidence", 1.0) or 1.0,
            "region_id": getattr(item, "region_id", None),
            "reason": getattr(item, "reason", "") or "",
            "suggested_label": getattr(item, "suggested_label", "") or "",
            "hint": getattr(item, "hint", "") or "",
        }
        new_field = FieldModel(
            file_id=f.id,
            label=lbl,
            original_label=orig_lbl,
            value=val,
            original_value=orig_val,
            confidence=conf,
            source=src,
            is_edited=is_edited,
            position=pos,
            page=item.page or 1,
            bbox=json.dumps(item.bbox) if item.bbox else None,
            is_sensitive=bool(item.is_sensitive),
            meta_info=json.dumps(meta_dict),
        )
        db.add(new_field)

        # Record into corrections table for learning/feedback
        if is_edited and src != "added":
            who = user.email or user.name or str(user.id)
            pipe_ver = getattr(f, "pipeline_version", None) or "2.2.0"
            corr = CorrectionModel(
                user_id=user.id,
                who_edited=who,
                doc_type=f.doc_type or "Document",
                document_id=f.id,
                original_label=orig_lbl,
                new_label=lbl,
                label=lbl,
                original_value=orig_val,
                corrected_value=val,
                new_value=val,
                pipeline_version=pipe_ver,
                layout_hint=f.page_condition,
                created_at=datetime.now(timezone.utc),
            )
            db.add(corr)

    # Part 3: Count document as needing review if low confidence OR unlabelled fields exist
    f.status = "Done, check" if (has_low_conf or has_unlabelled) else "Done"
    db.commit()

    return {"message": "Saved successfully", "status": f.status}


@router.post("/files/{file_id}/regions/{region_id}/reclassify")
def reclassify_region(
    file_id: str,
    region_id: str,
    payload: ReclassifyRegionRequest,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    f = (
        db.query(FileModel)
        .join(BatchModel, BatchModel.id == FileModel.batch_id)
        .filter(FileModel.id == file_id, BatchModel.user_id == user.id)
        .first()
    )
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    new_type = payload.new_structure_type.strip().lower()
    regions = json.loads(f.regions_data) if getattr(f, "regions_data", None) else []
    target_region = None
    old_type = "other"

    for r in regions:
        if r.get("region_id") == region_id or r.get("id") == region_id:
            target_region = r
            old_type = r.get("structure_type", "other")
            r["structure_type"] = new_type
            r["region_id"] = region_id
            r["id"] = region_id
            break

    if not target_region:
        raise HTTPException(status_code=404, detail="Region not found")

    GROUP_MAP = {
        "label_value_pair": "fields",
        "form_row": "fields",
        "heading": "fields",
        "paragraph": "fields",
        "footnote": "fields",
        "header_footer": "fields",
        "watermark": "fields",
        "side_by_side": "fields",
        "other": "fields",
        "table": "tables",
        "list": "lists",
        "checkbox_group": "checkboxes",
        "signature_stamp": "signatures_and_stamps",
        "handwriting": "signatures_and_stamps",
        "image_logo": "images_and_charts",
        "chart_diagram": "images_and_charts",
        "barcode_qr": "codes",
    }
    new_group = GROUP_MAP.get(new_type, "fields")

    who = user.email or user.name or str(user.id)
    corr = CorrectionModel(
        user_id=user.id,
        who_edited=who,
        doc_type=f.doc_type or "Document",
        document_id=f.id,
        original_label=f"region_{region_id}:{old_type}",
        new_label=f"region_{region_id}:{new_type}",
        label=f"region_{region_id}:{new_type}",
        original_value=old_type,
        corrected_value=new_type,
        new_value=new_type,
        pipeline_version=getattr(f, "pipeline_version", "2.3.0"),
        layout_hint=f.page_condition,
        created_at=datetime.now(timezone.utc),
    )
    db.add(corr)

    # Update associated fields for this region
    for fld in f.fields:
        meta = {}
        if getattr(fld, "meta_info", None):
            try:
                meta = json.loads(fld.meta_info)
            except Exception:
                meta = {}
        if meta.get("region_id") == region_id:
            meta["structure_type"] = new_type
            meta["structure_group"] = new_group
            meta["structure_confidence"] = 1.0
            fld.meta_info = json.dumps(meta)
            fld.source = "edited"
            fld.is_edited = True

    f.regions_data = json.dumps(regions)
    db.commit()

    return {
        "message": "Region reclassified successfully",
        "region_id": region_id,
        "old_structure_type": old_type,
        "new_structure_type": new_type,
        "structure_group": new_group,
    }


@router.get("/corrections/export")
def export_corrections(
    format: str = Query("json", regex="^(json|csv)$"),
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Part 3: Export review corrections table as JSON or CSV."""
    import csv
    import io
    from fastapi.responses import Response

    corrections = (
        db.query(CorrectionModel)
        .filter(CorrectionModel.user_id == user.id)
        .order_by(CorrectionModel.created_at.desc())
        .all()
    )

    data = [
        {
            "id": c.id,
            "document_id": c.document_id,
            "doc_type": c.doc_type,
            "original_label": c.original_label,
            "new_label": c.new_label or c.label,
            "original_value": c.original_value,
            "new_value": c.new_value or c.corrected_value,
            "who_edited": c.who_edited,
            "pipeline_version": c.pipeline_version,
            "timestamp": c.created_at.isoformat() if c.created_at else None,
        }
        for c in corrections
    ]

    if format == "json":
        return {"total": len(data), "corrections": data}
    
    # CSV format
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "id",
            "document_id",
            "doc_type",
            "original_label",
            "new_label",
            "original_value",
            "new_value",
            "who_edited",
            "pipeline_version",
            "timestamp",
        ],
    )
    writer.writeheader()
    for row in data:
        writer.writerow(row)
    
    csv_bytes = output.getvalue().encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="corrections.csv"'},
    )


@router.post("/files/{file_id}/unlock")
def unlock_file(
    file_id: str,
    payload: UnlockFileRequest,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Part 4, Point 2: Unlock a password-protected document."""
    f = (
        db.query(FileModel)
        .join(BatchModel, BatchModel.id == FileModel.batch_id)
        .filter(FileModel.id == file_id, BatchModel.user_id == user.id)
        .first()
    )
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    try:
        reader_res = UniversalDocumentReader.read_file(f.stored_path, password=payload.password)
        db.query(FieldModel).filter(FieldModel.file_id == f.id).delete()
        new_fields = []
        has_low_conf = False
        for pos, d in enumerate(reader_res.all_details):
            if d.confidence < 0.85:
                has_low_conf = True
            new_fields.append(FieldModel(
                file_id=f.id,
                label=d.label,
                value=d.value,
                original_value=d.value,
                confidence=d.confidence,
                source=d.source,
                position=pos,
                page=d.page,
                bbox=json.dumps(d.bbox) if d.bbox else None,
                is_sensitive=d.is_sensitive,
                detector_tag=getattr(d, "detector_tag", None),
            ))
        db.add_all(new_fields)
        f.doc_type = reader_res.doc_type
        f.page_count = reader_res.page_count
        f.status = "Done, check" if has_low_conf else "Done"
        f.stage = "Done"
        f.error = None
        db.commit()
        return {"message": "File unlocked successfully", "status": f.status}
    except Exception as e:
        if "password" in str(e).lower():
            raise HTTPException(status_code=400, detail="Incorrect password. This file is password protected.")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/files/{file_id}/accept-all")
def accept_all_suggestions(
    file_id: str,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Section 7: Accept all generated label suggestions for a document."""
    f = (
        db.query(FileModel)
        .join(BatchModel, BatchModel.id == FileModel.batch_id)
        .filter(FileModel.id == file_id, BatchModel.user_id == user.id)
        .first()
    )
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    registry = LearnedRegistry.get_instance()
    for fld in f.fields:
        meta = {}
        if fld.meta_info:
            try:
                meta = json.loads(fld.meta_info)
            except Exception:
                meta = {}
        sug_lbl = meta.get("suggested_label", "")
        if sug_lbl and not fld.label.strip():
            fld.label = sug_lbl
            fld.source = "verified by reviewer"
            fld.is_edited = True
            registry.record_feedback(f.doc_type or "Document", fld.original_label or "", sug_lbl, fld.value)
        elif fld.source == "generated":
            fld.source = "verified by reviewer"
            fld.is_edited = True

    has_low_conf = any(fld.confidence < 0.85 for fld in f.fields)
    has_empty = any(not fld.label.strip() for fld in f.fields)
    f.status = "Done, check" if (has_low_conf or has_empty) else "Done"
    db.commit()
    return {"message": "All suggestions accepted", "status": f.status}


@router.post("/files/{file_id}/promote-detail")
def promote_detail(
    file_id: str,
    payload: Dict[str, Any],
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Section 2: Promote a detail from More Details into Key Details."""
    field_id = payload.get("field_id")
    fld = (
        db.query(FieldModel)
        .join(FileModel, FileModel.id == FieldModel.file_id)
        .join(BatchModel, BatchModel.id == FileModel.batch_id)
        .filter(FieldModel.id == field_id, FileModel.id == file_id, BatchModel.user_id == user.id)
        .first()
    )
    if not fld:
        raise HTTPException(status_code=404, detail="Field not found")

    meta = {}
    if fld.meta_info:
        try:
            meta = json.loads(fld.meta_info)
        except Exception:
            meta = {}
    meta["is_promoted"] = True
    meta["in_more_details"] = False
    fld.meta_info = json.dumps(meta)
    db.commit()
    return {"message": "Detail promoted successfully"}


@router.post("/files/{file_id}/accept-split")
def accept_split(
    file_id: str,
    payload: Dict[str, Any],
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Section 4: Accept split suggestion for a mixed detail."""
    field_id = payload.get("field_id")
    fld = (
        db.query(FieldModel)
        .join(FileModel, FileModel.id == FieldModel.file_id)
        .join(BatchModel, BatchModel.id == FileModel.batch_id)
        .filter(FieldModel.id == field_id, FileModel.id == file_id, BatchModel.user_id == user.id)
        .first()
    )
    if not fld:
        raise HTTPException(status_code=404, detail="Field not found")

    meta = {}
    if fld.meta_info:
        try:
            meta = json.loads(fld.meta_info)
        except Exception:
            meta = {}
    meta["split_accepted"] = True
    fld.meta_info = json.dumps(meta)
    fld.is_edited = True
    db.commit()
    return {"message": "Split suggestion accepted"}


@router.post("/batches/{batch_id}/bulk-verify-clean")
def bulk_verify_clean(
    batch_id: str,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Section 7: Bulk action for documents where every item is above the threshold."""
    batch = db.query(BatchModel).filter(BatchModel.id == batch_id, BatchModel.user_id == user.id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    verified_count = 0
    for f in batch.files:
        if f.status in ["Done, check", "Done"] and f.stage == "Done":
            all_clean = all(
                fld.confidence >= 0.85 and bool(fld.label.strip())
                for fld in f.fields
            )
            if all_clean:
                f.status = "Done"
                f.check_reasons = None
                verified_count += 1
    db.commit()
    return {"message": f"Verified {verified_count} clean documents", "verified_count": verified_count}


@router.get("/files/{file_id}/page/{page_num}")
def get_file_page_image(
    file_id: str,
    page_num: int = 1,
    db: Session = Depends(get_db),
):
    f = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="File record not found")

    # 1. Directly serve from Postgres preview_data without touching disk
    if page_num == 1 and f.preview_data:
        try:
            import base64
            png_bytes = base64.b64decode(f.preview_data)
            return Response(content=png_bytes, media_type="image/png")
        except Exception as e:
            logger.warning(f"Error decoding preview_data for {file_id}: {e}")

    # 2. Render from disk if stored path exists
    if f.stored_path and os.path.exists(f.stored_path):
        try:
            png_bytes = render_page_to_png_bytes(f.stored_path, page_num=page_num, dpi=150)
            if page_num == 1 and not f.preview_data:
                import base64
                f.preview_data = base64.b64encode(png_bytes).decode('ascii')
                safe_commit(db)
            return Response(content=png_bytes, media_type="image/png")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Could not render page image: {str(e)}")

    raise HTTPException(status_code=404, detail="Document preview not available")


@router.delete("/batches/{batch_id}")
def delete_batch(
    batch_id: str,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch = (
        db.query(BatchModel)
        .filter(BatchModel.id == batch_id, BatchModel.user_id == user.id)
        .first()
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Remove stored files on disk
    for f in batch.files:
        if os.path.exists(f.stored_path):
            try:
                os.remove(f.stored_path)
            except Exception:
                pass

    db.delete(batch)
    db.commit()
    return {"message": "Batch deleted successfully"}


@router.delete("/batches")
def clear_all_batches(
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batches = db.query(BatchModel).filter(BatchModel.user_id == user.id).all()
    for batch in batches:
        for f in batch.files:
            if os.path.exists(f.stored_path):
                try:
                    os.remove(f.stored_path)
                except Exception:
                    pass
        db.delete(batch)
    db.commit()
    return {"message": "All batches cleared successfully"}


@router.get("/batches/{batch_id}/download")
def download_batch_zip(
    batch_id: str,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch = (
        db.query(BatchModel)
        .filter(BatchModel.id == batch_id, BatchModel.user_id == user.id)
        .first()
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. Add original files preserving original relative folder structure
        for f in batch.files:
            if os.path.exists(f.stored_path):
                rel = (f.relative_path or f.original_name).replace("\\", "/").lstrip("/")
                zf.write(f.stored_path, arcname=f"original_documents/{rel}")

        # 2. Build index.csv (Part 1, point 6 & Part 2, point 5)
        # Quote values that contain commas, one column per label found across batch,
        # leave cell empty when lacking detail, and column listing which labels were sensitive.
        all_labels = []
        for f in batch.files:
            for fld in f.fields:
                if fld.label not in all_labels:
                    all_labels.append(fld.label)

        csv_buffer = io.StringIO()
        csv_writer = csv.writer(csv_buffer, quoting=csv.QUOTE_MINIMAL)
        header = ["File", "Document Type"] + all_labels + ["Sensitive Labels", "Status"]
        csv_writer.writerow(header)

        for f in batch.files:
            field_map = {}
            for fld in f.fields:
                if fld.label not in field_map:
                    field_map[fld.label] = fld.value
                elif fld.value not in field_map[fld.label]:
                    field_map[fld.label] += "; " + fld.value
            sensitive_labels = [fld.label for fld in f.fields if fld.is_sensitive]
            row = [f.original_name, f.doc_type or "Document"]
            for lbl in all_labels:
                row.append(field_map.get(lbl, ""))
            row.append("; ".join(sensitive_labels))
            row.append(f.status)
            csv_writer.writerow(row)

        csv_bytes = csv_buffer.getvalue().encode("utf-8-sig")
        zf.writestr("index.csv", csv_bytes)
        zf.writestr("results.csv", csv_bytes)

        # 3. Build results.xlsx (one sheet per document type)
        wb = openpyxl.Workbook()
        wb.remove(wb.active)  # Remove default initial sheet

        # Group files by doc_type
        groups: Dict[str, List[FileModel]] = {}
        for f in batch.files:
            t = f.doc_type or "Document"
            groups.setdefault(t, []).append(f)

        for doc_type, group_files in groups.items():
            # Clean sheet name (max 31 chars, valid chars)
            sheet_title = re.sub(r"[\\/*?:\[\]]", "_", doc_type)[:31]
            ws = wb.create_sheet(title=sheet_title)

            # Find unique labels for this group
            group_labels = []
            for f in group_files:
                for fld in f.fields:
                    if fld.label not in group_labels:
                        group_labels.append(fld.label)

            sheet_header = ["File"] + group_labels + ["Sensitive Labels", "Status"]
            ws.append(sheet_header)

            for f in group_files:
                field_map = {}
                for fld in f.fields:
                    if fld.label not in field_map:
                        field_map[fld.label] = fld.value
                    elif fld.value not in field_map[fld.label]:
                        field_map[fld.label] += "; " + fld.value
                sensitive_labels = [fld.label for fld in f.fields if fld.is_sensitive]
                row = [f.original_name]
                for lbl in group_labels:
                    row.append(field_map.get(lbl, ""))
                row.append("; ".join(sensitive_labels))
                row.append(f.status)
                ws.append(row)

        excel_buffer = io.BytesIO()
        wb.save(excel_buffer)
        zf.writestr("results.xlsx", excel_buffer.getvalue())

    zip_buffer.seek(0)
    filename = f"batch_{batch.id[:8]}_results.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/files/{file_id}/retry")
def retry_file(
    file_id: str,
    background_tasks: BackgroundTasks,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-run AI extraction for a specific file and update results."""
    f = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    batch = db.query(BatchModel).filter(BatchModel.id == f.batch_id, BatchModel.user_id == user.id).first()
    if not batch:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Clear previous error or fields
    db.query(FieldModel).filter(FieldModel.file_id == f.id).delete()
    f.stage = "Reading"
    f.status = "Reading"
    f.error = None
    f.finished_at = None
    db.commit()

    # Re-run processing fresh immediately so frontend gets updated result
    try:
        process_file_background(f.id, None, True)
    except Exception as e:
        logger.error(f"Error retrying file {file_id}: {e}", exc_info=True)

    db.refresh(f)
    return {
        "message": "File extraction reprocessed",
        "file_id": f.id,
        "stage": f.stage,
        "status": f.status,
        "type": f.doc_type,
        "check_reasons": f.check_reasons
    }


@router.post("/batches/{batch_id}/retry-rate-limited")
def retry_batch_rate_limited(
    batch_id: str,
    background_tasks: BackgroundTasks,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-run AI extraction for all files in a batch that hit rate limits or failed."""
    batch = db.query(BatchModel).filter(BatchModel.id == batch_id, BatchModel.user_id == user.id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    retried_ids = []
    # First pass: retry failed, rate-limited, error, or empty files
    for f in batch.files:
        is_rl = False
        for fld in f.fields:
            if "rate limit" in str(fld.value).lower():
                is_rl = True
                break
        if is_rl or f.stage == "Failed" or not f.fields or f.error:
            db.query(FieldModel).filter(FieldModel.file_id == f.id).delete()
            f.stage = "Reading"
            f.status = "Reading"
            f.error = None
            f.finished_at = None
            retried_ids.append(f.id)
            background_tasks.add_task(process_file_background, f.id, None, True)

    # If all were marked done but user requested a full re-process, retry all
    if not retried_ids:
        for f in batch.files:
            db.query(FieldModel).filter(FieldModel.file_id == f.id).delete()
            f.stage = "Reading"
            f.status = "Reading"
            f.error = None
            f.finished_at = None
            retried_ids.append(f.id)
            background_tasks.add_task(process_file_background, f.id, None, True)

    db.commit()
    return {"message": f"Retrying {len(retried_ids)} files", "retried_count": len(retried_ids), "file_ids": retried_ids}


@router.post("/files/{file_id}/reprocess")
def reprocess_file(
    file_id: str,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reprocess a document with the latest GeneralizedDocumentPipeline version."""
    f = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    batch = db.query(BatchModel).filter(BatchModel.id == f.batch_id, BatchModel.user_id == user.id).first()
    if not batch:
        raise HTTPException(status_code=403, detail="Not authorized")

    if not os.path.exists(f.stored_path):
        raise HTTPException(status_code=404, detail="Underlying document file not found on disk")

    from app.core.generalized_pipeline import GeneralizedDocumentPipeline
    pipeline = GeneralizedDocumentPipeline()
    result = pipeline.process_file(f.stored_path)

    # Update database record
    f.doc_type = result["type"]
    f.pipeline_version = result["pipeline_version"]
    f.stage = "Done"
    f.status = "Done"
    f.error = None
    f.tables_data = json.dumps(result.get("tables", []))

    # Replace existing fields with the generalized pipeline extraction
    db.query(FieldModel).filter(FieldModel.file_id == f.id).delete()
    for idx, field in enumerate(result["fields"]):
        fld_record = FieldModel(
            file_id=f.id,
            label=field["label"],
            value=field["value"],
            original_value=field["value"],
            confidence=field["confidence"],
            source="pipeline",
            position=idx,
            page=field["page"],
            is_sensitive=False,
        )
        db.add(fld_record)

    db.commit()
    return {
        "message": "File reprocessed successfully",
        "file_id": f.id,
        "pipeline_version": result["pipeline_version"],
        "result": result,
    }


class UpdateTablesRequest(BaseModel):
    tables: List[Dict[str, Any]]


@router.put("/files/{file_id}/tables")
@router.post("/files/{file_id}/tables")
def update_file_tables(
    file_id: str,
    payload: UpdateTablesRequest,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    f = (
        db.query(FileModel)
        .join(BatchModel, BatchModel.id == FileModel.batch_id)
        .filter(FileModel.id == file_id, BatchModel.user_id == user.id)
        .first()
    )
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    with _sqlite_write_lock:
        f.tables_data = json.dumps(payload.tables)
        safe_commit(db)

    return {"message": "Tables updated successfully", "tables": payload.tables}


@router.get("/account/export")
def export_account_data(
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Full account export (JSON + CSV + 30-Day Expiry README) for Render free Postgres backup."""

    batches = db.query(BatchModel).filter(BatchModel.user_id == user.id).all()

    account_export = {
        "user_id": user.id,
        "user_name": user.name,
        "user_email": user.email,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "total_batches": len(batches),
        "batches": [],
    }

    csv_rows = []
    csv_rows.append([
        "batch_id", "batch_name", "file_id", "file_name", "document_type",
        "file_status", "field_label", "field_value", "confidence",
        "is_sensitive", "is_edited", "original_value", "page", "created_at"
    ])

    for b in batches:
        b_dict = {
            "batch_id": b.id,
            "batch_name": b.name,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "files": [],
        }
        for f in b.files:
            f_dict = {
                "file_id": f.id,
                "original_name": f.original_name,
                "relative_path": f.relative_path,
                "document_type": f.doc_type,
                "status": f.status,
                "stage": f.stage,
                "error": f.error,
                "check_reasons": f.check_reasons,
                "document_summary": f.document_summary,
                "created_at": f.created_at.isoformat() if f.created_at else None,
                "finished_at": f.finished_at.isoformat() if f.finished_at else None,
                "fields": [],
            }
            for fld in f.fields:
                f_dict["fields"].append({
                    "label": fld.label,
                    "value": fld.value,
                    "confidence": fld.confidence,
                    "is_sensitive": fld.is_sensitive,
                    "is_edited": fld.is_edited,
                    "original_value": fld.original_value,
                    "page": fld.page,
                })
                csv_rows.append([
                    b.id,
                    b.name or "",
                    f.id,
                    f.original_name or "",
                    f.doc_type or "",
                    f.status or "",
                    fld.label or "",
                    fld.value or "",
                    str(fld.confidence or ""),
                    str(bool(fld.is_sensitive)),
                    str(bool(fld.is_edited)),
                    fld.original_value or "",
                    str(fld.page or 1),
                    f.created_at.isoformat() if f.created_at else "",
                ])
            b_dict["files"].append(f_dict)
        account_export["batches"].append(b_dict)

    json_bytes = json.dumps(account_export, indent=2, ensure_ascii=False).encode("utf-8")

    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf, quoting=csv.QUOTE_MINIMAL)
    for row in csv_rows:
        writer.writerow(row)
    csv_bytes = csv_buf.getvalue().encode("utf-8")

    readme_content = (
        "================================================================================\n"
        "IMPORTANT NOTICE: RENDER FREE POSTGRESQL 30-DAY EXPIRY & DATA RETENTION\n"
        "================================================================================\n\n"
        "Render free-tier PostgreSQL databases expire and are deleted exactly 30 days\n"
        "after creation.\n\n"
        "To ensure zero data loss:\n"
        "1. Regularly export your account data using the 'Export Account Data' feature\n"
        "   in your dashboard before the 30-day mark.\n"
        "2. When your 30-day Render database expires, provision a new free database\n"
        "   instance in Render Dashboard, update the DATABASE_URL environment variable\n"
        "   in your Render Web Service settings, and redeploy.\n"
        "3. This archive contains:\n"
        "   - account_data.json: Complete structured dump of all batches, files, and fields.\n"
        "   - account_data.csv: Tabular representation of all extracted key-value records.\n"
        "   - README_30_DAY_EXPIRY.txt: This maintenance and recovery guide.\n\n"
        f"Export Timestamp: {datetime.now(timezone.utc).isoformat()}\n"
        f"Account ID: {user.id}\n"
        f"Account Email: {user.email}\n"
        "================================================================================\n"
    ).encode("utf-8")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("account_data.json", json_bytes)
        zf.writestr("account_data.csv", csv_bytes)
        zf.writestr("README_30_DAY_EXPIRY.txt", readme_content)

    zip_bytes = zip_buffer.getvalue()
    filename = f"account_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )



