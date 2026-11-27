# PowerShell Script for End-to-End Real Services Integration & Fault Injection
# Usage: .\scripts\integration_real.ps1
# Requires Docker Desktop engine running.

$ErrorActionPreference = "Stop"

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "ECM REAL SERVICES INTEGRATION & FAULT INJECTION TEST SUITE" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

# 1. Preflight check: Verify Docker Engine is active
Write-Host "[1/5] Checking Docker Engine availability..." -ForegroundColor Yellow
try {
    $dockerCheck = docker version 2>&1
    if ($dockerCheck -match "failed to connect" -or $dockerCheck -match "error during connect") {
        Write-Host "ERROR: Docker Desktop Engine is not running." -ForegroundColor Red
        Write-Host "Please start Docker Desktop and ensure 'Engine running' is indicated before retrying." -ForegroundColor Red
        exit 1
    }
    Write-Host "Docker Engine is active." -ForegroundColor Green
} catch {
    Write-Host "ERROR: Unable to invoke docker CLI. Error: $_" -ForegroundColor Red
    exit 1
}

# 2. Launch backing real services via Docker Compose
Write-Host "`n[2/5] Starting real infrastructure containers (Postgres, Redis, MinIO, OpenSearch)..." -ForegroundColor Yellow
docker compose -f docker-compose.yml up -d postgres redis minio opensearch

# 3. Wait for service health checks
Write-Host "`n[3/5] Waiting for services to achieve healthy status..." -ForegroundColor Yellow
$maxAttempts = 30
$servicesReady = $false
for ($i = 1; $i -le $maxAttempts; $i++) {
    Write-Host "Polling health status (Attempt $i/$maxAttempts)..."
    $unhealthy = docker compose ps --filter "health=unhealthy" -q
    $starting = docker compose ps --filter "health=starting" -q
    if (-not $unhealthy -and -not $starting) {
        $servicesReady = $true
        Write-Host "All infrastructure containers are healthy." -ForegroundColor Green
        break
    }
    Start-Sleep -Seconds 2
}

if (-not $servicesReady) {
    Write-Host "WARNING: Some services did not report healthy in time. Current status:" -ForegroundColor Yellow
    docker compose ps
}

# 4. Execute Real Services Integration & Contract Tests
Write-Host "`n[4/5] Executing real services integration and ECM contract test suite..." -ForegroundColor Yellow
$env:USE_REAL_SERVICES = "true"
$env:PYTHONPATH = "."

.venv311\Scripts\pytest.exe -o pythonpath=. `
    tests/test_integration_flow.py `
    tests/test_fault_injection.py `
    tests/test_ecm_contracts.py `
    -v

if ($LASTEXITCODE -ne 0) {
    Write-Host "Integration tests failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}

# 5. Clean teardown or status confirmation
Write-Host "`n[5/5] Real services integration tests PASSED successfully." -ForegroundColor Green
Write-Host "To keep containers running, leave as is. To terminate, run: docker compose down" -ForegroundColor Cyan
