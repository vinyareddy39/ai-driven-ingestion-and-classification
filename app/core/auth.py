"""ROLE-BASED AUTHENTICATION MODULE.

Supports Bearer token authentication dynamically loaded from environment (.env).
Unknown tokens return 401. X-User-Role header is ONLY accepted when AUTH_ALLOW_ROLE_HEADER=true (default false).
Fails startup if no tokens are configured and AUTH_ALLOW_ROLE_HEADER is false.
"""

import os
from typing import Dict, List, Optional
from fastapi import Depends, Header, HTTPException, status
from app.models.api_schemas import UserSessionResponse

# Pre-configured user definitions
STUB_USERS = {
    "reviewer": {
        "user_id": "usr-rev-01",
        "username": "reviewer@ecm.local",
        "role": "reviewer",
        "permissions": ["review:read", "review:action", "documents:read"],
    },
    "admin": {
        "user_id": "usr-adm-01",
        "username": "admin@ecm.local",
        "role": "admin",
        "permissions": [
            "admin:config",
            "admin:history",
            "review:read",
            "review:action",
            "documents:read",
            "reprocess:execute",
            "audit:read",
            "compliance:read",
            "ingest:write",
        ],
    },
    "compliance": {
        "user_id": "usr-cmp-01",
        "username": "compliance@ecm.local",
        "role": "compliance",
        "permissions": ["compliance:read", "documents:read", "audit:read"],
    },
    "viewer": {
        "user_id": "usr-viw-01",
        "username": "viewer@ecm.local",
        "role": "viewer",
        "permissions": ["dashboard:read", "documents:read"],
    },
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
    """Check if X-User-Role header bypass is explicitly enabled via environment."""
    load_dotenv_if_present()
    return os.getenv("AUTH_ALLOW_ROLE_HEADER", "false").lower() in ("true", "1", "yes")


def get_configured_tokens() -> Dict[str, str]:
    """Parse token:role pairs configured in AUTH_TOKENS environment variable."""
    load_dotenv_if_present()
    raw = os.getenv("AUTH_TOKENS", "").strip()
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
    if not tokens and not allow_header:
        raise RuntimeError(
            "Security configuration error: No AUTH_TOKENS configured in environment (.env) "
            "and AUTH_ALLOW_ROLE_HEADER is false. Server refuses to start in an unauthenticated state."
        )


def get_current_user(
    x_user_role: Optional[str] = Header(default=None, alias="X-User-Role"),
    authorization: Optional[str] = Header(default=None),
) -> UserSessionResponse:
    """Extract authenticated user session from Bearer token or permitted role header."""
    role: Optional[str] = None
    configured_tokens = get_configured_tokens()

    # 1. Check if X-User-Role is allowed by config
    if x_user_role:
        if not is_role_header_allowed():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-User-Role header is disabled. Provide a valid Bearer token in the Authorization header.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        candidate = x_user_role.lower().strip()
        if candidate in STUB_USERS:
            role = candidate
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid authentication role '{candidate}'.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # 2. Extract Bearer token from Authorization header
    elif authorization:
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed Authorization header. Format must be 'Bearer <token>'",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = parts[1].strip()
        if token in configured_tokens:
            role = configured_tokens[token]
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or unknown authentication token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # 3. No credentials provided
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided. Include 'Authorization: Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_data = STUB_USERS[role]
    return UserSessionResponse(
        user_id=user_data["user_id"],
        username=user_data["username"],
        role=user_data["role"],
        permissions=user_data["permissions"],
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
