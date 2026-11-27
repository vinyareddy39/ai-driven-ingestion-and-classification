# Engineering Assumptions & Architecture Decisions

## Operating Environment
1. **Local-First & Multi-Backend Architecture**: The system supports both containerized deployment (`docker-compose up` with PostgreSQL, Redis, MinIO, ClamAV, OpenSearch) and zero-dependency local execution (SQLite database, file-based S3 simulation, in-memory Redis Streams & OpenSearch engine, local Tesseract/PyMuPDF OCR engine, and ClamAV mock scanner) via clean interface abstraction. This ensures immediate local testability and evaluation on any developer workstation or CI environment.
2. **Python 3.11 / 3.14 Compatibility**: All code utilizes standard library features and modern typing compatible with Python 3.11 through 3.14. For Locust load testing on Python 3.14 where `gevent` monkey-patching has known upstream compatibility constraints with `ssl.SSLContext`, both the standard `locustfile.py` and an asynchronous `asyncio/httpx` high-throughput load runner are provided to deliver verified p50/p95 latency metrics for 50,000 docs/day equivalent throughput.

## Pipeline & Classification
3. **Document Classes & Risk Profiles**:
   - High-Risk Classes (10x error penalty in threshold tuning): `kyc_form`, `bank_statement`, `medical_report`, `claim_form`.
   - Low-Risk Classes: `invoice`, `contract`, `purchase_order`, `letter`.
   - Mandatory Unclassified Class: `unknown` (strictly rejected from auto-acceptance; always routed to Human Review).
4. **Decision Gate Logic**:
   - Default acceptance threshold: $\ge 0.90$ for low-risk classes, $\ge 0.95$ for high-risk classes.
   - Any document classified as `unknown` or with confidence $< 0.60$ or encountering classifier/PII sensitivity conflict is routed to the Human Review Queue with a `RESTRICTED_REVIEW` ACL.
   - Auto-accepted documents receive the standard `PUBLIC_ARCHIVE` or `CONFIDENTIAL_FINANCE` ACL and corresponding retention rules (e.g., 7 years for financial, 10 years for KYC/medical, 3 years for general correspondence).
5. **PII Sensitivity & Conflict Resolution**:
   - Detected PII types are scored across High (SSN, credit card, passport), Medium (EIN, phone, email, IBAN, person name), and Low sensitivity.
   - When low-risk document types contain high-sensitivity PII that contradicts expected template schemas, the decision gate enforces the stricter outcome (escalating to Human Review with restricted ACL).
   - Format-based Tax ID Distinction: Employer Identification Numbers (EIN, `XX-XXXXXXX`) represent corporate identifiers (medium sensitivity), while Social Security Numbers (SSN, `XXX-XX-XXXX`) remain strictly personal high-sensitivity PII regardless of label.
   - PII Target Performance: Target precision of at least 80% at recall of at least 98% across all sensitive PII entities, achieved by tuning score thresholds and suppressing non-sensitive background tags (such as generic calendar dates and corporate entity names).

## Reprocessing & Human Verification Integrity
6. **Immutability of Human-Verified Fields**:
   - Fields marked as `humanVerifiedFields` in the ECM metadata are treated as ground-truth and can never be overwritten by automated reprocessing passes. Conflicting automated predictions generate an audit diff event rather than modifying verified fields.
7. **Rate-Limited Reprocessing**:
   - Bulk reprocessing runs on a dedicated low-priority queue with token-bucket rate limiting to guarantee that live real-time ingestion streams are never starved of worker capacity.

## Frontend & API Contract (Phase 4)
8. **API First Architecture**:
   - All frontend interactions strictly use typed JSON REST endpoints under `/api/v1/`. Legacy HTMX HTML endpoints under `/review` are preserved for backward compatibility.
   - Response models are explicitly defined using Pydantic v2 schemas to ensure `/openapi.json` is strictly accurate and client code can be generated via `openapi-typescript`.
9. **Stub Authentication**:
   - A role-based stub authentication layer validates headers (`X-User-Role` or `Authorization: Bearer <role>_token`) supporting roles: `reviewer`, `admin`, `compliance`, `viewer`. Stub tokens are mapped directly in configuration until production OIDC/SSO integration.
10. **Data Grounding & Zero-Mock UI**:
    - The web frontend displays real data queried directly from the SQLite/PostgreSQL `ecm_documents`, `review_tasks`, and `audit_events` tables. Zero synthetic or hardcoded dashboard metrics are used in production screens.
11. **Config Validation & Floors**:
    - Admin threshold updates strictly validate class-specific minimum floor values (0.85 for low-risk, 0.92 for high-risk classes) in the backend to prevent security or compliance degradation.

