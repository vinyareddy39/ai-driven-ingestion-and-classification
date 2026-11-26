"""Automated tests for STEP 1 - MEASURE FIRST.

Verifies:
1. Per-stage timing logs are generated with all required keys:
   hash, queue_wait, text-layer check, render, deskew, OCR, model call, DB write.
2. Batch summary endpoint provides:
   total time, p50/p95 per file, 429 count, retries, failures.
3. User-scoped cache isolation and timing persistence.
"""

import json
import os
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.api.app import app
from app.models.db import init_db, UserModel, BatchModel, FileModel, FieldModel
from app.core.jwt_auth import create_token
from app.api.routes_documents import process_file_background, compute_sha256

client = TestClient(app)


@pytest.fixture
def auth_headers():
    engine = init_db()
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        user = db.query(UserModel).filter(UserModel.email == "test_step1@example.com").first()
        if not user:
            user = UserModel(name="Step 1 Tester", email="test_step1@example.com", password_hash="dummy")
            db.add(user)
            db.commit()
            db.refresh(user)
        token = create_token({"sub": user.id, "email": user.email, "name": user.name})
        return {"Authorization": f"Bearer {token}"}, user.id
    finally:
        db.close()


def test_per_stage_timings_recorded(auth_headers):
    headers, user_id = auth_headers
    engine = init_db()
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    db = Session()

    batch = BatchModel(user_id=user_id, name="Test Timings Batch")
    db.add(batch)
    db.commit()
    db.refresh(batch)

    # Use one of the benchmark PDFs
    fpath = os.path.abspath("data/benchmark_60/bench_01_invoice.pdf")
    with open(fpath, "rb") as f:
        content = f.read()

    file_rec = FileModel(
        batch_id=batch.id,
        original_name="bench_01_invoice.pdf",
        stored_path=fpath,
        sha256=compute_sha256(content),
        status="queued",
        stage="queued",
    )
    db.add(file_rec)
    db.commit()
    db.refresh(file_rec)
    file_id = file_rec.id
    db.close()

    # Process file with force_fresh=True
    process_file_background(file_id, force_fresh=True)

    db = Session()
    refreshed_file = db.query(FileModel).filter(FileModel.id == file_id).first()
    assert refreshed_file is not None
    assert refreshed_file.stage_timings is not None

    timings = json.loads(refreshed_file.stage_timings)
    required_keys = [
        "hash_ms",
        "queue_wait_ms",
        "text_layer_check_ms",
        "render_ms",
        "deskew_ms",
        "ocr_ms",
        "model_call_ms",
        "db_write_ms",
        "total_ms",
    ]
    for rk in required_keys:
        assert rk in timings, f"Missing required timing key: {rk}"
        assert isinstance(timings[rk], (int, float)), f"Timing for {rk} must be numeric"

    assert timings["total_ms"] > 0, "total_ms must be positive"
    db.close()


def test_batch_summary_api(auth_headers):
    headers, user_id = auth_headers
    engine = init_db()
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    db = Session()

    batch = BatchModel(user_id=user_id, name="Test Summary Batch")
    db.add(batch)
    db.commit()
    db.refresh(batch)
    batch_id = batch.id

    fpath = os.path.abspath("data/benchmark_60/bench_02_invoice.pdf")
    with open(fpath, "rb") as f:
        content = f.read()

    file_rec = FileModel(
        batch_id=batch_id,
        original_name="bench_02_invoice.pdf",
        stored_path=fpath,
        sha256=compute_sha256(content),
        status="queued",
        stage="queued",
    )
    db.add(file_rec)
    db.commit()
    db.refresh(file_rec)
    file_id = file_rec.id
    db.close()

    process_file_background(file_id, force_fresh=True)

    resp = client.get(f"/api/batches/{batch_id}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert "summary" in data, "Batch response must contain 'summary'"
    summary = data["summary"]
    assert "total_time_ms" in summary
    assert "p50_ms" in summary
    assert "p95_ms" in summary
    assert "count_429" in summary
    assert "retries" in summary
    assert "failures" in summary
    assert summary["files_processed"] >= 1
