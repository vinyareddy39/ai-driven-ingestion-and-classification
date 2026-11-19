"""Ingestion API endpoints supporting single upload, bulk upload, EML parsing, and scanner watch."""

import hashlib
import os
from pathlib import Path
from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from app.adapters.queue import get_queue_adapter
from app.adapters.storage import get_storage_adapter
from app.core.auth import get_current_user, require_role
from app.core.config import get_app_settings, get_pipeline_config
from app.models.api_schemas import UserSessionResponse
from app.models.schemas import IngestResponse
from app.core.security import setup_secure_logging

logger = setup_secure_logging("ecm.api.ingest")
router = APIRouter(prefix="/ingest", tags=["Ingestion"])


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


@router.post("", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_single_file(
    file: UploadFile = File(...),
    current_user: UserSessionResponse = Depends(require_role(["admin", "reviewer"])),
):
    """Upload a single file (PDF, TIFF, JPG, PNG, DOCX, EML)."""
    try:
        content = await file.read()
        return ingest_file_bytes(content, file.filename or "document.bin")
    except Exception as e:
        logger.error(f"Ingest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bulk", response_model=List[IngestResponse], status_code=status.HTTP_202_ACCEPTED)
async def ingest_bulk_files(
    files: List[UploadFile] = File(...),
    current_user: UserSessionResponse = Depends(require_role(["admin", "reviewer"])),
):
    """Upload multiple documents in a single bulk operation."""
    responses: List[IngestResponse] = []
    for f in files:
        content = await f.read()
        resp = ingest_file_bytes(content, f.filename or "batch_item.bin", queue_type="live")
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
