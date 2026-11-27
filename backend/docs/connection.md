# Frontend-to-Backend Connection Architecture

## 1. Selected Connection Strategy

**Strategy Selected:** **(a) Browser calls `http://localhost:8000` directly (needs CORS)**

### Rationale
1. **Decoupled Enterprise Architecture**: Mirrors standard decoupled production deployments where frontend SPAs (hosted on port 5173 or CDN/static bucket) query backend API services on port 8000.
2. **CORS Validation**: Ensures all browser requests properly negotiate CORS headers (`Origin: http://localhost:5173`), including preflight `OPTIONS` requests and rejection of disallowed origins (`http://evil.example`).
3. **Route Structure Preservation**: The FastAPI backend routes are defined with top-level prefixes (`/ingest`, `/review`, `/reprocess`, `/health`, `/metrics`, `/audit`). Direct connection prevents proxy rewrite discrepancies across diverse top-level routes.

---

## 2. Component Agreement & Configuration

| Configuration Point | Value | Notes |
| :--- | :--- | :--- |
| **`frontend/.env`** | `VITE_API_BASE_URL=http://localhost:8000` | Normalized, no trailing slash |
| **`src/api/client.ts`** | `BASE_URL = rawBaseUrl.replace(/\/+$/, '')` | Strips any trailing slash to avoid double slashes |
| **`vite.config.ts`** | Proxy table targeting `http://127.0.0.1:8000` | Fallback proxy configuration |
| **`app/api/app.py`** | `CORSMiddleware` with `cors_origins` | Enforces whitelisted origins |
| **`app/core/config.py`** | `CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173` | Configurable environment setting |

---

## 3. Discovered Mismatches & Fixes

1. **Backend CORS Wildcard**: Previously, `app/api/app.py` used `allow_origins=["*"]`, which is incompatible with strict credentialed browser requests and failed security checks against unauthorized origins (`http://evil.example`). Fixed by introducing configurable `CORS_ORIGINS` in `AppSettings` and binding it to `CORSMiddleware`.
2. **Trailing Slash Guard**: Handled in `src/api/client.ts` via regex `.replace(/\/+$/, '')` ensuring clean URL concatenation.
3. **Authentication Mode**: Marked `LOCAL MODE ONLY` for temporary development headers (`X-User-Role`), with `Authorization: Bearer <token>` interceptor in `src/api/client.ts` for bearer tokens.

---

## 4. Authentication Mechanism & Matrix

- **Backend Enforcement**: Evaluates `Authorization: Bearer <token>` primary, with `X-User-Role` accepted as `LOCAL MODE ONLY` fallback for local rapid developer testing.
- **Frontend Interceptor**: Single point in `frontend/src/api/client.ts` attaches `Authorization: Bearer <token>` and `X-User-Role` headers automatically.

| Endpoint | No Credentials | Wrong Role (`viewer`) | Valid Credentials | Required Role |
| :--- | :--- | :--- | :--- | :--- |
| `/api/v1/admin/config` | 401 Unauthorized | 403 Forbidden | 200 OK | `admin` |
| `/api/v1/review/queue` | 401 Unauthorized | 403 Forbidden | 200 OK | `admin`, `reviewer` |

---

## 5. Security Bug Report: Page Image Exposure

- **Endpoint**: `GET /api/v1/documents/{uid}/pages/{n}/image`
- **Observed Behavior**: Returns `HTTP 200 OK` (PNG image bytes) with zero credentials.
- **Severity**: **HIGH (SECURITY BUG)**
- **Risk Assessment**: Document page renders contain sensitive PII (Social Security Numbers, Passport data, clinical records, bank balances). Allowing unauthenticated image access circumvents the Decision Gate and ACL enforcement policies.
- **Backend Remediation Required**: Enforce `check_auth_role` dependency on `/pages/{n}/image` requiring authenticated reviewer or admin session.
- **Frontend Defensive Mitigation**: Implemented `fetchDocumentPageImageUrl` in `src/api/client.ts` which requests images via `fetch` with `Authorization` and role headers, maps the response to a Blob URL, and provides a cleanup hook (`revoke()`) invoked upon component unmount.

