# Backend Change Requests for Collaborator

This document tracks backend API requests and security improvements identified during frontend development and end-to-end integration.

---

## 1. Security Bug: Authenticate Document Page Images

- **Endpoint:** `GET /api/v1/documents/{uid}/pages/{page_number}/image`
- **Current Behavior:** Returns `200 OK` (PNG image) even when no `Authorization` header or `X-User-Role` is provided.
- **Risk:** Document pages may contain PII (Personally Identifiable Information) or proprietary corporate data. Unauthenticated direct URL access allows unauthorized viewing.
- **Requested Change:** Add `Depends(check_auth_role(["reviewer", "admin"]))` or `get_current_user` to the endpoint handler in `app/api/routes_v1.py`.
- **Frontend Mitigation:** The frontend currently wraps image fetches in `fetchDocumentPageImageUrl()` (`src/api/client.ts`), which automatically attaches the active role/token header and creates an ephemeral `blob:` URL that is revoked on unmount.

---

## 2. API v1 Review Detail Endpoint Alias

- **Endpoint:** `GET /api/v1/review/{uid}`
- **Current Workaround:** The frontend fetches `/review/api/task/{uid}` via raw `fetch` because the endpoint was mounted under the legacy `/review` router rather than `/api/v1/`.
- **Requested Change:** Add an endpoint alias in `/api/v1/`:
  - **Method:** `GET`
  - **Path:** `/api/v1/review/{uid}`
  - **Auth:** Requires role `reviewer` or `admin`
  - **Response Shape:** `ReviewTaskDetail` (matching existing `/review/api/task/{uid}`)

---

## 3. Explicit Response Model for Review Action

- **Endpoint:** `POST /api/v1/review/{document_uid}/action`
- **Current Behavior:** OpenAPI schema lists response as generic `{}`.
- **Requested Change:** Define a concrete Pydantic response model, e.g.:
```python
class ReviewActionResponse(BaseModel):
    document_uid: str
    action: str
    review_status: str
    reviewer_id: str
    updated_at: str
```
- **Benefit:** Allows `openapi-typescript` to generate strictly-typed response handlers in `schema.d.ts`.
