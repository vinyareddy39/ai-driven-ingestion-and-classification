# Document Reader

An AI document reading and structure extraction platform designed with a clean, decoupled architecture:
- **/backend**: Server-side FastAPI application, layout analyzers, database models, and background workers.
- **/frontend**: Client-side React/TypeScript single-page application (SPA).
- **/tests-data**: Benchmark files, ground truth datasets, and evaluation suites.
- **/docs**: Architecture specifications, deployment manuals, and project records.
- **/scripts**: Operational, evaluation, and diagnostic utilities.

---

## 1. Directory Structure

```
ml/
├── backend/                  # Everything that runs on the server
│   ├── app/                  # Application code (api, core, models, workers, adapters)
│   ├── config/               # Pipeline, taxonomy, and detector YAML configs
│   ├── migrations/           # Database schema migrations (Alembic)
│   ├── tests/                # Backend unit and integration test suites
│   ├── .env.example          # Backend environment variable template (NO secrets)
│   ├── Dockerfile            # Container deployment definition
│   ├── pytest.ini            # Pytest test discovery config
│   └── requirements.txt      # Python dependencies
│
├── frontend/                 # Everything that runs in the browser
│   ├── src/                  # React + TypeScript source (App.tsx, api client)
│   ├── index.html            # SPA entry HTML
│   ├── package.json          # Frontend dependencies
│   ├── vite.config.ts        # Vite configuration
│   └── .env.example          # Frontend environment template (NO secrets)
│
├── tests-data/               # Test documents and benchmarks (outside app code)
│   ├── synthetic_tests/      # Ground-truth synthetic test documents
│   ├── benchmark_60/         # Standard 60-document benchmark suite
│   ├── test_folders/         # Nested folder upload fixtures
│   ├── test_robust_proofs/   # Degraded, noisy, and rotated test images
│   ├── structure_eval_suite/ # Page structure recognition benchmarks
│   └── table_eval_suite/     # Table detection & arithmetic checks
│
├── docs/                     # Project documentation
│   ├── DEPLOYMENT.md         # Step-by-step Render & Vercel deployment guide
│   ├── api-contract.md       # API endpoint contracts and specifications
│   └── unsorted/             # Historical test logs and proof archives
│
├── scripts/                  # Standalone maintenance & benchmark scripts
│   ├── record_baseline_ui.js # Playwright E2E browser UI test automation
│   ├── start_services.ps1    # Automated server launcher
│   └── verify_all.ps1        # Full pipeline verification script
│
├── evidence/                 # Verification evidence captures
│   ├── before/               # Pre-restructuring tests & UI screenshots
│   └── after/                # Post-restructuring tests & UI screenshots
│
├── .gitignore                # Strict exclusion for secrets, logs, and build artifacts
├── Makefile                  # Build and run aliases
└── README.md                 # Project overview and instructions
```

---

## 2. Quickstart & Commands

### Prerequisites
* Python 3.11+
* Node.js 18+ & npm

### Starting the Backend
```bash
cd backend
uvicorn app.api.app:app --host 127.0.0.1 --port 8000
```
*API is accessible at `http://127.0.0.1:8000` with interactive docs at `http://127.0.0.1:8000/docs`.*

### Starting the Frontend
```bash
cd frontend
npm run dev -- --host 0.0.0.0 --port 5173
```
*Web application is accessible at `http://localhost:5173`.*

### Running the Test Suite
```bash
cd backend
pytest
```

---

## 3. Configuration & Environment Variables

### Backend Configuration (`backend/.env`)
Copy `backend/.env.example` to `backend/.env` and configure:
* `DATABASE_URL`: Connection string (`postgresql://...` for production, `sqlite:///./data/ecm_pipeline.db` for local).
* `JWT_SECRET`: Random 32+ character key for HS256 auth tokens.
* `OCR_ENGINE`: `hybrid` (recommended for <512MB RAM free-tier) or `trocr` (for GPU instances).
* `DELETE_UPLOAD_AFTER_PROCESSING`: `true` to purge temporary files from ephemeral disk after DB commit.

### Frontend Configuration (`frontend/.env`)
Copy `frontend/.env.example` to `frontend/.env`:
* `VITE_API_URL`: Backend URL (e.g. `http://localhost:8000` for local dev or your Render URL in production).

---

## 4. Production Deployment

For detailed production instructions covering Render Free Web Service (512MB limit), Render PostgreSQL (30-day lifecycle management), and Vercel Hobby tier, refer to [DEPLOYMENT.md](docs/DEPLOYMENT.md).
