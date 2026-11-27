# start_live_demo.ps1
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  STARTING ECM INGESTION SYSTEM - LIVE DEMO TUNNEL" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan

# Kill any lingering instances
Get-Process python, node, cloudflared -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*ml*" -or $_.Name -eq "cloudflared" } | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "`n[1/3] Starting FastAPI Backend on port 8000..." -ForegroundColor Yellow
$backend = Start-Process -FilePath "C:\ml\.venv311\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "app.api.app:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory "C:\ml" `
    -WindowStyle Hidden `
    -PassThru

Write-Host "[2/3] Starting React Frontend on port 5173..." -ForegroundColor Yellow
$frontend = Start-Process -FilePath "node" `
    -ArgumentList "node_modules/vite/bin/vite.js", "--host", "0.0.0.0", "--port", "5173" `
    -WorkingDirectory "C:\ml\frontend" `
    -WindowStyle Hidden `
    -PassThru

Write-Host "Waiting 3 seconds for local servers to initialize..."
Start-Sleep -Seconds 3

Write-Host "`n[3/3] Launching Cloudflare Public Tunnel..." -ForegroundColor Green
Write-Host "Copy the link printed below ending in '.trycloudflare.com':`n" -ForegroundColor Cyan
& "C:\ml\cloudflared.exe" tunnel --url http://127.0.0.1:5173
