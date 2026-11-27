# Complete ECM Pipeline & Prescription Flow: Frontend API Contract (v1.0.0)

This document specifies the exact REST API contract implemented by the FastAPI backend for the React frontend owned by the collaborator.

---

## 1. Global Standards & Infrastructure

### 1.1 Base URL
- Local Development: `http://localhost:8000`
- Production (Render): `https://<render-service-slug>.onrender.com`
- Primary API Prefix: `/api/v1`

### 1.2 Authentication & Authorization Headers
All secured endpoints require an RFC 7519 signed JWT or role token passed in the standard HTTP header:
```http
Authorization: Bearer <access_token>
```
- **Error Response for Missing Token**: `401 Unauthorized` with header `WWW-Authenticate: Bearer`
```json
{
  "detail": "Authentication credentials were not provided. Include 'Authorization: Bearer <token>'."
}
```
- **Error Response for Expired/Invalid Token**: `401 Unauthorized`
```json
{
  "detail": "Invalid or expired authentication token."
}
```
- **Error Response for Role Permission Mismatch**: `403 Forbidden`
```json
{
  "detail": "Access denied for role 'patient'. Required roles: ['admin', 'reviewer', 'compliance']"
}
```

### 1.3 CORS Policy
- Allowed Methods: `GET`, `POST`, `PUT`, `DELETE`, `OPTIONS`
- Allowed Headers: `Content-Type`, `Authorization`, `X-User-Role`, `X-Requested-With`
- Preflight `OPTIONS` responses return `200 OK` with `Access-Control-Allow-Origin: <origin>` and `Access-Control-Allow-Credentials: true`.

---

## 2. Screen & Workflow Endpoint Catalog

### Screen 1: App Shell & Health Check
*Used on initial page load by all clients to detect server operational mode and display version badges.*

#### `GET /api/v1/system/info`
- **Auth**: Authenticated (`patient`, `reviewer`, `compliance`, `admin`)
- **Response 200 OK**:
```json
{
  "mode": "LOCAL MODE",
  "version": "1.0.0",
  "max_upload_mb": 10,
  "allowed_file_types": [
    "image/jpeg",
    "image/png",
    "image/jpg",
    "application/pdf"
  ],
  "timestamp": "2026-11-19T09:15:00.000000Z"
}
```

---

### Screen 2: Patient & Staff Authentication (`/login`, `/register`)

#### `POST /api/v1/auth/register`
- **Auth**: Public
- **Request Body**:
```json
{
  "email": "patient@ecm.local",
  "password": "SecurePassword123!",
  "full_name": "Jane Doe",
  "role": "patient"
}
```
- **Response 201 Created**:
```json
{
  "user_id": "usr-8a9b7c6d5e4f",
  "email": "patient@ecm.local",
  "role": "patient",
  "message": "User registered successfully."
}
```

#### `POST /api/v1/auth/login`
- **Auth**: Public (Rate-limited: 5 failed attempts per IP/minute)
- **Request Body**:
```json
{
  "email": "patient@ecm.local",
  "password": "SecurePassword123!"
}
```
- **Response 200 OK**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "user_id": "usr-8a9b7c6d5e4f",
    "username": "patient@ecm.local",
    "role": "patient",
    "permissions": ["patient:read", "patient:write", "prescriptions:read", "prescriptions:write"]
  }
}
```

#### `GET /api/v1/auth/me`
- **Auth**: Bearer token
- **Response 200 OK**:
```json
{
  "user_id": "usr-8a9b7c6d5e4f",
  "username": "patient@ecm.local",
  "role": "patient",
  "permissions": ["patient:read", "patient:write", "prescriptions:read", "prescriptions:write"]
}
```

---

### Screen 3: Document Upload & Batch Ingestion (`/upload`)

#### `POST /api/v1/ingest`
- **Auth**: Bearer token (`patient`, `reviewer`, `admin`)
- **Content-Type**: `multipart/form-data`
- **Form Data**:
  - `file`: binary file (PDF, PNG, JPG)
  - `batch_id`: optional string (UUID/batch identifier)
- **Response 200 OK**:
```json
{
  "uid": "doc-a1b2c3d4e5f6",
  "file_name": "invoice_acme.pdf",
  "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "status": "QUEUED",
  "batch_id": "batch-2026-001",
  "created_at": "2026-11-19T09:15:00.000000Z"
}
```

---

### Screen 4: Batch Progress & Aggregated Results (`/batches/:batchId`)

#### `GET /api/v1/batches/{batch_id}`
- **Auth**: Bearer token (Owner of batch or Staff: `admin`, `reviewer`, `compliance`)
- **Response 200 OK**:
```json
{
  "batch_id": "batch-2026-001",
  "user_id": "usr-8a9b7c6d5e4f",
  "progress": {
    "total": 10,
    "queued": 0,
    "processing": 1,
    "done": 7,
    "needs_review": 1,
    "failed": 0,
    "quarantined": 1,
    "duplicate": 0
  },
  "counts_by_type": {
    "invoice": 5,
    "receipt": 3,
    "medical_report": 1,
    "unknown": 1
  },
  "items": [
    {
      "uid": "doc-a1b2c3d4e5f6",
      "file_name": "invoice_acme.pdf",
      "doc_type": "invoice",
      "review_status": "auto_accepted",
      "confidence": 0.96,
      "error_detail": null,
      "created_at": "2026-11-19T09:15:00.000000Z"
    },
    {
      "uid": "doc-f6e5d4c3b2a1",
      "file_name": "malware_test.exe",
      "doc_type": "unknown",
      "review_status": "quarantined",
      "confidence": 0.0,
      "error_detail": "Antivirus threat detected: EICAR",
      "created_at": "2026-11-19T09:15:05.000000Z"
    }
  ]
}
```
- **Error 404 Not Found**: If batch does not exist or belongs to another non-staff user.

---

### Screen 5: Document Browser & Status Inspection (`/documents`)

#### `GET /api/v1/documents`
- **Auth**: Bearer token (`admin`, `reviewer`, `compliance`)
- **Query Parameters**:
  - `page`: int (default 1)
  - `page_size`: int (default 20, max 100)
  - `q`: optional search query
  - `doc_type`: optional filter (`invoice`, `receipt`, `medical_report`, etc.)
  - `review_status`: optional filter (`pending_review`, `auto_accepted`, `approved`, `rejected`)
- **Response 200 OK**:
```json
{
  "items": [
    {
      "uid": "doc-a1b2c3d4e5f6",
      "file_name": "invoice_acme.pdf",
      "file_size": 24500,
      "mime_type": "application/pdf",
      "doc_type": "invoice",
      "confidence": 0.96,
      "review_status": "auto_accepted",
      "pii_detected": false,
      "pii_types": [],
      "classifier_version": "v1.0",
      "is_link": false,
      "linked_to_uid": null,
      "quarantine_reason": null,
      "created_at": "2026-11-19T09:15:00.000000Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

#### `GET /api/v1/documents/{uid}/pages/{page}/image`
- **Auth**: Bearer token (`admin`, `reviewer`, `compliance`)
- **Query Parameters**: `thumbnail` (bool), `width` (int)
- **Response 200 OK**: Binary PNG image payload (`Content-Type: image/png`).
- **Error 401 Unauthorized**: No token provided.

---

### Screen 6: Human Review Queue & Correction Studio (`/review`)

#### `GET /api/v1/review/queue`
- **Auth**: Staff (`reviewer`, `compliance`, `admin`)
- **Response 200 OK**:
```json
{
  "tasks": [
    {
      "task_id": "task-7890abcdef",
      "document_uid": "doc-a1b2c3d4e5f6",
      "file_name": "kyc_alice_smith.pdf",
      "predicted_type": "kyc_form",
      "confidence": 0.74,
      "confidence_threshold": 0.95,
      "decision_reason": "Low classification confidence 0.74 < 0.95",
      "pii_detected": true,
      "pii_types": ["PERSON", "PASSPORT"],
      "created_at": "2026-11-19T09:15:00.000000Z"
    }
  ],
  "total_pending": 1
}
```

#### `POST /api/v1/review/{document_uid}/action`
- **Auth**: Staff (`reviewer`, `admin`)
- **Request Body**:
```json
{
  "action": "CONFIRM",
  "reviewer_id": "usr-staff-reviewer",
  "corrected_doc_type": null,
  "human_verified_fields": {
    "full_name": "Alice Verified Smith",
    "id_number": "A1234567"
  },
  "review_notes": "Identity confirmed against government passport register."
}
```
- **Response 200 OK**:
```json
{
  "success": true,
  "document_uid": "doc-a1b2c3d4e5f6",
  "review_status": "approved",
  "doc_type": "kyc_form",
  "message": "Human review action 'CONFIRM' recorded successfully.",
  "updated_at": "2026-11-19T09:18:00.000000Z"
}
```

---

### Screen 7: Patient Prescription & Timetable Studio (`/prescriptions`)

#### `POST /api/v1/prescriptions`
- **Auth**: Bearer token (`patient`, `reviewer`, `admin`)
- **Content-Type**: `multipart/form-data`
- **Form Data**: `file` (image or PDF scan of prescription)
- **Response 201 Created**:
```json
{
  "prescription_id": "rx-3f4e5d6c7b8a",
  "patient_id": "usr-8a9b7c6d5e4f",
  "status": "extracted",
  "image_url": "/api/v1/prescriptions/rx-3f4e5d6c7b8a/image",
  "items": [
    {
      "id": "item-01",
      "drug_name": "Amoxicillin",
      "strength": "500mg",
      "dose": "1 capsule",
      "frequency": "three times daily",
      "timing": "with meals",
      "duration_days": 7,
      "schedule_rule": "three times daily with meals for 7 days",
      "verified_by_user": false,
      "confidence": {
        "drug_name": 0.95,
        "strength": 0.94,
        "dose": 0.92,
        "frequency": 0.91,
        "timing": 0.88,
        "duration_days": 0.90
      }
    }
  ],
  "disclaimer": "Safety notice: Every medication item must be confirmed or corrected by the patient before scheduled doses can be generated."
}
```

#### `POST /api/v1/prescriptions/{prescription_id}/items/{item_id}/confirm`
- **Auth**: Owner of prescription (`patient`) or Staff
- **Request Body**:
```json
{
  "drug_name": "Amoxicillin",
  "strength": "500mg",
  "dose": "1 capsule",
  "frequency": "three times daily",
  "timing": "with meals",
  "duration_days": 7,
  "schedule_rule": "three times daily with meals for 7 days"
}
```
- **Response 200 OK**:
```json
{
  "success": true,
  "item_id": "item-01",
  "verified_by_user": true,
  "verified_at": "2026-11-19T09:20:00.000000Z"
}
```

#### `GET /api/v1/prescriptions/{prescription_id}/timetable`
- **Auth**: Owner (`patient`) or Staff
- **Invariant**: If any medication item is NOT verified by user, returns `409 Conflict`!
- **Response 200 OK**:
```json
{
  "prescription_id": "rx-3f4e5d6c7b8a",
  "generated_at": "2026-11-19T09:21:00.000000Z",
  "disclaimer": "This timetable was generated from user-confirmed prescription fields. Consult your physician or pharmacist with any dosage questions.",
  "slots": [
    {
      "slot_id": "slot-101",
      "drug_name": "Amoxicillin",
      "dose": "1 capsule",
      "scheduled_at": "2026-11-19T08:00:00Z",
      "instruction": "Take 1 capsule with breakfast",
      "status": "pending"
    },
    {
      "slot_id": "slot-102",
      "drug_name": "Amoxicillin",
      "dose": "1 capsule",
      "scheduled_at": "2026-11-19T13:00:00Z",
      "instruction": "Take 1 capsule with lunch",
      "status": "pending"
    },
    {
      "slot_id": "slot-103",
      "drug_name": "Amoxicillin",
      "dose": "1 capsule",
      "scheduled_at": "2026-11-19T19:00:00Z",
      "instruction": "Take 1 capsule with dinner",
      "status": "pending"
    }
  ]
}
```

#### `POST /api/v1/prescriptions/slots/{slot_id}/status`
- **Auth**: Owner (`patient`)
- **Request Body**:
```json
{
  "status": "taken"
}
```
- **Response 200 OK**:
```json
{
  "slot_id": "slot-101",
  "status": "taken",
  "status_changed_at": "2026-11-19T08:05:00.000000Z"
}
```
