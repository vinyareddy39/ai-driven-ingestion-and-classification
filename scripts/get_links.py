import urllib.request
import re

req = urllib.request.Request("https://www.7-zip.org/download.html", headers={"User-Agent": "Mozilla/5.0"})
html = urllib.request.urlopen(req, timeout=15).read().decode()
links = re.findall(r'href=[\"\'](a/[^\"\']+)[\"\']', html)
print("Found links:", links)
