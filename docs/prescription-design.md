# Patient-Facing Prescription & Medication Timetable Architecture Design

**System:** AI-Assisted Clinical Document Pipeline — Patient Prescription Extension  
**Status:** DESIGN & CONTRACT SPECIFICATION (STAGE 1)  
**Security Tier:** Strict Healthcare Data Residency & Zero-Leakage Privacy  

---

## 1. Architectural Philosophy & Safety Invariants

This subsystem extends the core Enterprise Content Management (ECM) pipeline with an interactive patient workflow:
$$\text{Scan / Photo} \longrightarrow \text{OCR} \longrightarrow \text{Field Extraction} \longrightarrow \text{User Verification} \longrightarrow \text{Timetable Generation}$$

### Non-Negotiable Clinical & Privacy Invariants:
1. **Zero Auto-Acceptance**:
   No timetable slot may ever be synthesized from unconfirmed AI output. Every extracted medication entity (`drug_name`, `strength`, `dose`, `frequency`, `timing`, `duration_days`) requires explicit patient confirmation (`verified_by_user = True`) prior to schedule generation.
2. **Deterministic Schedule Parsing**:
   Medication frequency and timing interpretation must rely strictly on rule-based algorithmic parsing, never speculative LLM generation. Ambiguous instructions trigger a `NEEDS_CLARIFICATION` state rather than guessing.
3. **Residency Restriction**:
   Prescriptions and extracted drug entities are classified as protected health information (PHI) and must never be transmitted across third-party hosted LLM endpoints. All inference runs strictly within the local security boundary.
4. **Non-Medical Advice Disclaimer**:
   Every timetable query returns a mandatory regulatory disclaimer: *This schedule is an AI-assisted adherence reference for personal use and does not constitute medical advice. Never alter dosages or treatment regimens without consulting your licensed physician.*
5. **Masking & Log Hygiene**:
   Patient identifiers, prescription document text, and drug names tied to individuals are excluded from URLs, application logging, and unauthenticated error traces.

---

## 2. Component Reuse vs. New Extensions

| Component | Architecture Strategy | Implementation / Location |
|---|---|---|
| **OCR Engine** | **REUSED** | UB-Mannheim Tesseract `v5.4.0` via `HybridPyMuPDF-Tesseract v2.4.0` (`app/adapters/ocr.py`). Preserves paragraph and line geometry. |
| **Presidio PII Tagging** | **REUSED** | `PresidioPIIDetector` (`app/adapters/pii.py`) detecting doctor/patient names, phone numbers, and National IDs. |
| **Decision Gate & Audit** | **REUSED** | `stage_decision_gate` and `stage_audit_record` (`app/workers/stages.py`) logging lifecycle transitions to `audit_events`. |
| **Model Version Tracking**| **REUSED** | Retains model and OCR versions in `prescriptions.model_version` and `prescriptions.ocr_engine`. |
| **Review & Corrections** | **REUSED** | Review state transition pattern and training data JSONL export (`app/api/routes_review.py`). |
| **User Authentication** | **NEW** | User registration, login, bcrypt/argon2 hashing, and JWT tokens (`app/api/routes_auth.py`, `users` table). |
| **Per-User Isolation** | **NEW** | Strict ownership filtering on every SQL query (`user_id = current_user.id`). User B receives 404 for User A assets. |
| **Medication Extractor** | **NEW** | Domain extractor parsing `drug_name`, `strength`, `dose`, `frequency`, `timing`, `duration_days` (`app/workers/medication_extractor.py`). |
| **Timetable Generator** | **NEW** | Deterministic calendar slot projection mapping medical frequencies (OD, BD, TDS, QID, HS) to timestamps (`app/workers/timetable.py`). |
| **Reminders Engine** | **NEW** | Scheduled dispatch records with pluggable notification adapters (`app/workers/reminders.py`, `reminders` table). |

---

## 3. Portable Database Schema (SQLAlchemy / Alembic)

All models are authored without SQLite-specific syntax to guarantee identical migration on PostgreSQL.

### Entity-Relationship Architecture:
```
 users (1) <────── (N) prescriptions (1) <────── (N) extracted_items (1)
   │                           │                                │
   │                           │                                │
   └──────────────── (N) timetable_slots (1) <──────────────────┘
                               │
                               └───────── (N) reminders
```

### Table Definitions:

#### 1. `users`
- `id`: VARCHAR(36) PRIMARY KEY
- `email`: VARCHAR(255) UNIQUE NOT NULL (Indexed)
- `password_hash`: VARCHAR(255) NOT NULL
- `role`: VARCHAR(32) NOT NULL DEFAULT 'patient'
- `created_at`: DATETIME DEFAULT UTC
- `disabled`: BOOLEAN NOT NULL DEFAULT FALSE

#### 2. `prescriptions`
- `id`: VARCHAR(36) PRIMARY KEY
- `user_id`: VARCHAR(36) FOREIGN KEY $\rightarrow$ `users.id` (Indexed)
- `file_key`: VARCHAR(255) NOT NULL (Indexed)
- `status`: VARCHAR(32) NOT NULL DEFAULT 'QUEUED' (Indexed)
  - Values: `QUEUED`, `PROCESSING`, `NEEDS_REVIEW`, `CONFIRMED`, `FAILED`
- `model_version`: VARCHAR(50) DEFAULT 'v1.0'
- `ocr_engine`: VARCHAR(50) DEFAULT 'HybridPyMuPDF-Tesseract'
- `pii_detected`: BOOLEAN NOT NULL DEFAULT FALSE
- `created_at`: DATETIME DEFAULT UTC

#### 3. `extracted_items`
- `id`: VARCHAR(36) PRIMARY KEY
- `prescription_id`: VARCHAR(36) FOREIGN KEY $\rightarrow$ `prescriptions.id` (Indexed)
- `raw_text`: TEXT (Source text snippet extracted from OCR)
- `drug_name`: VARCHAR(255) NOT NULL
- `strength`: VARCHAR(100) DEFAULT '' (e.g., '500mg', '10mg/5ml')
- `dose`: VARCHAR(100) DEFAULT '' (e.g., '1 tablet', '2 puffs')
- `frequency`: VARCHAR(100) DEFAULT '' (e.g., 'TDS', 'twice daily')
- `timing`: VARCHAR(100) DEFAULT '' (e.g., 'after_meals', 'before_bed')
- `duration_days`: INTEGER NULL (e.g., 7, 14, 30)
- `schedule_rule`: VARCHAR(255) DEFAULT '' (Normalized scheduling expression)
- `confidence_json`: TEXT DEFAULT '{}' (Per-field confidence scores)
- `verified_by_user`: BOOLEAN NOT NULL DEFAULT FALSE (Indexed)
- `verified_at`: DATETIME NULL

#### 4. `timetable_slots`
- `id`: VARCHAR(36) PRIMARY KEY
- `user_id`: VARCHAR(36) FOREIGN KEY $\rightarrow$ `users.id` (Indexed)
- `prescription_id`: VARCHAR(36) FOREIGN KEY $\rightarrow$ `prescriptions.id` (Indexed)
- `extracted_item_id`: VARCHAR(36) FOREIGN KEY $\rightarrow$ `extracted_items.id` (Indexed)
- `scheduled_at`: DATETIME NOT NULL (Indexed)
- `instruction`: VARCHAR(255) DEFAULT '' (e.g., 'Take 1 tablet after breakfast')
- `status`: VARCHAR(32) NOT NULL DEFAULT 'pending' (Indexed)
  - Values: `pending`, `taken`, `skipped`
- `status_changed_at`: DATETIME NULL

#### 5. `reminders`
- `id`: VARCHAR(36) PRIMARY KEY
- `slot_id`: VARCHAR(36) FOREIGN KEY $\rightarrow$ `timetable_slots.id` (Indexed)
- `channel`: VARCHAR(32) NOT NULL DEFAULT 'email' (e.g., 'email', 'sms', 'push')
- `send_at`: DATETIME NOT NULL (Indexed)
- `sent_at`: DATETIME NULL

---

## 4. Prescription State Machine

```
   [ Upload Image ]
          │
          ▼
       QUEUED  ────────► (Background Task Picks Up Job)
          │
          ▼
      PROCESSING ──────► (Tesseract OCR + Field Extraction + PII Tagging)
          │
          ▼
     NEEDS_REVIEW ◄────► (User Confirms / Corrects Every Extracted Item)
          │
          ├───────────────────────────────┐
          │ (All Items Verified)          │ (Unparseable / Corrupt Image)
          ▼                               ▼
      CONFIRMED                        FAILED
          │
          ▼
   [ Generate Slots in timetable_slots ]
```

---

## 5. API Route Specification

| HTTP Method | Route | Auth / Role | Description |
|---|---|---|---|
| `POST` | `/api/v1/auth/signup` | Public | Register new patient account |
| `POST` | `/api/v1/auth/login` | Public | Authenticate user; returns access and refresh JWTs |
| `POST` | `/api/v1/auth/refresh` | Public | Issue new access token using valid refresh token |
| `POST` | `/api/v1/auth/logout` | Authenticated | Revoke refresh token and terminate active session |
| `GET` | `/api/v1/auth/me` | Authenticated | Return authenticated profile & role permissions |
| `POST` | `/api/v1/prescriptions` | Patient / User | Multipart upload; saves raw file to storage key, enqueues job, returns `job_id` |
| `GET` | `/api/v1/prescriptions/{id}/status` | Owner Only | Poll job processing status (`QUEUED`, `PROCESSING`, `NEEDS_REVIEW`, `FAILED`) |
| `GET` | `/api/v1/prescriptions/{id}` | Owner Only | Fetch full prescription payload with extracted items, confidences, and review flags |
| `GET` | `/api/v1/prescriptions/{id}/image` | Owner Only | Render authenticated prescription image with `?page=` and `?width=` scaling |
| `PATCH` | `/api/v1/prescriptions/{id}/items/{item_id}` | Owner Only | Patient updates/corrects extracted fields (`verified_by_user = True`) |
| `POST` | `/api/v1/prescriptions/{id}/confirm` | Owner Only | Transition to `CONFIRMED` and generate timetable slots (Rejects with 409 if any item is unverified) |
| `GET` | `/api/v1/timetable` | Owner Only | Query patient's timetable slots filtered by `?from=` and `?to=` date window |
| `PATCH` | `/api/v1/timetable/slots/{id}` | Owner Only | Mark slot as `taken`, `skipped`, or `pending` |
| `GET` | `/api/v1/reminders/preferences` | Owner Only | Get reminder channel preferences |
| `PUT` | `/api/v1/reminders/preferences` | Owner Only | Update reminder channel, advance notice minutes, and toggle enable/disable |
