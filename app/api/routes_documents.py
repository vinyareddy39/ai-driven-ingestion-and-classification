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
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Response, UploadFile, status
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
    conf: Optional[float] = 1.0
    src: Optional[str] = "read"
    page: Optional[int] = 1
    bbox: Optional[Any] = None
    is_sensitive: Optional[bool] = False


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


_sqlite_write_lock = threading.Lock()


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

        if not force_fresh and user_id:
            cached_done = (
                db.query(FileModel)
                .join(BatchModel, BatchModel.id == FileModel.batch_id)
                .filter(
                    FileModel.cache_key == cache_key,
                    BatchModel.user_id == user_id,
                    FileModel.stage.in_(["Done", "done"]),
                    FileModel.id != f.id,
                )
                .order_by(FileModel.created_at.desc())
                .first()
            )
            if cached_done:
                c_fields = db.query(FieldModel).filter(FieldModel.file_id == cached_done.id).all()
                has_rate_limit = any("rate limit" in str(cf.value).lower() for cf in c_fields)
                if c_fields and not has_rate_limit:
                    f.started_at = datetime.now(timezone.utc)
                    f.stage = "Done"
                    f.status = "done"
                    f.doc_type = cached_done.doc_type
                    f.page_count = cached_done.page_count
                    f.page_condition = cached_done.page_condition
                    new_fields = []
                    for cf in c_fields:
                        new_fields.append(FieldModel(
                            file_id=f.id,
                            label=cf.label,
                            value=cf.value,
                            original_value=cf.original_value,
                            confidence=cf.confidence,
                            source="cache",
                            position=cf.position,
                        ))
                    db.add_all(new_fields)
                    f.finished_at = datetime.now(timezone.utc)
                    total_ms = round((time.perf_counter() - t0) * 1000, 2)
                    f.stage_timings = json.dumps({
                        "hash_ms": hash_ms,
                        "text_check_ms": 0.0,
                        "render_ms": 0.0,
                        "deskew_ms": 0.0,
                        "model_ms": 0.0,
                        "db_write_ms": 0.5,
                        "total_ms": total_ms,
                    })
                    db.commit()
                    logger.info(f"User cache hit for {f.original_name} (key: {cache_key[:12]}). Finished in {total_ms}ms.")
                    return

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

        # 1. Multi-Format Universal Document Reading
        t_read = time.perf_counter()
        try:
            reader_result = UniversalDocumentReader.read_file(f.stored_path)
        except PasswordProtectedException:
            with _sqlite_write_lock:
                f.stage = "Done"
                f.status = "Locked"
                f.error = "This file is password protected."
                f.finished_at = datetime.now(timezone.utc)
                safe_commit(db)
            logger.info(f"File {f.original_name} is password protected.")
            return
        except EmptyFileException:
            with _sqlite_write_lock:
                f.stage = "Done"
                f.status = "Empty"
                f.error = "This file is empty."
                f.finished_at = datetime.now(timezone.utc)
                safe_commit(db)
            logger.info(f"File {f.original_name} is empty.")
            return
        except DamagedFileException:
            with _sqlite_write_lock:
                f.stage = "Done"
                f.status = "Damaged"
                f.error = "This file looks damaged. Try uploading it again from the original."
                f.finished_at = datetime.now(timezone.utc)
                safe_commit(db)
            logger.info(f"File {f.original_name} is damaged or corrupt.")
            return
        except Exception as e:
            logger.error(f"Error reading file {file_id}: {e}", exc_info=True)
            with _sqlite_write_lock:
                f.stage = "Done"
                f.status = "check"
                f.error = "We couldn't read this one yet. We'll keep trying."
                f.finished_at = datetime.now(timezone.utc)
                safe_commit(db)
            return

        f.page_count = reader_result.page_count
        f.doc_type = reader_result.doc_type
        f.page_condition = "clean"
        ext = os.path.splitext(f.stored_path)[1].lower()

        # If image or PDF, also detect condition & render first page image
        if ext in [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"]:
            try:
                img, pc = render_first_page_image(f.stored_path, dpi=120)
                if pc > f.page_count:
                    f.page_count = pc
                cond, _ = detect_page_condition(img)
                f.page_condition = cond
            except Exception:
                pass

        details = list(reader_result.all_details)

        # Check for blank pages and add neutral note
        for p in reader_result.pages:
            if p.is_blank:
                details.append(ExtractedDetail(
                    label=f"Page {p.page_number}",
                    value="Nothing to read on this page",
                    confidence=1.0,
                    page=p.page_number,
                    bbox=None,
                    is_sensitive=False,
                ))

        # If zero details found by local reader, try provider fallback
        if not details:
            try:
                from app.core.comprehensive_extractor import is_sensitive_detail
                orchestrator = get_fallback_orchestrator()
                worker_loop = get_persistent_worker_loop()
                future = asyncio.run_coroutine_threadsafe(
                    orchestrator.extract_document(
                        images_b64=None,
                        local_ocr_text="\n".join(p.full_text for p in reader_result.pages),
                        is_sensitive=reader_result.is_sensitive,
                        user_id=user_id,
                        sha256=f.sha256,
                    ),
                    worker_loop,
                )
                prov_res = future.result(timeout=40.0)
                if prov_res and prov_res.fields:
                    full_text_lower = "\n".join(p.full_text for p in reader_result.pages).lower()
                    for f_item in prov_res.fields:
                        lbl = str(f_item.get("label", "")).strip()
                        val = str(f_item.get("value", "")).strip()
                        if val and val.lower() in full_text_lower:
                            details.append(ExtractedDetail(
                                label=lbl,
                                value=val,
                                confidence=float(f_item.get("confidence", 0.90)),
                                page=1,
                                is_sensitive=is_sensitive_detail(lbl, val),
                            ))
            except Exception as e:
                logger.warning(f"Fallback extraction exception: {e}")

        new_fields = []
        has_low_conf = False
        for pos, d in enumerate(details):
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

        total_ms = round((time.perf_counter() - t0) * 1000, 2)
        with _sqlite_write_lock:
            db.query(FieldModel).filter(FieldModel.file_id == f.id).delete()
            db.add_all(new_fields)
            f.stage = "Done"
            f.status = "Done, check" if has_low_conf else "Done"
            f.error = None
            f.finished_at = datetime.now(timezone.utc)
            f.stage_timings = json.dumps({
                "queue_wait_ms": queue_wait_ms,
                "total_ms": total_ms,
                "provider": "local_universal_reader",
                "details_count": len(new_fields),
                "sensitive_count": sum(1 for x in new_fields if x.is_sensitive),
            })
            safe_commit(db)

        sens_count = sum(1 for x in new_fields if x.is_sensitive)
        logger.info(f"File {f.original_name} completed in {total_ms}ms: {len(new_fields)} details ({sens_count} sensitive).")

    except Exception as e:
        logger.error(f"Error processing file {file_id}: {e}", exc_info=True)
        if f:
            f.stage = "Failed"
            f.status = "failed"
            f.error = str(e)
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
    files: List[UploadFile] = File(...),
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    # Part 4, Point 2: Unsupported type blocked at upload before anything is sent
    for upload in files:
        filename = upload.filename or ""
        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail="This file type isn't supported. Supported types: PDF, PNG, JPG, TIFF, BMP, TXT, CSV, DOCX, XLSX, EML."
            )

    batch_name = f"Batch · {len(files)} files"
    batch = BatchModel(user_id=user.id, name=batch_name)
    db.add(batch)
    db.commit()
    db.refresh(batch)

    saved_files = []
    for upload in files:
        file_bytes = upload.file.read()
        sha256 = compute_sha256(file_bytes)

        # Check duplicate
        dup_file = (
            db.query(FileModel)
            .filter(FileModel.sha256 == sha256)
            .order_by(FileModel.created_at.asc())
            .first()
        )
        dup_name = dup_file.original_name if dup_file else None

        safe_filename = re.sub(r"[^a-zA-Z0-9_.-]", "_", upload.filename or "doc")
        file_id = str(uuid.uuid4())
        stored_path = os.path.join(STORAGE_DIR, f"{file_id}_{safe_filename}")
        with open(stored_path, "wb") as f_out:
            f_out.write(file_bytes)

        file_record = FileModel(
            id=file_id,
            batch_id=batch.id,
            original_name=upload.filename or safe_filename,
            stored_path=stored_path,
            sha256=sha256,
            status="Waiting",
            stage="Waiting",
            duplicate_of=dup_name,
        )
        db.add(file_record)
        saved_files.append(file_record)

    db.commit()

    # Launch background thread to process batch files
    thread = threading.Thread(target=process_batch_background, args=(batch.id,), daemon=True)
    thread.start()

    return {
        "id": batch.id,
        "name": batch.name,
        "file_count": len(saved_files),
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
    }


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
        fields_data = [
            {
                "id": fld.id,
                "label": fld.label,
                "value": fld.value,
                "orig": fld.original_value,
                "conf": fld.confidence,
                "src": fld.source,
                "page": fld.page or 1,
                "bbox": json.loads(fld.bbox) if fld.bbox else None,
                "is_sensitive": bool(fld.is_sensitive),
                "detector_tag": getattr(fld, "detector_tag", None),
                "is_unlabelled": bool(fld.label.startswith("Unlabelled")),
            }
            for fld in f.fields
        ]
        
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

        user_facing_clean_errors = [
            "This file is password protected.",
            "This file is empty.",
            "This file looks damaged. Try uploading it again from the original.",
            "We couldn't read this one yet. We'll keep trying."
        ]
        clean_err = f.error
        if clean_err and clean_err not in user_facing_clean_errors:
            if "password" in clean_err.lower():
                clean_err = "This file is password protected."
            elif "empty" in clean_err.lower():
                clean_err = "This file is empty."
            elif "damaged" in clean_err.lower() or "corrupt" in clean_err.lower():
                clean_err = "This file looks damaged. Try uploading it again from the original."
            else:
                clean_err = "We couldn't read this one yet. We'll keep trying."

        # Part 5, Point 3: While waiting, show only neutral states: 'Waiting' or 'Still reading'
        clean_stage = f.stage
        if clean_stage not in ["Done", "Failed"]:
            clean_stage = "Waiting" if clean_stage == "Waiting" else "Still reading"

        files_data.append({
            "id": f.id,
            "name": f.original_name,
            "type": f.doc_type or "Document",
            "cond": f.page_condition or "clean",
            "dup": f.duplicate_of,
            "status": f.status,
            "stage": clean_stage,
            "error": clean_err,
            "provider": f.provider_name or timings_dict.get("provider", "local_ocr"),
            "model": f.model_name or timings_dict.get("model", "default"),
            "is_fallback": f.is_fallback or timings_dict.get("is_fallback", False),
            "timings": timings_dict,
            "fields": fields_data,
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
    f = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    fields_data = [
        {
            "id": fld.id,
            "label": fld.label,
            "value": fld.value,
            "orig": fld.original_value,
            "conf": fld.confidence,
            "src": fld.source,
            "page": fld.page or 1,
            "bbox": json.loads(fld.bbox) if fld.bbox else None,
            "is_sensitive": bool(fld.is_sensitive),
            "detector_tag": getattr(fld, "detector_tag", None),
            "is_unlabelled": bool(fld.label.startswith("Unlabelled")),
        }
        for fld in f.fields
    ]

    clean_stage = f.stage
    if clean_stage not in ["Done", "Failed"]:
        clean_stage = "Waiting" if clean_stage == "Waiting" else "Still reading"

    return {
        "id": f.id,
        "batch_id": f.batch_id,
        "name": f.original_name,
        "type": f.doc_type or "Document",
        "cond": f.page_condition or "clean",
        "dup": f.duplicate_of,
        "status": f.status,
        "stage": clean_stage,
        "error": f.error,
        "fields": fields_data,
    }


@router.put("/files/{file_id}/fields")
def update_file_fields(
    file_id: str,
    payload: UpdateFieldsRequest,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    f = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    # Record corrections for learning
    existing_fields = {fld.label: fld.original_value for fld in f.fields}

    # Delete old fields
    db.query(FieldModel).filter(FieldModel.file_id == f.id).delete()

    has_low_conf = False
    for pos, item in enumerate(payload.fields):
        lbl = item.label.strip()
        val = item.value.strip()
        orig = (item.orig or val).strip()
        src = item.src or "read"
        conf = item.conf if item.conf is not None else 1.0

        if not lbl and not val:
            continue

        # Detect edit
        if src == "read" and val != orig:
            src = "edited"
        elif src == "edited" and val == orig:
            src = "read"

        if conf < 0.85:
            has_low_conf = True

        new_field = FieldModel(
            file_id=f.id,
            label=lbl,
            value=val,
            original_value=orig,
            confidence=conf,
            source=src,
            position=pos,
            page=item.page or 1,
            bbox=json.dumps(item.bbox) if item.bbox else None,
            is_sensitive=bool(item.is_sensitive),
        )
        db.add(new_field)

        # Record into corrections table if user corrected a read value
        if src == "edited" and orig and val != orig:
            corr = CorrectionModel(
                user_id=user.id,
                doc_type=f.doc_type or "Document",
                label=lbl,
                original_value=orig,
                corrected_value=val,
                layout_hint=f.page_condition,
            )
            db.add(corr)

    f.status = "Done, check" if has_low_conf else "Done"
    db.commit()

    return {"message": "Saved successfully", "status": f.status}


@router.post("/files/{file_id}/unlock")
def unlock_file(
    file_id: str,
    payload: UnlockFileRequest,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Part 4, Point 2: Unlock a password-protected document."""
    f = db.query(FileModel).filter(FileModel.id == file_id).first()
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

    f.status = "Done, check" if has_low_conf else "Done"
    db.commit()

    return {"message": "Saved successfully", "status": f.status}


@router.get("/files/{file_id}/page/{page_num}")
def get_file_page_image(
    file_id: str,
    page_num: int = 1,
    db: Session = Depends(get_db),
):
    f = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not f or not os.path.exists(f.stored_path):
        raise HTTPException(status_code=404, detail="File image not found")

    try:
        png_bytes = render_page_to_png_bytes(f.stored_path, page_num=page_num, dpi=150)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not render page image: {str(e)}")


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
        # 1. Add original files
        for f in batch.files:
            if os.path.exists(f.stored_path):
                zf.write(f.stored_path, arcname=f"original_documents/{f.original_name}")

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
    """Re-run AI extraction for a specific file (e.g. if rate limit was reached)."""
    f = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    batch = db.query(BatchModel).filter(BatchModel.id == f.batch_id, BatchModel.user_id == user.id).first()
    if not batch:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Clear previous error or rate limit fields
    db.query(FieldModel).filter(FieldModel.file_id == f.id).delete()
    f.stage = "Reading"
    f.status = "Reading"
    f.error = None
    f.finished_at = None
    db.commit()

    # Launch background worker with force_fresh=True
    background_tasks.add_task(process_file_background, f.id, None, True)

    return {"message": "Retrying file extraction", "file_id": f.id, "stage": "Reading"}


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
