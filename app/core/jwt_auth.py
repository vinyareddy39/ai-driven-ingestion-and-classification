"""JWT Authentication and Bcrypt Password Hashing."""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional
import bcrypt
from fastapi import Depends, HTTPException, Header, Request, status
from sqlalchemy.orm import Session

from app.models.db import UserModel, get_db

JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-docsort-key-change-in-prod-xyz789")
JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """Hash password using standard bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _b64_url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64_url_decode(s: str) -> bytes:
    padding = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode((s + padding).encode("utf-8"))


def create_token(payload: Dict[str, Any], expires_in_seconds: int = 86400 * 7) -> str:
    """Generate a standard HS256 JWT token."""
    header = {"alg": "HS256", "typ": "JWT"}
    body = dict(payload)
    now = int(time.time())
    body["iat"] = now
    body["exp"] = now + expires_in_seconds

    header_b64 = _b64_url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    body_b64 = _b64_url_encode(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{body_b64}".encode("utf-8")

    sig = hmac.new(JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64_url_encode(sig)

    return f"{header_b64}.{body_b64}.{sig_b64}"


def decode_token(token: str) -> Dict[str, Any]:
    """Verify and decode an HS256 JWT token."""
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")

    header_b64, body_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{body_b64}".encode("utf-8")
    expected_sig = hmac.new(JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()

    try:
        actual_sig = _b64_url_decode(sig_b64)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token signature encoding")

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token signature")

    try:
        body = json.loads(_b64_url_decode(body_b64).decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    exp = body.get("exp")
    if exp and int(time.time()) > exp:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")

    return body


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> UserModel:
    """Extract authenticated user from Authorization header or cookie or query param."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    elif "access_token" in request.cookies:
        token = request.cookies.get("access_token")
    elif "token" in request.query_params:
        token = request.query_params.get("token")

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    payload = decode_token(token)
    user_id = payload.get("sub") or payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token claims")

    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user
