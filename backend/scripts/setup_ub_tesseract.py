import urllib.request
import subprocess
from pathlib import Path

tools_dir = Path("C:/ml/tools")
tools_dir.mkdir(parents=True, exist_ok=True)
downloads_dir = Path("C:/ml/downloads")
downloads_dir.mkdir(parents=True, exist_ok=True)

# 1. Download 7zr.exe
seven_zr = tools_dir / "7zr.exe"
if not seven_zr.exists():
    print("Downloading 7zr.exe...")
    url = "https://github.com/ip7z/7zip/releases/download/26.06/7zr.exe"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp, open(seven_zr, "wb") as f:
        f.write(resp.read())
print("7zr.exe downloaded. Size:", seven_zr.stat().st_size)

# 2. Download 7z extra 7z
extra_7z = downloads_dir / "7z2606-extra.7z"
if not extra_7z.exists():
    print("Downloading 7z2606-extra.7z...")
    url = "https://github.com/ip7z/7zip/releases/download/26.06/7z2606-extra.7z"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp, open(extra_7z, "wb") as f:
        f.write(resp.read())
print("7z extra downloaded. Size:", extra_7z.stat().st_size)

# 3. Extract extra_7z with 7zr.exe
full_7z_dir = tools_dir / "7z_full"
full_7z_dir.mkdir(parents=True, exist_ok=True)
res = subprocess.run([str(seven_zr), "x", str(extra_7z), f"-o{full_7z_dir}", "-y"], capture_output=True, text=True)
print("7zr extract extra return code:", res.returncode)

# 4. Check for 7za.exe
za_exe = full_7z_dir / "x64" / "7za.exe"
if not za_exe.exists():
    za_exe = full_7z_dir / "7za.exe"
print("7za path:", za_exe, "Exists:", za_exe.exists())

# 5. Extract UB-Mannheim Tesseract installer
ub_installer = downloads_dir / "tesseract-ocr-w64-setup-5.4.0.20240606.exe"
ub_target = tools_dir / "tesseract_ub"
ub_target.mkdir(parents=True, exist_ok=True)
print(f"Extracting UB-Mannheim installer to {ub_target}...")
res2 = subprocess.run([str(za_exe), "x", str(ub_installer), f"-o{ub_target}", "-y"], capture_output=True, text=True)
print("7za extract tesseract return code:", res2.returncode)

# Check tesseract.exe
tess_exe = ub_target / "tesseract.exe"
print("Tesseract.exe exists:", tess_exe.exists())
if tess_exe.exists():
    tess_ver = subprocess.run([str(tess_exe), "--version"], capture_output=True, text=True)
    print("TESSERACT VERSION OUTPUT:\n" + tess_ver.stdout)
    if tess_ver.stderr:
        print("TESSERACT STDERR:\n" + tess_ver.stderr)
