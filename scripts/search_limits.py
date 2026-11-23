import os
import re

exclude = {".git", "node_modules", "__pycache__", ".venv311", ".cache", "cache", "dist", "data", "downloads", "tools"}

patterns = [
    re.compile(r"25\s*mb", re.I),
    re.compile(r"25\s*\*\s*1024", re.I),
    re.compile(r"26214400"),
    re.compile(r"max.*25", re.I),
    re.compile(r"25.*max", re.I),
    re.compile(r"max_upload", re.I),
    re.compile(r"max_size", re.I),
    re.compile(r"maxsize", re.I),
    re.compile(r"upload.*limit", re.I),
    re.compile(r"file.*limit", re.I),
    re.compile(r"content-length", re.I),
    re.compile(r"client_max_body_size", re.I),
    re.compile(r"413"),
]

for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in exclude]
    for f in files:
        if not f.endswith(('.py', '.ts', '.tsx', '.js', '.jsx', '.json', '.yaml', '.yml', '.env', '.example', '.md', 'Dockerfile', '.conf')):
            continue
        p = os.path.join(root, f)
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                for idx, line in enumerate(fh, 1):
                    for pat in patterns:
                        if pat.search(line):
                            print(f"{p}:{idx}: {line.strip()}")
                            break
        except Exception as e:
            pass
