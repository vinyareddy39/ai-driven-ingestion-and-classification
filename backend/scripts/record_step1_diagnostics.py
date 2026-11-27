import json
import os
import subprocess
import sys
import psutil
from datetime import datetime, timezone

output_dir = "evidence/20261126_212000/raw_outputs"
os.makedirs(output_dir, exist_ok=True)

# 1. Git info
try:
    git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    git_status = subprocess.check_output(["git", "status", "--porcelain"], text=True).strip().splitlines()
except Exception as e:
    git_commit = str(e)
    git_status = []

# 2. Environment variable names
env_var_names = sorted(list(os.environ.keys()))

# 3. Ports and Processes
port_listeners = []
for conn in psutil.net_connections(kind='inet'):
    if conn.laddr and conn.laddr.port in (8000, 5173):
        try:
            proc = psutil.Process(conn.pid) if conn.pid else None
            port_listeners.append({
                "port": conn.laddr.port,
                "ip": conn.laddr.ip,
                "status": conn.status,
                "pid": conn.pid,
                "name": proc.name() if proc else None,
                "cmdline": " ".join(proc.cmdline()[:3]) if proc else None
            })
        except Exception:
            port_listeners.append({
                "port": conn.laddr.port,
                "ip": conn.laddr.ip,
                "status": conn.status,
                "pid": conn.pid
            })

# 4. Storage and DB
db_path = os.path.abspath("data/ecm_pipeline.db")
storage_path = os.path.abspath("data/storage")

# 5. Database size & table count
db_exists = os.path.exists(db_path)
storage_exists = os.path.exists(storage_path)

state = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "urls": {
        "frontend_local": "http://localhost:5173",
        "backend_local": "http://127.0.0.1:8000",
        "proxy_route": "/api -> http://127.0.0.1:8000"
    },
    "startup_commands": {
        "backend": ".venv311\\Scripts\\python.exe -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000",
        "frontend": "npm --prefix frontend run dev -- --host 0.0.0.0 --port 5173",
        "background_reader": "In-process thread pool (routes_documents.process_batch_background) + Standalone worker service (app.workers.service)"
    },
    "git": {
        "commit": git_commit,
        "dirty_file_count": len(git_status)
    },
    "env_var_names": env_var_names,
    "port_listeners": port_listeners,
    "storage": {
        "database_file": db_path,
        "database_exists": db_exists,
        "database_size_bytes": os.path.getsize(db_path) if db_exists else 0,
        "storage_dir": storage_path,
        "storage_exists": storage_exists,
        "files_in_storage": len(os.listdir(storage_path)) if storage_exists else 0
    }
}

json_path = os.path.join(output_dir, "step1_system_state.json")
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2)

txt_path = os.path.join(output_dir, "step1_system_state.txt")
with open(txt_path, "w", encoding="utf-8") as f:
    f.write(f"STEP 1 SYSTEM STATE DIAGNOSTICS\n")
    f.write(f"=========================================\n")
    f.write(f"Timestamp: {state['timestamp']}\n")
    f.write(f"Git Commit: {state['git']['commit']}\n")
    f.write(f"Frontend URL: {state['urls']['frontend_local']}\n")
    f.write(f"Backend URL: {state['urls']['backend_local']}\n")
    f.write(f"Database File: {state['storage']['database_file']} (Size: {state['storage']['database_size_bytes']} bytes)\n")
    f.write(f"Storage Directory: {state['storage']['storage_dir']} (Files: {state['storage']['files_in_storage']})\n")
    f.write(f"Port Listeners: {json.dumps(state['port_listeners'], indent=2)}\n")
    f.write(f"Environment Variable Names ({len(env_var_names)}): {', '.join(env_var_names)}\n")

print(f"Recorded diagnostics to {json_path} and {txt_path}")
