Start-Process -FilePath "C:\ml\.venv311\Scripts\python.exe" -ArgumentList "-m uvicorn app.api.app:app --host 127.0.0.1 --port 8000" -WorkingDirectory "C:\ml\backend" -WindowStyle Hidden
Start-Process -FilePath "cmd.exe" -ArgumentList "/c cd /d C:\ml\frontend && npx vite --host 0.0.0.0 --port 5173" -WindowStyle Hidden
Start-Sleep -Seconds 4
Get-NetTCPConnection -LocalPort 8000, 5173 -ErrorAction SilentlyContinue | Select-Object LocalPort, State, OwningProcess
