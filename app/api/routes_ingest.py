"""Ingestion API endpoints supporting single upload, bulk upload, EML parsing, and scanner watch."""

import hashlib
import os
from pathlib import Path
import shutil
from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from app.adapters.queue import get_queue_adapter
from app.adapters.storage import get_storage_adapter
from app.core.auth import get_current_user, require_role
from app.core.config import get_app_settings, get_pipeline_config
from app.models.api_schemas import UserSessionResponse
from app.models.db import DocumentModel, get_db_session
from app.models.schemas import IngestResponse
from app.core.security import setup_secure_logging

logger = setup_secure_logging("ecm.api.ingest")
router = APIRouter(prefix="/ingest", tags=["Ingestion"])

CHUNK_SIZE = 1024 * 1024  # 1 MB chunk streaming
ALLOWED_EXTENSIONS = {".pdf", ".tiff", ".tif", ".jpg", ".jpeg", ".png", ".docx", ".eml"}


def ingest_file_bytes(file_bytes: bytes, file_name: str, queue_type: str = "live") -> IngestResponse:
    """Store original untouched asset in storage with SHA-256 and enqueue for pipeline."""
    sha256_hash = hashlib.sha256(file_bytes).hexdigest()
    doc_uid = str(uuid.uuid4())

    storage = get_storage_adapter()
    # Key is SHA-256: raw asset stored untouched
    storage_path = storage.save(sha256_hash, file_bytes)

    cfg = get_pipeline_config()
    queue_name = cfg.queues.live_queue if queue_type == "live" else cfg.queues.bulk_queue
    queue = get_queue_adapter()

    payload = {
        "uid": doc_uid,
        "sha256": sha256_hash,
        "file_name": file_name,
        "storage_path": storage_path,
        "is_reprocess": False,
        "retries": 0,
    }
    queue.push(queue_name, payload)
    logger.info(f"Ingested document {doc_uid} ({file_name}, sha256: {sha256_hash}) to {queue_name}")

    return IngestResponse(
        uid=doc_uid,
        sha256=sha256_hash,
        file_name=file_name,
        status="QUEUED",
        queue=queue_name,
        message="Asset saved untouched with SHA-256; queued for processing",
    )


async def stream_and_save_upload(
    file: UploadFile,
    queue_type: str = "live",
    batch_id: Optional[str] = None,
    current_user: Optional[UserSessionResponse] = None,
) -> IngestResponse:
    """Stream upload to disk in chunks, enforcing MAX_UPLOAD_MB and validating content safely."""
    settings = get_app_settings()
    max_upload_mb = settings.MAX_UPLOAD_MB
    max_upload_bytes = max_upload_mb * 1024 * 1024

    file_name = file.filename or "document.bin"
    ext = Path(file_name).suffix.lower()

    # 1. Validate file extension or MIME type
    allowed_mimes = [t.strip().lower() for t in settings.ALLOWED_FILE_TYPES.split(",") if t.strip()]
    content_type = (file.content_type or "").lower()
    if ext not in ALLOWED_EXTENSIONS and content_type not in allowed_mimes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{ext or content_type}'. Allowed formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # 2. Prepare temporary streaming destination
    temp_dir = Path(settings.STORAGE_LOCAL_DIR) / "_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = temp_dir / f"upload_{uuid.uuid4().hex}.tmp"

    hasher = hashlib.sha256()
    total_bytes = 0
    first_chunk = True
    is_corrupt_pdf = False

    try:
        with open(temp_file, "wb") as f_out:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break

                # Inspect first chunk for valid header
                if first_chunk:
                    first_chunk = False
                    if ext == ".pdf":
                        if not chunk.startswith(b"%PDF-"):
                            is_corrupt_pdf = True

                total_bytes += len(chunk)
                if total_bytes > max_upload_bytes:
                    # Enforce limit early: stop streaming and reject immediately
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds maximum allowed size of {max_upload_mb} MB.",
                    )

                hasher.update(chunk)
                f_out.write(chunk)

        # 3. Reject empty files
        if total_bytes == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )

        # 4. Reject corrupt PDFs
        if is_corrupt_pdf:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Corrupt PDF: file does not contain a valid PDF header.",
            )

        # 5. Persist to storage adapter without reading entire file into RAM
        sha256_hash = hasher.hexdigest()
        storage = get_storage_adapter()
        storage_path = storage.save_file(
            sha256_hash,
            str(temp_file),
            content_type=content_type or "application/octet-stream",
        )

    except HTTPException:
        # Delete partial file on rejection
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass
        raise
    except Exception as e:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass
        logger.error(f"Streaming upload failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Upload processing failed: {str(e)}")
    finally:
        # Always clean up temp file if still present
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass

    # 6. Ensure BatchModel exists and record document in database immediately
    if not batch_id:
        batch_id = f"batch-{uuid.uuid4().hex[:12]}"

    doc_uid = str(uuid.uuid4())
    user_id = current_user.user_id if current_user else None
    db = get_db_session()
    try:
        from app.models.db import BatchModel
        existing_batch = db.query(BatchModel).filter(BatchModel.batch_id == batch_id).first()
        if not existing_batch:
            b_count = db.query(BatchModel).count()
            num = b_count + 1
            new_batch = BatchModel(
                batch_id=batch_id,
                number=num,
                name=f"Upload #{num}",
                user_id=user_id,
            )
            db.add(new_batch)
            db.commit()

        init_doc = DocumentModel(
            uid=doc_uid,
            sha256=sha256_hash,
            file_name=file_name,
            file_size=total_bytes,
            mime_type=content_type or "application/octet-stream",
            storage_path=storage_path,
            batch_id=batch_id,
            user_id=user_id,
            doc_type="unknown",
            confidence=0.0,
            retention_class="STANDARD_ARCHIVE",
            acl="INTERNAL_CONFIDENTIAL",
            target_workflow="INGEST_PIPELINE",
            review_status="queued",
            extracted_fields_json="{}",
            human_verified_fields_json="{}",
            field_confidences_json="{}",
            pii_detected=False,
            pii_types_json="[]",
            ocr_engine="unknown",
            ocr_version="1.0",
            classifier_model="unknown",
            classifier_version="v1.0",
            decision_reason="Queued for automated processing",
        )
        db.add(init_doc)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Could not persist initial DocumentModel for {doc_uid}: {e}")
    finally:
        db.close()

    # 7. Queue document for background execution
    cfg = get_pipeline_config()
    queue_name = cfg.queues.live_queue if queue_type == "live" else cfg.queues.bulk_queue
    queue = get_queue_adapter()

    payload = {
        "uid": doc_uid,
        "sha256": sha256_hash,
        "file_name": file_name,
        "storage_path": storage_path,
        "batch_id": batch_id,
        "user_id": user_id,
        "is_reprocess": False,
        "retries": 0,
    }
    queue.push(queue_name, payload)
    logger.info(f"Ingested document {doc_uid} ({file_name}, sha256: {sha256_hash}, batch: {batch_id}) to {queue_name}")

    return IngestResponse(
        uid=doc_uid,
        sha256=sha256_hash,
        file_name=file_name,
        status="QUEUED",
        queue=queue_name,
        batch_id=batch_id,
        message="Asset saved untouched with SHA-256; queued for processing",
    )


@router.post("", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_single_file(
    file: UploadFile = File(...),
    batch_id: Optional[str] = Query(None),
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Upload a single file (PDF, TIFF, JPG, PNG, DOCX, EML) with streaming chunk validation."""
    return await stream_and_save_upload(file, queue_type="live", batch_id=batch_id, current_user=current_user)


@router.post("/bulk", response_model=List[IngestResponse], status_code=status.HTTP_202_ACCEPTED)
async def ingest_bulk_files(
    files: List[UploadFile] = File(...),
    batch_id: Optional[str] = Query(None),
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Upload multiple documents in a single bulk operation with streaming chunk validation."""
    if not batch_id:
        batch_id = f"batch-{uuid.uuid4().hex[:12]}"
    responses: List[IngestResponse] = []
    for f in files:
        resp = await stream_and_save_upload(f, queue_type="bulk", batch_id=batch_id, current_user=current_user)
        responses.append(resp)
    return responses


@router.post("/scanner_watch_trigger", status_code=status.HTTP_200_OK)
def trigger_scanner_folder():
    """Poll watched scanner directory and ingest new files."""
    settings = get_app_settings()
    watch_dir = Path(settings.SCANNER_WATCH_DIR)
    if not watch_dir.exists():
        watch_dir.mkdir(parents=True, exist_ok=True)
        return {"ingested_count": 0, "message": "Scanner directory was empty"}

    count = 0
    for file_path in watch_dir.iterdir():
        if file_path.is_file():
            with open(file_path, "rb") as f:
                content = f.read()
            ingest_file_bytes(content, file_path.name)
            # Remove or archive watched file after ingestion
            file_path.unlink()
            count += 1

    return {"ingested_count": count, "message": f"Ingested {count} files from scanner folder"}
