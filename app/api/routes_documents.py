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
            f.stage = "processing"
            f.status = "processing"
            safe_commit(db)

        # 1. Text-layer check (Fast Lane: classify from page 1 and detect multi-page text)
        t_tl = time.perf_counter()
        ext = os.path.splitext(f.stored_path)[1].lower()
        pages_text = []
        page_count = 1
        if ext == ".pdf":
            try:
                doc = fitz.open(f.stored_path)
                page_count = len(doc)
                for p in doc:
                    txt = p.get_text().strip()
                    if txt:
                        pages_text.append(txt)
                doc.close()
            except Exception:
                pass
        f.page_count = page_count
        digital_text = "\n".join(pages_text).strip()
        is_digital = len(digital_text) > 40
        text_check_ms = round((time.perf_counter() - t_tl) * 1000, 2)

        # 2. Render first page (150 DPI, long side about 1000px, JPEG quality 75)
        t_rnd = time.perf_counter()
        try:
            dpi = 120 if is_digital else 150
            img, pc = render_first_page_image(f.stored_path, dpi=dpi)
            if pc > f.page_count:
                f.page_count = pc
        except Exception as e:
            f.stage = "Failed"
            f.status = "failed"
            f.error = f"Failed to render document: {str(e)}"
            f.finished_at = datetime.now(timezone.utc)
            db.commit()
            return
        render_ms = round((time.perf_counter() - t_rnd) * 1000, 2)

        # 3. Detect condition & skip deskew when skew is under 1 degree
        t_dsk = time.perf_counter()
        if is_digital:
            f.page_condition = "clean (digital)"
            cleaned_img = img
        else:
            condition, skew_angle = detect_page_condition(img)
            f.page_condition = condition
            cleaned_img = deskew_and_clean(img, skew_angle)
        deskew_ms = round((time.perf_counter() - t_dsk) * 1000, 2)

        # 4. Fetch at most 5-10 learned corrections per doc type
        corrections_list = []
        if user_id:
            user_corrections = db.query(CorrectionModel).filter(CorrectionModel.user_id == user_id).all()
            for c in user_corrections[:8]:
                corrections_list.append({
                    "doc_type": c.doc_type,
                    "label": c.label,
                    "original_value": c.original_value,
                    "corrected_value": c.corrected_value,
                })

        # 5. Multi-page preparation and Dynamic Sensitivity Detection
        t_mdl = time.perf_counter()
        images_b64 = []
        if not is_digital:
            if ext == ".pdf":
                try:
                    doc = fitz.open(f.stored_path)
                    for page in doc:
                        pix = page.get_pixmap(dpi=150)
                        p_img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                        if pix.n == 4:
                            p_img = cv2.cvtColor(p_img, cv2.COLOR_RGBA2BGR)
                        elif pix.n == 3:
                            p_img = cv2.cvtColor(p_img, cv2.COLOR_RGB2BGR)
                        h_p, w_p = p_img.shape[:2]
                        max_p = max(h_p, w_p)
                        if max_p > 1000:
                            scale = 1000.0 / max_p
                            p_img = cv2.resize(p_img, (int(w_p * scale), int(h_p * scale)), interpolation=cv2.INTER_AREA)
                        _, buf = cv2.imencode(".jpg", p_img, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                        images_b64.append(base64.b64encode(buf).decode("utf-8"))
                    doc.close()
                except Exception:
                    pass
            if not images_b64:
                _, buf = cv2.imencode(".jpg", cleaned_img, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                images_b64.append(base64.b64encode(buf).decode("utf-8"))

        local_ocr_text = digital_text if is_digital else ""
        is_sensitive, _, pii_entities = evaluate_document_sensitivity(local_ocr_text, doc_type=None, confidence=0.0)

        orchestrator = get_fallback_orchestrator()
        worker_loop = get_persistent_worker_loop()
        try:
            future = asyncio.run_coroutine_threadsafe(
                orchestrator.extract_document(
                    images_b64=images_b64 if not is_digital else None,
                    local_ocr_text=local_ocr_text,
                    is_sensitive=is_sensitive,
                    user_id=user_id,
                    sha256=f.sha256,
                    corrections=corrections_list,
                ),
                worker_loop,
            )
            provider_result = future.result(timeout=60.0)
        except Exception as e:
            logger.error(f"Error running provider orchestrator: {e}", exc_info=True)
            from app.core.providers import ProviderResult
            provider_result = ProviderResult(
                doc_type="Document",
                title="Document",
                fields=[],
                provider_name="error_handler",
                model_name="none",
                is_fallback=True,
                requires_review=True,
                status="check",
                error_message=str(e),
            )

        model_ms = round((time.perf_counter() - t_mdl) * 1000, 2)

        f.provider_name = provider_result.provider_name
        f.model_name = provider_result.model_name
        f.is_fallback = provider_result.is_fallback
        f.prompt_version = PROMPT_VERSION
        f.doc_type = provider_result.doc_type

        raw_fields = provider_result.fields or []
        calibrated_fields = cross_check_confidence(raw_fields)

        # 6. Prepare fields & check review gate
        has_low_conf = provider_result.requires_review or len(calibrated_fields) == 0
        new_fields = []
        for pos, item in enumerate(calibrated_fields):
            lbl = str(item.get("label", "")).strip()
            val = str(item.get("value", "")).strip()
            conf = float(item.get("confidence", 0.95))
            if conf < 0.85:
                has_low_conf = True

            new_fields.append(FieldModel(
                file_id=f.id,
                label=lbl,
                value=val,
                original_value=val,
                confidence=conf,
                source="read",
                position=pos,
            ))

        # 7. SQLite atomic batch write
        t_db = time.perf_counter()
        with _sqlite_write_lock:
            db.query(FieldModel).filter(FieldModel.file_id == f.id).delete()
            db.add_all(new_fields)
            f.stage = "Done"
            f.status = "check" if has_low_conf else "done"
            f.error = None
            f.finished_at = datetime.now(timezone.utc)
            db_write_ms = round((time.perf_counter() - t_db) * 1000, 2)
            total_ms = round((time.perf_counter() - t0) * 1000, 2)

            stage_timings = {
                "queue_wait_ms": queue_wait_ms,
                "hash_ms": hash_ms,
                "text_layer_check_ms": text_check_ms,
                "render_ms": render_ms,
                "deskew_ms": deskew_ms,
                "ocr_ms": 0.0,
                "model_call_ms": model_ms,
                "db_write_ms": db_write_ms,
                "total_ms": total_ms,
                "provider": provider_result.provider_name,
                "model": provider_result.model_name,
                "is_fallback": provider_result.is_fallback,
            }
            }
            f.stage_timings = json.dumps(stage_timings)
            safe_commit(db)
        logger.info(f"File {f.original_name} finished in {total_ms}ms (queue wait {queue_wait_ms}ms): {stage_timings}")

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

    # Progress calculation matching demo: Waiting=0, Reading=0.35, Extracting=0.7, Done/Failed=1.0
    stage_weights = {"Waiting": 0.0, "Reading": 0.35, "Extracting": 0.7, "Done": 1.0, "Failed": 1.0}
    part = sum(stage_weights.get(f.stage, 0.0) for f in batch.files)
    pct = round((part / total_files * 100)) if total_files > 0 else 0

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

        clean_err = f.error
        if clean_err and ("Fast Lane" in clean_err or "connect to text LLMs" in clean_err):
            clean_err = None

        files_data.append({
            "id": f.id,
            "name": f.original_name,
            "type": f.doc_type or "Document",
            "cond": f.page_condition or "clean",
            "dup": f.duplicate_of,
            "status": f.status,
            "stage": f.stage,
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
        }
        for fld in f.fields
    ]

    return {
        "id": f.id,
        "batch_id": f.batch_id,
        "name": f.original_name,
        "type": f.doc_type or "Document",
        "cond": f.page_condition or "clean",
        "dup": f.duplicate_of,
        "status": f.status,
        "stage": f.stage,
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

        # 2. Build results.csv
        # Find all unique labels across entire batch
        all_labels = []
        for f in batch.files:
            for fld in f.fields:
                if fld.label not in all_labels:
                    all_labels.append(fld.label)

        csv_buffer = io.StringIO()
        csv_writer = csv.writer(csv_buffer)
        header = ["File", "Document Type"] + all_labels + ["Status"]
        csv_writer.writerow(header)

        for f in batch.files:
            field_map = {fld.label: fld.value for fld in f.fields}
            row = [f.original_name, f.doc_type or "Document"]
            for lbl in all_labels:
                row.append(field_map.get(lbl, ""))
            row.append(f.status)
            csv_writer.writerow(row)

        zf.writestr("results.csv", csv_buffer.getvalue().encode("utf-8-sig"))

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

            sheet_header = ["File"] + group_labels + ["Status"]
            ws.append(sheet_header)

            for f in group_files:
                field_map = {fld.label: fld.value for fld in f.fields}
                row = [f.original_name]
                for lbl in group_labels:
                    row.append(field_map.get(lbl, ""))
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
