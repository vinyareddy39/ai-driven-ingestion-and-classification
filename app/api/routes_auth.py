"""Authentication API routes: login, logout, me, and admin user management."""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from app.core.auth import get_current_user, require_role
from app.core.jwt_auth import (
    check_login_rate_limit,
    create_token,
    decode_token,
    hash_password,
    record_failed_login,
    reset_failed_login,
    revoke_token,
    verify_password,
)
from app.models.api_schemas import UserSessionResponse
from app.models.db import AuditEventModel, UserModel, get_db_session
from app.models.prescription_schemas import (
    AdminPasswordResetRequest,
    AdminRoleUpdateRequest,
    AdminUserCreateRequest,
    AdminUserStatusRequest,
    AuthUserResponse,
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserSignupRequest,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


def _get_client_ip(request: Request) -> str:
    """Extract client IP address safely, checking proxy headers."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def _log_auth_event(
    db,
    event_type: str,
    status_str: str,
    user_id: Optional[str] = None,
    email: Optional[str] = None,
    ip: str = "127.0.0.1",
    extra: Optional[Dict[str, Any]] = None,
):
    """Write an immutable audit log entry for authentication events."""
    payload = {
        "user_id": user_id,
        "email": email,
        "client_ip": ip,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)

    evt = AuditEventModel(
        event_id=f"evt-auth-{uuid.uuid4().hex[:12]}",
        document_uid=user_id or "auth-system",
        sha256="",
        event_type=event_type,
        stage_name="auth",
        status=status_str,
        payload_json=json.dumps(payload),
        created_at=datetime.now(timezone.utc),
    )
    db.add(evt)
    db.commit()


@router.post("/signup", response_model=AuthUserResponse, status_code=status.HTTP_201_CREATED)
def signup(req: UserSignupRequest, request: Request):
    """Register a new user account with Argon2id hashed credentials."""
    db = get_db_session()
    try:
        existing = db.query(UserModel).filter(UserModel.email == req.email.lower().strip()).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email address already exists.",
            )

        user_id = f"usr-{uuid.uuid4().hex[:12]}"
        hashed_pw = hash_password(req.password)
        now = datetime.now(timezone.utc)
        name = req.email.split("@")[0].replace(".", " ").title()

        new_user = UserModel(
            id=user_id,
            name=name,
            email=req.email.lower().strip(),
            password_hash=hashed_pw,
            role=req.role or "uploader",
            created_at=now,
            disabled=False,
        )
        db.add(new_user)
        db.commit()

        _log_auth_event(
            db,
            event_type="USER_CREATED",
            status_str="SUCCESS",
            user_id=new_user.id,
            email=new_user.email,
            ip=_get_client_ip(request),
            extra={"role": new_user.role, "self_registered": True},
        )

        return AuthUserResponse(
            user_id=new_user.id,
            name=new_user.name,
            email=new_user.email,
            role=new_user.role,
            created_at=new_user.created_at,
        )
    finally:
        db.close()


@router.post("/login", response_model=TokenResponse)
def login(req: UserLoginRequest, request: Request, response: Response):
    """Authenticate with email and password, returning 8-hour token and user profile."""
    email_clean = req.email.lower().strip()
    client_ip = _get_client_ip(request)

    # 1. Rate limiting check: 5 failed attempts per email in 10 minutes -> 429 for 10 minutes
    check_login_rate_limit(email_clean)

    db = get_db_session()
    try:
        user = db.query(UserModel).filter(UserModel.email == email_clean).first()

        # 2. Verify password with constant-time comparison
        if not user or not verify_password(req.password, user.password_hash):
            record_failed_login(email_clean)
            _log_auth_event(
                db,
                event_type="LOGIN_FAILURE",
                status_str="FAILURE",
                email=email_clean,
                ip=client_ip,
                extra={"reason": "Invalid credentials"},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="That email or password isn't right. Try again.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 3. Check if account is disabled
        if user.disabled:
            _log_auth_event(
                db,
                event_type="LOGIN_FAILURE",
                status_str="FAILURE",
                user_id=user.id,
                email=email_clean,
                ip=client_ip,
                extra={"reason": "Account disabled"},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled. Please contact customer support.",
            )

        # 4. Successful login: clear rate limit counter
        reset_failed_login(email_clean)

        user_name = user.name or user.email.split("@")[0].replace(".", " ").title()
        expires_in = 28800  # 8 hours

        # 5. Create signed 8-hour JWT token
        access_token = create_token(
            payload={
                "sub": user.id,
                "email": user.email,
                "name": user_name,
                "role": user.role,
                "type": "access",
            },
            expires_in_seconds=expires_in,
        )

        # 6. Set httpOnly session cookie for direct browser links and downloads
        response.set_cookie(
            key="access_token",
            value=access_token,
            max_age=expires_in,
            httponly=True,
            samesite="lax",
            secure=False,  # True in production HTTPS
        )

        _log_auth_event(
            db,
            event_type="LOGIN_SUCCESS",
            status_str="SUCCESS",
            user_id=user.id,
            email=user.email,
            ip=client_ip,
            extra={"role": user.role},
        )

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=expires_in,
            name=user_name,
            email=user.email,
            role=user.role,
        )
    finally:
        db.close()


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(
    request: Request,
    response: Response,
    current_user: UserSessionResponse = Depends(get_current_user),
):
    """Revoke active session token immediately and clear httpOnly session cookie."""
    client_ip = _get_client_ip(request)

    # Extract token from header, cookie, or query param
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    elif "access_token" in request.cookies:
        token = request.cookies.get("access_token")
    elif "token" in request.query_params:
        token = request.query_params.get("token")

    if token:
        revoke_token(token, user_id=current_user.user_id)

    # Clear session cookie
    response.delete_cookie(key="access_token")

    db = get_db_session()
    try:
        _log_auth_event(
            db,
            event_type="LOGOUT",
            status_str="SUCCESS",
            user_id=current_user.user_id,
            email=current_user.username,
            ip=client_ip,
        )
    finally:
        db.close()

    return {"status": "logged_out", "message": "Session successfully terminated."}


@router.get("/me", response_model=AuthUserResponse)
def get_authenticated_user(current_user: UserSessionResponse = Depends(get_current_user)):
    """Retrieve profile and role for currently authenticated user."""
    return AuthUserResponse(
        user_id=current_user.user_id,
        name=current_user.name or current_user.username.split("@")[0].title(),
        email=current_user.username,
        role=current_user.role,
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Admin User Management Endpoints (Admin role only)
# ---------------------------------------------------------------------------

@router.post("/users", response_model=AuthUserResponse, status_code=status.HTTP_201_CREATED)
def admin_create_user(
    req: AdminUserCreateRequest,
    request: Request,
    admin_user: UserSessionResponse = Depends(require_role(["admin"])),
):
    """Admin only: Create a new user account with specified role and hashed password."""
    db = get_db_session()
    try:
        clean_email = req.email.lower().strip()
        existing = db.query(UserModel).filter(UserModel.email == clean_email).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"User with email '{clean_email}' already exists.",
            )

        user_id = f"usr-{uuid.uuid4().hex[:12]}"
        hashed_pw = hash_password(req.password)
        name = req.name or clean_email.split("@")[0].replace(".", " ").title()

        new_user = UserModel(
            id=user_id,
            name=name,
            email=clean_email,
            password_hash=hashed_pw,
            role=req.role.lower().strip(),
            created_at=datetime.now(timezone.utc),
            disabled=False,
        )
        db.add(new_user)
        db.commit()

        _log_auth_event(
            db,
            event_type="USER_CREATED",
            status_str="SUCCESS",
            user_id=new_user.id,
            email=new_user.email,
            ip=_get_client_ip(request),
            extra={"created_by": admin_user.user_id, "role": new_user.role},
        )

        return AuthUserResponse(
            user_id=new_user.id,
            name=new_user.name,
            email=new_user.email,
            role=new_user.role,
            created_at=new_user.created_at,
        )
    finally:
        db.close()


@router.get("/users", response_model=List[AuthUserResponse])
def admin_list_users(admin_user: UserSessionResponse = Depends(require_role(["admin"]))):
    """Admin only: List all registered user accounts."""
    db = get_db_session()
    try:
        users = db.query(UserModel).order_by(UserModel.created_at.desc()).all()
        return [
            AuthUserResponse(
                user_id=u.id,
                name=u.name or u.email.split("@")[0].title(),
                email=u.email,
                role=u.role,
                created_at=u.created_at,
            )
            for u in users
        ]
    finally:
        db.close()


@router.put("/users/{user_id}/role", response_model=AuthUserResponse)
def admin_change_user_role(
    user_id: str,
    req: AdminRoleUpdateRequest,
    request: Request,
    admin_user: UserSessionResponse = Depends(require_role(["admin"])),
):
    """Admin only: Change a user's role (uploader, reviewer, admin)."""
    db = get_db_session()
    try:
        user = db.query(UserModel).filter(UserModel.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found")

        old_role = user.role
        user.role = req.role.lower().strip()
        db.commit()

        _log_auth_event(
            db,
            event_type="ROLE_CHANGED",
            status_str="SUCCESS",
            user_id=user.id,
            email=user.email,
            ip=_get_client_ip(request),
            extra={"changed_by": admin_user.user_id, "old_role": old_role, "new_role": user.role},
        )

        return AuthUserResponse(
            user_id=user.id,
            name=user.name or user.email.split("@")[0].title(),
            email=user.email,
            role=user.role,
            created_at=user.created_at,
        )
    finally:
        db.close()


@router.put("/users/{user_id}/status")
def admin_set_user_status(
    user_id: str,
    req: AdminUserStatusRequest,
    admin_user: UserSessionResponse = Depends(require_role(["admin"])),
):
    """Admin only: Deactivate or activate a user account."""
    db = get_db_session()
    try:
        user = db.query(UserModel).filter(UserModel.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found")

        user.disabled = req.disabled
        db.commit()
        return {"status": "success", "user_id": user.id, "disabled": user.disabled}
    finally:
        db.close()


@router.post("/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: str,
    req: AdminPasswordResetRequest,
    admin_user: UserSessionResponse = Depends(require_role(["admin"])),
):
    """Admin only: Reset a user's password with Argon2id hash."""
    db = get_db_session()
    try:
        user = db.query(UserModel).filter(UserModel.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User '{user_id}' not found")

        user.password_hash = hash_password(req.new_password)
        db.commit()
        return {"status": "success", "message": f"Password reset successfully for {user.email}"}
    finally:
        db.close()
