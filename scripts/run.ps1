# Windows PowerShell Automation Script for ECM Ingestion Pipeline
param(
    [Parameter(Position=0)]
    [ValidateSet("test", "eval", "load", "demo", "up", "down", "train", "scaffold", "frontend-dev", "frontend-test", "frontend-build", "help")]
    [string]$Command = "help"
)

$PythonExe = "python"

switch ($Command) {
    "frontend-dev" {
        Write-Host "Starting Vite frontend development server on http://localhost:5173..." -ForegroundColor Cyan
        Set-Location frontend
        npm run dev
    }
    "frontend-test" {
        Write-Host "Running frontend unit and contract test suite..." -ForegroundColor Cyan
        Set-Location frontend
        npm test
    }
    "frontend-build" {
        Write-Host "Building production frontend assets..." -ForegroundColor Cyan
        Set-Location frontend
        npm run build
    }
    "test" {
        Write-Host "Running pytest test suite..." -ForegroundColor Cyan
        & $PythonExe -m pytest -v tests/
    }
    "eval" {
        Write-Host "Running locked test set evaluation..." -ForegroundColor Cyan
        & $PythonExe -m tests.evaluation_runner
    }
    "load" {
        Write-Host "Running load and throughput benchmark (50,000 docs/day target)..." -ForegroundColor Cyan
        & $PythonExe -m tests.load_runner
    }
    "demo" {
        Write-Host "Running pipeline ingestion demo and launching review UI status..." -ForegroundColor Cyan
        & $PythonExe -m app.api.demo_runner
    }
    "train" {
        Write-Host "Training classifier and tuning cost-sensitive thresholds..." -ForegroundColor Cyan
        & $PythonExe -m app.models.classifier_train
    }
    "scaffold" {
        Write-Host "Verifying directory scaffolding..." -ForegroundColor Cyan
        & $PythonExe -c "import app; print('Scaffolding verified.')"
    }
    "up" {
        Write-Host "Starting containerized services with docker-compose..." -ForegroundColor Cyan
        docker-compose up -d
    }
    "down" {
        Write-Host "Stopping containerized services with docker-compose..." -ForegroundColor Cyan
        docker-compose down
    }
    Default {
        Write-Host "==========================================================" -ForegroundColor Yellow
        Write-Host "  ECM Ingestion Pipeline - PowerShell Runner (run.ps1)   " -ForegroundColor Yellow
        Write-Host "==========================================================" -ForegroundColor Yellow
        Write-Host "Usage: .\run.ps1 <command>"
        Write-Host ""
        Write-Host "Available commands:"
        Write-Host "  .\run.ps1 test    - Run 41 unit, integration, and contract tests"
        Write-Host "  .\run.ps1 eval    - Run locked test set evaluation & audit check"
        Write-Host "  .\run.ps1 load    - Run 50k docs/day throughput benchmark"
        Write-Host "  .\run.ps1 demo    - Ingest sample batch and display review UI"
        Write-Host "  .\run.ps1 train   - Retrain model and tune thresholds"
        Write-Host "  .\run.ps1 up      - Start Docker Compose stack"
        Write-Host "  .\run.ps1 down    - Stop Docker Compose stack"
        Write-Host "  .\run.ps1 frontend-dev   - Start Vite frontend dev server (port 5173)"
        Write-Host "  .\run.ps1 frontend-test  - Run Vitest unit & contract tests"
        Write-Host "  .\run.ps1 frontend-build - Build production frontend bundle"
        Write-Host "==========================================================" -ForegroundColor Yellow
    }
}
