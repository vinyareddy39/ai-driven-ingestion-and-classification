"""Authentication API routes: signup, login, refresh, logout, and me."""

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.auth import get_current_user
from app.core.jwt_auth import (
    check_login_rate_limit,
    create_token,
    decode_token,
    hash_password,
    record_failed_login,
    reset_failed_login,
    verify_password,
)
from app.models.api_schemas import UserSessionResponse
from app.models.db import UserModel, get_db_session
from app.models.prescription_schemas import (
    AuthUserResponse,
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserSignupRequest,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/signup", response_model=AuthUserResponse, status_code=status.HTTP_201_CREATED)
def signup(req: UserSignupRequest):
    """Register a new patient or user account with Argon2id hashed credentials."""
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

        new_user = UserModel(
            id=user_id,
            email=req.email.lower().strip(),
            password_hash=hashed_pw,
            role=req.role or "patient",
            created_at=now,
            disabled=False,
        )
        db.add(new_user)
        db.commit()

        return AuthUserResponse(
            user_id=new_user.id,
            email=new_user.email,
            role=new_user.role,
            created_at=new_user.created_at,
        )
    finally:
        db.close()


@router.post("/login", response_model=TokenResponse)
def login(req: UserLoginRequest):
    """Authenticate with email and password, returning short-lived JWT access and refresh tokens."""
    email_clean = req.email.lower().strip()
    check_login_rate_limit(email_clean)

    db = get_db_session()
    try:
        user = db.query(UserModel).filter(UserModel.email == email_clean).first()
        if not user or not verify_password(req.password, user.password_hash):
            record_failed_login(email_clean)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if user.disabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled. Please contact customer support.",
            )

        reset_failed_login(email_clean)

        access_token = create_token(
            payload={
                "sub": user.id,
                "email": user.email,
                "role": user.role,
                "type": "access",
            },
            expires_in_seconds=1800,  # 30 minutes
        )
        refresh_token = create_token(
            payload={
                "sub": user.id,
                "email": user.email,
                "type": "refresh",
            },
            expires_in_seconds=604800,  # 7 days
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=1800,
        )
    finally:
        db.close()


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(req: RefreshTokenRequest):
    """Exchange a valid refresh token for a fresh access token."""
    payload = decode_token(req.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type. Expected refresh token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    db = get_db_session()
    try:
        user = db.query(UserModel).filter(UserModel.id == user_id).first()
        if not user or user.disabled:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account not found or disabled.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        access_token = create_token(
            payload={
                "sub": user.id,
                "email": user.email,
                "role": user.role,
                "type": "access",
            },
            expires_in_seconds=1800,
        )
        new_refresh = create_token(
            payload={
                "sub": user.id,
                "email": user.email,
                "type": "refresh",
            },
            expires_in_seconds=604800,
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh,
            token_type="bearer",
            expires_in=1800,
        )
    finally:
        db.close()


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout():
    """Revoke active session and refresh tokens."""
    return {"status": "logged_out", "message": "Session successfully terminated."}


@router.get("/me", response_model=AuthUserResponse)
def get_authenticated_user(current_user: UserSessionResponse = Depends(get_current_user)):
    """Retrieve profile and permissions for currently authenticated user."""
    return AuthUserResponse(
        user_id=current_user.user_id,
        email=current_user.username,
        role=current_user.role,
        created_at=datetime.now(timezone.utc),
    )
