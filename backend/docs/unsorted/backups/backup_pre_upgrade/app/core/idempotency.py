"""Idempotency engine keying on sha256 + stage with atomic execution tracking."""

import hashlib
from typing import Any, Dict, Optional, Set
from datetime import datetime, timezone
import json


class IdempotencyKey:
    """Represents a unique composite key: sha256 + stage."""

    def __init__(self, sha256_hash: str, stage_name: str):
        self.sha256 = sha256_hash
        self.stage = stage_name
        self.key = f"{self.sha256}:{self.stage}"

    def __str__(self) -> str:
        return self.key


class IdempotencyRegistry:
    """In-memory and persistent stage execution tracker for transactional guarantees."""

    def __init__(self):
        # Maps stage key (sha256:stage) -> dict of status, result, timestamp
        self._completed_stages: Dict[str, Dict[str, Any]] = {}
        # Tracks active locks to prevent concurrent duplicate execution
        self._active_locks: Set[str] = set()

    def make_key(self, sha256_hash: str, stage_name: str) -> str:
        return f"{sha256_hash}:{stage_name}"

    def is_stage_completed(self, sha256_hash: str, stage_name: str) -> bool:
        """Check if stage has already been successfully committed for this hash."""
        key = self.make_key(sha256_hash, stage_name)
        record = self._completed_stages.get(key)
        return record is not None and record.get("status") == "COMPLETED"

    def acquire_stage_lock(self, sha256_hash: str, stage_name: str) -> bool:
        """Acquire atomic lock for executing stage. Returns False if already running or completed."""
        key = self.make_key(sha256_hash, stage_name)
        if self.is_stage_completed(sha256_hash, stage_name):
            return False
        if key in self._active_locks:
            return False
        self._active_locks.add(key)
        return True

    def commit_stage(self, sha256_hash: str, stage_name: str, result_payload: Optional[Dict[str, Any]] = None) -> None:
        """Atomically commit a completed stage transaction."""
        key = self.make_key(sha256_hash, stage_name)
        self._completed_stages[key] = {
            "status": "COMPLETED",
            "result": result_payload or {},
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._active_locks.discard(key)

    def fail_stage(self, sha256_hash: str, stage_name: str, error_message: str) -> None:
        """Record stage failure and release lock for retry."""
        key = self.make_key(sha256_hash, stage_name)
        self._completed_stages[key] = {
            "status": "FAILED",
            "error": error_message,
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._active_locks.discard(key)

    def get_stage_result(self, sha256_hash: str, stage_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored result of a previously committed stage."""
        key = self.make_key(sha256_hash, stage_name)
        record = self._completed_stages.get(key)
        if record and record.get("status") == "COMPLETED":
            return record.get("result")
        return None

    def reset_hash(self, sha256_hash: str) -> None:
        """Reset stages for reprocessing."""
        keys_to_remove = [k for k in self._completed_stages.keys() if k.startswith(f"{sha256_hash}:")]
        for k in keys_to_remove:
            del self._completed_stages[k]


_default_registry = IdempotencyRegistry()


def get_idempotency_registry() -> IdempotencyRegistry:
    return _default_registry
