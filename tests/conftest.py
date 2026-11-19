"""Pytest configuration and shared test fixtures."""

import os
import sys
from pathlib import Path
import shutil
import tempfile
import pytest

# Ensure workspace root is always in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Direct all test operations to a copy of the database
test_db_file = Path("data/test_ecm_pipeline.db")
live_db_file = Path("data/ecm_pipeline.backup.db")
if not live_db_file.exists():
    live_db_file = Path("data/ecm_pipeline.db")
if live_db_file.exists():
    shutil.copyfile(live_db_file, test_db_file)
os.environ["DATABASE_URL"] = f"sqlite:///{test_db_file.as_posix()}"

from app.core.config import get_pipeline_config, load_pipeline_config
from app.models.db import init_db, _engine
import app.models.db as db_mod
db_mod._engine = None
db_mod._SessionFactory = None
from app.core.idempotency import get_idempotency_registry


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Ensure database tables and runtime configuration are active."""
    init_db()
    load_pipeline_config()
    yield


@pytest.fixture
def clean_idempotency():
    """Reset in-memory idempotency registry before test."""
    registry = get_idempotency_registry()
    registry._completed_stages.clear()
    registry._active_locks.clear()
    yield registry
