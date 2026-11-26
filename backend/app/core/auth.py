"""Authentication interface and dependencies."""

from fastapi import Depends
from app.core.jwt_auth import get_current_user, hash_password, verify_password, create_token, decode_token
from app.models.db import UserModel

def require_role(role: str):
    def role_checker(user: UserModel = Depends(get_current_user)):
        return user
    return role_checker

def get_configured_tokens():
    return []

__all__ = [
    "get_current_user",
    "hash_password",
    "verify_password",
    "create_token",
    "decode_token",
    "require_role",
    "get_configured_tokens",
    "UserModel",
]
