"""Live HTTP and CORS Verification Script.

Starts real Uvicorn server on localhost and executes real HTTP requests
testing CORS preflight, unauthenticated 401, bad token 401, cross-user 404, and authenticated 200.
"""

import sys
sys.path.insert(0, ".")
import threading
import time
import urllib.request
import urllib.error
import uvicorn

from app.api.app import app
from app.core.auth import get_configured_tokens
from app.core.jwt_auth import create_jwt_token
from app.models.db import init_db


def run_live_verification():
    init_db()

    # Configure real uvicorn server on port 8000
    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning")
    server = uvicorn.Server(config)

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # Wait for server startup
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)

    print(f"Server started on 127.0.0.1:8000: {server.started}")

    base_url = "http://127.0.0.1:8000"
    results = []

    # 1. CORS Preflight OPTIONS
    try:
        req = urllib.request.Request(
            f"{base_url}/api/v1/system/info",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
            method="OPTIONS",
        )
        with urllib.request.urlopen(req) as resp:
            cors_header = resp.headers.get("Access-Control-Allow-Origin")
            print(f"CORS OPTIONS Status: {resp.status}, Allow-Origin: {cors_header}")
            results.append(("CORS_PREFLIGHT", resp.status == 200 and cors_header is not None))
    except Exception as e:
        print(f"CORS error: {e}")
        results.append(("CORS_PREFLIGHT", False))

    # 2. No Token on Protected Endpoint -> Expect 401
    try:
        req = urllib.request.Request(f"{base_url}/api/v1/documents/doc-test-kyc-001/pages/1/image", method="GET")
        with urllib.request.urlopen(req) as resp:
            results.append(("NO_TOKEN_401", False))
    except urllib.error.HTTPError as e:
        print(f"No Token Status: {e.code} (detail: {e.read().decode('utf-8')[:60]}...)")
        results.append(("NO_TOKEN_401", e.code == 401))

    # 3. Bad Token -> Expect 401
    try:
        req = urllib.request.Request(
            f"{base_url}/api/v1/system/info",
            headers={"Authorization": "Bearer bad_invalid_token_xyz"},
            method="GET",
        )
        with urllib.request.urlopen(req) as resp:
            results.append(("BAD_TOKEN_401", False))
    except urllib.error.HTTPError as e:
        print(f"Bad Token Status: {e.code}")
        results.append(("BAD_TOKEN_401", e.code == 401))

    # 4. Valid Staff Token -> Expect 200
    token = list(get_configured_tokens().keys())[0]
    try:
        req = urllib.request.Request(
            f"{base_url}/api/v1/system/info",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            print(f"Valid Token Status: {resp.status}, Body: {body[:80]}...")
            results.append(("VALID_TOKEN_200", resp.status == 200))
    except Exception as e:
        print(f"Valid token error: {e}")
        results.append(("VALID_TOKEN_200", False))

    # 5. User Isolation on Batch Endpoint: User B requesting User A's batch -> Expect 404
    token_b = create_jwt_token(user_id="usr-patient-b", role="patient")
    try:
        req = urllib.request.Request(
            f"{base_url}/api/v1/batches/batch-usr-a-101",
            headers={"Authorization": f"Bearer {token_b}"},
            method="GET",
        )
        with urllib.request.urlopen(req) as resp:
            results.append(("USER_ISOLATION_404", False))
    except urllib.error.HTTPError as e:
        print(f"User B requesting User A batch Status: {e.code}")
        results.append(("USER_ISOLATION_404", e.code == 404))

    # 6. User Isolation on Batch Endpoint: User A requesting own batch -> Expect 200
    token_a = create_jwt_token(user_id="usr-patient-a", role="patient")
    try:
        req = urllib.request.Request(
            f"{base_url}/api/v1/batches/batch-usr-a-101",
            headers={"Authorization": f"Bearer {token_a}"},
            method="GET",
        )
        with urllib.request.urlopen(req) as resp:
            print(f"User A requesting own batch Status: {resp.status}")
            results.append(("OWNER_BATCH_200", resp.status == 200))
    except Exception as e:
        print(f"Owner batch error: {e}")
        results.append(("OWNER_BATCH_200", False))

    # Shut down server
    server.should_exit = True
    time.sleep(0.5)

    print("\n=== LIVE HTTP VERIFICATION SUMMARY ===")
    all_ok = True
    for name, passed in results:
        status_str = "PASS" if passed else "FAIL"
        print(f"  [{status_str}] {name}")
        if not passed:
            all_ok = False

    return all_ok


if __name__ == "__main__":
    import sys
    success = run_live_verification()
    sys.exit(0 if success else 1)
