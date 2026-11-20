# Frontend Specification & Screen Implementation Guide: Patient Prescription Flow

**Audience:** Collaborator / Frontend Engineering Team  
**Technology Stack:** React 18, Vite, TypeScript, Tailwind CSS, TanStack React Query  
**Backend API Contract:** Documented in `openapi.json` and `docs/prescription-design.md`  

---

## 1. Global Authentication & Session Handling

### Architecture & Guidelines:
- Store the access JWT in memory / `localStorage` under key `ecm_patient_token`.
- Supply header `Authorization: Bearer <token>` on all `/api/v1/prescriptions/*`, `/api/v1/timetable/*`, and `/api/v1/reminders/*` requests.
- When an API response returns `401 Unauthorized`, trigger refresh using `POST /api/v1/auth/refresh`. If refresh fails, clear tokens and redirect to `/login`.
- For image rendering, use `<AuthenticatedImage>` component (fetching through `blob:` URL with auth headers) rather than raw `<img src="/api/v1/...">`.

---

## 2. Screen 1: Authentication (Login & Signup)

### UI Layout & Interactions:
- Tabbed interface toggling between **Sign In** and **Create Account**.
- Email and password inputs with client-side regex format checking and minimum 8-character length.
- Remember me toggle storing refresh token.

### API Endpoints Called:
1. `POST /api/v1/auth/signup`
   - Body: `{"email": "...", "password": "...", "role": "patient"}`
   - Success: `201 Created` $\rightarrow$ auto-login or redirect to sign-in.
2. `POST /api/v1/auth/login`
   - Body: `{"email": "...", "password": "..."}`
   - Success: `200 OK` $\rightarrow$ save `access_token` and `refresh_token`, redirect to `/prescriptions/upload`.
3. `GET /api/v1/auth/me`
   - Header: `Authorization: Bearer <access_token>`
   - Success: `200 OK` $\rightarrow$ store user profile in state.

### States to Handle:
- **Idle / Pristine**: Clean form inputs.
- **Loading**: Disable buttons; show spinner on submit.
- **Validation Error**: Inline red helper text under email/password.
- **Authentication Error (401)**: Generic alert message: *"Invalid email or password. Please try again."* (Never leak whether the email exists).
- **Network Failure**: Toast notification indicating server is unreachable.

---

## 3. Screen 2: Prescription Capture & Upload

### UI Layout & Interactions:
- Drag-and-drop file upload target supporting `.pdf`, `.png`, `.jpg`, `.jpeg`.
- **Camera Capture Button** for mobile/tablet browsers triggering `<input type="file" accept="image/*" capture="environment">`.
- Image preview card showing thumbnail, file size, and remove button.
- Upload progress bar (0% $\rightarrow$ 100%) tracking `onUploadProgress`.
- Post-upload polling state displaying animated badge: *"Extracting medications with OCR..."*

### API Endpoints Called:
1. `POST /api/v1/prescriptions`
   - Request: `multipart/form-data` with key `file`.
   - Response: `202 Accepted` returning `{"job_id": "...", "prescription_id": "rx-..."}`.
2. `GET /api/v1/prescriptions/{prescription_id}/status`
   - Polling interval: Every 2.5 seconds using TanStack React Query (`refetchInterval: 2500`).
   - Terminal status: When `status === "NEEDS_REVIEW"`, navigate to `/prescriptions/{id}/review`. When `status === "FAILED"`, show error.

### States to Handle:
- **Empty / Ready**: Centered upload card with upload icon and camera button.
- **File Selected**: Preview thumbnail with clear button.
- **Uploading**: Linear progress indicator with percentage.
- **Processing (QUEUED / PROCESSING)**: Pulsing progress skeleton with message: *"Reading prescription text and identifying medications..."*
- **Error (422 / 500)**: Alert card with retry button.

---

## 4. Screen 3: Interactive Prescription Verification & Review

### UI Layout & Interactions:
- **Two-Column Split Layout**:
  - **Left Column (50% Desktop)**: Interactive Document Image Viewer powered by `AuthenticatedImage` component. Supports zoom controls (`+`, `-`, reset) and page pagination for multi-page prescriptions.
  - **Right Column (50% Desktop)**: Medication Items List.
- **Medication Item Card**:
  - Displays `drug_name`, `strength`, `dose`, `frequency`, `timing`, and `duration_days`.
  - **Low-Confidence Visual Indicators**: Amber border and warning badge (`⚠️ Review Needed`) on any field with confidence `< 0.85`.
  - Inline input editing: Each field is directly editable by the patient.
  - **"Verify This Item" Toggle**: Checkbox or button turning green (`✓ Confirmed`) when patient confirms accuracy.
- **Bottom Action Bar**:
  - Sticky footer with **"Confirm Medication Schedule"** button.
  - Button is disabled until **every item has been verified by the user**. Displays tooltip: *"Please verify all extracted medications to generate your timetable."*

### API Endpoints Called:
1. `GET /api/v1/prescriptions/{prescription_id}`
   - Response: Extracted items list, field confidences, model version, and verification flags.
2. `GET /api/v1/prescriptions/{prescription_id}/image?page=1&width=800`
   - Renders authenticated document scan.
3. `PATCH /api/v1/prescriptions/{prescription_id}/items/{item_id}`
   - Body: `{"drug_name": "...", "strength": "...", "dose": "...", "frequency": "...", "timing": "...", "duration_days": 7, "verified_by_user": true}`
   - Triggered when patient edits a field or clicks "Verify Item".
4. `POST /api/v1/prescriptions/{prescription_id}/confirm`
   - Called upon clicking "Confirm Medication Schedule".
   - Success: `200 OK` $\rightarrow$ redirects to `/timetable`.
   - Error `409 Conflict`: Displays toast: *"All items must be confirmed before timetable generation."*

### States to Handle:
- **Loading**: Split skeleton showing image placeholder and field form placeholders.
- **Needs Review**: Active interactive state with editable fields and amber highlights.
- **All Verified**: Sticky footer button turns vibrant green with confirmation modal.
- **Conflict (409)**: Banner alert highlighting unverified items.
- **Unauthorized (401/403/404)**: Redirect to 404 *"Prescription not found or access denied."*

---

## 5. Screen 4: Medication Timetable & Adherence Tracker

### UI Layout & Interactions:
- **Date Selector / Header**: Daily view with previous/next day arrows and quick-select date strip.
- **Time Block Sections**: Slots automatically grouped into four standard daily buckets:
  1. 🌅 **Morning** (06:00 – 11:59)
  2. ☀️ **Afternoon** (12:00 – 16:59)
  3. 🌆 **Evening** (17:00 – 21:59)
  4. 🌙 **Night / Bedtime** (22:00 – 05:59)
- **Slot Card Elements**:
  - Medication name and strength in bold (e.g., **Amoxicillin 500mg**).
  - Specific intake instruction (e.g., *"Take 1 capsule after breakfast"*).
  - Exact scheduled time pill (e.g., `08:00 AM`).
  - **Adherence Action Buttons**:
    - `[✓ Taken]`: Turns card green; records timestamp.
    - `[⊘ Skip]`: Turns card muted gray; records skipped status.
    - `[Undo]`: Reverts status back to `pending`.
- **Mandatory Medical Disclaimer Banner**:
  - Persistent alert at the bottom of the screen rendering the backend `disclaimer` field.

### API Endpoints Called:
1. `GET /api/v1/timetable?from={start_iso}&to={end_iso}`
   - Fetches scheduled dose slots for selected date range.
2. `PATCH /api/v1/timetable/slots/{slot_id}`
   - Body: `{"status": "taken"}` (or `"skipped"`, `"pending"`).
   - Optimistic UI update: Toggle state locally immediately, revert on network error.
3. `GET /api/v1/reminders/preferences` & `PUT /api/v1/reminders/preferences`
   - Quick settings drawer allowing patient to configure reminder channel (`email`, `sms`, `push`) and advance notice window (e.g. 15 minutes before dose).

### States to Handle:
- **Loading**: Grouped card skeletons for each time block.
- **Empty State**: Friendly graphic with text: *"No medications scheduled for this day."*
- **Active Timetable**: Cards grouped by time block with status badges.
- **Optimistic Error**: Toast *"Failed to update dose status. Reverting..."*

---

## 6. Screen 5: Multi-File Ingestion Desk & Segregated Batch Results (`/batches/:batchId`)

### UI Layout & Interactions:
- **Multi-File Selection & Dropzone**:
  - Native file input configured with `multiple` attribute (`<input type="file" multiple ... />`).
  - Drag-and-drop zone accepts `FileList` containing multiple files simultaneously.
  - Per-file dynamic validation against `MAX_UPLOAD_MB` / `max_upload_size_bytes` fetched from `GET /api/v1/system/info`.
  - Shows clear per-file error badges (e.g. *"File is 230 MB. Maximum allowed is 200 MB."*) while preserving valid files in the queue.
- **Batch Upload & Progress Tracking**:
  - Generates a unique `batch_id` per session.
  - Dispatches each valid file concurrently via `POST /ingest?batch_id={batch_id}` with Bearer token authentication.
  - Real-time per-file progress list with percentage bars, byte counters, and upload indicators.
- **Segregated Results View (Grouped by Document Type)**:
  - Transition immediately to `/batches/:batchId` upon upload completion.
  - Real-time polling (`GET /api/v1/batches/{batch_id}`) every 2 seconds while `progress.queued > 0` or `progress.processing > 0`.
  - **Category Segregation Accordions / Tabs**:
    - Group files under 9 standard document type categories:
      `invoice`, `receipt`, `bank_statement`, `medical_report`, `kyc_form`, `contract`, `claim_form`, `prescription`, and `unknown`.
    - Display file count badge per category tab (e.g., `Invoices (10)`, `Bank Statements (10)`).
    - Status pills on each file row: `Auto-Accepted` (green), `Needs Review` (amber), `Quarantined` (rose), `Duplicate Linked` (blue).
    - Confidence metric bar (e.g., `96.4%`) with review reason badge (`"High-risk class below threshold 0.95"`).
  - **Review-Needed Quick Filter**:
    - Dedicated tab / toggle to isolate all documents in the batch requiring human attention (`review_status === "pending_review"`).
  - **Split File Detail Drawer**:
    - Clicking any document in the list opens a slide-over modal rendering authenticated preview (`GET /api/v1/documents/{uid}/pages/1/image`) beside extracted fields and confidence scores.

### API Endpoints Called:
1. `GET /api/v1/system/info`
   - Dynamically loads `max_upload_size_bytes` (`MAX_UPLOAD_MB`) and allowed extensions/MIME types.
2. `POST /ingest?batch_id={batch_id}`
   - Request: `multipart/form-data` with `file` and query param `batch_id`.
   - Header: `Authorization: Bearer <token>`
   - Response: `202 Accepted` returning `{"uid": "...", "batch_id": "...", "status": "QUEUED"}`.
3. `GET /api/v1/batches/{batch_id}`
   - Header: `Authorization: Bearer <access_token>`
   - Success: `200 OK` $\rightarrow$ Returns `BatchDetailResponse` with `progress`, `counts_by_type`, and `items` (including `confidence`, `doc_type`, `review_status`, and `review_reason`).
   - Polling: Polls every 2 seconds until `progress.queued == 0 && progress.processing == 0`.
   - Error: `404 Not Found` $\rightarrow$ Displays *"Batch not found or unauthorized"*.

### States to Handle:
- **Loading / Initializing**: Skeleton loader with 6 progress cards and batch header.
- **In-Progress (Queued / Processing)**: Animated pulse bar tracking completion `(done + needs_review + quarantined) / total * 100%`.
- **Completed**: Segregated category tabs populated with count badges and files.
- **Empty Batch**: Graphic with message *"No documents found in this batch"*.
- **Error / Fetch Failure**: Dismissible banner with retry action button.

---

## 7. Minimal Patch for Frontend Collaborator (`frontend/src/components/BatchResultView.tsx`)

```tsx
// Patch for frontend/src/components/BatchResultView.tsx
// Add category grouping and type tabs:

const STANDARD_CATEGORIES = [
  'all',
  'invoice',
  'receipt',
  'bank_statement',
  'medical_report',
  'kyc_form',
  'contract',
  'claim_form',
  'prescription',
  'unknown',
] as const;

// Inside BatchResultView component:
const [activeCategory, setActiveCategory] = useState<string>('all');
const [statusFilter, setStatusFilter] = useState<string>('all');

const filteredItems = useMemo(() => {
  if (!batchData?.items) return [];
  return batchData.items.filter((item) => {
    const matchesCat = activeCategory === 'all' || item.doc_type === activeCategory;
    const matchesStatus =
      statusFilter === 'all' ||
      (statusFilter === 'review' && item.review_status === 'pending_review') ||
      (statusFilter === 'done' && (item.review_status === 'auto_accepted' || item.review_status === 'approved'));
    return matchesCat && matchesStatus;
  });
}, [batchData?.items, activeCategory, statusFilter]);
```

---

## 8. API Client Regeneration Note

After merging the backend routes, please run:
```bash
npm run api:gen
```
This updates `src/api/schema.d.ts` from `openapi.json` and satisfies the `ContractFreshness.test.ts` test suite.
