# Frontend-to-Backend Fit & Compatibility Report

**Evaluation Date**: 2026-11-19  
**Branch**: `backend/prescriptions` (merged with `origin/main` commit `a890b44`)  
**Backend Mode**: LOCAL MODE / REAL SERVICES compatible  
**Backend Test Suite**: 126/126 tests passing  

---

## 1. Executive Summary

The collaborator's frontend (`frontend/`) from `origin/main` was pulled and cleanly merged into `backend/prescriptions` without pushing or editing any frontend files.
- The backend test suite continues to pass **126/126 tests in 27.53 seconds**.
- The frontend directory structure is populated with modern React 19 + TypeScript + Vite components.
- Running `npm run api:gen` succeeded in **180ms**, generating `src/api/schema.d.ts` from `openapi.json` (54 API paths).
- TypeScript build check (`tsc -b --noEmit`) revealed compilation errors caused by undeclared dependencies in `frontend/package.json` (`react-router-dom`, `@tanstack/react-query`), missing wrapper exports in `client.ts`, and path parameter naming differences.

---

## 2. Screen Inventory & Status

| Screen | Target Requirement | Status in `frontend/` | File Location |
|---|---|---|---|
| **Login / Signup** | Patient & Staff JWT authentication | **MISSING** | No login/signup views built |
| **Upload Desk** | Single/Bulk document ingestion & file dropzone | **EXISTS** | `src/components/UploadDesk.tsx`, `src/pages/UploadPage.tsx` |
| **Batch Results** | Ingestion batch summary & progress | **PARTIAL** | Integrated into UploadDesk; no dedicated multi-batch screen |
| **Documents Explorer** | Filterable document list with compliance status | **EXISTS** | `src/pages/DocumentsListPage.tsx`, `src/components/AuditSearch.tsx` |
| **Review Queue** | Human review queue sorted by risk/confidence | **EXISTS** | `src/components/ReviewQueue.tsx`, `src/pages/ReviewQueuePage.tsx` |
| **Review Detail** | Side-by-side OCR image, field editor & PII toggle | **EXISTS** | `src/components/ReviewDetail.tsx`, `src/pages/ReviewDetailPage.tsx` |
| **Prescription Review** | Patient medication confirmation & amber warnings | **MISSING** | Collaborator has not yet authored prescription review |
| **Medication Timetable** | Adherence slots, dose instructions, disclaimer | **MISSING** | Collaborator has not yet authored timetable view |
| **Admin Config** | Threshold sliders, safety floors, restart history | **EXISTS** | `src/pages/AdminPage.tsx` |
| **Dashboard** | System KPIs, stage latencies, queue metrics | **EXISTS** | `src/components/DashboardView.tsx`, `src/pages/DashboardPage.tsx` |
| **Reprocess Hub** | Dry-run query matches, conflict preservation | **EXISTS** | `src/components/ReprocessHub.tsx`, `src/pages/ReprocessPage.tsx` |

---

## 3. Endpoints Call Matrix & `openapi.json` Alignment

All 54 backend endpoints are implemented in FastAPI. Below is the alignment check for every route referenced in `frontend/src`:

| Frontend API Path | HTTP Method | Status in `openapi.json` | Notes / Discrepancy |
|---|---|---|---|
| `/api/v1/system/info` | GET | **EXISTS** | Matches `SystemInfoResponse` |
| `/api/v1/auth/me` | GET | **EXISTS** | Matches `UserSessionResponse` |
| `/api/v1/review/queue` | GET | **EXISTS** | Matches `ReviewQueueResponse` |
| `/api/v1/review/{document_uid}` | GET | **EXISTS** | Matches `ReviewDetailResponse` |
| `/api/v1/review/{document_uid}/action` | POST | **EXISTS** | Matches `ReviewActionRequest` |
| `/api/v1/documents` | GET | **EXISTS** | Matches `DocumentListResponse` |
| `/api/v1/documents/{document_uid}/status` | GET | **EXISTS** | Matches `DocumentStatusResponse` |
| `/api/v1/documents/{document_uid}/compliance` | GET | **EXISTS** | Matches `DocumentComplianceDetailResponse` |
| `/api/v1/documents/{document_uid}` | GET | **EXISTS** *(Param Mismatch)* | Backend uses `{document_uid}`; `AuditSearch.tsx:148` calls `/api/v1/documents/{uid}` |
| `/api/v1/documents/{document_uid}/audit-trail` | GET | **EXISTS** | Matches `AuditTrailResponse` |
| `/api/v1/documents/{document_uid}/pages/{page_num}/image` | GET | **EXISTS** *(Param Mismatch)* | Backend uses `{document_uid}` & `{page_num}`; `client.ts` uses `{uid}` & `{pageNumber}` |
| `/api/v1/documents/{document_uid}/pii/reveal` | POST | **EXISTS** | Matches `PIIRevealRequest` |
| `/api/v1/reprocess/preview` | POST | **EXISTS** | Matches `ReprocessPreviewRequest` / `ReprocessResponse` |
| `/api/v1/reprocess` | POST | **EXISTS** | Matches `ReprocessExecutionRequest` |
| `/api/v1/dashboard/metrics` | GET | **EXISTS** | Matches `DashboardMetricsResponse` |
| `/api/v1/admin/config` | GET, PUT | **EXISTS** | Matches `AdminConfigResponse` / `AdminConfigUpdateRequest` |
| `/api/v1/admin/config/history` | GET | **EXISTS** | Matches `ConfigHistoryResponse` |
| `/api/v1/ingest` | POST | **EXISTS** | File multipart upload |
| `/api/v1/auth/signup` | POST | **EXISTS** | Ready for collaborator login screen |
| `/api/v1/auth/login` | POST | **EXISTS** | Ready for collaborator login screen |
| `/api/v1/prescriptions` | POST | **EXISTS** | Ready for collaborator prescription upload screen |
| `/api/v1/prescriptions/{id}` | GET | **EXISTS** | Ready for collaborator prescription review screen |
| `/api/v1/prescriptions/{id}/confirm` | POST | **EXISTS** | Ready for collaborator confirmation button |
| `/api/v1/timetable` | GET | **EXISTS** | Ready for collaborator timetable view |
| `/api/v1/timetable/slots/{id}` | PATCH | **EXISTS** | Ready for collaborator dose adherence tracking |

---

## 4. TypeScript Compile Errors (`npx tsc -b --noEmit`)

Running `npx tsc -b --noEmit` produced the following raw diagnostic errors:

```text
src/components/AuditSearch.tsx(148,12): error TS2345: Argument of type '"/api/v1/documents/{uid}"' is not assignable to parameter of type 'PathsWithMethod<paths, "get">'.
src/components/PIIMaskedValue.tsx(3,10): error TS2614: Module '"../api/client"' has no exported member 'getActiveRole'.
src/components/Shell.tsx(2,46): error TS2307: Cannot find module 'react-router-dom' or its corresponding type declarations.
src/components/Shell.tsx(3,26): error TS2307: Cannot find module '@tanstack/react-query' or its corresponding type declarations.
src/components/Shell.tsx(15,10): error TS2614: Module '"../api/client"' has no exported member 'api'.
src/components/Shell.tsx(15,15): error TS2614: Module '"../api/client"' has no exported member 'getActiveRole'.
src/components/Shell.tsx(15,30): error TS2614: Module '"../api/client"' has no exported member 'setActiveRole'.
src/pages/AdminPage.tsx(2,55): error TS2307: Cannot find module '@tanstack/react-query' or its corresponding type declarations.
src/pages/AdminPage.tsx(16,3): error TS2614: Module '"../api/client"' has no exported member 'AdminConfigResponse'.
src/pages/ReviewQueuePage.tsx(2,29): error TS2307: Cannot find module 'react-router-dom' or its corresponding type declarations.
src/pages/ReviewQueuePage.tsx(3,26): error TS2307: Cannot find module '@tanstack/react-query' or its corresponding type declarations.
src/tests/ConfidenceBadge.test.tsx(3,32): error TS2307: Cannot find module '@testing-library/react' or its corresponding type declarations.
```

---

## 5. Collaborator Action Punch-List

In accordance with standing rules (**zero edits under `frontend/`**), the collaborator must execute the following fixes in their own workspace:

1. **Install Missing Dependencies**:
   ```bash
   cd frontend
   npm install react-router-dom @tanstack/react-query
   npm install -D @testing-library/react @testing-library/jest-dom @types/react-router-dom
   ```

2. **Align Client Exports (`frontend/src/api/client.ts`)**:
   Add role helpers and alias exports matching what `Shell.tsx`, `AdminPage.tsx`, and `ReviewDetailPage.tsx` expect:
   ```typescript
   export const api = client;
   export function getActiveRole(): string {
     return localStorage.getItem("ecm_role") || "reviewer";
   }
   export function setActiveRole(role: string): void {
     localStorage.setItem("ecm_role", role);
   }
   ```

3. **Fix Path Parameter Identifiers**:
   - In `AuditSearch.tsx:148`: change `/api/v1/documents/{uid}` to `/api/v1/documents/{document_uid}` with `{ params: { path: { document_uid: uid } } }`.
   - In `client.ts`: update image route string to `/api/v1/documents/${encodeURIComponent(uid)}/pages/${pageNumber}/image`.

4. **Implement Missing Health Screens (Stage 1-5 Frontend Tasks)**:
   - Implement `LoginPage.tsx` / `SignupPage.tsx` using `/api/v1/auth/login` and `/api/v1/auth/signup`.
   - Implement `PrescriptionReviewPage.tsx` using `/api/v1/prescriptions/{id}` and `/api/v1/prescriptions/{id}/confirm`.
   - Implement `TimetablePage.tsx` rendering scheduled dose slots and the mandatory medical disclaimer.
