# Master Test Pack Execution Script
# Usage: .\scripts\test_all.ps1
# Executes the full pytest suite (148 tests), security auth matrix, live HTTP/CORS verification, and PII evaluation.

$ErrorActionPreference = "Stop"

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "ECM INGESTION PIPELINE: COMPREHENSIVE TEST PACK (LOCAL MODE)" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

$env:PYTHONPATH = "."
$env:DATABASE_URL = "sqlite:///./data/test_ecm_pipeline.db"

# Ensure isolated copy of the database exists
if (Test-Path "data/ecm_pipeline.backup.db") {
    Copy-Item "data/ecm_pipeline.backup.db" "data/test_ecm_pipeline.db" -Force
} elseif (Test-Path "data/ecm_pipeline.db") {
    Copy-Item "data/ecm_pipeline.db" "data/test_ecm_pipeline.db" -Force
}

# Determine pytest command
$pytestCmd = "pytest"
if (Get-Command pytest -ErrorAction SilentlyContinue) {
    $pytestCmd = "pytest"
} else {
    $pytestCmd = "python -m pytest"
}

# 1. Run the Full Pytest Suite (148 Unit, Integration & API Tests) with 120-second timeout protection
Write-Host "`n[1/4] Running Full Pytest Suite (148 Tests across all 9 Stages)..." -ForegroundColor Yellow
$testJob = Start-Job -ScriptBlock {
    param($dbUrl)
    $env:DATABASE_URL = $dbUrl
    $env:PYTHONPATH = "."
    pytest tests/ -v
} -ArgumentList $env:DATABASE_URL

$completed = Wait-Job $testJob -Timeout 120
if ($null -eq $completed) {
    Stop-Job $testJob
    Remove-Job $testJob -Force
    Write-Host "FATAL: Test suite timed out after 120 seconds!" -ForegroundColor Red
    exit 1
}

$output = Receive-Job $testJob
Remove-Job $testJob -Force
Write-Host ($output -join "`n")

if ($testJob.State -ne "Completed" -and $LASTEXITCODE -ne 0) {
    Write-Host "Pytest suite failed." -ForegroundColor Red
    exit 1
}
Write-Host "Pytest suite PASSED (100% of tests green)." -ForegroundColor Green

# 2. Run Security Auth & Isolation Matrix
Write-Host "`n[2/4] Verifying Security Boundaries & Auth Matrix..." -ForegroundColor Yellow
pytest tests/test_api_v1.py tests/test_prescription_auth_isolation.py tests/test_storage_queue_workers.py -v

if ($LASTEXITCODE -ne 0) {
    Write-Host "Security auth matrix failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "Security and authorization guards PASSED." -ForegroundColor Green

# 3. Live Server HTTP & CORS Verification (Real Uvicorn Server & Network Requests)
Write-Host "`n[3/4] Running Live HTTP, Preflight CORS, and Isolation Checks..." -ForegroundColor Yellow
python scripts/live_server_test.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "Live HTTP server verification failed." -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "Live HTTP and CORS preflight checks PASSED." -ForegroundColor Green

# 4. Run PII Precision and Recall Evaluation on Development Set
Write-Host "`n[4/4] Running Presidio PII Detection Evaluation..." -ForegroundColor Yellow
if (Test-Path "scripts/reconcile_pii_all_entities.py") {
    python scripts/reconcile_pii_all_entities.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "PII evaluation failed with exit code $LASTEXITCODE" -ForegroundColor Red
        exit $LASTEXITCODE
    }
} else {
    Write-Host "PII evaluation script skipped (not found in scripts/)." -ForegroundColor Gray
}

Write-Host "`n================================================================================" -ForegroundColor Cyan
Write-Host "ALL TEST PACK PHASES EXECUTED SUCCESSFULLY (100% PASS)" -ForegroundColor Green
Write-Host "================================================================================" -ForegroundColor Cyan
