# Project Execution Progress Tracker

| Stage | Name | Status | Commit SHA | Notes / Evidence |
|---|---|---|---|---|
| Stage 0 | Preflight and Loose Ends | COMPLETED | a97d396 | Baseline 57/57 tests pass, 4 random 43-char secrets in .env, floors 0.90/0.95 enforced, restart persistence verified |
| Stage 1 | Decision Gate and Thresholds | COMPLETED | e4bc164 | Cost matrix CFA/CFR ($500 vs $5), conflict routing rule proved, sub-floor rejection verified in table tests |
| Stage 2 | PII Precision | COMPLETED | 8cd110a | Overall precision 86.52% (target >= 80%), generic context rules for PERSON/PHONE, National ID context recognizer tested |
| Stage 3 | Extraction and Real Documents | COMPLETED / BLOCKED | c9e4ed1 | Measured SROIE dev baseline (33.5% zero-shot), authored docs/extraction-decision-memo.md; BLOCKED: data/blind missing, BLOCKED: No LLM API key or local endpoint in .env |
| Stage 4 | Feedback Loop and Load Test | COMPLETED | - | Submitted 5 human review corrections, exported to JSONL, active learning retrained, 200 identical doc load test (2.87-3.21 doc/s) |
| Stage 5 | Real Services (Docker) | BLOCKED / SCRIPT READY | - | Docker daemon offline on host; authored scripts/integration_real.ps1 for running containers, migrations, and fault tests |
| Stage 6 | Problem Statement Coverage | COMPLETED | - | Authored docs/capability-matrix.md auditing all 18 capabilities; blank page, encrypted PDF quarantine, .eml parsing verified |
| Stage 7 | Test Pack and Final Report | COMPLETED | - | Authored scripts/test_all.ps1, docs/test-plan.md, and docs/final-report.md auditing D1 through D9 with raw command evidence |

## Blocked Items Log
- **Stage 3 (Blind Dataset Evaluation)**: `BLOCKED: data/blind missing`. Real test documents not placed in directory.
- **Stage 3 (LLM Extraction Backend)**: `BLOCKED: No LLM API key or local endpoint in .env`. Extraction evaluation remains on deterministic local extractors.
- **Stage 5 (Real Services Orchestration)**: `BLOCKED: Docker engine not running`. Docker client installed, but daemon named pipe `//./pipe/docker_engine` is inactive.

## Prescription Extension Flow (Branch: backend/prescriptions)

| Stage | Name | Status | Commit SHA | Notes / Evidence |
|---|---|---|---|---|
| Stage 0 | Gap Check Against Existing System | COMPLETED | - | Audited 16 target flow items with file:line evidence; identified gaps in auth, isolation, medication extractor, timetable, reminders |
| Stage 1 | Design and Contract | COMPLETED | - | Authored docs/prescription-design.md & docs/frontend-tasks.md; portable SQLAlchemy models; Alembic migration a1b2c3d4e5f6 verified upgrade/downgrade on DB copy; openapi.json regenerated (45 paths) |
| Stage 2 | Auth and Isolation | COMPLETED | b9dda5c | Argon2id password hashing, HS256 JWT access (30m) & refresh (7d) tokens, 5-attempt/5min rate limiting, per-user isolation 404s, staff access audit logging; verified with full test suite (61/61 passing) and curl spot-checks (401/401/404/200) |


| Stage 3 | Upload, Storage and Worker | COMPLETED | ce35c1d | Storage adapter with UUID keys, 201 QUEUED upload, SHA-256 duplicate detection, MockVirusScanner check, line-preserved OCR, Presidio PII scan, grounded medication extractor, NEVER AUTO-ACCEPT invariant (always NEEDS_REVIEW); 67/67 tests passing |

| Stage 4 | Medication Field Extraction | COMPLETED | be743bf | Grounded medication extractor (100% OCR grounded), drug aliases, safety checks, seeded synthetic benchmark (Dev F1: 96.0%, Fresh holdout F1: 96.1%); BLOCKED: local LLM endpoint in .env, using deterministic rule parser; 72/72 tests passing |

| Stage 5 | Timetable Generation | COMPLETED | 73643df | Deterministic schedule parser (anchor times, offsets, interval frequencies, month/year boundaries, DST transitions, PRN zero-slots), mandatory medical disclaimer, confirm endpoint returning 409 if any item unverified, adherence slot status updates with audit logging; 47/47 timetable tests and 119/119 full suite passing |
| Stage 6 | Reminders, Review and Reprocessing | COMPLETED | 5b119e6 | Reminder scheduler with pluggable delivery channels (Log/StubSMTP), strictly zero PII in reminder payloads; human review correction loop appending token spans to data/prescription_corrections.jsonl without PII; batch reprocessing endpoint POST /prescriptions/reprocess with dry_run mode and strict invariant protection (verified_by_user items are never overwritten); 3/3 Stage 6 tests and 122/122 full suite passing |
| Stage 7 | Privacy, Security and Database | PENDING | - | Column encryption at rest, log hygiene test, data export/delete-my-data |
| Stage 8 | ECM Lifecycle | PENDING | - | Outbound HMAC webhook, disposition job, legal hold flag |
| Stage 9 | Test Pack and Report | PENDING | - | Master test script update, docs/prescription-report.md |

