import sys
import os
sys.path.insert(0, os.path.abspath("."))
import threading

import time
import traceback
import os

os.environ["DISABLE_LIFESPAN_WORKER"] = "1"

def print_stacks():
    time.sleep(5)
    while True:
        print("\n--- Periodic Stack Trace ---", flush=True)
        for thread_id, frame in sys._current_frames().items():
            print(f"Thread {thread_id}:", flush=True)
            traceback.print_stack(frame)
        time.sleep(5)

t = threading.Thread(target=print_stacks, daemon=True)
t.start()

print("1. Starting import of app...", flush=True)
from app.api.app import app
print("2. app imported. Creating TestClient...", flush=True)
from fastapi.testclient import TestClient
client = TestClient(app)
print("3. TestClient created. Making GET request...", flush=True)
r = client.get("/api/v1/system/info")
print("4. Done GET! Status:", r.status_code, flush=True)
