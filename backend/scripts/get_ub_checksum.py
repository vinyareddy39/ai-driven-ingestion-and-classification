import urllib.request
import json

api_url = "https://api.github.com/repos/UB-Mannheim/tesseract/releases/tags/v5.4.0.20240606"
req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read().decode())

print("Body:")
print(data.get("body"))
