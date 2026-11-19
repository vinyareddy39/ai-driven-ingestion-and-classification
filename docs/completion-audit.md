# Independent Completion Audit: AI Document Ingestion & ECM Pipeline

**Auditor:** Independent Technical Auditor  
**Date:** 2026-11-19  
**Execution Environment:** Windows Host (PowerShell, Python 3.11, SQLite)  
**Audit Target:** End-to-End ECM Pipeline (Trigger/Capture -> OCR -> Enrichment/Routing -> Review/Approval -> Distribution -> Archival)  

---

## Executive Summary & Completion Scorecard

This audit evaluates the codebase strictly on what is built and verifiable through live command execution, database inspection, and code tracing. All earlier claims from `docs/final-report.md` and `docs/progress.md` have been re-tested independently.

### Status Scale Reference
- **0 - NOT BUILT**: No implementation exists in the codebase.
- **1 - STUB**: File or route exists with placeholder or no real logic.
- **2 - BUILT**: Real operational logic implemented, but unverified.
- **3 - TESTED**: Verified by automated test suites using synthetic/mock data.
- **4 - VERIFIED**: Verified end-to-end on running server or live local binary with pasted output.
- **5 - MEASURED**: Accuracy or performance quantitatively benchmarked on unseen real datasets.

### High-Level Scorecard

| Area | Weight | Built % ($\ge 2$) | Proven % ($\ge 4$) | Weighted Built | Weighted Proven |
|---|---|---|---|---|---|
| **1. Trigger / Capture** | 10% | 100.0% | 0.0% | 10.0% | 0.0% |
| **2. OCR Engine & Processing** | 15% | 100.0% | 55.6% | 15.0% | 8.3% |
| **3. Enrichment & Routing** | 20% | 100.0% | 30.0% | 20.0% | 6.0% |
| **4. Review & Approval** | 15% | 100.0% | 71.4% | 15.0% | 10.7% |
| **5. Distribution** | 10% | 20.0% | 0.0% | 2.0% | 0.0% |
| **6. Archival & Retention** | 10% | 14.3% | 0.0% | 1.4% | 0.0% |
| **7. Security & Privacy** | 10% | 100.0% | 80.0% | 10.0% | 8.0% |
| **8. Frontend Client** | 5% | 100.0% | 60.0% | 5.0% | 3.0% |
| **9. Operations & Docker** | 5% | 80.0% | 60.0% | 4.0% | 3.0% |
| **TOTAL** | **100%** | — | — | **82.4% BUILT** | **39.0% PROVEN** |

---

## PART 1: ECM Workflow Stages

### 1. Trigger / Capture (Weight: 10%)
- **Single File API (`POST /ingest`)**: `Status: 3 (TESTED)`. Built with FastAPI `UploadFile`, payload validation, SHA-256 dedupe check, and background task handoff. Evidence: `app/api/routes_ingest.py:24`, `tests/test_integration_flow.py:test_full_flow_ingest_to_searchable_document`.
- **Bulk Upload (`POST /ingest/bulk`)**: `Status: 3 (TESTED)`. Batch multipart parsing returning list of document UIDs. Evidence: `app/api/routes_ingest.py:46`.
- **RFC 822 Email (`.eml`) Ingestion**: `Status: 3 (TESTED)`. Parses headers (`From`, `To`, `Subject`, `Date`) and extracts multipart body text. Evidence: `app/adapters/ocr.py:124-159`.
- **Scanner Watch Folder**: `Status: 2 (BUILT)`. Endpoint `POST /ingest/scanner_watch_trigger` exists and polls directory if configured; background watcher daemon not running. Evidence: `app/api/routes_ingest.py:65`.
- **Migration Batch**: `Status: 2 (BUILT)`. Batch query reprocess route exists (`/reprocess`), but no legacy ECM connector (e.g. FileNet/Documentum importer).
- **Virus Scan**: `Status: 2 (BUILT)`. Byte-level scan checking EICAR signature; real ClamAV daemon is absent. Evidence: `app/workers/stages.py:48-62`.
- **Duplicate Detection**: `Status: 3 (TESTED)`. SHA-256 collision detection creates pointer link rather than duplicating storage. Evidence: `app/workers/stages.py:112`, `tests/test_integration_flow.py:test_duplicate_creates_link_not_copy`.
- **Blank Page Detection**: `Status: 3 (TESTED)`. Pixel luminance variance detection (`is_blank_image`). Evidence: `app/adapters/ocr.py:46-55`.
- **Password-Protected File Handling**: `Status: 3 (TESTED)`. Detects `doc.is_encrypted` and routes to `QUARANTINED`. Evidence: `app/workers/stages.py:82-95`.
- **Quarantine Handling**: `Status: 3 (TESTED)`. Stored in DB with `quarantine_reason` and blocked from downstream OCR. Evidence: `app/models/db.py:DocumentModel.quarantine_reason`.
- **Idempotency & Stage Retries**: `Status: 3 (TESTED)`. Transactional composite locks (`sha256 + stage_name`) and Dead Letter Queue handler. Evidence: `app/core/idempotency.py`, `app/workers/dlq.py`.
- **Missing / Gaps**: No real ClamAV daemon; watch folder is manual HTTP trigger rather than an OS filesystem event listener (e.g. `watchdog`); no IMAP/POP3 email poller.

### 2. OCR (Weight: 15%)
- **Engine & Binary**: `Status: 4 (VERIFIED)`. `HybridPyMuPDF-Tesseract v2.4.0` calling local UB-Mannheim Tesseract `v5.4.0.20240606` at `C:\ml\tools\tesseract_ub\tesseract.exe`.
- **Embedded-Text vs Raster Scans**: `Status: 4 (VERIFIED)`. Raster images dispatched directly to Tesseract. Tested on 200 raster scans: 0 embedded-text hits, 200 Tesseract hits.
- **Line & Layout Preservation**: `Status: 4 (VERIFIED)`. Tesseract TSV output grouped by `par_num` and `line_num`.
- **Language Support**: `Status: 3 (TESTED)`. Configured for `eng`.
- **Deskew & Denoise**: `Status: 3 (TESTED)`. OpenCV deskewing via `cv2.minAreaRect` and rotation warp. Evidence: `app/adapters/ocr.py:65-95`.
- **Multi-Document Splitting**: `Status: 3 (TESTED)`. Splits multi-document streams on form boundary keywords. Evidence: `app/workers/stages.py:504`.
- **Outage Handling**: `Status: 3 (TESTED)`. OCR failure triggers retries then DLQ routing. Evidence: `tests/test_fault_injection.py:test_ocr_outage_leads_to_retries_then_dlq_and_alert`.
- **Measured Speed per Page**: `Status: 4 (VERIFIED)`. Sample timings: 770ms, 908ms, 860ms, 878ms, 951ms per page.
- **Measured Real Document Accuracy**: `Status: 4 (VERIFIED)`. SROIE receipts baseline: 33.5% field extraction due to degraded scan character substitutions.
- **Missing / Gaps**: Non-English language dictionaries not downloaded; multi-page TIFF splitting unverified.

### 3. Enrichment and Routing (Weight: 20%)
- **Document Classification**: `Status: 3 (TESTED)`. Calibrated Logistic Regression + TF-IDF across 8 document classes + unknown. Evidence: `app/workers/stages.py:stage_classify`.
- **Field Extraction**: `Status: 3 (TESTED)`. `GenericFuzzyExtractor` + Pydantic schema validation. Evidence: `app/workers/fuzzy_extractor.py`.
- **PII Detection**: `Status: 4 (VERIFIED)`. `PresidioPIIDetector` with custom recognizers. Evaluated on Holdout 3 (1,067 entities): Overall Precision 86.52%, Recall 95.03%.
- **Confidence Thresholds & Compliance Floors**: `Status: 4 (VERIFIED)`. High risk floor 0.95, low risk 0.90. Live test: `POST /api/v1/admin/config` with `kyc_form: 0.93` rejected with HTTP 400.
- **Decision Gate Rules**: `Status: 3 (TESTED)`. Table-driven tests covering auto-accept, review triage, and unknown routing. Evidence: `tests/test_decision_gate.py`.
- **Conflict Rule**: `Status: 3 (TESTED)`. Low-risk doc with high-risk PII forces `ROUTE_TO_REVIEW` with `RESTRICTED_REVIEW` ACL. Evidence: `tests/test_integration_flow.py:test_conflict_routes_to_review_with_stricter_acl`.
- **Model Version Tracking**: `Status: 4 (VERIFIED)`. `ecm_documents` records `classifier_model` and `classifier_version`. SQL query `SELECT uid, file_name, doc_type, classifier_version, confidence FROM ecm_documents WHERE confidence < 0.80` verified live on 1,790 records.
- **Missing / Gaps**: No LLM extraction endpoint active in `.env`; `data/blind/` missing on disk.

### 4. Review and Approval (Weight: 15%)
- **Review Queue**: `Status: 4 (VERIFIED)`. HTMX queue (`GET /review`) and REST API (`GET /api/v1/review/queue`). Tested with live curl: returns 401 unauthenticated, 403 on viewer role, 200 on reviewer token.
- **Confirm / Correct / Reject Actions**: `Status: 4 (VERIFIED)`. `apply_review_decision` supports all three actions: `CONFIRM` (marks `human_verified`), `CORRECT` (updates doc type and fields), `REJECT` (marks `rejected`). Evidence: `app/api/routes_review.py:214-230`.
- **Human-Verified Protection**: `Status: 3 (TESTED)`. `human_verified_fields_json` preserved across batch reprocessing. Evidence: `tests/test_reprocessing.py`.
- **Reviewer Identity & Timestamp**: `Status: 4 (VERIFIED)`. Recorded in `ecm_documents.reviewer_id` and `updated_at`.
- **Feedback Loop to Training Data**: `Status: 4 (VERIFIED)`. 5 review corrections submitted and exported via `GET /review/export/training_data.jsonl`; model retrained via `scripts/retrain_with_corrections.py`.
- **Missing / Gaps**: No multi-level approval hierarchy (e.g. Maker-Checker / dual authorization for claims > $10,000).

### 5. Distribution (Weight: 10%)
- **Workflow Handoff**: `Status: 1 (STUB)`. `target_workflow` (`kyc_verification`, `ap_processing`, `general_review`) is **only a string label in the SQLite database column**. No HTTP webhook, no message sent to an external workflow engine (e.g. Camunda, Temporal), and no real handoff occurs.
- **Folder / Location Assignment**: `Status: 1 (STUB)`. Storage path is recorded in DB, but no document routing to department network shares or Nuxeo folder hierarchy.
- **Notifications**: `Status: 0 (NOT BUILT)`. Zero notification code exists (no email, Slack, Teams, or SMS dispatch on acceptance or rejection).
- **Downstream API Export**: `Status: 1 (STUB)`. Training data JSONL export exists, but no automated webhook push to downstream enterprise systems.
- **Search Index Delivery**: `Status: 2 (BUILT)`. In-memory dictionary index adapter exists (`app/adapters/search.py`), but OpenSearch container is inactive.
- **Auditor Note**: **Distribution is almost entirely a database label. Nothing is physically delivered to any external system.**

### 6. Archival (Weight: 10%)
- **Retention Rules Enforcement**: `Status: 1 (STUB)`. `retention_class` (`10_YEARS_KYC`, `7_YEARS_FINANCIAL`) is **only a string label in a database column**. No background job, cron, or policy daemon enforces document lifecycle.
- **Legal Hold**: `Status: 0 (NOT BUILT)`. Zero occurrences of `legal_hold` in the codebase. No API or flag to freeze document deletion.
- **Disposition / Deletion Schedule**: `Status: 0 (NOT BUILT)`. No deletion scheduler or purging mechanism implemented.
- **Immutable / WORM Storage**: `Status: 0 (NOT BUILT)`. Raw files stored in plain local filesystem without object locking or write-once enforcement.
- **Archive Tiering & Restore**: `Status: 0 (NOT BUILT)`. No cold storage integration (e.g. AWS Glacier / Azure Archive).
- **Audit-Trail Retention**: `Status: 3 (TESTED)`. SQLite table `audit_events` holds 12,585 logged events, but has no immutable retention enforcement or export policy.
- **Auditor Note**: **Archival is strictly a metadata label with zero lifecycle enforcement.**

---

## PART 2: Technical Layers

### A. Backend API
- **Total Endpoints**: 33 routes discovered via `GET /openapi.json` across 6 tags.
- **Authentication & RBAC Matrix (Live Curl Evidence)**:
  - `GET /metrics`: No Auth: `401 Unauthorized` | Viewer: `200 OK` (aggregate counters) | Reviewer: `200 OK`
  - `GET /review`: No Auth: `401 Unauthorized` | Viewer: `403 Forbidden` | Reviewer: `200 OK`
  - `GET /api/v1/review/queue`: No Auth: `401 Unauthorized` | Viewer: `403 Forbidden` | Reviewer: `200 OK`
  - `GET /api/v1/admin/config`: No Auth: `401 Unauthorized` | Reviewer: `403 Forbidden` | Admin: `200 OK`
  - `GET /api/v1/documents`: No Auth: `401 Unauthorized` | Viewer: `200 OK` | Compliance: `200 OK`
  - `GET /audit/dummy-uid`: No Auth: `401 Unauthorized` | Viewer: `403 Forbidden` | Compliance: `404 Not Found`
  - `GET /health/live`: No Auth: `200 OK` (public liveness probe)
  - `GET /health/ready`: No Auth: `200 OK`
- **Pydantic Validation**: All v1 routes use strict Pydantic v2 request/response schemas in `app/models/api_schemas.py`.
- **CORS Configuration**: Controlled via `CORS_ORIGINS` env var; defaults to `http://localhost:5173`.
- **Layer Score: 4 (VERIFIED)**.

### B. Database Layer
- **Engine**: SQLite (`data/ecm_pipeline.db`).
- **Table Audit (Live Read-Only SQL Inspection)**:
  - `ecm_documents`: 1,790 rows, 31 columns, 4 indexes.
  - `audit_events`: 12,585 rows, 9 columns, 4 indexes.
  - `review_tasks`: 359 rows, 10 columns, 3 indexes.
  - `config_history`: 5 rows, 5 columns, 1 index.
  - `stage_executions`: 0 rows, 9 columns, 3 indexes.
  - `alembic_version`: 1 row (active migration revision: `07595e940744`).
- **Model Version Query**: Tested live SQL query: `SELECT uid, file_name, doc_type, classifier_version, confidence FROM ecm_documents WHERE confidence < 0.80 LIMIT 5` executes in <1ms and returns valid rows.
- **Foreign Keys**: Pragma check shows 0 enforced SQLite foreign keys (relational integrity maintained at application layer).
- **Production Architecture Reality**: PostgreSQL, Redis, MinIO, and OpenSearch are defined in `docker-compose.yml`, but **code runs against SQLite and local memory/filesystem adapters**.
- **Layer Score: 3 (TESTED / SQLite verified live)**.

### C. Storage, Queue, and Workers
- **Storage**: Plain local directory (`data/storage/`). MinIO adapter implemented in `app/adapters/storage.py`, but MinIO container is not running. Status: 2.
- **Queue**: In-memory Python `queue.Queue` (`app/adapters/queue.py:InMemoryQueueAdapter`). Redis adapter exists in code, but Redis container is not running. Status: 2.
- **Worker Allocation**: Dedicated worker threads for live ingestion vs bulk queue. Tested up to 4 concurrent worker threads in load benchmark. Status: 3.
- **Dead-Letter Handling**: `DeadLetterQueueHandler` records failed payloads and routes to DLQ queue. Status: 3.
- **Layer Score: 2.5 (BUILT / TESTED in local mode)**.

### D. Frontend (Collaborator-Owned)
- **Framework**: React 18, Vite, TypeScript, Tailwind CSS, TanStack React Query.
- **Test Suite (`npm run test`)**:
  - `ConfidenceBadge.test.tsx`: 4 passed.
  - `PIIMaskedValue.test.tsx`: 2 passed.
  - `ReviewValidation.test.tsx`: 3 passed.
  - `ContractFreshness.test.ts`: **FAILED** (`Generated TypeScript client is missing path: /api/v1/documents/{document_uid}/compliance. Run 'npm run api:gen' to refresh`).
- **Typecheck (`tsc --noEmit`)**: **PASSED (0 errors)**.
- **Build (`npm run build`)**: **PASSED in 4.22s** (`dist/index.html` 0.77 kB, `dist/assets/index-*.js` 300 kB).
- **Security Grep Analysis**:
  - `<img`: Found only in `AuthenticatedImage.tsx` rendering `<img src={blobUrl} />` from an authenticated blob object URL. Zero unauthenticated image tags.
  - `dangerouslySetInnerHTML`: Zero occurrences.
  - `console.log`: Zero occurrences in production components.
  - `hardcoded-token`: Found dev fallbacks (`token-reviewer-secret` in `AuthenticatedImage.tsx:22` and `PIIMaskedValue.tsx:42` if `localStorage['ecm_token']` is empty).
- **Browser Behavior**: **NOT VERIFIED** (no live browser session run in this turn).
- **Layer Score: 3.5 (BUILD & UNIT TESTS VERIFIED; Contract freshness failed; Browser unobserved)**.

### E. Security & Privacy
- **Auth Model**: Bearer tokens loaded from `.env`, mapped to 4 roles (`reviewer`, `admin`, `compliance`, `viewer`).
- **Role Enforcement**: `get_current_user` rejects missing/malformed tokens with 401; denies unauthorized actions with 403.
- **Role Header Spoofing**: `X-User-Role` header strictly rejected when `AUTH_ALLOW_ROLE_HEADER=false`.
- **PII Masking & Reveal Audit**: Sensitive PII masked in logs; `POST /api/v1/documents/{uid}/pii/reveal` records audit event while excluding the unmasked value.
- **Git History Audit**: Checked full commit history with `git log -p`: `.env` was never committed; `.env` is confirmed in `.gitignore`.
- **Layer Score: 4 (VERIFIED)**.

### F. AI / ML Quality
- **PII Detection (Holdout 3, 1,067 GT Entities)**:
  - Overall Precision: **86.52%** (PASS against $\ge 80\%$ target).
  - Overall Recall: **95.03%** (NOT MET against $\ge 98\%$ target; misses caused by severe scan degradation where text is missing from OCR).
  - Entity breakdown: EMAIL 97.06% prec / 92.52% rec; IBAN 100% / 100%; MEDICAL 100% / 95%; PASSPORT 95% / 95%; PERSON 77.35% prec / 94.75% rec; PHONE 87.97% prec / 95.94% rec; EIN 100% / 95%; SSN 100% / 92.5%.
- **Classification Accuracy**: 100% on synthetic validation split; 98.24% on Holdout 3; 2.0% on real SROIE receipts (49/50 routed to unknown).
- **Field Extraction Accuracy**: 94.20% on Holdout 3 synthetic; 33.5% on real SROIE receipts (zero-shot regex baseline).
- **Blind Dataset**: `data/blind/` missing on disk (`BLOCKED`).
- **LLM Extractor**: Stopped due to no endpoint/API key in `.env`.
- **Layer Score: 3.5 (MEASURED on synthetic & SROIE dev; Unseen blind eval blocked)**.

### G. Testing and Operations
- **Full Pytest Suite**: **57 passed in 18.27s (100% PASS)** executed against an isolated DB copy (`data/test_ecm_pipeline.db`).
- **Load Benchmark**: 3 repetitions of 200 identical raster scan documents measured:
  - Throughput: 2.87 – 3.21 doc/s.
  - Latency: p50 = 1,154ms – 1,171ms; p95 = 2,139ms – 2,436ms.
- **Docker Engine State**: `docker version` reports client 29.6.1, but daemon named pipe `//./pipe/docker_engine` is offline (`BLOCKED`). `docker compose ps` cannot connect.
- **Observability**: Token-protected `/metrics` export aggregate counters; `/health/live` and `/health/ready` verified.
- **Layer Score: 3.5 (LOCAL TEST SUITE 100% PASS; Docker daemon down)**.

---

## PART 3: Detailed Scoring & Gap Analysis

### 1. Scoring Summary by Area

```text
Area                         | Weight | Built Score | Proven Score | Status
-----------------------------------------------------------------------------------------
Trigger / Capture            | 10     | 100.0%      |   0.0%       | Local logic tested
OCR Engine                   | 15     | 100.0%      |  55.6%       | UB-Mannheim binary verified
Enrichment & Routing         | 20     | 100.0%      |  30.0%       | Gate & PII verified
Review & Approval            | 15     | 100.0%      |  71.4%       | Live HTTP review verified
Distribution                 | 10     |  20.0%      |   0.0%       | GAP: DB label only
Archival & Retention         | 10     |  14.3%      |   0.0%       | GAP: DB label only
Security & Privacy           | 10     | 100.0%      |  80.0%       | Live 401/403/200 verified
Frontend Client              |  5     | 100.0%      |  60.0%       | Build & typecheck verified
Operations & Docker          |  5     |  80.0%      |  60.0%       | 57/57 pytest pass; Docker down
-----------------------------------------------------------------------------------------
COMPOSITE OVERALL            | 100    |  82.4%      |  39.0%       | PARTIALLY PROVEN
```

### 2. Arithmetic Computation
- **BUILT %** $= (10 \times 1.0) + (15 \times 1.0) + (20 \times 1.0) + (15 \times 1.0) + (10 \times 0.20) + (10 \times 0.143) + (10 \times 1.0) + (5 \times 1.0) + (5 \times 0.80) = 10 + 15 + 20 + 15 + 2.0 + 1.43 + 10 + 5 + 4.0 = \mathbf{82.4\%}$
- **PROVEN %** $= (10 \times 0.0) + (15 \times 0.556) + (20 \times 0.30) + (15 \times 0.714) + (10 \times 0.0) + (10 \times 0.0) + (10 \times 0.80) + (5 \times 0.60) + (5 \times 0.60) = 0 + 8.34 + 6.0 + 10.71 + 0 + 0 + 8.0 + 3.0 + 3.0 = \mathbf{39.0\%}$

---

## Key Auditor Findings & Next Steps

1. **The Distribution Gap**:
   `target_workflow` (`kyc_verification`, `ap_processing`, `general_review`) is solely a text label in the database. There is no webhook dispatcher, message queue publisher, or downstream API client to physically hand off accepted documents.
2. **The Archival Gap**:
   `retention_class` (`10_YEARS_KYC`, `7_YEARS_FINANCIAL`) is strictly a label. No legal hold flag, disposition cron job, or WORM/immutable storage layer exists.
3. **The Database & Infrastructure Reality**:
   The production microservice stack (Postgres, Redis, MinIO, OpenSearch) exists in Docker Compose files, but the application currently operates purely in SQLite and local file storage because the host Docker daemon is offline.
4. **The Frontend Contract Gap**:
   Frontend builds cleanly and passes typechecking, but `npm run test` fails on `ContractFreshness.test.ts` because the collaborator has not yet regenerated `src/api/schema.d.ts` via `npm run api:gen`.
