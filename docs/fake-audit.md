# Fake vs Real Audit: ECM Document Pipeline & Ingestion System

**Audit Date:** November 19, 2026  
**Auditor:** Independent Systems Integrity Auditor (Antigravity)  
**Scope:** Entire repository (`app/`, `frontend/`, `scripts/`, `data/`, `tests/`, `config/`).

---

## 1. Summary of Pipeline Stages: Real vs Partial vs Fake

| Pipeline Stage | Status | Component / Engine | Evidence (File:Line) | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Intake (Streaming Upload)** | **REAL** | `routes_ingest.py` | [`app/api/routes_ingest.py:46-120`](file:///C:/ml/app/api/routes_ingest.py#L46-L120) | Streams 1 MB chunks to disk, enforces `MAX_UPLOAD_MB` dynamically, validates magic bytes (`%PDF`, PNG/TIFF headers). |
| **Virus Scanning** | **PARTIAL** | `ClamAVScanner` / `MockVirusScanner` | [`app/adapters/virus.py:11-61`](file:///C:/ml/app/adapters/virus.py#L11-L61)<br>[`app/api/routes_prescriptions.py:11,123`](file:///C:/ml/app/api/routes_prescriptions.py#L11-L123) | Real ClamAV TCP socket scanner exists, but defaults to `MockVirusScanner` (EICAR signature check) if ClamAV daemon is absent. `routes_prescriptions.py` directly instantiated `MockVirusScanner`. |
| **Deduplication Check** | **REAL** | `stage_dedupe` | [`app/workers/stages.py:47-59`](file:///C:/ml/app/workers/stages.py#L47-L59) | Queries database/storage for identical SHA-256 hash. Re-linking instead of duplicating storage. |
| **Integrity & Preprocess** | **REAL** | `stage_preprocess` / PyMuPDF | [`app/workers/stages.py:64-103`](file:///C:/ml/app/workers/stages.py#L64-L103) | Checks encryption, password protection, and structural integrity via PyMuPDF. |
| **Document Splitting** | **REAL** | `stage_split_document` / PyMuPDF | [`app/workers/stages.py:109-152`](file:///C:/ml/app/workers/stages.py#L109-L152) | Scans page text for separator barcodes/tokens and splits multi-page PDFs dynamically. |
| **OCR Engine** | **REAL** | TrOCR (CUDA) & Hybrid PyMuPDF / Tesseract | [`app/adapters/ocr.py:164-320`](file:///C:/ml/app/adapters/ocr.py#L164-L320)<br>[`app/adapters/ocr.py:328-490`](file:///C:/ml/app/adapters/ocr.py#L328-L490) | Extracts native digital text layers first (`text_layer`), executes TrOCR on GPU (`microsoft/trocr-base-stage1`) or Tesseract for raster scans. Output is 100% computed from input. |
| **Classification** | **REAL** | Scikit-Learn TF-IDF + Logistic Regression | [`app/adapters/classifier.py:24-65`](file:///C:/ml/app/adapters/classifier.py#L24-L65)<br>[`data/models/classifier_v1.joblib`](file:///C:/ml/data/models/classifier_v1.joblib) | Loads real trained model (`char_word_tfidf_logistic_regression v2.0.0`) from disk. Computes real probability distribution over 9 classes. Fallback heuristic rules exist if model file is missing. |
| **Field Extraction** | **REAL** | `GenericFuzzyExtractor` / Schema Validation | [`app/workers/fuzzy_extractor.py:52-175`](file:///C:/ml/app/workers/fuzzy_extractor.py#L52-L175)<br>[`app/workers/stages.py:250-300`](file:///C:/ml/app/workers/stages.py#L250-L300) | Strictly parses actual OCR text lines for dates, amounts, counterparties using fuzzy Levenshtein <= 2 and regex. Never returns canned or hardcoded values; missing fields evaluate to `None`. |
| **PII Detection** | **REAL** | Microsoft Presidio + spaCy + Custom Patterns | [`app/adapters/pii.py:12-80`](file:///C:/ml/app/adapters/pii.py#L12-L80) | Analyzes input text for SSN, credit cards, emails, phone numbers, passport numbers, and medical licenses. Sensitivity levels computed from detected entities. |
| **Confidence & Decision Gate** | **REAL** | `stage_decision_gate` | [`app/workers/stages.py:324-421`](file:///C:/ml/app/workers/stages.py#L324-L421) | Evaluates classifier confidence against class-specific thresholds in `pipeline_config.yaml`. Enforces strict business rules: `unknown` never auto-accepts; schema failure routes to review; high-sensitivity PII conflict forces stricter review. |
| **Review & Human Triage** | **REAL** | FastAPI Review Routes & DB | [`app/api/routes_v1.py:350-480`](file:///C:/ml/app/api/routes_v1.py#L350-L480)<br>[`app/api/routes_review.py:170-220`](file:///C:/ml/app/api/routes_review.py#L170-L220) | Review actions (CONFIRM, RECLASSIFY, CORRECT, REJECT) write real human corrections to SQLite/Postgres. Human corrections are locked from re-processing overwrite. |
| **Routing & ECM Persistence** | **REAL (Misnamed)** | `FakeECM` (SQLite / Postgres) | [`app/adapters/ecm.py:10-56`](file:///C:/ml/app/adapters/ecm.py#L10-L56) | Despite being named `FakeECM`, this adapter commits real records, hashes, ACLs, and retention classes to SQLite/Postgres. Nuxeo adapter has an optional stub fallback mode ([`app/adapters/ecm.py:196`](file:///C:/ml/app/adapters/ecm.py#L196)). |
| **Search Indexing** | **PARTIAL** | OpenSearch / `InMemorySearchIndex` | [`app/adapters/search.py:8-51`](file:///C:/ml/app/adapters/search.py#L8-L51)<br>[`app/adapters/search.py:53-113`](file:///C:/ml/app/adapters/search.py#L53-L113) | Production OpenSearch adapter exists. In development/local mode without an active OpenSearch cluster, falls back to in-memory dictionary filtering. |
| **Audit Logging** | **REAL** | `stage_audit_record` & `AuditEventModel` | [`app/workers/stages.py:516-560`](file:///C:/ml/app/workers/stages.py#L516-L560) | Every processed asset records model version, confidence, OCR engine, and pipeline event to `audit_events` table in SQLite/Postgres. |
| **Observability & Dashboard** | **PARTIAL (Data Contamination)**| `routes_v1.py` / `DashboardView.tsx` | [`app/api/routes_v1.py:65-150`](file:///C:/ml/app/api/routes_v1.py#L65-L150)<br>[`data/ecm_pipeline.db`](file:///C:/ml/data/ecm_pipeline.db) | The dashboard endpoint computes real SQL `COUNT` and aggregations from `ecm_documents`, but the live SQLite database contains 1,793 test/seed documents from previous integration test runs (`load-test-*`, `canonical-*`), which skews the UI metrics. |
| **Prescription Image Serving**| **FAKE FALLBACK** | `routes_prescriptions.py` | [`app/api/routes_prescriptions.py:276-278`](file:///C:/ml/app/api/routes_prescriptions.py#L276-L278) | Returns a hardcoded 1x1 transparent PNG when the file key is missing in storage instead of returning HTTP 404. |
| **SMTP Reminders** | **STUB** | `StubSMTPReminderChannel` | [`app/workers/reminders.py:62-85`](file:///C:/ml/app/workers/reminders.py#L62-L85) | Appends outgoing reminders to an in-memory list `sent_emails` rather than connecting to an SMTP host. |
| **Hosted LLM Client** | **NOT IMPLEMENTED** | `HostedLLMClient` | [`app/workers/llm_client.py:118`](file:///C:/ml/app/workers/llm_client.py#L118) | Raises `NotImplementedError` for hosted LLM calls; local fallback extraction handles processing. |
| **User Role Authentication** | **PARTIAL / DEMO STUB** | `STUB_USERS` / `Shell.tsx` | [`app/core/auth.py:14-49`](file:///C:/ml/app/core/auth.py#L14-L49)<br>[`frontend/src/components/Shell.tsx:131-150`](file:///C:/ml/frontend/src/components/Shell.tsx#L131-L150) | In local mode, static tokens map to 4 demo accounts (`admin`, `reviewer`, `compliance`, `viewer`). Frontend Shell contains an "Active Role (Stub)" selector. |

---

## 2. Seed Records and Database Contamination in Active App

The current database file `data/ecm_pipeline.db` contains records generated during automated load tests and previous development runs:

- **Total Documents in `ecm_documents`:** 1,793 rows
  * `auto_accepted`: 1,414
  * `pending_review`: 363
  * `human_verified`: 15
  * `quarantined`: 1
- **Breakdown by UID Prefix:**
  * `load-test-*`: 1,158 rows (synthetic load testing artifacts)
  * `canonical-*`: 20 rows (synthetic deduplication fixtures)
  * `integ-test-*`: 17 rows (integration test artifacts)
  * `crash-test-*`: 17 rows (failure injection tests)
  * `warmup-*`: 10 rows (startup test runs)
  * Real / manual uploads: Remaining ~571 rows.

**Impact on User Interface:**
When the frontend loads `http://localhost:5173/`, `GET /api/v1/dashboard/metrics` counts all 1,793 rows in the database. The user sees 1,793 processed documents and 363 review queue tasks that originated from test scripts, rather than only documents uploaded and processed by the user.

---

## 3. Discovered Fakes, Mocks, and Stubs Across Repo

1. **`app/adapters/virus.py` (lines 11-18, 56-61):**
   * `MockVirusScanner`: Detects EICAR test signature (`X5O!P%@...`) or simulated string `VIRUS_INFECTED_PAYLOAD`.
   * When `VIRUS_SCANNER_BACKEND` is not `clamav`, defaults to this mock scanner.
2. **`app/api/routes_prescriptions.py` (line 11, line 123):**
   * Imports `MockVirusScanner` directly instead of using factory `get_virus_scanner()`.
3. **`app/api/routes_prescriptions.py` (lines 276-278):**
   * Returns fake 1x1 transparent PNG when file asset is missing in storage.
4. **`app/adapters/ecm.py` (line 10, lines 196-203):**
   * Class is named `FakeECM` (though it executes real database queries).
   * `NuxeoAdapter` contains `stub_mode` and an in-memory dictionary `_stub_store`.
5. **`app/workers/reminders.py` (lines 62-85):**
   * `StubSMTPReminderChannel` stores dispatched emails in an in-memory list `self.sent_emails = []`.
6. **`app/workers/llm_client.py` (lines 116-119):**
   * `HostedLLMClient.complete()` raises `NotImplementedError("Hosted LLM endpoint configured for synthetic benchmarks only.")`.
7. **`app/core/auth.py` (lines 14-49):**
   * `STUB_USERS` dictionary contains mock users (`admin@ecm.local`, `reviewer@ecm.local`, etc.).
8. **`frontend/src/components/Shell.tsx` (lines 131-150):**
   * UI displays "Active Role (Stub)" dropdown for switching simulated roles.
9. **`frontend/src/components/DashboardView.tsx` (line 211):**
   * UI text mentions `Confidence >= 85% -> Auto-Accepted (FakeECM / Nuxeo)`.
10. **`app/adapters/search.py` (lines 8-51):**
    * `InMemorySearchIndex`: Python dictionary fallback when OpenSearch cluster is not connected.
