import json
import os
import urllib.request
from pathlib import Path

target_dir = Path("C:/ml/tools/tesseract")
target_dir.mkdir(parents=True, exist_ok=True)
tessdata_dir = target_dir / "tessdata"
tessdata_dir.mkdir(parents=True, exist_ok=True)

api_url = "https://api.github.com/repos/azmat21/Tesseract4.0WindowBinaries/contents/x64"
req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})

print("Fetching x64 file list...")
with urllib.request.urlopen(req, timeout=15) as r:
    files = json.loads(r.read())

print(f"Downloading {len(files)} files to {target_dir}...")
for f in files:
    fname = f["name"]
    download_url = f["download_url"]
    dest = target_dir / fname
    if not dest.exists() or dest.stat().st_size == 0:
        print(f"  Downloading {fname}...")
        urllib.request.urlretrieve(download_url, dest)

eng_data = tessdata_dir / "eng.traineddata"
if not eng_data.exists() or eng_data.stat().st_size == 0:
    print("Downloading eng.traineddata...")
    urllib.request.urlretrieve(
        "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata",
        eng_data
    )

print("Tesseract binary installation complete.")
