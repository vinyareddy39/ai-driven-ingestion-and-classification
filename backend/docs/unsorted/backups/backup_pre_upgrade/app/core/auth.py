"""ROLE-BASED AUTHENTICATION MODULE.

Supports Bearer token authentication dynamically loaded from environment (.env),
httpOnly session cookies for browser navigation, and signed short-lived query tokens for downloads/previews.
"""

import os
from typing import Dict, List, Optional
from fastapi import Depends, Header, HTTPException, Request, status
from app.models.api_schemas import UserSessionResponse

# Pre-configured user definitions for backwards compatibility
STUB_USERS = {
    "reviewer": {
        "user_id": "usr-rev-01",
        "username": "reviewer@ecm.local",
        "name": "Reviewer Staff",
        "role": "reviewer",
        "permissions": ["upload:create", "batches:read", "batches:download", "review:read", "review:action", "documents:read"],
    },
    "admin": {
        "user_id": "usr-adm-01",
        "username": "admin@ecm.local",
        "name": "Admin System",
        "role": "admin",
        "permissions": [
            "admin:users",
            "admin:config",
            "admin:history",
            "review:read",
            "review:action",
            "documents:read",
            "reprocess:execute",
            "audit:read",
            "compliance:read",
            "ingest:write",
            "batches:read",
            "batches:download",
            "upload:create",
            "pii:read",
        ],
    },
    "uploader": {
        "user_id": "usr-upl-01",
        "username": "uploader@ecm.local",
        "name": "Standard Uploader",
        "role": "uploader",
        "permissions": ["upload:create", "batches:read_own", "batches:download_own", "documents:read_own"],
    },
    "compliance": {
        "user_id": "usr-cmp-01",
        "username": "compliance@ecm.local",
        "name": "Compliance Officer",
        "role": "compliance",
        "permissions": ["compliance:read", "documents:read", "audit:read"],
    },
    "viewer": {
        "user_id": "usr-viw-01",
        "username": "viewer@ecm.local",
        "name": "Read-Only Viewer",
        "role": "viewer",
        "permissions": ["dashboard:read", "documents:read"],
    },
    "patient": {
        "user_id": "usr-patient",
        "username": "patient@ecm.local",
        "name": "Patient User",
        "role": "uploader",
        "permissions": ["upload:create", "batches:read_own", "batches:download_own", "documents:read_own"],
    },
}

ROLE_PERMISSIONS: Dict[str, List[str]] = {
    "uploader": ["upload:create", "batches:read_own", "batches:download_own", "documents:read_own"],
    "reviewer": [
        "upload:create",
        "batches:read",
        "batches:download",
        "review:read",
        "review:action",
        "documents:read",
    ],
    "admin": [
        "admin:users",
        "admin:config",
        "admin:history",
        "review:read",
        "review:action",
        "documents:read",
        "reprocess:execute",
        "audit:read",
        "compliance:read",
        "ingest:write",
        "batches:read",
        "batches:download",
        "upload:create",
        "pii:read",
    ],
    "compliance": ["compliance:read", "documents:read", "audit:read"],
    "viewer": ["dashboard:read", "documents:read"],
    "patient": ["upload:create", "batches:read_own", "batches:download_own", "documents:read_own"],
}


def load_dotenv_if_present():
    """Load key-value pairs from .env into os.environ if not already present."""
    env_paths = [os.path.join(os.getcwd(), ".env"), os.path.abspath(".env")]
    for p in env_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass
            break


def is_role_header_allowed() -> bool:
    """Check if X-User-Role header bypass is explicitly enabled via environment or .env."""
    if os.getenv("ENVIRONMENT", "development").lower() in ("production", "prod"):
        return False
    if "AUTH_ALLOW_ROLE_HEADER" in os.environ:
        return os.environ["AUTH_ALLOW_ROLE_HEADER"].lower() in ("true", "1", "yes")
    load_dotenv_if_present()
    return os.getenv("AUTH_ALLOW_ROLE_HEADER", "false").lower() in ("true", "1", "yes")


def get_configured_tokens() -> Dict[str, str]:
    """Parse token:role pairs configured in AUTH_TOKENS environment variable."""
    load_dotenv_if_present()
    raw = os.getenv("AUTH_TOKENS")
    if not raw:
        try:
            from app.core.settings import get_app_settings
            raw = get_app_settings().AUTH_TOKENS
        except Exception:
            raw = ""
    tokens: Dict[str, str] = {}
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if ":" in part:
                t, r = part.split(":", 1)
                tokens[t.strip()] = r.strip()
    return tokens


def validate_auth_config():
    """Fail startup if no tokens are configured and AUTH_ALLOW_ROLE_HEADER is false."""
    tokens = get_configured_tokens()
    allow_header = is_role_header_allowed()
    jwt_secret = os.getenv("JWT_SECRET")
    if not tokens and not allow_header and not jwt_secret:
        raise RuntimeError(
            "Security configuration error: No AUTH_TOKENS or JWT_SECRET configured in environment (.env). "
            "Server refuses to start in an unauthenticated state."
        )


def get_current_user(
    request: Request,
    x_user_role: Optional[str] = Header(default=None, alias="X-User-Role"),
    authorization: Optional[str] = Header(default=None),
) -> UserSessionResponse:
    """Extract authenticated user session from Bearer token, httpOnly cookie, or signed query token."""
    configured_tokens = get_configured_tokens()
    raw_token: Optional[str] = None

    # 1. Primary: Extract from Authorization header (Bearer token)
    if authorization:
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed Authorization header. Format must be 'Bearer <token>'",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raw_token = parts[1].strip()

    # 2. Secondary: Extract from httpOnly cookie (for browser direct links / downloads)
    elif "access_token" in request.cookies:
        raw_token = request.cookies.get("access_token")

    # 3. Tertiary: Extract from query parameter `?token=` (for signed preview / download URLs)
    elif "token" in request.query_params:
        raw_token = request.query_params.get("token")

    # If a token was provided in header, cookie, or query parameter
    if raw_token:
        # Check revocation (both JWTs and revoked static tokens)
        from app.core.jwt_auth import is_token_revoked
        if is_token_revoked(raw_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Check if token is an RFC 7519 signed JWT
        if raw_token.count(".") == 2:
            from app.core.jwt_auth import decode_token
            payload = decode_token(raw_token)
            role = payload.get("role", "uploader")
            permissions = ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS["uploader"])
            user_id = payload.get("sub", "usr-anonymous")
            email = payload.get("email", "user@docsort.local")
            name = payload.get("name") or email.split("@")[0]

            return UserSessionResponse(
                user_id=user_id,
                username=email,
                name=name,
                role=role,
                permissions=permissions,
            )
        elif raw_token in configured_tokens:
            role = configured_tokens[raw_token]
            user_data = STUB_USERS.get(role, STUB_USERS["viewer"])
            return UserSessionResponse(
                user_id=user_data["user_id"],
                username=user_data["username"],
                name=user_data.get("name", user_data["username"].split("@")[0]),
                role=user_data["role"],
                permissions=user_data["permissions"],
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or unknown authentication token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # 4. Fallback: Check if X-User-Role is allowed by config (dev only)
    if x_user_role:
        if is_role_header_allowed():
            candidate = x_user_role.lower().strip()
            if candidate in STUB_USERS:
                user_data = STUB_USERS[candidate]
                return UserSessionResponse(
                    user_id=user_data["user_id"],
                    username=user_data["username"],
                    name=user_data.get("name", user_data["username"].split("@")[0]),
                    role=user_data["role"],
                    permissions=user_data["permissions"],
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid authentication role '{candidate}'.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-User-Role header is disabled in production.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # 5. No credentials provided at all -> 401
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication credentials were not provided. Include 'Authorization: Bearer <token>' or login session.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_role(allowed_roles: List[str]):
    """FastAPI dependency factory to enforce role-based access control."""
    def role_checker(user: UserSessionResponse = Depends(get_current_user)) -> UserSessionResponse:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied for role '{user.role}'. Required roles: {allowed_roles}",
            )
        return user
    return role_checker
