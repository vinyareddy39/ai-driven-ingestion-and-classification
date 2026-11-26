@echo off
cls
color 0A
echo =======================================================
echo   STARTING ECM INGESTION SYSTEM - LIVE DEMO TUNNEL
echo =======================================================
echo.

echo [1/3] Starting FastAPI Backend on port 8000...
start "Backend - FastAPI" /min "C:\ml\.venv311\Scripts\python.exe" -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000

echo [2/3] Starting React Frontend on port 5173...
start "Frontend - Vite" /min cmd /c "cd /d C:\ml\frontend && node node_modules\vite\bin\vite.js --host 0.0.0.0 --port 5173"

echo Waiting 3 seconds for local servers to initialize...
timeout /t 3 /nobreak >nul

echo [3/3] Launching Cloudflare Public Tunnel...
echo.
echo Look for the link below ending in trycloudflare.com:
echo =======================================================
"C:\ml\cloudflared.exe" tunnel --url http://127.0.0.1:5173
pause
