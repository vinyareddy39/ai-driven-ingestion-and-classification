# Frontend & Integration Findings Log

**Environment:** `LOCAL MODE` / `REAL SERVICES`  
**Git Branch:** `frontend/ui`  
**Testing Backend Host:** `http://127.0.0.1:8000`  
**Frontend Host:** `http://localhost:5173`  

---

## 1. Setup & Baseline Audit

- **Node version:** `v25.9.0`
- **TypeScript version:** `5.7.2` (downgraded from `7.0.2` template placeholder to satisfy `openapi-typescript` peer dependency)
- **Git branch:** `frontend/ui` (isolated feature branch, no unrequested merge to main)
- **Build toolchain:** Vite 8.3 + TailwindCSS 3.4 + Vitest 4.1 + Oxlint 1.90
- **Contract generation:** `npm run api:gen` generates `src/api/schema.d.ts` directly from the live OpenAPI schema (`openapi.json`, 30 paths).

---

## 2. Page & Component Inventory

| Screen / Component | File | Backend Endpoints Called | State Handling (Loading, Error, Empty) |
|-------------------|------|--------------------------|----------------------------------------|
| **App Shell** | `src/App.tsx` | `GET /api/v1/dashboard/metrics` (30s interval) | Error banner if metrics fail; active tab state |
| **Navbar** | `src/components/Navbar.tsx` | Metrics passed via props | Shows live queue pill + pending review badge |
| **Pipeline Dashboard** | `src/components/DashboardView.tsx` | `GET /api/v1/dashboard/metrics` | "No classified assets yet", "No documents ingested yet" |
| **Ingestion Desk** | `src/components/UploadDesk.tsx` | `GET /api/v1/system/info`, `POST /ingest`, `GET /api/v1/documents/{uid}/status` | Live polling spinner, size/MIME validation error, duplicate alert |
| **Review Queue** | `src/components/ReviewQueue.tsx` | `GET /api/v1/review/queue` | Spinner, red error banner, "No documents pending review." |
| **Review Detail** | `src/components/ReviewDetail.tsx` | `GET /review/api/task/{uid}`, `POST /api/v1/review/{document_uid}/action` | Spinner, 404 not found, error banner, decision recorded banner. **Never auto-accepts on open.** |
| **Audit & Search** | `src/components/AuditSearch.tsx` | `GET /api/v1/documents`, `GET /api/v1/documents/{uid}` | Skeleton loading, error banner, "No documents found", inline audit timeline |
| **Reprocessing Hub** | `src/components/ReprocessHub.tsx` | `POST /api/v1/reprocess/preview` (`dry_run: true/false`) | Loading spinner, error banner, **Run disabled until dry-run preview completes**, human-verified protection banner |

---

## 3. Static Audit Results

1. **`console.log` occurrences:** 0 found in production code.
2. **`dangerouslySetInnerHTML` occurrences:** 0 found.
3. **`localStorage` / `sessionStorage` occurrences:** 0 found.
4. **Hardcoded URLs:** 0 found. All requests route through `BASE_URL` (configured via `VITE_API_BASE_URL`).
5. **Auto-accept check:** Opening `ReviewDetail` creates zero side-effects. Decisions require explicit button submission.
6. **Reprocess safety check:** Safety banner explicitly reminds users that human-verified fields are protected. No overwrite controls exist.
7. **Zero-handling rule:** Empty repository displays "0 assets" and "No classified assets yet" rather than fabricated placeholders.

---

## 4. End-to-End Live Integration Verification

Live probe evidence gathered using `scripts/connection_check.mjs` against running backend (`PID 27928`):

```
==============================================================
connection_check.mjs  ·  LOCAL MODE
BASE   : http://127.0.0.1:8000
ROLE   : admin
UID    : 21c9c7dd-cf95-4ecb-b20b-686a3923c228
==============================================================

[GET /api/v1/system/info]        STATUS: 200  SHAPE: OK  RESULT: PASS
[GET /api/v1/auth/me]            STATUS: 200  SHAPE: OK  RESULT: PASS
[GET /api/v1/review/queue]       STATUS: 200  SHAPE: OK  RESULT: PASS
[GET /api/v1/documents]          STATUS: 200  SHAPE: OK  RESULT: PASS
[GET /api/v1/documents/{uid}]    STATUS: 200  SHAPE: OK  RESULT: PASS
[GET /api/v1/audit/{uid}]        STATUS: 200  SHAPE: OK  RESULT: PASS
[POST /api/v1/reprocess/preview] STATUS: 200  SHAPE: OK  RESULT: PASS
[GET /api/v1/dashboard/metrics]  STATUS: 200  SHAPE: OK  RESULT: PASS
[GET /api/v1/admin/config]       STATUS: 200  SHAPE: OK  RESULT: PASS
[GET /api/v1/admin/config/history] STATUS: 200 SHAPE: OK RESULT: PASS
==============================================================
TOTAL 10  |  PASS 10  |  FAIL 0
==============================================================
```

### Real Document Ingestion Test Cases
1. **Clean Document (`clean_invoice.pdf`):** Ingested -> UID `21c9c7dd-cf95-4ecb-b20b-686a3923c228` -> Settled at `pending_review` (classified unknown, mandatory human review triggered).
2. **Unknown Document (`unknown_file.pdf`):** Ingested -> UID `57da0485-5acb-44d6-8702-4b0beec7e0b2` -> Settled at `pending_review`.
3. **Duplicate Submission (`clean_invoice.pdf`):** Ingested -> Identical SHA-256 detected -> Linked to existing UID.

---

## 5. Security & Auth Audit

- **Role header vs Bearer token:** Backend supports both `Authorization: Bearer <token>` and `X-User-Role: <role>`. Frontend client dynamically supports both via `client.ts` request interceptor.
- **Access control verification:**
  - `GET /api/v1/admin/config` without credentials -> `401 Unauthorized`
  - `GET /api/v1/admin/config` with `X-User-Role: reviewer` -> `403 Forbidden`
  - `GET /api/v1/admin/config` with `X-User-Role: admin` -> `200 OK`
- **CORS boundary:** Disallowed origin `http://evil.com` receives `400 Bad Request` with no `Access-Control-Allow-Origin` header emitted.
- **Image security finding:** Flagged security bug in `docs/backend-requests.md` regarding unauthenticated page image endpoint; client mitigated via `fetchDocumentPageImageUrl()`.
