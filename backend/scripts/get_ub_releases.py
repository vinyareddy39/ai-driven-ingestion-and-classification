import urllib.request
import json
import hashlib
from pathlib import Path

# Get release info
api_url = "https://api.github.com/repos/UB-Mannheim/tesseract/releases"
req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read().decode())

print("Found releases:")
for r in data[:3]:
    print(f"Tag: {r.get('tag_name')}")
    for asset in r.get("assets", []):
        print(f"  Asset: {asset['name']} ({asset['size']} bytes) -> {asset['browser_download_url']}")
