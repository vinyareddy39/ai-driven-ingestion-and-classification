$ErrorActionPreference = "Continue"

Write-Host "Stopping any stale uvicorn or vite processes..."
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*uvicorn*" } | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "Starting FastAPI Backend on http://127.0.0.1:8000..."
$b = Start-Process -FilePath "C:\ml\.venv311\Scripts\python.exe" -ArgumentList "-m uvicorn app.api.app:app --host 127.0.0.1 --port 8000" -WorkingDirectory "C:\ml\backend" -PassThru -WindowStyle Hidden

Start-Sleep -Seconds 3

Write-Host "Starting Vite Frontend on http://127.0.0.1:5173..."
$f = Start-Process -FilePath "cmd.exe" -ArgumentList "/c cd /d C:\ml\frontend && node node_modules\vite\bin\vite.js --host 0.0.0.0 --port 5173" -PassThru -WindowStyle Hidden

Start-Sleep -Seconds 3

Write-Host "Stopping old cloudflared processes..."
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "Starting Cloudflare tunnel..."
if (Test-Path "C:\ml\tunnel.log") {
    Remove-Item "C:\ml\tunnel.log" -Force -ErrorAction SilentlyContinue
}

$c = Start-Process -FilePath "C:\ml\cloudflared.exe" -ArgumentList "tunnel --url http://127.0.0.1:5173 --logfile C:\ml\tunnel.log" -PassThru -WindowStyle Hidden

Write-Host "Waiting for tunnel URL in tunnel.log..."
$tunnelUrl = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path "C:\ml\tunnel.log") {
        $content = Get-Content "C:\ml\tunnel.log" -Raw
        if ($content -match "https://[a-zA-Z0-9-]+\.trycloudflare\.com") {
            $tunnelUrl = $matches[0]
            break
        }
    }
}

Write-Host "=========================================="
Write-Host "Backend PID: $($b.Id)"
Write-Host "Frontend PID: $($f.Id)"
Write-Host "Cloudflared PID: $($c.Id)"
if ($tunnelUrl) {
    Write-Host "ACTIVE TUNNEL URL: $tunnelUrl" -ForegroundColor Green
} else {
    Write-Host "Tunnel did not return URL within 30s. Check tunnel.log." -ForegroundColor Yellow
}
Write-Host "=========================================="
