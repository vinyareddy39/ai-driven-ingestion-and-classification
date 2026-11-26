"""Unit tests for idempotency engine and stage locking."""

import pytest
from app.core.idempotency import IdempotencyKey, IdempotencyRegistry


def test_idempotency_composite_key():
    k = IdempotencyKey("abcdef123456", "ocr")
    assert str(k) == "abcdef123456:ocr"


def test_stage_lock_and_commit():
    registry = IdempotencyRegistry()
    sha = "test_sha_001"
    stage = "classify"

    # Initially not completed
    assert not registry.is_stage_completed(sha, stage)

    # Acquire lock
    assert registry.acquire_stage_lock(sha, stage) is True
    # Duplicate acquire while locked fails
    assert registry.acquire_stage_lock(sha, stage) is False

    # Commit stage
    registry.commit_stage(sha, stage, {"class": "invoice", "confidence": 0.98})
    assert registry.is_stage_completed(sha, stage) is True

    # Lock acquisition after completion fails
    assert registry.acquire_stage_lock(sha, stage) is False

    # Stored result is retrievable
    res = registry.get_stage_result(sha, stage)
    assert res["class"] == "invoice"
    assert res["confidence"] == 0.98


def test_stage_failure_releases_lock():
    registry = IdempotencyRegistry()
    sha = "test_sha_002"
    stage = "ocr"

    assert registry.acquire_stage_lock(sha, stage) is True
    registry.fail_stage(sha, stage, "OCR Engine Timeout")
    assert not registry.is_stage_completed(sha, stage)

    # Can re-acquire lock for retry
    assert registry.acquire_stage_lock(sha, stage) is True
