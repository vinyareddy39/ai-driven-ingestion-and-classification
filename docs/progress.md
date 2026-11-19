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
| Stage 2 | Auth and Isolation | PENDING | - | User signup, login, argon2/bcrypt hashing, JWT tokens, per-user isolation 404s |
| Stage 3 | Upload, Storage and Worker | PENDING | - | Storage adapter by random key, OCR, PII tagging, always NEEDS_REVIEW |
| Stage 4 | Medication Field Extraction | PENDING | - | Grounded drug, strength, dose, frequency, timing extraction on synthetic scans |
| Stage 5 | Timetable Generation | PENDING | - | Deterministic schedule parser, 40+ unit tests, confirm endpoint with 409 check |
| Stage 6 | Reminders, Review and Reprocessing | PENDING | - | Reminder scheduler, training JSONL export, batch reprocess query |
| Stage 7 | Privacy, Security and Database | PENDING | - | Column encryption at rest, log hygiene test, data export/delete-my-data |
| Stage 8 | ECM Lifecycle | PENDING | - | Outbound HMAC webhook, disposition job, legal hold flag |
| Stage 9 | Test Pack and Report | PENDING | - | Master test script update, docs/prescription-report.md |

