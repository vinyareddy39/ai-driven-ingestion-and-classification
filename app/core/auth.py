"""Authentication interface and dependencies."""

from fastapi import Depends
from app.core.jwt_auth import get_current_user, hash_password, verify_password, create_token, decode_token
from app.models.db import UserModel

__all__ = [
    "get_current_user",
    "hash_password",
    "verify_password",
    "create_token",
    "decode_token",
    "UserModel",
]
