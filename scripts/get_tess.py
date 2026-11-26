import urllib.request
import re

url = "https://digi.bib.uni-mannheim.de/tesseract/"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode("utf-8")
    matches = re.findall(r'href="(tesseract-ocr-w64-setup-[^"]+\.exe)"', html)
    print("Found files:", matches[-5:])
except Exception as e:
    print("Error:", e)
