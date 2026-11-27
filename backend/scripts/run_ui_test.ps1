param(
    [string]$Phase = "after"
)

Write-Host "Starting backend..."
$backend = Start-Process -FilePath "C:\ml\.venv311\Scripts\python.exe" -ArgumentList "-m uvicorn app.api.app:app --host 127.0.0.1 --port 8000" -WorkingDirectory "C:\ml\backend" -PassThru

Write-Host "Starting frontend..."
$frontend = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run dev -- --host 0.0.0.0 --port 5173" -WorkingDirectory "C:\ml\frontend" -PassThru

Write-Host "Backend PID: $($backend.Id), Frontend PID: $($frontend.Id)"
Start-Sleep -Seconds 8

$env:NODE_PATH = "C:\ml\frontend\node_modules"
try {
    Write-Host "Running Playwright test for $Phase..."
    node scripts/record_baseline_ui.js $Phase
} finally {
    Write-Host "Stopping backend and frontend processes..."
    Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue
    Get-Process -Name uvicorn, node -ErrorAction SilentlyContinue | Where-Object { $_.Path -match 'ml' } | Stop-Process -Force -ErrorAction SilentlyContinue
}
