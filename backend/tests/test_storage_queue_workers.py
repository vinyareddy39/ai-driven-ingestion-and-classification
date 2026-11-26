"""Unit tests for Stage 6: Database-backed persistent queue, restart recovery, and storage guards."""

import json
import pytest

from app.adapters.queue import DatabaseQueue
from app.core.settings import AppSettings, ProductionSecurityError, validate_production_safety
from app.models.db import PipelineJobModel, get_db_session, init_db


class TestDatabaseQueueAndRestartRecovery:
    """Verify that DatabaseQueue guarantees message persistence, FIFO order, and survives restarts."""

    @pytest.fixture(autouse=True)
    def setup_jobs_table(self):
        init_db()
        db = get_db_session()
        db.query(PipelineJobModel).filter(PipelineJobModel.queue_name == "test_live_queue").delete()
        db.commit()
        db.close()
        return True

    def test_database_queue_push_pop_ack_lifecycle(self):
        queue = DatabaseQueue()

        # 1. Push jobs
        job_id_1 = queue.push("test_live_queue", {"doc_id": "doc-001", "type": "invoice"})
        job_id_2 = queue.push("test_live_queue", {"doc_id": "doc-002", "type": "receipt"})
        assert queue.length("test_live_queue") == 2

        # 2. Pop first job (FIFO)
        item1 = queue.pop("test_live_queue")
        assert item1 is not None
        pop_id_1, payload_1 = item1
        assert pop_id_1 == job_id_1
        assert payload_1["doc_id"] == "doc-001"
        assert queue.length("test_live_queue") == 1

        # 3. Ack first job
        ok = queue.ack("test_live_queue", "group-1", pop_id_1)
        assert ok is True

        # 4. Pop second job
        item2 = queue.pop("test_live_queue")
        assert item2 is not None
        pop_id_2, payload_2 = item2
        assert pop_id_2 == job_id_2
        assert payload_2["doc_id"] == "doc-002"

        # 5. Empty queue returns None
        assert queue.pop("test_live_queue") is None

    def test_simulated_process_restart_preserves_unprocessed_jobs(self):
        """Simulate a worker crash and reboot: new worker process picks up uncompleted jobs."""
        worker_1 = DatabaseQueue()

        # Worker 1 pushes 3 jobs
        worker_1.push("test_live_queue", {"batch_id": "b1", "seq": 1})
        worker_1.push("test_live_queue", {"batch_id": "b1", "seq": 2})
        worker_1.push("test_live_queue", {"batch_id": "b1", "seq": 3})

        # Worker 1 processes 1 job and dies
        item = worker_1.pop("test_live_queue")
        assert item is not None
        worker_1.ack("test_live_queue", "group-1", item[0])
        del worker_1

        # Simulated reboot: Worker 2 starts fresh
        worker_2 = DatabaseQueue()
        assert worker_2.length("test_live_queue") == 2

        # Verify next job is seq 2
        item2 = worker_2.pop("test_live_queue")
        assert item2 is not None
        assert item2[1]["seq"] == 2
        worker_2.ack("test_live_queue", "group-1", item2[0])

        # Verify final job is seq 3
        item3 = worker_2.pop("test_live_queue")
        assert item3 is not None
        assert item3[1]["seq"] == 3
        worker_2.ack("test_live_queue", "group-1", item3[0])

        assert worker_2.length("test_live_queue") == 0


class TestStorageProductionGuard:
    """Verify production storage invariants."""

    def test_production_refuses_local_storage(self):
        settings = AppSettings(
            APP_ENV="production",
            SECRET_KEY="super_secure_random_key_that_is_at_least_32_characters_long",
            DATABASE_URL="postgresql://user:pass@host:5432/db",
            DATA_ENCRYPTION_KEY="k" * 32,
            CORS_ORIGINS="https://app.ecm.com",
            AUTH_ALLOW_ROLE_HEADER=False,
            STORAGE_BACKEND="local",  # Forbidden in production!
        )
        with pytest.raises(ProductionSecurityError) as exc_info:
            validate_production_safety(settings)
        assert "STORAGE_BACKEND='local' is forbidden" in str(exc_info.value)

    def test_production_accepts_s3_storage(self):
        settings = AppSettings(
            APP_ENV="production",
            SECRET_KEY="super_secure_random_key_that_is_at_least_32_characters_long",
            DATABASE_URL="postgresql://user:pass@host:5432/db",
            DATA_ENCRYPTION_KEY="k" * 32,
            CORS_ORIGINS="https://app.ecm.com",
            AUTH_ALLOW_ROLE_HEADER=False,
            STORAGE_BACKEND="s3",  # Permitted in production
        )
        assert validate_production_safety(settings) is True
