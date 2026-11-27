# Stage 0: Audit and Skip List

**Audit Date**: 2026-11-19  
**Branch**: `backend/complete`  
**Execution Environment**: LOCAL MODE (Ready for REAL SERVICES / PostgreSQL / S3)  

---

## 1. System Inventory Summary

- **DB Engine**: SQLite (`sqlite3` / `sqlite:///./data/ecm_pipeline.db`) via portable SQLAlchemy models
- **Tables and Live Row Counts**:
  - `alembic_version`: 1 row
  - `audit_events`: 12,585 rows
  - `config_history`: 5 rows
  - `ecm_documents`: 1,790 rows
  - `extracted_items`: 0 rows
  - `prescriptions`: 4 rows
  - `reminders`: 0 rows
  - `review_tasks`: 359 rows
  - `stage_executions`: 0 rows
  - `timetable_slots`: 0 rows
  - `users`: 6 rows
- **File Storage**: `LocalFileStorage` adapter storing binary files at `./data/storage` (UUID/hash keys), pluggable to `MinioStorage` / S3 via `STORAGE_BACKEND`.
- **Work Queue**: Multi-tier queue adapter (`InMemoryQueue` for local mode, `RedisQueue` for distributed live/bulk queues, and `LivePipelineWorker` background thread).

---

## 2. Core Capability Audit & Skip Matrix

| Capability / Feature | Status | Evidence (File:Line & Command) | Decision |
|---|---|---|---|
| **Upload Pipeline** (Single, bulk, scanner folder, .eml) | **EXISTS** (Status 4) | `app/api/routes_ingest.py:27`, `app/workers/scanner_watcher.py:23`, `app/workers/email_ingest.py:18` | **SKIP** |
| **Ingestion Safeguards** (Virus scan, SHA-256 duplicate, blank page, encrypted PDF quarantine) | **EXISTS** (Status 4) | `app/adapters/virus.py:15`, `app/workers/stages.py:73`, `app/adapters/ocr.py:90`, `tests/test_stages_unit.py` | **SKIP** |
| **OCR Engine** (Line breaks preserved, bounding boxes, PyMuPDF + Tesseract) | **EXISTS** (Status 4) | `app/adapters/ocr.py:65`, `tests/test_stages_unit.py:14` | **SKIP** |
| **Document Classification & Extractor** (Multi-class, confidence scoring) | **EXISTS** (Status 4) | `app/workers/stages.py:120`, `app/workers/field_extractor.py:22` | **SKIP** |
| **Decision Gate & Compliance Floors** (0.90/0.95 floors, conflict rule, unknown default) | **EXISTS** (Status 4) | `app/workers/stages.py:185`, `config/pipeline_config.yaml:12`, `tests/test_decision_gate.py` | **SKIP** |
| **PII Detection & Context Recognizers** (Presidio, Indian Aadhaar/PAN, context words) | **EXISTS** (Status 4) | `app/adapters/pii.py:45`, `tests/test_national_id.py`, `tests/test_security_masking.py` | **SKIP** |
| **Human Review Workflow** (Queue, assign, confirm/correct, human-verified protection) | **EXISTS** (Status 4) | `app/api/routes_v1.py:122`, `app/api/routes_review.py:30`, `app/workers/reprocessing.py:45` | **SKIP** |
| **Reprocessing Routes** (Preview dry-run, live reprocess, conflict detection) | **EXISTS** (Status 4) | `app/api/routes_reprocess.py:35`, `tests/test_reprocessing.py` | **SKIP** |
| **Staff Role Authentication** (Bearer tokens, image route protection, PII reveal audit) | **EXISTS** (Status 4) | `app/core/auth.py:25`, `app/api/routes_v1.py:440,490`, `tests/test_api_v1.py` | **SKIP** |
| **Patient Authentication & Isolation** (Argon2id, HS256 JWT + Refresh, 5-min rate limit, 404 isolation) | **EXISTS** (Status 4) | `app/api/routes_auth.py:29`, `app/core/jwt_auth.py`, `tests/test_prescription_auth_isolation.py` | **SKIP** |
| **Prescription Worker & Extraction** (Never auto-accept NEEDS_REVIEW, reference drug formulary) | **EXISTS** (Status 4) | `app/workers/prescription_worker.py:35`, `app/workers/medication_extractor.py:75` | **SKIP** |
| **Deterministic Timetable** (Anchor meals, offsets, intervals, DST transitions, disclaimer, 409 verify check) | **EXISTS** (Status 4) | `app/workers/timetable.py:45`, `tests/test_timetable_parser.py` (47 table-driven tests) | **SKIP** |
| **Reminders & Safe Notifications** (Log & SMTP channels, zero PII/URL in payload) | **EXISTS** (Status 4) | `app/workers/reminders.py:40`, `tests/test_prescription_reminders_and_review.py` | **SKIP** |
| **Health Privacy & Security** (Fernet AES-128 column encryption at rest, GDPR export & hard delete) | **EXISTS** (Status 4) | `app/models/db.py:50`, `app/api/routes_prescriptions.py:800`, `tests/test_prescription_privacy_security.py` | **SKIP** |
| **Audit Trail & Observability** (AuditEventModel, config history restart persistence, Prometheus metrics) | **EXISTS** (Status 4) | `app/models/db.py:80,110`, `app/api/routes_observability.py:35` | **SKIP** |
| **Database Migrations** (Alembic versions: document schema, prescription tables, encrypted columns) | **EXISTS** (Status 4) | `alembic/versions/` (3 revisions applied) | **SKIP** |
| **Health Endpoints & CORS** (`/health/live`, `/health/ready`, configurable `CORS_ORIGINS`) | **EXISTS** (Status 4) | `app/api/routes_observability.py:89,95`, `app/api/app.py:86` | **SKIP** |

---

## 3. Gaps to Build in Subsequent Stages

1. **Stage 1 (Configuration & Secrets)**:
   - Unified `pydantic-settings` module with all 24 required environment variables.
   - Strict production startup validation (refuse startup if secrets missing, role header enabled, or wildcard CORS).
   - Author `.env.example` with placeholders and comments.
2. **Stage 2 (Database & PostgreSQL)**:
   - Alembic migration adding `batch_id` column and composite indices on `(batch_id, user_id, status)`.
   - Backup/restore procedures documented in `docs/operations.md`.
3. **Stage 3 (AI Services & Residency Router)**:
   - `LLMClient` interface with local backend (Ollama) and hosted provider backend.
   - Residency routing: restricted high-risk classes locked to local model; fallback to deterministic extractor if endpoint down.
   - Add `receipt` document class with total/date extraction rules.
4. **Stage 4 (Batch Results & ECM Flow)**:
   - `GET /api/v1/batches/{id}` endpoint with aggregation counts and per-file progress in constant query time.
   - Signed outbound webhook dispatcher with HMAC signature and delivery attempts table.
   - Legal hold flag and retention disposition worker.
5. **Stage 6 (Storage & Queue Hardening)**:
   - S3-compatible adapter validation (prevent local disk in production).
   - Postgres-backed job table for crash resilience.
6. **Stage 8 (Deployment Manifests)**:
   - `render.yaml` infrastructure-as-code blueprint for Render.
   - `frontend/vercel.json` and `frontend/.env.example` for Vercel deployment.
   - Comprehensive deployment runbook `docs/deploy.md` and `scripts/smoke_deployed.ps1`.
