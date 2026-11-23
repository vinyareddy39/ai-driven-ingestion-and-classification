import psutil
import os

current_pid = os.getpid()
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        if proc.pid == current_pid:
            continue
        cmdline = " ".join(proc.info.get('cmdline') or []).lower()
        name = (proc.info.get('name') or "").lower()
        if 'vite' in cmdline or 'uvicorn' in cmdline or 'cloudflared' in name or 'cloudflared' in cmdline or 'run_daemon' in cmdline:
            print(f"Killing PID {proc.pid}: {name} - {cmdline[:60]}")
            proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
print("Cleanup complete.")
