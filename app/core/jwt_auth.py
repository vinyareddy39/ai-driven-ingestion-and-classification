"""JWT Token Generation, Verification, Password Hashing, and Rate Limiting."""

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from fastapi import HTTPException, status
from app.core.auth import load_dotenv_if_present

_hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)


def get_jwt_secret() -> str:
    """Retrieve JWT secret from environment, falling back to a deterministic development key."""
    load_dotenv_if_present()
    secret = os.getenv("JWT_SECRET")
    if not secret:
        secret = "ecm_insecure_default_dev_secret_replace_in_env_32char"
    return secret


def hash_password(password: str) -> str:
    """Hash password using Argon2id with recommended parameters."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against Argon2 hash with constant-time comparison."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(data_str: str) -> bytes:
    padding = "=" * (4 - (len(data_str) % 4)) if len(data_str) % 4 != 0 else ""
    return base64.urlsafe_b64decode(data_str + padding)


def create_token(payload: Dict[str, Any], expires_in_seconds: int = 1800) -> str:
    """Generate RFC 7519 compliant HS256 signed JWT."""
    secret = get_jwt_secret().encode("utf-8")
    now = int(time.time())
    full_payload = {
        **payload,
        "iat": now,
        "exp": now + expires_in_seconds,
    }

    header = {"alg": "HS256", "typ": "JWT"}
    header_json = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload_json = json.dumps(full_payload, separators=(",", ":")).encode("utf-8")

    segment1 = _b64url_encode(header_json)
    segment2 = _b64url_encode(payload_json)
    signing_input = f"{segment1}.{segment2}".encode("utf-8")

    signature = hmac.new(secret, signing_input, hashlib.sha256).digest()
    segment3 = _b64url_encode(signature)

    return f"{segment1}.{segment2}.{segment3}"


def decode_token(token_str: str) -> Dict[str, Any]:
    """Verify and decode signed JWT; raises HTTPException 401 on failure or expiry."""
    secret = get_jwt_secret().encode("utf-8")
    parts = token_str.split(".")
    if len(parts) != 3:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    segment1, segment2, segment3 = parts
    signing_input = f"{segment1}.{segment2}".encode("utf-8")
    expected_sig = hmac.new(secret, signing_input, hashlib.sha256).digest()

    try:
        provided_sig = _b64url_decode(segment3)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token encoding.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not hmac.compare_digest(expected_sig, provided_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token signature verification failed.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = json.loads(_b64url_decode(segment2).decode("utf-8"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    now = int(time.time())
    if "exp" in payload and payload["exp"] < now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


# ---------------------------------------------------------------------------
# In-Memory Rate Limiting for Login
# ---------------------------------------------------------------------------

_LOGIN_ATTEMPTS: Dict[str, List[float]] = {}
MAX_LOGIN_ATTEMPTS = 5
WINDOW_SECONDS = 300  # 5 minutes


def check_login_rate_limit(key: str):
    """Enforce maximum 5 failed attempts per 5-minute sliding window."""
    now = time.time()
    attempts = _LOGIN_ATTEMPTS.get(key, [])
    # Filter attempts within window
    attempts = [t for t in attempts if now - t < WINDOW_SECONDS]
    _LOGIN_ATTEMPTS[key] = attempts
    if len(attempts) >= MAX_LOGIN_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again after 5 minutes.",
        )


def record_failed_login(key: str):
    """Record a failed login attempt for rate limiting."""
    now = time.time()
    attempts = _LOGIN_ATTEMPTS.get(key, [])
    attempts.append(now)
    _LOGIN_ATTEMPTS[key] = attempts


def reset_failed_login(key: str):
    """Reset failed attempts upon successful login."""
    if key in _LOGIN_ATTEMPTS:
        del _LOGIN_ATTEMPTS[key]
