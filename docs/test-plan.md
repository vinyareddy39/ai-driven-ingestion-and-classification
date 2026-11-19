# Comprehensive Pipeline Test Plan & Verification Strategy

**Project:** AI-Driven ECM Document Ingestion Engine  
**Execution Mode:** LOCAL MODE / REAL SERVICES  
**Status:** ACTIVE SPECIFICATION  

---

## 1. Overview
This test plan defines the multi-layer quality assurance framework for the document ingestion, classification, extraction, Presidio PII tagging, and Nuxeo routing pipeline. It establishes the test suites, security boundaries, fault injection drills, and acceptance criteria required for production certification.

---

## 2. Test Architecture & Directory Structure

```
tests/
├── conftest.py                   # Isolated SQLite test database copy, clean state fixtures
├── test_api_v1.py                # REST API v1 endpoints, image leak protection, auth matrix
├── test_config.py                # Configuration loading, mandatory compliance floors, policy
├── test_decision_gate.py         # Table-driven decision gate rules, threshold tuning, triage
├── test_ecm_contracts.py         # ECM contract compliance (FakeECM vs NuxeoAdapterStub)
├── test_fault_injection.py       # Worker crash recovery, OCR engine outage and DLQ retries
├── test_idempotency.py           # Deduplication composite locks, stage transactional commits
├── test_integration_flow.py      # End-to-end flow: ingest -> dedupe -> ocr -> pii -> ecm
├── test_national_id.py           # National ID regex pattern with mandatory context guards
├── test_no_fallbacks.py          # Anti-tamper verification (zero hardcoded fallback values)
├── test_reprocessing.py          # Batch reprocess protection of human-verified fields
├── test_security_masking.py      # PII log masking and redaction filters
└── test_stages_unit.py           # Individual pipeline worker stages unit verification
```

---

## 3. Test Execution Packs & Workflows

### 3.1 Local Core Test Pack (`scripts/test_all.ps1`)
Runs completely inside the local environment against an isolated copy of the SQLite database (`data/test_ecm_pipeline.db`):
1. **Full Pytest Execution**: 57 tests across unit, integration, and security layers.
2. **Auth & Perimeter Matrix**: Rejects unauthenticated requests with HTTP 401; verifies RBAC permissions for reviewer, admin, compliance, and viewer roles.
3. **PII Evaluation Benchmark**: Evaluates all 8 entity types against ground-truth development labels.

### 3.2 Real Infrastructure Integration Pack (`scripts/integration_real.ps1`)
Requires Docker Desktop engine running:
1. Orchestrates real backing containers: PostgreSQL, Redis, MinIO, OpenSearch via Docker Compose.
2. Waits for health checks to pass.
3. Runs database schema migrations.
4. Executes live integration tests, fault injection scenarios, and contract validation.

### 3.3 Manual Spot Check Verification
Verifies HTTP endpoints using `curl.exe`:
```powershell
# 1. Audit endpoint without token -> 401 Unauthorized
curl.exe -i http://127.0.0.1:8000/api/v1/documents/doc-test-01/compliance

# 2. Review queue without token -> 401 Unauthorized
curl.exe -i http://127.0.0.1:8000/review

# 3. Document page image without token -> 401 Unauthorized
curl.exe -i http://127.0.0.1:8000/api/v1/documents/doc-test-01/pages/1/image
```
