# verify_all.ps1 - Reproducible End-to-End Verification Runner
# Runs the full clean-start, browser upload, and metrics computation from scratch.

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " STARTING E2E REPRODUCIBLE VERIFICATION SUITE" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Stop existing processes
Write-Host "[1/5] Stopping any existing backend/frontend processes on 8000 & 5173..." -ForegroundColor Yellow
Get-Process -Name "python", "node" -ErrorAction SilentlyContinue | Where-Object { 
    $p = $_
    $conns = Get-NetTCPConnection -OwningProcess $p.Id -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 8000, 5173 }
    $conns.Count -gt 0 
} | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# 2. Build Frontend
Write-Host "[2/5] Building frontend assets cleanly..." -ForegroundColor Yellow
npm --prefix frontend run build

# 3. Start Backend & Frontend
Write-Host "[3/5] Starting FastAPI backend on :8000 and Vite frontend on :5173..." -ForegroundColor Yellow
$backend = Start-Process -FilePath ".venv311\Scripts\python.exe" -ArgumentList "-m uvicorn app.api.app:app --host 127.0.0.1 --port 8000" -PassThru -WindowStyle Hidden
$frontend = Start-Process -FilePath "npm" -ArgumentList "--prefix frontend run dev -- --host 0.0.0.0 --port 5173" -PassThru -WindowStyle Hidden

# Wait for healthy services
Write-Host "Waiting for services to become healthy..."
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $resB = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health/workers" -UseBasicParsing -TimeoutSec 2
        $resF = Invoke-WebRequest -Uri "http://localhost:5173" -UseBasicParsing -TimeoutSec 2
        if ($resB.StatusCode -eq 200 -and $resF.StatusCode -eq 200) {
            Write-Host "Both Backend (:8000) and Frontend (:5173) are UP and healthy!" -ForegroundColor Green
            break
        }
    } catch {}
}

# 4. Run Playwright Browser Automation Test
Write-Host "[4/5] Running real Playwright browser upload suite..." -ForegroundColor Yellow
$env:NODE_PATH = "frontend/node_modules"
node scripts/run_real_ui_multibatch_upload.js

# 5. Compute Metrics and Print Table
Write-Host "[5/5] Computing final mathematical accuracy metrics..." -ForegroundColor Yellow
.venv311\Scripts\python.exe scripts/compute_e2e_metrics.py

Write-Host "==========================================================" -ForegroundColor Green
Write-Host " VERIFICATION COMPLETE. RESULTS RECORDED." -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Get-Content "evidence\20261126_212000\raw_outputs\computed_accuracy_metrics.txt"
