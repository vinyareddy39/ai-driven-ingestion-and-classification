# Production Deployment Guide: Free-Tier Infrastructure

This guide details the step-by-step deployment procedure for running the **Document Reader** platform within free-tier infrastructure constraints:
- **Backend**: Render Free Web Service (Python 3.11 FastAPI, 512MB RAM limit)
- **Database**: Render Free PostgreSQL (1 GB storage, 30-day lifecycle)
- **Frontend**: Vercel Hobby Tier (Vite + React SPA, global edge CDN)
- **Object Storage (Optional)**: Cloudflare R2 (10 GB free storage, $0.00 egress)

---

## 1. Architectural Summary & Free-Tier Optimization

### In-Process Background Processing
Render's free tier permits only a single web service without separate background worker containers. The application runs asynchronous background processing in an in-process thread pool (`concurrent.futures.ThreadPoolExecutor`) inside the single web service. All batch and document states (`Still reading`, `Done`, `Done, check`, `Failed`) are persisted directly in PostgreSQL.

### RAM Optimization & Peak Memory Footprint
* **Free Tier Limit**: 512 MB RAM (Hard limit; processes exceeding 512 MB are immediately terminated with `OOMKilled exit code 137`).
* **Optimized Engine**: `HybridOCREngine` (`fitz` / PyMuPDF + OpenCV deskewing + lightweight Tesseract OCR).
* **Lazy Loading**: Heavy PyTorch (`torch`) and HuggingFace Transformers (`TrOCR`) modules are strictly isolated and never loaded when `OCR_ENGINE=hybrid` is configured.
* **Component Reading Text from Images**: In hybrid mode, image files (e.g. PNG, JPG, scanned PDFs) are read by **local Tesseract OCR** via `pytesseract` operating on preprocessed (deskewed and contrast-normalized) image buffers.
* **Peak Memory Benchmark (Concurrent Ingestion)**:
  * Baseline Process RSS: **~112 MB**
  * Peak Process RSS during concurrent 10-file batch: **178.4 MB** (< 35% of 512 MB limit)
  * Average processing time per digital file: **~0.15s**
  * Average processing time per scanned image: **~1.4s**

---

## 2. External AI Services & Data Privacy

### Strict Opt-In Gate: `ENABLE_EXTERNAL_AI`
By default, **all external AI calls are OFF and completely impossible** unless `ENABLE_EXTERNAL_AI=true` is explicitly set in the server environment.

### Outbound Endpoints Where Data Can Leave the System
When `ENABLE_EXTERNAL_AI=true` is enabled with valid API keys:
1. **Google Gemini API**: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` (Transmits extracted text blocks and base64 document images when `GEMINI_API_KEY` is present).
2. **Groq LPU API**: `https://api.groq.com/openai/v1/chat/completions` (Transmits extracted text blocks and document images when `GROQ_API_KEY` is present).
3. **Anthropic API**: `https://api.anthropic.com/v1/messages` (Transmits document images when `ANTHROPIC_API_KEY` is present).
4. **OpenRouter API**: `https://openrouter.ai/api/v1/chat/completions` (Transmits document images when `OPENROUTER_API_KEY` is present).

> [!WARNING]
> **Third-Party Data Transmission Notice**: When `ENABLE_EXTERNAL_AI=true`, document content, extracted text, and rendered page images are transmitted to external third-party servers. When enabled, a prominent warning banner is displayed across the frontend UI:
> `⚠️ WARNING: External AI is enabled. Document content, extracted text and images may be transmitted to third-party APIs (Google Gemini, Groq, Anthropic).`

When `ENABLE_EXTERNAL_AI=false` (the default) or when API keys are empty:
- **Zero outbound HTTP requests carry document content**. The application relies exclusively on the local deterministic pipeline and local Tesseract OCR engine.

---

## 3. Environment Variables & Production Safety

The application performs strict validation upon startup. In production (`APP_ENV=production`), the application **refuses to start with an explicit error message** if any required variable is missing or insecure.

### Required Environment Variables

| Variable Name | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `APP_ENV` | Yes | `local` | Set to `production` in production. |
| `DATABASE_URL` | Yes (in prod) | *None* | Connection URL for PostgreSQL. SQLite is rejected in production. |
| `JWT_SECRET` / `SECRET_KEY` | Yes (in prod) | *None* | 32+ character cryptographically random key for HS256 JWT tokens. |
| `DATA_ENCRYPTION_KEY` / `ENCRYPTION_KEY` | Yes (in prod) | *None* | 32-byte secret (base64 or string) for column-level encryption. **App refuses to start without it.** |
| `CORS_ORIGINS` | Yes (in prod) | *None* | Comma-separated whitelist of allowed frontend domains. Wildcard `*` is rejected. |
| `MAX_UPLOAD_MB` | Yes (in prod) | `200` | Maximum file upload size in megabytes (must be > 0 and <= 500). |
| `OCR_ENGINE` | No | `hybrid` | Lightweight OCR backend (`hybrid` fits comfortably in 512MB RAM). |
| `ENABLE_EXTERNAL_AI` | No | `false` | Explicit opt-in flag for third-party AI calls. Defaults to `false`. |
| `DELETE_UPLOAD_AFTER_PROCESSING` | No | `true` | Purges ephemeral uploaded files from container disk after processing. |

### Key Rotation Instructions (`DATA_ENCRYPTION_KEY`)
To rotate the data encryption key without losing access to existing encrypted records:
1. Generate a new 32-byte key:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. The application provides `rotate_encryption_key(ciphertext, old_key, new_key)` in `app.core.security`.
3. Set `DATA_ENCRYPTION_KEY_OLD=<current_key>` and `DATA_ENCRYPTION_KEY=<new_key>`.
4. Run the migration script:
   ```bash
   python scripts/rotate_keys.py
   ```
5. Remove `DATA_ENCRYPTION_KEY_OLD` after rotation completes. Stored values remain decryptable across process restarts.

---

## 4. Render Database Setup (PostgreSQL)

1. Log in to [Render Dashboard](https://dashboard.render.com/).
2. Click **New +** -> **PostgreSQL**.
3. Configure the database instance:
   * **Name**: `document-reader-db`
   * **Database**: `doc_reader`
   * **User**: `doc_user`
   * **Plan**: **Free** (1 GB storage, 30-day validity).
4. Click **Create Database**.
5. Copy the **Internal Database URL** (e.g. `postgres://doc_user:...@dpg-xxx.render.com/doc_reader`).

### ⚠️ 30-Day PostgreSQL Expiration Notice
Render's free PostgreSQL instances expire after **30 days**. Use the dashboard's **"Export Account Data (JSON & CSV)"** button before day 25 to preserve all batches, documents, and extracted field data.

---

## 5. Render Web Service Setup (FastAPI Backend)

1. In Render Dashboard, click **New +** -> **Web Service**.
2. Connect your Git repository.
3. Configure service parameters:
   * **Name**: `document-reader-backend`
   * **Environment**: `Python 3`
   * **Root Directory**: `backend`
   * **Build Command**:
     ```bash
     pip install --upgrade pip && pip install -r requirements.txt
     ```
   * **Start Command**:
     ```bash
     uvicorn app.api.app:app --host 0.0.0.0 --port $PORT --workers 1
     ```
   * **Plan**: **Free** (0.1 CPU, 512 MB RAM).
4. Configure **Environment Variables**:
   * `APP_ENV`: `production`
   * `DATABASE_URL`: `[Your Render Postgres URL]`
   * `JWT_SECRET`: `[32+ character random string]`
   * `DATA_ENCRYPTION_KEY`: `[32+ character random string]`
   * `CORS_ORIGINS`: `https://your-frontend.vercel.app`
   * `MAX_UPLOAD_MB`: `200`
   * `OCR_ENGINE`: `hybrid`
   * `ENABLE_EXTERNAL_AI`: `false`
   * `DELETE_UPLOAD_AFTER_PROCESSING`: `true`

---

## 6. Vercel Setup (Vite React Frontend)

1. Log in to [Vercel Dashboard](https://vercel.com/).
2. Click **Add New...** -> **Project**.
3. Import your Git repository.
4. Configure project settings:
   * **Framework Preset**: `Vite`
   * **Root Directory**: `frontend`
   * **Build Command**: `npm run build`
   * **Output Directory**: `dist`
   * **Install Command**: `npm install`
5. Configure **Environment Variables**:
   * `VITE_API_URL`: `https://document-reader-backend.onrender.com` (Your Render Web Service URL without trailing slash).
6. Click **Deploy**.

---

## 7. Verification Evidence & Benchmarks

All claims in this deployment guide have been tested and verified:
- **Image Reading Accuracy Report**: [image_accuracy_results.json](file:///C:/ml/evidence/image_reading_evaluation/image_accuracy_results.json)
- **Production Variable Refusal Tests**: [production_variable_refusals.json](file:///C:/ml/evidence/config_verification/production_variable_refusals.json)
- **Peak RAM Benchmark (10 concurrent files)**: [memory_benchmark_report.json](file:///C:/ml/evidence/memory_benchmark/memory_benchmark_report.json)
- **Clean Clone Verification Script**: [verify_clone.ps1](file:///C:/ml/scripts/verify_clone.ps1)
