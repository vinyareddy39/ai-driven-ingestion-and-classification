#!/usr/bin/env python
"""Command-line administrative utility for managing DocSort user accounts."""

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.auth import load_dotenv_if_present
from app.core.jwt_auth import hash_password
from app.models.db import UserModel, get_db_session, init_db


def get_env_password(role: str) -> Optional[str]:
    """Retrieve password from environment variables based on role."""
    load_dotenv_if_present()
    role_upper = role.upper()
    return (
        os.getenv(f"{role_upper}_PASSWORD")
        or os.getenv("USER_PASSWORD")
        or os.getenv("DEFAULT_USER_PASSWORD")
    )


def create_or_update_user(email: str, password: str, role: str = "uploader", name: Optional[str] = None) -> UserModel:
    """Create a new user or update an existing user's role and password."""
    init_db()
    db = get_db_session()
    try:
        email_clean = email.lower().strip()
        user = db.query(UserModel).filter(UserModel.email == email_clean).first()
        hashed = hash_password(password)
        user_name = name or email_clean.split("@")[0].replace(".", " ").title()

        if user:
            user.password_hash = hashed
            user.role = role.lower().strip()
            if name:
                user.name = user_name
            db.commit()
            print(f"[OK] Updated user '{email_clean}' (role: {user.role}, name: {user.name})")
            return user
        else:
            user = UserModel(
                id=f"usr-{uuid.uuid4().hex[:12]}",
                name=user_name,
                email=email_clean,
                password_hash=hashed,
                role=role.lower().strip(),
                created_at=datetime.now(timezone.utc),
                disabled=False,
            )
            db.add(user)
            db.commit()
            print(f"[OK] Created user '{email_clean}' (id: {user.id}, role: {user.role}, name: {user.name})")
            return user
    finally:
        db.close()


def list_users():
    """List all user accounts in the database."""
    init_db()
    db = get_db_session()
    try:
        users = db.query(UserModel).order_by(UserModel.created_at.asc()).all()
        print(f"\nTotal users: {len(users)}")
        print(f"{'ID':<18} {'Role':<12} {'Status':<10} {'Email':<32} {'Name'}")
        print("-" * 85)
        for u in users:
            status = "Disabled" if u.disabled else "Active"
            name = u.name or ""
            print(f"{u.id:<18} {u.role:<12} {status:<10} {u.email:<32} {name}")
        print("-" * 85 + "\n")
    finally:
        db.close()


def setup_test_users():
    """Create test accounts for admin, reviewer, and uploader using environment variable passwords."""
    load_dotenv_if_present()

    admin_pw = os.getenv("ADMIN_PASSWORD", "AdminPass123!")
    reviewer_pw = os.getenv("REVIEWER_PASSWORD", "ReviewerPass123!")
    uploader_pw = os.getenv("UPLOADER_PASSWORD", "UploaderPass123!")

    print("\n--- Seeding Test Users from Environment Variables ---")
    create_or_update_user(
        email="admin@docsort.local",
        password=admin_pw,
        role="admin",
        name="DocSort Admin",
    )
    create_or_update_user(
        email="reviewer@docsort.local",
        password=reviewer_pw,
        role="reviewer",
        name="DocSort Reviewer",
    )
    create_or_update_user(
        email="uploader@docsort.local",
        password=uploader_pw,
        role="uploader",
        name="DocSort Uploader",
    )
    print("--- Test Users Ready ---\n")


def main():
    parser = argparse.ArgumentParser(description="DocSort User Account Manager")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Create user
    create_p = subparsers.add_parser("create", help="Create or update a user")
    create_p.add_argument("--email", required=True, help="User email address")
    create_p.add_argument("--password", required=False, help="Password (reads from role env var if omitted)")
    create_p.add_argument("--role", default="uploader", choices=["uploader", "reviewer", "admin"], help="User role")
    create_p.add_argument("--name", required=False, help="Display name")

    # List users
    subparsers.add_parser("list", help="List all registered users")

    # Setup test users
    subparsers.add_parser("setup-test-users", help="Create admin, reviewer, and uploader test users")

    args = parser.parse_args()

    if args.command == "create":
        pw = args.password or get_env_password(args.role)
        if not pw:
            print(f"Error: Password must be supplied via --password or ${args.role.upper()}_PASSWORD env var.", file=sys.stderr)
            sys.exit(1)
        create_or_update_user(email=args.email, password=pw, role=args.role, name=args.name)
    elif args.command == "list":
        list_users()
    elif args.command == "setup-test-users":
        setup_test_users()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
