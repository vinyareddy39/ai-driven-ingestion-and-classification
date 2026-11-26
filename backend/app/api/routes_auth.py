"""User registration, login, logout, and current user profile routes."""

import re
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.core.jwt_auth import (
    create_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.models.db import UserModel, get_db

router = APIRouter(prefix="/api", tags=["auth"])


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: str
    name: str
    email: str


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    name = req.name.strip()
    email = req.email.strip().lower()
    password = req.password

    if not name:
        raise HTTPException(status_code=400, detail="Enter your name.")
    if not re.match(r"^\S+@\S+\.\S+$", email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password needs at least 6 characters.")

    existing = db.query(UserModel).filter(UserModel.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    pw_hash = hash_password(password)
    user = UserModel(name=name, email=email, password_hash=pw_hash)
    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "message": "Registered. Now sign in.",
    }


@router.post("/login")
def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    password = req.password

    user = db.query(UserModel).filter(UserModel.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = create_token({"sub": user.id, "email": user.email, "name": user.name})
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 7,
    )

    return {
        "token": token,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
        },
    }


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Logged out"}


@router.get("/me")
def get_me(user: UserModel = Depends(get_current_user)):
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
    }
