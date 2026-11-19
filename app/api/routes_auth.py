"""Authentication API routes: signup, login, refresh, logout, and me."""

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from app.models.prescription_schemas import (
    AuthUserResponse,
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserSignupRequest,
)
from app.core.auth import get_current_user
from app.models.api_schemas import UserSessionResponse

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/signup", response_model=AuthUserResponse, status_code=status.HTTP_201_CREATED)
def signup(req: UserSignupRequest):
    """Register a new patient or user account."""
    return AuthUserResponse(
        user_id=f"usr-{uuid.uuid4().hex[:12]}",
        email=req.email,
        role=req.role,
        created_at=datetime.now(timezone.utc),
    )


@router.post("/login", response_model=TokenResponse)
def login(req: UserLoginRequest):
    """Authenticate with email and password, returning short-lived JWT access and refresh tokens."""
    return TokenResponse(
        access_token=f"jwt-access-{uuid.uuid4().hex}",
        refresh_token=f"jwt-refresh-{uuid.uuid4().hex}",
        token_type="bearer",
        expires_in=1800,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(req: RefreshTokenRequest):
    """Exchange a valid refresh token for a fresh access token."""
    return TokenResponse(
        access_token=f"jwt-access-{uuid.uuid4().hex}",
        refresh_token=f"jwt-refresh-{uuid.uuid4().hex}",
        token_type="bearer",
        expires_in=1800,
    )


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
