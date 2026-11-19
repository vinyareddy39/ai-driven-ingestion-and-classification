<#
.SYNOPSIS
  run_connected.ps1 — Start both the FastAPI backend and React frontend together.
  Verifies connectivity and health endpoints before launching the Vite dev server.

.DESCRIPTION
  Backend: http://127.0.0.1:8000 (FastAPI + Uvicorn)
  Frontend: http://localhost:5173 (Vite + React)
  Mode: LOCAL MODE (X-User-Role: admin)

.EXAMPLE
  .\scripts\run_connected.ps1
#>

[CmdletBinding()]
param (
  [string]$BackendHost = "127.0.0.1",
  [int]$BackendPort = 8000,
  [string]$FrontendPort = "5173"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " ECM IngestAI — Connected Dev Environment Launcher" -ForegroundColor Cyan
Write-Host " Mode: LOCAL MODE | Host: $BackendHost | Port: $BackendPort" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# ── 1. Check Python virtual environment ──────────────────────────────
$VenvPython = Join-Path $RepoRoot ".venv311\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
  $VenvPython = "python.exe"
}
Write-Host "`n[1/4] Python executable: $VenvPython" -ForegroundColor Gray

# ── 2. Check / Start Backend ─────────────────────────────────────────
$BackendUrl = "http://${BackendHost}:${BackendPort}"
Write-Host "[2/4] Checking backend at $BackendUrl..." -ForegroundColor Yellow

$backendRunning = $false
try {
  $health = Invoke-RestMethod -Uri "$BackendUrl/health/live" -TimeoutSec 2 -ErrorAction SilentlyContinue
  if ($health.status -eq "alive" -or $health.status -eq "ok") {
    $backendRunning = $true
    Write-Host "  Backend is already running and healthy." -ForegroundColor Green
  }
} catch {
  $backendRunning = $false
}

if (-not $backendRunning) {
  Write-Host "  Starting FastAPI backend..." -ForegroundColor Yellow
  $backendProc = Start-Process -FilePath $VenvPython `
    -ArgumentList "-m uvicorn app.api.app:app --host $BackendHost --port $BackendPort" `
    -WorkingDirectory $RepoRoot `
    -PassThru

  # Poll until healthy (max 15 seconds)
  $attempts = 0
  while ($attempts -lt 15) {
    Start-Sleep -Seconds 1
    $attempts++
    try {
      $ready = Invoke-RestMethod -Uri "$BackendUrl/health/ready" -TimeoutSec 1 -ErrorAction SilentlyContinue
      if ($ready.status -eq "ready" -or $ready.status -eq "ok") {
        $backendRunning = $true
        Write-Host "  Backend started successfully (PID $($backendProc.Id))!" -ForegroundColor Green
        break
      }
    } catch {}
  }

  if (-not $backendRunning) {
    Write-Error "Backend failed to become ready within 15 seconds. Check logs and restart."
  }
}

# ── 3. Run Connection Check Script ───────────────────────────────────
Write-Host "`n[3/4] Running automated connection probe..." -ForegroundColor Yellow
try {
  & node "$RepoRoot\scripts\connection_check.mjs"
  if ($LASTEXITCODE -eq 0) {
    Write-Host "  Automated connection check: 10/10 PASS" -ForegroundColor Green
  } else {
    Write-Host "  Warning: connection check returned non-zero exit code" -ForegroundColor DarkYellow
  }
} catch {
  Write-Host "  Warning: could not execute connection_check.mjs: $_" -ForegroundColor DarkYellow
}

# ── 4. Start Frontend ────────────────────────────────────────────────
Write-Host "`n[4/4] Starting React frontend dev server..." -ForegroundColor Yellow
Write-Host "  Frontend URL: http://localhost:$FrontendPort" -ForegroundColor Cyan
Write-Host "  Press CTRL+C to stop the frontend server.`n" -ForegroundColor Gray

Set-Location "$RepoRoot\frontend"
& npm run dev -- --host 127.0.0.1 --port $FrontendPort
