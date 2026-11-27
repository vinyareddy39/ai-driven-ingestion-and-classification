$tempClone = "C:\Users\Sri Vidya Reddy\AppData\Local\Temp\test_ml_clean_clone"
if (Test-Path $tempClone) { Remove-Item -Path $tempClone -Recurse -Force }
git clone "C:\ml" $tempClone
Set-Location "$tempClone\backend"
& "C:\ml\.venv311\Scripts\python.exe" -c "import app.core.config_loader, app.models.db, app.adapters.ocr, app.core.auth; print('SUCCESS: Clean clone backend imports functional!')"
Set-Location "C:\ml"
Remove-Item -Path $tempClone -Recurse -Force
Write-Host "Verified and cleaned up clone successfully."
