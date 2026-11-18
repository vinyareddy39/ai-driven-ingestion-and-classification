import urllib.request
import hashlib
from pathlib import Path

best_url = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/eng.traineddata"
target_file = Path("C:/ml/tools/tesseract_ub/tessdata/eng.traineddata")

print(f"Downloading tessdata_best from {best_url}...")
req = urllib.request.Request(best_url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=120) as resp, open(target_file, "wb") as f:
    f.write(resp.read())

sha256 = hashlib.sha256()
with open(target_file, "rb") as f:
    for chunk in iter(lambda: f.read(65536), b""):
        sha256.update(chunk)

print(f"tessdata_best eng.traineddata installed: {target_file.stat().st_size} bytes")
print(f"SHA-256: {sha256.hexdigest()}")
