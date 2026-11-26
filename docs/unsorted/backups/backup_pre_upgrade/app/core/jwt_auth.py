"""JWT Token Generation, Verification, Password Hashing, Revocation, and Rate Limiting."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from fastapi import HTTPException, status
from app.core.auth import load_dotenv_if_present

_hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)

# In-memory fast cache for revoked token hashes (populated on startup)
_REVOKED_TOKENS: Set[str] = set()
_CACHE_INITIALIZED: bool = False


def _init_revocation_cache():
    """Load unexpired revoked token hashes from database into memory."""
    global _REVOKED_TOKENS, _CACHE_INITIALIZED
    if _CACHE_INITIALIZED:
        return
    try:
        from app.models.db import get_db_session, RevokedTokenModel
        db = get_db_session()
        try:
            now = int(time.time())
            rows = db.query(RevokedTokenModel).filter(RevokedTokenModel.expires_at > now).all()
            for r in rows:
                _REVOKED_TOKENS.add(r.token_hash)
            _CACHE_INITIALIZED = True
        finally:
            db.close()
    except Exception:
        _CACHE_INITIALIZED = True


def get_jwt_secret() -> str:
    """Retrieve JWT secret from environment or .env, generating a secure secret if unset."""
    load_dotenv_if_present()
    secret = os.getenv("JWT_SECRET")
    if not secret:
        # Generate cryptographically secure secret and persist in process env
        secret = secrets.token_urlsafe(48)
        os.environ["JWT_SECRET"] = secret
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


def create_token(payload: Dict[str, Any], expires_in_seconds: int = 28800) -> str:
    """Generate RFC 7519 compliant HS256 signed JWT (default 8 hours expiry)."""
    secret = get_jwt_secret().encode("utf-8")
    now = int(time.time())
    full_payload = {
        **payload,
        "jti": uuid.uuid4().hex,
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


def create_jwt_token(user_id: str, role: str = "uploader", name: Optional[str] = None, email: Optional[str] = None, expires_in_seconds: int = 28800) -> str:
    """Convenience helper to create signed JWT for a user ID and role."""
    return create_token(
        {"sub": user_id, "role": role, "name": name, "email": email},
        expires_in_seconds=expires_in_seconds
    )


def revoke_token(token_str: str, user_id: Optional[str] = None) -> bool:
    """Revoke a token immediately by adding its SHA-256 hash to revoked_tokens table and cache."""
    _init_revocation_cache()
    token_hash = hashlib.sha256(token_str.strip().encode("utf-8")).hexdigest()
    _REVOKED_TOKENS.add(token_hash)

    # Determine expiry from payload or default to 8 hours
    exp = int(time.time()) + 28800
    try:
        parts = token_str.split(".")
        if len(parts) == 3:
            payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
            if "exp" in payload:
                exp = int(payload["exp"])
            if not user_id and "sub" in payload:
                user_id = payload["sub"]
    except Exception:
        pass

    try:
        from app.models.db import get_db_session, RevokedTokenModel
        db = get_db_session()
        try:
            existing = db.query(RevokedTokenModel).filter(RevokedTokenModel.token_hash == token_hash).first()
            if not existing:
                rev_entry = RevokedTokenModel(
                    token_hash=token_hash,
                    user_id=user_id,
                    expires_at=exp,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(rev_entry)
                db.commit()
        finally:
            db.close()
    except Exception:
        pass

    return True


def is_token_revoked(token_str: str) -> bool:
    """Check if token hash exists in revoked cache or database."""
    _init_revocation_cache()
    token_hash = hashlib.sha256(token_str.strip().encode("utf-8")).hexdigest()
    if token_hash in _REVOKED_TOKENS:
        return True

    try:
        from app.models.db import get_db_session, RevokedTokenModel
        db = get_db_session()
        try:
            row = db.query(RevokedTokenModel).filter(RevokedTokenModel.token_hash == token_hash).first()
            if row:
                _REVOKED_TOKENS.add(token_hash)
                return True
        finally:
            db.close()
    except Exception:
        pass

    return False


def decode_token(token_str: str) -> Dict[str, Any]:
    """Verify and decode signed JWT; raises HTTPException 401 on failure, revocation, or expiry."""
    if is_token_revoked(token_str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked or session ended.",
            headers={"WWW-Authenticate": "Bearer"},
        )

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
# Rate Limiting for Login (5 failed attempts per email in 10 minutes -> 429 for 10 min)
# ---------------------------------------------------------------------------

_LOGIN_ATTEMPTS: Dict[str, List[float]] = {}
_LOGIN_LOCKOUTS: Dict[str, float] = {}
MAX_LOGIN_ATTEMPTS = 5
WINDOW_SECONDS = 600    # 10 minutes
LOCKOUT_SECONDS = 600   # 10 minutes


def check_login_rate_limit(key: str):
    """Enforce maximum 5 failed attempts per 10-minute sliding window with 10-minute lockout."""
    key = key.lower().strip()
    now = time.time()

    # Check active lockout
    locked_until = _LOGIN_LOCKOUTS.get(key, 0.0)
    if now < locked_until:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again after 10 minutes.",
        )

    # Clean expired attempts
    attempts = _LOGIN_ATTEMPTS.get(key, [])
    attempts = [t for t in attempts if now - t < WINDOW_SECONDS]
    _LOGIN_ATTEMPTS[key] = attempts

    if len(attempts) >= MAX_LOGIN_ATTEMPTS:
        _LOGIN_LOCKOUTS[key] = now + LOCKOUT_SECONDS
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again after 10 minutes.",
        )


def record_failed_login(key: str):
    """Record a failed login attempt for rate limiting."""
    key = key.lower().strip()
    now = time.time()
    attempts = _LOGIN_ATTEMPTS.get(key, [])
    attempts = [t for t in attempts if now - t < WINDOW_SECONDS]
    attempts.append(now)
    _LOGIN_ATTEMPTS[key] = attempts
    if len(attempts) >= MAX_LOGIN_ATTEMPTS:
        _LOGIN_LOCKOUTS[key] = now + LOCKOUT_SECONDS


def reset_failed_login(key: str):
    """Reset failed attempts upon successful login."""
    key = key.lower().strip()
    _LOGIN_ATTEMPTS.pop(key, None)
    _LOGIN_LOCKOUTS.pop(key, None)
