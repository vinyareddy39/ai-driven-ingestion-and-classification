import subprocess
import time
import os
import sys
import re
import atexit
import signal
import psutil

print("Cleaning up old ECM services...")
current_pid = os.getpid()
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        if proc.pid == current_pid:
            continue
        cmdline = " ".join(proc.info.get('cmdline') or []).lower()
        name = (proc.info.get('name') or "").lower()
        if 'vite' in cmdline or 'uvicorn' in cmdline or 'cloudflared' in name or 'cloudflared' in cmdline:
            proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

time.sleep(1)
print("Starting ECM Ingestion Services with Cloudflare Tunnel...")

# 1. Start Backend
backend_proc = subprocess.Popen(
    [r"C:\ml\.venv311\Scripts\python.exe", "-m", "uvicorn", "app.api.app:app", "--host", "127.0.0.1", "--port", "8000"],
    cwd=r"C:\ml",
)

# 2. Start Frontend
frontend_proc = subprocess.Popen(
    ["cmd.exe", "/c", "node", r"node_modules\vite\bin\vite.js", "--host", "0.0.0.0", "--port", "5173", "--strictPort"],
    cwd=r"C:\ml\frontend",
)

def cleanup():
    print("Shutting down processes...")
    for p in [backend_proc, frontend_proc]:
        try:
            p.terminate()
            p.wait(timeout=2)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass

atexit.register(cleanup)
signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

time.sleep(3)

def start_tunnel():
    return subprocess.Popen(
        [r"C:\ml\cloudflared.exe", "tunnel", "--url", "http://127.0.0.1:5173"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

tunnel_proc = start_tunnel()
url = None
print("Waiting for Cloudflare Tunnel URL...")

while True:
    line = tunnel_proc.stdout.readline()
    if line:
        sys.stdout.write(line)
        sys.stdout.flush()
        m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
        if m and "api.trycloudflare.com" not in m.group(0) and m.group(0) != url:
            url = m.group(0)
            print(f"\n=======================================================")
            print(f"ACTIVE_CLOUDFLARE_LINK: {url}")
            print(f"=======================================================\n")
            try:
                os.makedirs("data", exist_ok=True)
                with open("data/active_tunnel_url.txt", "w", encoding="utf-8") as f:
                    f.write(url + "\n")
            except Exception:
                pass

        # Detect severed / unregistered tunnel connection
        if "unauthorized: tunnel not found" in line.lower():
            print("\nCloudflare reported Tunnel Not Found! Terminating dead tunnel and obtaining a new URL...")
            try:
                tunnel_proc.terminate()
                tunnel_proc.kill()
            except Exception:
                pass

    if tunnel_proc.poll() is not None:
        print("Cloudflare exited or was terminated! Restarting tunnel in 2 seconds...")
        time.sleep(2)
        url = None
        tunnel_proc = start_tunnel()

    time.sleep(0.01)
