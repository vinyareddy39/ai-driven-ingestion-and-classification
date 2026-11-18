import urllib.request
import subprocess
from pathlib import Path

url = "https://github.com/ip7z/7zip/releases/download/26.06/7z2606-x64.exe"
dest = Path("C:/ml/downloads/7z2606-x64.exe")
if not dest.exists():
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as f:
        f.write(resp.read())

seven_zr = Path("C:/ml/tools/7zr.exe")
out_dir = Path("C:/ml/tools/7z_real")
out_dir.mkdir(parents=True, exist_ok=True)
res = subprocess.run([str(seven_zr), "x", str(dest), f"-o{out_dir}", "-y"], capture_output=True, text=True)
print("Return code:", res.returncode)
print("Files:", [p.name for p in out_dir.iterdir()])
