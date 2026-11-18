import urllib.request
import py7zr
import subprocess
import shutil
from pathlib import Path

# 1. Download 7z extra
extra_url = "https://www.7-zip.org/a/7z2301-extra.7z"
extra_path = Path("C:/ml/downloads/7z2301-extra.7z")
extra_dir = Path("C:/ml/tools/7z")
extra_dir.mkdir(parents=True, exist_ok=True)

if not extra_path.exists():
    print("Downloading 7z-extra...")
    req = urllib.request.Request(extra_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(extra_path, "wb") as f:
        f.write(resp.read())

print("Extracting 7z extra...")
with py7zr.SevenZipFile(extra_path) as z:
    z.extractall(extra_dir)

print("Files in 7z dir:", [p.name for p in extra_dir.iterdir()])

# Check for x64/7za.exe
seven_zip = extra_dir / "x64" / "7za.exe"
if not seven_zip.exists():
    seven_zip = extra_dir / "7za.exe"
print("7za path:", seven_zip)

# 2. Extract UB-Mannheim installer
installer = Path("C:/ml/downloads/tesseract-ocr-w64-setup-5.4.0.20240606.exe")
ub_out = Path("C:/ml/tools/tesseract_ub")
ub_out.mkdir(parents=True, exist_ok=True)

print(f"Extracting {installer} to {ub_out}...")
cmd = [str(seven_zip), "x", str(installer), f"-o{ub_out}", "-y"]
res = subprocess.run(cmd, capture_output=True, text=True)
print("Return code:", res.returncode)
print("Output:\n", res.stdout[-500:] if res.stdout else "No output")
if res.stderr:
    print("Stderr:\n", res.stderr)

tess_exe = ub_out / "tesseract.exe"
print("Tesseract.exe exists:", tess_exe.exists())
