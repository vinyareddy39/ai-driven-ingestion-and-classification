# Production Deployment Guide: Render (Backend + Worker + Postgres), Vercel (Frontend), and Cloudflare R2

This guide provides exact, ordered steps for deploying the enterprise document ingestion, classification, and prescription pipeline to production.

---

## 1. Architecture Overview

- **Frontend**: React 18 + Vite SPA deployed on **Vercel** or **Cloudflare Pages** with client-side SPA routing (`frontend/vercel.json`).
- **Web Service**: FastAPI container running on **Render** Web Service (`render.yaml`), bound dynamically to `$PORT`. The web service handles API traffic and multipart upload orchestration, and **never runs OCR**.
- **Background Worker**: Dedicated standalone background worker service (`python -m app.workers.service`) on **Render**, sharing PostgreSQL and R2 / S3. It executes OCR, Presidio PII scanning, document classification, and outbound webhooks.
- **Database**: Managed **Render PostgreSQL** (`ecm-postgres`) with automatic Alembic migrations run in `preDeployCommand`.
- **File Storage**: **Cloudflare R2** (S3-compatible object storage) for large file direct-to-storage uploads up to 2 GB with zero proxy egress fees.
- **Job Queue**: PostgreSQL row-locking queue (`SELECT ... FOR UPDATE SKIP LOCKED` on `pipeline_jobs` table) guaranteeing zero lost jobs and crash recovery across restarts.

---

## 2. Render Instance Size Recommendations & GPU Constraints

> [!WARNING]
> **Free Tier Limitations**:
> Render's Free tier instances sleep after 15 minutes of inactivity (causing 50+ second cold start delays) and have only 512 MB of RAM. Processing large PDFs and raster image batches on 512 MB can trigger Linux Out-Of-Memory (OOM) process termination (`kill -9`).

### Recommended Sizing:
- **Web Service (`ecm-backend`)**:
  - Minimum: **Starter** (512 MB - 1 GB RAM, 0.5 CPU)
  - Recommended: **Standard** (2 GB RAM, 1 CPU) for high-concurrency multipart upload sessions.
- **Background Worker (`ecm-worker`)**:
  - Minimum: **Starter** (512 MB RAM, 0.5 CPU)
  - Recommended: **Standard** (2 GB RAM, 1 CPU) to process 500+ file batches and multi-page PDFs with text layer extraction.
- **PostgreSQL Database (`ecm-postgres`)**:
  - **Starter** or **Standard** managed database.
- *(Note: Render plans and pricing change periodically; verify Render's current pricing plans at [render.com/pricing](https://render.com/pricing)).*

> [!NOTE]
> **No GPU on Render**: Render native web/worker instances do not offer dedicated NVIDIA GPUs. The application is configured to run production OCR using CPU engines (PyMuPDF high-speed text layer extraction first, Tesseract CPU OCR for scanned pages). TrOCR/CUDA is automatically active only when a GPU device is detected.

---

## 3. Step 1: Cloudflare R2 Bucket, Token, and CORS Setup

Cloudflare R2 allows browser clients to upload files up to 2 GB directly to object storage via presigned multipart S3 URLs.

### A. Create the Bucket
1. In Cloudflare Dashboard, navigate to **R2** $\rightarrow$ **Create Bucket**.
2. Name the bucket (e.g. `ecm-production-assets`).
3. Set location to **Automatic**.

### B. Configure R2 Bucket CORS Rule
In bucket **Settings** $\rightarrow$ **CORS Policy**, add:
```json
[
  {
    "AllowedOrigins": [
      "https://*.vercel.app",
      "https://your-custom-domain.com"
    ],
    "AllowedMethods": [
      "GET",
      "PUT",
      "POST",
      "HEAD",
      "DELETE"
    ],
    "AllowedHeaders": [
      "*"
    ],
    "ExposeHeaders": [
      "ETag"
    ],
    "MaxAgeSeconds": 3600
  }
]
```
*(The `ExposeHeaders: ["ETag"]` directive is mandatory so the browser can read part ETags for multipart completion).*

### C. Create an API Token (Scoped to One Bucket Only)
1. Go to **R2** $\rightarrow$ **Manage R2 API Tokens** $\rightarrow$ **Create API Token**.
2. Set permissions to **Object Read & Write**.
3. Set scope to **Specific bucket only**: select `ecm-production-assets`.
4. Copy:
   - **Access Key ID**
   - **Secret Access Key**
   - **Jurisdiction-specific S3 Endpoint URL** (format: `https://<accountid>.r2.cloudflarestorage.com`)

---

## 4. Step 2: Generate Production Secrets

Generate cryptographically strong 32-byte URL-safe secrets locally:
```powershell
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(32)); print('DATA_ENCRYPTION_KEY=' + secrets.token_urlsafe(32)); print('WEBHOOK_SIGNING_SECRET=' + secrets.token_urlsafe(32))"
```

---

## 5. Step 3: Deploy Backend & Worker on Render

1. Log in to [dashboard.render.com](https://dashboard.render.com).
2. Click **New +** $\rightarrow$ **Blueprint**.
3. Connect your repository and select your deployment branch.
4. Render detects `render.yaml` and provisions:
   - `ecm-postgres` (PostgreSQL Database)
   - `ecm-backend` (Web Service)
   - `ecm-worker` (Background Worker Service)
5. Fill in the declared environment variables marked `sync: false`:
   - `SECRET_KEY`: `<generated_secret_key>`
   - `DATA_ENCRYPTION_KEY`: `<generated_encryption_key>`
   - `S3_ENDPOINT_URL`: `https://<accountid>.r2.cloudflarestorage.com`
   - `S3_BUCKET_NAME`: `ecm-production-assets`
   - `AWS_ACCESS_KEY_ID`: `<r2_access_key_id>`
   - `AWS_SECRET_ACCESS_KEY`: `<r2_secret_access_key>`
   - `CORS_ORIGINS`: `https://your-app.vercel.app` (placeholder initially)
   - `WEBHOOK_SIGNING_SECRET`: `<generated_webhook_secret>`
6. Deploy the Blueprint. Render executes `alembic upgrade head` before starting `ecm-backend`.
7. Once deployed, note the backend public URL: `https://ecm-backend-xxxx.onrender.com`.
8. Verify readiness:
   ```bash
   curl -i https://ecm-backend-xxxx.onrender.com/health/ready
   # Returns HTTP 200 OK: {"status": "READY", "database": "CONNECTED", "queue": "CONNECTED"}
   ```

---

## 6. Step 4: Create the Initial Admin User (One-Off Command)

> [!IMPORTANT]
> Never commit credentials or admin passwords to git. Run this one-off command in the **Render Web Shell** (`ecm-backend` $\rightarrow$ **Shell**):

```bash
python -c "
from app.models.db import UserModel, get_db_session;
from app.core.jwt_auth import hash_password;
import secrets, uuid;

db = get_db_session();
email = 'admin@enterprise.local';
pwd = secrets.token_urlsafe(16);
user = UserModel(
    id=f'usr-admin-{uuid.uuid4().hex[:8]}',
    email=email,
    password_hash=hash_password(pwd),
    role='admin',
    disabled=False
);
db.merge(user);
db.commit();
print(f'ADMIN CREATED: email={email} temporary_password={pwd}');
"
```
Record the temporary password and immediately log in to change it.

---

## 7. Step 5: Deploy Frontend on Vercel

1. Log in to [vercel.com](https://vercel.com) and click **Add New...** $\rightarrow$ **Project**.
2. Import your GitHub repository.
3. Configure Project Settings:
   - **Framework Preset**: Vite
   - **Root Directory**: `frontend`
   - **Build Command**: `npm run build`
   - **Output Directory**: `dist`
4. Add Environment Variable:
   - `VITE_API_BASE_URL`: `https://ecm-backend-xxxx.onrender.com`
5. Click **Deploy**. Vercel serves the SPA and rewrites all route paths to `/index.html` via `vercel.json`.
6. Copy your production frontend URL (e.g. `https://ecm-ingest.vercel.app`).

---

## 8. Step 6: Update CORS_ORIGINS & Finalize

1. Return to **Render Dashboard** $\rightarrow$ `ecm-backend` $\rightarrow$ **Environment**.
2. Set `CORS_ORIGINS` to your exact Vercel frontend URL:
   ```
   CORS_ORIGINS=https://ecm-ingest.vercel.app
   ```
3. Save changes. Render triggers a zero-downtime redeploy.

---

## 9. Step 7: Post-Deployment Smoke Test

Execute the automated smoke verification script against the live endpoint:
```powershell
$env:BACKEND_URL="https://ecm-backend-xxxx.onrender.com"
$env:AUTH_TOKEN="<your_jwt_access_token>"
./scripts/smoke_deployed.ps1
```
The smoke test verifies:
- Service health & readiness probe (`/health/ready`)
- System information & engine status (`/api/v1/system/info`)
- CORS preflight headers for Vercel origin
- JWT authentication matrix (401 on unauthenticated access)
- Multipart upload initiation (`/api/v1/uploads/init`)
- Batch results query (`/api/v1/batches/{id}`)

---

## 10. Rollback & Secret Rotation

### Rollback:
- **Render**: Navigate to `ecm-backend` $\rightarrow$ **Events** / **Deploys**, select the previous successful deploy, and click **Rollback to this deploy**.
- **Vercel**: Navigate to **Deployments**, select the previous deployment, and click **Promote to Production**.

### Secret Rotation:
1. **Rotate `SECRET_KEY`**: Update `SECRET_KEY` in Render environment variables. Active user JWT sessions will expire and require re-login.
2. **Rotate `DATA_ENCRYPTION_KEY`**: Run a database migration script re-encrypting `EncryptedText` columns with the new Fernet key before swapping the environment variable.
3. **Rotate R2 / S3 Keys**: Generate a new R2 API token in Cloudflare, update `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` on Render, and delete the old token from Cloudflare once verified.
