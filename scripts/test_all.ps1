# Master Test Pack Execution Script
# Usage: .\scripts\test_all.ps1
# Executes the full test suite, security auth matrix, and PII evaluation.

$ErrorActionPreference = "Stop"

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "ECM INGESTION PIPELINE: COMPREHENSIVE TEST PACK (LOCAL MODE)" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

$env:PYTHONPATH = "."

# 1. Run the Full Pytest Suite on Isolated Database Copy
Write-Host "`n[1/3] Running Full Pytest Suite (57 Unit, Integration & API Tests)..." -ForegroundColor Yellow
.venv311\Scripts\pytest.exe -o pythonpath=. tests/ -v

if ($LASTEXITCODE -ne 0) {
    Write-Host "Pytest suite failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "Pytest suite PASSED (100% of tests green)." -ForegroundColor Green

# 2. Run Route Group Authorization Matrix & Security Verification
Write-Host "`n[2/3] Verifying Security Boundaries & Auth Matrix..." -ForegroundColor Yellow
.venv311\Scripts\pytest.exe -o pythonpath=. `
    tests/test_api_v1.py::test_page_image_leak_unauthenticated_rejected `
    tests/test_api_v1.py::test_route_group_authorization_matrix `
    tests/test_api_v1.py::test_floors_and_config_history_restart_persistence `
    -v

if ($LASTEXITCODE -ne 0) {
    Write-Host "Security auth matrix failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "Security and authorization guards PASSED." -ForegroundColor Green

# 3. Run PII Precision and Recall Evaluation on Development Set
Write-Host "`n[3/3] Running Presidio PII Detection Evaluation..." -ForegroundColor Yellow
.venv311\Scripts\python.exe scripts/reconcile_pii_all_entities.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "PII evaluation failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "`n================================================================================" -ForegroundColor Cyan
Write-Host "ALL TEST PACK PHASES EXECUTED SUCCESSFULLY (100% PASS)" -ForegroundColor Green
Write-Host "================================================================================" -ForegroundColor Cyan
