# Frontend & Backend API Contract Specification

This document defines the REST API contract between the Document Ingestion & Classification Pipeline backend and the React TypeScript web frontend, specifying the required endpoints for each screen and marking each as **EXISTS** or **MISSING**.

---

## 1. Existing Legacy Endpoints (Audit Baseline)

From `/openapi.json` and code inspection:

| Method | Path | Summary | Content-Type | Status | Note |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `POST` | `/ingest` | Ingest Single File | `multipart/form-data` | **EXISTS** | Ingests document, returns `IngestResponse` |
| `POST` | `/ingest/bulk` | Ingest Bulk Files | `multipart/form-data` | **EXISTS** | Ingests multiple documents |
| `POST` | `/ingest/scanner_watch_trigger` | Trigger Scanner Folder | N/A | **EXISTS** | Triggers local scan folder watch |
| `GET` | `/review` | Get Review Queue Page | `text/html` | **EXISTS (HTML only)** | Legacy HTMX HTML template |
| `GET` | `/review/{document_uid}` | Get Document Review Detail | `text/html` | **EXISTS (HTML only)** | Legacy HTMX HTML template |
| `POST` | `/review/{document_uid}/action` | Process Review Action | `text/html` | **EXISTS (HTML only)** | Legacy HTMX form handler |
| `GET` | `/review/export/training_data.jsonl` | Export Verified Training Data | `text/plain` | **EXISTS** | JSONL export |
| `POST` | `/reprocess` | Reprocess Documents By Query | `application/json` | **EXISTS** | Returns `ReprocessResponse` |
| `GET` | `/metrics` | Prometheus Metrics | `text/plain` | **EXISTS** | Raw Prometheus format |
| `GET` | `/health/live` | Liveness Check | `application/json` | **EXISTS** | Returns `{"status":"ALIVE"}` |
| `GET` | `/health/ready` | Readiness Check | `application/json` | **EXISTS** | Returns dependency statuses |
| `GET` | `/audit/{uid}` | Get Asset Audit Report | `application/json` | **EXISTS** | Returns dictionary of audit events |

---

## 2. Screen-by-Screen API Requirements

### Screen 1: App Shell (Navigation, Mode Badge & Health)
*Requirements: Sidebar, role-aware navigation, mode badge showing `LOCAL MODE` or `REAL SERVICES`, health indicator.*

| Endpoint | Method | Purpose | Status | Request / Response Contract |
| :--- | :---: | :--- | :---: | :--- |
| `GET /api/v1/system/info` | `GET` | Mode badge (`LOCAL MODE` vs `REAL SERVICES`), active storage/DB adapters, pipeline version. | **MISSING** | **Resp**: `SystemInfoResponse` (`mode: str`, `version: str`, `storage_backend: str`, `ocr_engine: str`, `classifier_version: str`, `uptime_seconds: float`) |
| `GET /health/live` | `GET` | Live health probe for shell status indicator. | **EXISTS** | **Resp**: `{"status": "ALIVE"}` |
| `GET /api/v1/auth/me` | `GET` | Current authenticated user stub and active role. | **MISSING** | **Resp**: `UserSessionResponse` (`user_id: str`, `username: str`, `role: str`, `permissions: List[str]`) |

---

### Screen 2: Review Queue
*Requirements: Table sorted by risk then confidence; columns: thumbnail, predicted type, confidence, review reason, PII sensitivity, age; filtering & keyboard navigation.*

| Endpoint | Method | Purpose | Status | Request / Response Contract |
| :--- | :---: | :--- | :---: | :--- |
| `GET /api/v1/review/queue` | `GET` | Paginated, sorted, filterable review queue in JSON. | **MISSING** | **Query**: `page`, `page_size`, `sort_by` (`risk`, `confidence`, `age`), `doc_type`, `risk_level`, `pii_sensitivity`<br>**Resp**: `ReviewQueueResponse` (`items: List[ReviewQueueItem]`, `total: int`, `page: int`, `page_size: int`) |

---

### Screen 3: Review Detail Screen
*Requirements: Page image beside OCR text with bounding-box highlights for extracted fields and PII; prediction, confidence and per-field confidences; model name and version; editable type and fields; Confirm and Correct buttons; reviewer ID and timestamp recorded; corrected fields show a "human-verified" badge. Opening must never auto-accept.*

| Endpoint | Method | Purpose | Status | Request / Response Contract |
| :--- | :---: | :--- | :---: | :--- |
| `GET /api/v1/review/{document_uid}` | `GET` | JSON detail for a review task including fields, bounding boxes, confidences, and model info. | **MISSING** | **Resp**: `ReviewDetailResponse` (`document_uid`, `task_id`, `file_name`, `doc_type`, `confidence`, `model_name`, `model_version`, `ocr_engine`, `ocr_version`, `decision_reason`, `extracted_fields`, `human_verified_fields`, `field_confidences`, `pii_entities`, `ocr_text`, `ocr_words`, `page_count`) |
| `GET /api/v1/documents/{document_uid}/pages/{page_num}/image` | `GET` | Rendered page image PNG/JPEG for bounding box overlay. | **MISSING** | **Resp**: Binary image (`image/png`) |
| `POST /api/v1/review/{document_uid}/action` | `POST` | Process reviewer confirmation or correction with audit logging. | **MISSING** | **Req**: `ReviewActionRequest` (`reviewer_id: str`, `action: CONFIRM\|CORRECT\|REJECT`, `corrected_type: Optional[str]`, `corrected_fields: Optional[Dict[str, Any]]`, `review_notes: Optional[str]`)<br>**Resp**: `ReviewActionResponse` (`success: bool`, `document_uid: str`, `review_status: str`, `updated_at: datetime`) |

---

### Screen 4: Upload and Ingest
*Requirements: Drag-and-drop with multiple files, upload progress, duplicate detection result (link to original), quarantine reason for corrupt/infected/password-protected files, per-file status updates by polling.*

| Endpoint | Method | Purpose | Status | Request / Response Contract |
| :--- | :---: | :--- | :---: | :--- |
| `POST /ingest` | `POST` | Single file ingestion. | **EXISTS** | **Req**: `multipart/form-data` (`file`)<br>**Resp**: `IngestResponse` (`uid`, `sha256`, `file_name`, `status`, `queue`, `message`) |
| `POST /ingest/bulk` | `POST` | Multi-file batch ingestion. | **EXISTS** | **Req**: `multipart/form-data` (`files`)<br>**Resp**: `List[IngestResponse]` |
| `GET /api/v1/documents/{document_uid}/status` | `GET` | Fast status polling endpoint for ingested files. | **MISSING** | **Resp**: `DocumentStatusResponse` (`uid: str`, `status: str`, `doc_type: str`, `confidence: float`, `is_link: bool`, `linked_to_uid: Optional[str]`, `quarantine_reason: Optional[str]`) |

---

### Screen 5: Documents List and Search
*Requirements: Full-text plus filters (type, confidence range, model version, review status, PII types, date), result highlights, pagination.*

| Endpoint | Method | Purpose | Status | Request / Response Contract |
| :--- | :---: | :--- | :---: | :--- |
| `GET /api/v1/documents` | `GET` | Paginated list with filtering and search across all documents. | **MISSING** | **Query**: `q`, `doc_type`, `min_confidence`, `max_confidence`, `model_version`, `review_status`, `pii_type`, `start_date`, `end_date`, `page`, `page_size`<br>**Resp**: `DocumentListResponse` (`items: List[DocumentSummaryItem]`, `total: int`, `page: int`, `page_size: int`, `total_pages: int`) |

---

### Screen 6: Document Detail (Compliance View)
*Requirements: AIClassification record, audit trail timeline, retention class and ACL with the rule that produced them, "why was this classified, retained and restricted this way" panel built only from stored fields. If a field is missing, show "missing" in red; never invent text.*

| Endpoint | Method | Purpose | Status | Request / Response Contract |
| :--- | :---: | :--- | :---: | :--- |
| `GET /api/v1/documents/{document_uid}` | `GET` | Full compliance record including decision rules, retention, ACL, classification metadata, PII tags. | **MISSING** | **Resp**: `DocumentComplianceDetailResponse` (`uid`, `sha256`, `file_name`, `doc_type`, `confidence`, `retention_class`, `acl`, `decision_rule`, `decision_reason`, `target_workflow`, `classifier_model`, `classifier_version`, `pii_detected`, `pii_entities`, `extracted_fields`, `human_verified_fields`, `created_at`, `updated_at`) |
| `GET /api/v1/documents/{document_uid}/audit` | `GET` | Chronological audit trail timeline of all stages and human interactions. | **MISSING** | **Resp**: `AuditTrailResponse` (`document_uid: str`, `events: List[AuditEventItem]`) |

---

### Screen 7: Reprocess Screen (ML Engineer)
*Requirements: Build a query (classifierVersion below X, confidence below Y), show dry-run count and sample, run it, track progress, show diffs for conflicts with human-verified fields. Never offer an overwrite of human-verified values.*

| Endpoint | Method | Purpose | Status | Request / Response Contract |
| :--- | :---: | :--- | :---: | :--- |
| `POST /api/v1/reprocess/preview` | `POST` | Dry-run preview: counts matched documents, samples documents, identifies human-verified field conflicts. | **MISSING** | **Req**: `ReprocessPreviewRequest` (`query: Optional[str]`, `classifier_version_filter: Optional[str]`, `min_confidence: Optional[float]`, `target_types: Optional[List[str]]`)<br>**Resp**: `ReprocessPreviewResponse` (`matched_count: int`, `human_verified_conflict_count: int`, `sample_documents: List[ReprocessSampleItem]`) |
| `POST /reprocess` | `POST` | Execute reprocess job. | **EXISTS** | **Req**: `ReprocessRequest`<br>**Resp**: `ReprocessResponse` (`matched_count`, `queued_count`, `skipped_count`, `dry_run`, `job_id`) |
| `GET /api/v1/reprocess/jobs/{job_id}` | `GET` | Track reprocess job execution progress. | **MISSING** | **Resp**: `ReprocessJobStatusResponse` (`job_id: str`, `status: str`, `total_documents: int`, `processed_documents: int`, `errors_count: int`) |

---

### Screen 8: Dashboard Screen (Everyone)
*Requirements: Queue depth, stage latency, error rate, STP rate, review queue size, per-class counts, dead-letter count. Source is the backend's metrics endpoint only; show "no data yet" rather than zeros when nothing has run.*

| Endpoint | Method | Purpose | Status | Request / Response Contract |
| :--- | :---: | :--- | :---: | :--- |
| `GET /api/v1/dashboard/metrics` | `GET` | Structured JSON summary calculated from real database & telemetry. | **MISSING** | **Resp**: `DashboardMetricsResponse` (`has_data: bool`, `total_ingested: int`, `queue_depth: int`, `review_queue_size: int`, `stp_rate: Optional[float]`, `error_rate: Optional[float]`, `stage_latencies_ms: Dict[str, StageLatencyMetric]`, `per_class_counts: Dict[str, int]`, `dead_letter_count: int`) |
| `GET /metrics` | `GET` | Raw Prometheus format metrics. | **EXISTS** | **Resp**: `text/plain` |

---

### Screen 9: Admin Screen
*Requirements: Thresholds per class, routing, PII policy. Validate inputs, show current vs proposed values, require confirmation, display config change history. Do not let the UI weaken a high-risk class threshold below the configured floor (0.85 low-risk, 0.92 high-risk).*

| Endpoint | Method | Purpose | Status | Request / Response Contract |
| :--- | :---: | :--- | :---: | :--- |
| `GET /api/v1/admin/config` | `GET` | Current thresholds, minimum allowed floors, routing targets, and PII policy. | **MISSING** | **Resp**: `AdminConfigResponse` (`classes: Dict[str, ClassThresholdConfig]`, `routing_rules: Dict[str, str]`, `pii_policy: Dict[str, Any]`, `high_risk_floor: float`, `low_risk_floor: float`) |
| `POST /api/v1/admin/config` | `POST` | Update configuration with server-side validation against floors. | **MISSING** | **Req**: `AdminConfigUpdateRequest` (`updated_by: str`, `class_thresholds: Dict[str, float]`, `pii_policy: Optional[Dict[str, Any]]`)<br>**Resp**: `AdminConfigUpdateResponse` (`success: bool`, `message: str`, `effective_config: AdminConfigResponse`) |
| `GET /api/v1/admin/config/history` | `GET` | Audit log of configuration modifications. | **MISSING** | **Resp**: `ConfigHistoryResponse` (`history: List[ConfigHistoryItem]`) |

---

## 3. Authentication & CORS Strategy

- **CORS**: Enabled on FastAPI application for `http://localhost:5173` (Vite dev server) with allowed origins configurable via `CORS_ORIGINS` environment variable.
- **Auth Stub**: HTTP Bearer token or `X-User-Role` header with four active roles:
  - `reviewer`: Access to Review Queue, Review Detail, Actions.
  - `compliance`: Access to Documents Search, Document Detail (Compliance View), Audit Trail.
  - `admin`: Access to Admin thresholds, PII policy, and configuration history.
  - `viewer`: Read-only access to Dashboard and Document Search.
