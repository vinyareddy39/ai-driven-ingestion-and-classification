# Manual Connection & Screen Click-Through Checklist

**Mode:** `LOCAL MODE`  
**Backend:** `http://127.0.0.1:8000` (FastAPI / Uvicorn)  
**Frontend:** `http://localhost:5173` (Vite / React 19)  
**Auth Model:** `X-User-Role: admin` (LOCAL MODE Header) / `Authorization: Bearer <token>` (Enterprise)  

---

## Pre-Flight Verification

Execute in PowerShell from repo root:
```powershell
# 1. Run automated 10-endpoint connection probe
node scripts/connection_check.mjs

# 2. Start connected environment
.\scripts\run_connected.ps1
```
Open your browser to `http://localhost:5173`.

---

## Screen 1: Pipeline Dashboard (`/dashboard`)

| Step | Action | Expected Observation | Backend Call |
|------|--------|----------------------|--------------|
| 1.1 | Open homepage | Page loads with dark theme, 5 KPI cards (STP Rate, Total Repository, Pending Review, Quarantined, SHA-256 Deduped) | `GET /api/v1/dashboard/metrics` |
| 1.2 | Observe KPI numbers | Real counts from DB (not zeros or mocks). If DB is fresh, "0 assets" displayed honestly. | `GET /api/v1/dashboard/metrics` |
| 1.3 | Check 9-Stage Flow | 9 stage cards (Virus Scan S1 -> Decision Gate S9) showing latency p50 values and technology tags. | `GET /api/v1/dashboard/metrics` (`stage_latencies`) |
| 1.4 | Check Classified Breakdown | Bar chart showing distribution by document class. If empty, displays "No classified assets yet." | `GET /api/v1/dashboard/metrics` (`type_breakdown`) |
| 1.5 | Check Recent Assets Table | Recent ingested documents with UID, Class, Confidence %, PII badge, and Status pill. | `GET /api/v1/dashboard/metrics` (`recent_documents`) |
| 1.6 | Click Refresh (top-right) | Spinner rotates; metrics re-fetch; pending review badge updates. | `GET /api/v1/dashboard/metrics` |

---

## Screen 2: Ingestion Desk (`/ingest`)

| Step | Action | Expected Observation | Backend Call |
|------|--------|----------------------|--------------|
| 2.1 | Click "Ingestion Desk" tab | Drop zone displays live limits read from backend: "Max 25 MB · PDF, PNG, JPEG, TIFF, EML" | `GET /api/v1/system/info` |
| 2.2 | Try file > 25 MB | Red error banner before upload: "File exceeds limit (25 MB)" | *None (Client-side validation)* |
| 2.3 | Upload clean document (`sample.pdf`) | Progress spinner appears; upload returns 202; result card renders UID, SHA-256, Queue (`live`). | `POST /ingest` (multipart/form-data) |
| 2.4 | Watch live status settling | Status badge starts at `QUEUED`, polls every 2s, transitions to `pending_review` or `auto_accepted`. | `GET /api/v1/documents/{uid}/status` |
| 2.5 | Click "Upload another file" | Form resets to clean drop zone. | *None* |

---

## Screen 3: Duplicate Upload & Linking

| Step | Action | Expected Observation | Backend Call |
|------|--------|----------------------|--------------|
| 3.1 | Upload the exact same file again | Upload accepted; backend SHA-256 deduplicator detects identical hash. | `POST /ingest` |
| 3.2 | Check Duplicate Banner | Yellow alert banner appears: **"Duplicate document detected — linked to {original_uid}"**. | `GET /api/v1/documents/{uid}/status` returns `is_link: true` |
| 3.3 | Verify zero storage waste | Status card highlights "Bitwise digest match — storage linked". | `GET /api/v1/documents/{uid}` |

---

## Screen 4: Review & Triage Queue (`/review`)

| Step | Action | Expected Observation | Backend Call |
|------|--------|----------------------|--------------|
| 4.1 | Click "Review & Triage" tab | Navbar badge shows count of pending items. Table lists all tasks with file name, predicted type, confidence, PII status, and decision reason. | `GET /api/v1/review/queue` |
| 4.2 | Check confidence colors | Green for ≥ 85%, Amber for 70–84%, Red for < 70%. | *Client calculation on API confidence* |
| 4.3 | Check empty state | If no documents pending review, displays "No documents pending review." | `GET /api/v1/review/queue` |
| 4.4 | Click "Review →" | Opens Review Detail screen for that specific UID. | Transitions to Review Detail |

---

## Screen 5: Review Detail (`/review/:uid`)

| Step | Action | Expected Observation | Backend Call |
|------|--------|----------------------|--------------|
| 5.1 | Open document detail | Shows metadata (file name, SHA-256 truncated, retention class, ACL, decision reason). | `GET /review/api/task/{uid}` |
| 5.2 | Verify rule: NO auto-accept | Opening the screen does NOT submit any review decision. Status remains PENDING. | *Zero POST requests made on mount* |
| 5.3 | Inspect Extracted Fields | Key/value table shows extracted fields with individual field confidence percentages. | From task detail |
| 5.4 | Inspect Evidence Text | Scrollable text box shows raw OCR excerpt. | From task detail |
| 5.5 | Correct a field | Select "CORRECT", input corrected type (e.g. `invoice`), enter review notes. Click "Submit Review Decision". | `POST /api/v1/review/{document_uid}/action` |
| 5.6 | Check result | Green banner: "Decision recorded." Returns to Review Queue after 1.5s. | Badge count decrements on queue refresh |
| 5.7 | Re-open same document in Audit | Human-verified badge appears in green on the corrected fields. | `GET /api/v1/documents/{uid}` |

---

## Screen 6: Audit & Search (`/audit`)

| Step | Action | Expected Observation | Backend Call |
|------|--------|----------------------|--------------|
| 6.1 | Click "Audit & Search" tab | Paginated table of all repository documents. Shows total asset count. | `GET /api/v1/documents?page=1&page_size=20` |
| 6.2 | Filter by Type | Dropdown filters table client-side by document class (invoice, contract, etc.). | *Client-side filtering* |
| 6.3 | Filter "Show duplicates only" | Checkbox filters list to show only bitwise deduplicated links (`LINK →` badge). | *Client-side filtering* |
| 6.4 | Click "Audit" on any row | Expands inline Audit Panel below row showing timeline events, classifier model, and OCR engine. | `GET /api/v1/documents/{uid}` |
| 6.5 | Verify Human Verified fields | Any human-corrected fields display a green "Human Verified" badge. | `humanVerifiedFields` in audit detail |

---

## Screen 7: Reprocessing Hub (`/reprocess`)

| Step | Action | Expected Observation | Backend Call |
|------|--------|----------------------|--------------|
| 7.1 | Click "Reprocessing Hub" tab | Warning banner displayed: **"Reprocessing does not overwrite human-verified fields."** | *Static safety guarantee* |
| 7.2 | Check "Run Reprocess" button | Button is **disabled** initially — requires dry-run preview first. | *Safety gate* |
| 7.3 | Click "Preview (dry run)" | Calls dry-run endpoint. Shows preview card: "Would reprocess N documents (queued: 0, skipped: 0)". | `POST /api/v1/reprocess/preview` (`dry_run: true`) |
| 7.4 | Verify Run button state | "Run Reprocess" button is now **enabled**. | *State unlock* |
| 7.5 | Click "Run Reprocess" | Submits live job. Shows teal success banner: "Job started: job-reproc-{id}". | `POST /api/v1/reprocess/preview` (`dry_run: false`) |

---

## Screen 8: Security & Authentication Boundaries

| Test | curl Command | Expected Status |
|------|--------------|-----------------|
| Unauthenticated Config | `curl.exe -i http://127.0.0.1:8000/api/v1/admin/config` | `401 Unauthorized` |
| Reviewer Role on Admin Config | `curl.exe -i -H "X-User-Role: reviewer" http://127.0.0.1:8000/api/v1/admin/config` | `403 Forbidden` |
| Admin Role on Admin Config | `curl.exe -i -H "X-User-Role: admin" http://127.0.0.1:8000/api/v1/admin/config` | `200 OK` |
| Disallowed CORS Origin | `curl.exe -i -X OPTIONS http://127.0.0.1:8000/api/v1/system/info -H "Origin: http://evil.com"` | `400 Bad Request` (No Allow-Origin header) |

---

## Screen 9: Page Images & Authenticated Blob Fetch

| Test | Target | Expected Behavior |
|------|--------|-------------------|
| Direct Unauthenticated Image Fetch | `GET /api/v1/documents/{uid}/pages/1/image` | Returns 200 (Flagged as backend SECURITY BUG in `docs/connection.md`) |
| Frontend Secure Fetch Wrapper | `fetchDocumentPageImageUrl(uid, page)` in `src/api/client.ts` | Attaches Authorization & role header, creates ephemeral Object URL, revokes URL on cleanup |
