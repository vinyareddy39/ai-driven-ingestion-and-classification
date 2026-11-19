# Production Deployment Guide: FastAPI Backend on Render & React Frontend on Vercel

This guide provides end-to-end instructions for deploying the document ingestion, classification, and prescription pipeline to production.

---

## 1. Architecture Overview

- **Frontend**: React 18 + Vite SPA deployed on **Vercel** with client-side SPA routing (`frontend/vercel.json`).
- **Backend**: FastAPI Dockerized container running on **Render** Web Service (`render.yaml`), bound dynamically to `$PORT`.
- **Database**: Managed **Render PostgreSQL** database (`ecm-postgres`) with automatic Alembic migrations run in `preDeployCommand`.
- **File Storage**: **Amazon S3** (or S3-compatible Cloudflare R2 / MinIO) for immutable document asset storage.
- **Message Queue**: Persistent database-backed queue (`QUEUE_BACKEND=database`) running on PostgreSQL `pipeline_jobs` table to guarantee zero message loss across container restarts.

---

## 2. Generating Production Secrets

Before deploying, generate cryptographically secure secrets in PowerShell or Python:
```powershell
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(32)); print('DATA_ENCRYPTION_KEY=' + secrets.token_urlsafe(32)); print('WEBHOOK_SIGNING_SECRET=' + secrets.token_urlsafe(32)); print('ADMIN_TOKEN=' + secrets.token_urlsafe(32))"
```
Keep these values secure. **Never commit them to git.**

---

## 3. Step 1: Object Storage Setup (Amazon S3 / Cloudflare R2)

1. Create a dedicated S3 bucket: e.g. `ecm-production-assets`.
2. Block public access (all document reads and writes are securely routed through authenticated FastAPI backend endpoints).
3. Configure bucket CORS policy:
```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET", "PUT", "POST", "HEAD"],
    "AllowedOrigins": ["https://*.vercel.app", "https://your-custom-domain.com"],
    "ExposeHeaders": ["ETag"]
  }
]
```
4. Create an IAM user with programmatic access (`s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, `s3:ListBucket`) on `arn:aws:s3:::ecm-production-assets/*`.
5. Record `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `S3_BUCKET_NAME`.

---

## 4. Step 2: Backend & Database Deployment on Render

1. Log in to your [Render Dashboard](https://dashboard.render.com/).
2. Click **New +** $\rightarrow$ **Blueprint**.
3. Connect your GitHub repository and select the `main` (or production) branch.
4. Render automatically parses `render.yaml` and provisions:
   - PostgreSQL database: `ecm-postgres`
   - Web service: `ecm-backend`
5. In the Render Dashboard, open `ecm-backend` $\rightarrow$ **Environment** and populate the `sync: false` secrets:
   - `SECRET_KEY`: `<generated_secret_key_32_chars>`
   - `DATA_ENCRYPTION_KEY`: `<generated_encryption_key_32_chars>`
   - `AUTH_TOKENS`: `<token1>:admin,<token2>:reviewer,<token3>:compliance`
   - `CORS_ORIGINS`: `https://<your-vercel-app>.vercel.app`
   - `WEBHOOK_SIGNING_SECRET`: `<generated_webhook_secret>`
   - `S3_BUCKET_NAME`: `ecm-production-assets`
   - `AWS_ACCESS_KEY_ID`: `<your_aws_access_key>`
   - `AWS_SECRET_ACCESS_KEY`: `<your_aws_secret_key>`
   - `S3_REGION`: `us-east-1`
6. Click **Manual Deploy** $\rightarrow$ **Deploy Latest Commit**.
   - Render automatically executes `preDeployCommand: alembic upgrade head` against PostgreSQL.
   - The health check tests `GET /api/v1/system/info`.
7. Note your public backend URL: `https://ecm-backend-xxxx.onrender.com`.

---

## 5. Step 3: Frontend Deployment on Vercel

1. Log in to [Vercel](https://vercel.com/).
2. Click **Add New...** $\rightarrow$ **Project**.
3. Import your GitHub repository.
4. Configure Project Settings:
   - **Framework Preset**: Vite
   - **Root Directory**: `frontend`
   - **Build Command**: `npm run build`
   - **Output Directory**: `dist`
5. Add Environment Variable:
   - `VITE_API_BASE_URL`: `https://ecm-backend-xxxx.onrender.com`
6. Click **Deploy**.
7. Vercel applies the SPA rewrites defined in `frontend/vercel.json`.

---

## 6. Step 4: Post-Deployment Smoke Verification

Run the automated smoke test script locally against the live deployment:
```powershell
./scripts/smoke_deployed.ps1 -BackendUrl "https://ecm-backend-xxxx.onrender.com" -AdminToken "<your_admin_token>"
```

### Manual Verification Matrix:
1. **Unauthenticated access check**:
   ```bash
   curl -i https://ecm-backend-xxxx.onrender.com/api/v1/documents
   # Returns HTTP 401 Unauthorized
   ```
2. **CORS Preflight check**:
   ```bash
   curl -i -X OPTIONS https://ecm-backend-xxxx.onrender.com/api/v1/system/info \
     -H "Origin: https://your-app.vercel.app" \
     -H "Access-Control-Request-Method: GET"
   # Returns HTTP 200 OK with Access-Control-Allow-Origin: https://your-app.vercel.app
   ```
3. **Health check with token**:
   ```bash
   curl -i https://ecm-backend-xxxx.onrender.com/api/v1/system/info \
     -H "Authorization: Bearer <your_admin_token>"
   # Returns HTTP 200 OK with {"mode": "REAL SERVICES", "version": "1.0.0"}
   ```
