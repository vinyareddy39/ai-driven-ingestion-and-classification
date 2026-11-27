import subprocess
import sys
import time
import os

# Kill existing instances if any
os.system("taskkill /F /IM cloudflared.exe 2>nul")

DETACHED_FLAGS = (
    subprocess.CREATE_NEW_PROCESS_GROUP
    | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
)

print("[1] Launching Backend on port 8000...")
backend_cmd = [
    r"C:\ml\.venv311\Scripts\python.exe",
    "-m",
    "uvicorn",
    "app.api.app:app",
    "--host",
    "127.0.0.1",
    "--port",
    "8000",
]
p_backend = subprocess.Popen(
    backend_cmd,
    cwd=r"C:\ml",
    creationflags=DETACHED_FLAGS,
    stdout=open(r"C:\ml\backend.log", "w"),
    stderr=subprocess.STDOUT,
)

print("[2] Launching Frontend on port 5173...")
frontend_cmd = [
    "cmd.exe",
    "/c",
    "node",
    r"node_modules\vite\bin\vite.js",
    "--host",
    "0.0.0.0",
    "--port",
    "5173",
]
p_frontend = subprocess.Popen(
    frontend_cmd,
    cwd=r"C:\ml\frontend",
    creationflags=DETACHED_FLAGS,
    stdout=open(r"C:\ml\frontend.log", "w"),
    stderr=subprocess.STDOUT,
)

time.sleep(4)

print("[3] Launching Cloudflare Tunnel...")
# Remove old tunnel log
try:
    os.remove(r"C:\ml\tunnel.log")
except Exception:
    pass

tunnel_cmd = [
    r"C:\ml\cloudflared.exe",
    "tunnel",
    "--url",
    "http://127.0.0.1:5173",
    "--logfile",
    r"C:\ml\tunnel.log",
]
p_tunnel = subprocess.Popen(
    tunnel_cmd,
    cwd=r"C:\ml",
    creationflags=DETACHED_FLAGS,
)

# Wait up to 10 seconds for the tunnel URL to appear in tunnel.log
url = None
for _ in range(20):
    time.sleep(1)
    if os.path.exists(r"C:\ml\tunnel.log"):
        with open(r"C:\ml\tunnel.log", "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            for line in content.splitlines():
                if "trycloudflare.com" in line:
                    # Look for https://...
                    import re
                    m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                    if m:
                        url = m.group(0)
                        break
            if url:
                break

if url:
    print(f"SUCCESS_URL: {url}")
else:
    print("WAITING_URL...")
