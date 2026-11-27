import os
import sys
import shutil
import hashlib
import subprocess
import urllib.request
from pathlib import Path

DOWNLOAD_URL = "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
TESSDATA_BEST_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/eng.traineddata"

download_dir = Path("C:/ml/downloads")
download_dir.mkdir(parents=True, exist_ok=True)
installer_path = download_dir / "tesseract-ocr-w64-setup-5.4.0.20240606.exe"

install_dir = Path("C:/ml/tools/tesseract_ub")
old_dir = Path("C:/ml/tools/tesseract")

print("1. Removing unofficial Tesseract binary...")
if old_dir.exists():
    try:
        shutil.rmtree(old_dir)
        print(f"   Removed old directory: {old_dir}")
    except Exception as e:
        print(f"   Warning removing old directory: {e}")

print("2. Downloading official UB-Mannheim Tesseract installer...")
if not installer_path.exists() or installer_path.stat().st_size == 0:
    req = urllib.request.Request(DOWNLOAD_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(installer_path, "wb") as out:
        shutil.copyfileobj(resp, out)
    print(f"   Downloaded {installer_path.name} ({installer_path.stat().st_size} bytes)")
else:
    print(f"   Installer already exists: {installer_path} ({installer_path.stat().st_size} bytes)")

# Compute SHA-256
sha256 = hashlib.sha256()
with open(installer_path, "rb") as f:
    for chunk in iter(lambda: f.read(65536), b""):
        sha256.update(chunk)
installer_hash = sha256.hexdigest()
print(f"   Installer SHA-256 Checksum: {installer_hash}")

print("3. Executing silent installation to C:\\ml\\tools\\tesseract_ub...")
install_dir.mkdir(parents=True, exist_ok=True)
# NSIS installer command line: /S /D=target
cmd = [str(installer_path), "/S", f"/D={install_dir}"]
print(f"   Running: {' '.join(cmd)}")
proc = subprocess.run(cmd, capture_output=True, text=True)
print(f"   Installer exited with code: {proc.returncode}")

# Check if tesseract.exe exists in install_dir
tess_exe = install_dir / "tesseract.exe"
print(f"   Tesseract executable exists: {tess_exe.exists()}")

print("4. Downloading tessdata_best for English...")
tessdata_dir = install_dir / "tessdata"
tessdata_dir.mkdir(parents=True, exist_ok=True)
best_eng = tessdata_dir / "eng.traineddata"
print(f"   Fetching {TESSDATA_BEST_URL}...")
req = urllib.request.Request(TESSDATA_BEST_URL, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=120) as resp, open(best_eng, "wb") as out:
    shutil.copyfileobj(resp, out)

sha_best = hashlib.sha256()
with open(best_eng, "rb") as f:
    for chunk in iter(lambda: f.read(65536), b""):
        sha_best.update(chunk)
print(f"   tessdata_best eng.traineddata size: {best_eng.stat().st_size} bytes, SHA-256: {sha_best.hexdigest()}")

print("5. Verifying tesseract installation...")
if tess_exe.exists():
    res = subprocess.run([str(tess_exe), "--version"], capture_output=True, text=True)
    print("   STDOUT:\n" + res.stdout)
    if res.stderr:
        print("   STDERR:\n" + res.stderr)
else:
    print(f"   ERROR: {tess_exe} not found in {install_dir}. Directory contents: {list(install_dir.iterdir())}")
