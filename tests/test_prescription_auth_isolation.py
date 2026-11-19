"""Comprehensive Tests for Stage 2: Patient Auth, Rate Limiting, and User Isolation.

Verifies:
1. User registration with Argon2id password hashing.
2. Login with valid credentials issuing RFC 7519 signed JWTs.
3. Login failure with wrong password returns generic 401.
4. Rate limiting triggers 429 after 5 failed login attempts.
5. Token refresh exchange.
6. User B receives 404 (not 403) when requesting User A's prescription or image.
7. Staff access to patient prescription succeeds and logs an explicit audit event.
"""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from app.api.app import app
from app.core.auth import get_configured_tokens
from app.core.jwt_auth import _LOGIN_ATTEMPTS
from app.models.db import (
    AuditEventModel,
    PrescriptionModel,
    UserModel,
    get_db_session,
    init_db,
)


@pytest.fixture(scope="module")
def client():
    init_db()
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_auth_state():
    _LOGIN_ATTEMPTS.clear()
    yield
    _LOGIN_ATTEMPTS.clear()


def test_patient_signup_and_login_flow(client: TestClient):
    """Test user signup, Argon2 password hashing, and JWT token issuance."""
    email = f"patient_{datetime.now().timestamp()}@health.local"
    pw = "SuperSecureP@ssw0rd!"

    # 1. Signup
    signup_resp = client.post("/api/v1/auth/signup", json={"email": email, "password": pw, "role": "patient"})
    assert signup_resp.status_code == 201
    user_data = signup_resp.json()
    assert user_data["email"] == email.lower()
    assert user_data["role"] == "patient"
    user_id = user_data["user_id"]

    # Verify password was hashed with Argon2 in DB
    db = get_db_session()
    user_row = db.query(UserModel).filter(UserModel.id == user_id).first()
    assert user_row is not None
    assert user_row.password_hash.startswith("$argon2id$")
    assert pw not in user_row.password_hash
    db.close()

    # 2. Login Success
    login_resp = client.post("/api/v1/auth/login", json={"email": email, "password": pw})
    assert login_resp.status_code == 200
    token_data = login_resp.json()
    assert "access_token" in token_data
    assert "refresh_token" in token_data
    assert token_data["token_type"] == "bearer"
    access_token = token_data["access_token"]
    assert access_token.count(".") == 2  # Standard JWT format

    # 3. Access Protected Route /auth/me
    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["user_id"] == user_id
    assert me_resp.json()["username"] == email.lower()

    # 4. Token Refresh
    ref_resp = client.post("/api/v1/auth/refresh", json={"refresh_token": token_data["refresh_token"]})
    assert ref_resp.status_code == 200
    assert "access_token" in ref_resp.json()


def test_login_generic_error_and_rate_limiting(client: TestClient):
    """Test wrong password gives generic 401 and 5 failures trigger 429."""
    email = "ratelimit_patient@health.local"
    pw = "ValidPassword123!"

    # Create account
    client.post("/api/v1/auth/signup", json={"email": email, "password": pw})

    # Failed login 1..4 -> 401 with generic message
    for _ in range(4):
        resp = client.post("/api/v1/auth/login", json={"email": email, "password": "WrongPassword"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid email or password."

    # 5th failure -> triggers rate limit
    resp_5 = client.post("/api/v1/auth/login", json={"email": email, "password": "WrongPassword"})
    assert resp_5.status_code == 401

    # 6th attempt -> 429 Too Many Requests
    resp_6 = client.post("/api/v1/auth/login", json={"email": email, "password": "WrongPassword"})
    assert resp_6.status_code == 429
    assert "Too many failed login attempts" in resp_6.json()["detail"]


def test_user_isolation_returns_404_not_403(client: TestClient):
    """User B requesting User A's prescription or image must receive 404 Not Found."""
    # Register User A
    email_a = "patient_a@health.local"
    client.post("/api/v1/auth/signup", json={"email": email_a, "password": "PasswordA123!"})
    tok_a = client.post("/api/v1/auth/login", json={"email": email_a, "password": "PasswordA123!"}).json()["access_token"]
    hdr_a = {"Authorization": f"Bearer {tok_a}"}

    # Register User B
    email_b = "patient_b@health.local"
    client.post("/api/v1/auth/signup", json={"email": email_b, "password": "PasswordB123!"})
    tok_b = client.post("/api/v1/auth/login", json={"email": email_b, "password": "PasswordB123!"}).json()["access_token"]
    hdr_b = {"Authorization": f"Bearer {tok_b}"}

    # Get User A's ID
    user_a_id = client.get("/api/v1/auth/me", headers=hdr_a).json()["user_id"]

    # Seed Prescription A owned by User A
    rx_a_id = "rx-user-a-secret-001"
    db = get_db_session()
    db.query(PrescriptionModel).filter(PrescriptionModel.id == rx_a_id).delete()
    rx_a = PrescriptionModel(
        id=rx_a_id,
        user_id=user_a_id,
        file_key="prescriptions/user_a/rx01.pdf",
        status="NEEDS_REVIEW",
        model_version="v1.0",
        ocr_engine="HybridPyMuPDF-Tesseract",
        created_at=datetime.now(timezone.utc),
    )
    db.merge(rx_a)
    db.commit()
    db.close()

    # 1. User A (Owner) can read Prescription A -> 200 OK
    resp_owner = client.get(f"/api/v1/prescriptions/{rx_a_id}", headers=hdr_a)
    assert resp_owner.status_code == 200
    assert resp_owner.json()["prescription_id"] == rx_a_id

    # 2. User B gets 404 (NOT 403) on User A's prescription
    resp_other = client.get(f"/api/v1/prescriptions/{rx_a_id}", headers=hdr_b)
    assert resp_other.status_code == 404
    assert resp_other.json()["detail"] == "Prescription not found"

    # 3. User B gets 404 on User A's status
    status_other = client.get(f"/api/v1/prescriptions/{rx_a_id}/status", headers=hdr_b)
    assert status_other.status_code == 404

    # 4. User B gets 404 on User A's image route
    img_other = client.get(f"/api/v1/prescriptions/{rx_a_id}/image", headers=hdr_b)
    assert img_other.status_code == 404

    # 5. User B gets 404 on item patch
    patch_other = client.patch(f"/api/v1/prescriptions/{rx_a_id}/items/some-item", headers=hdr_b, json={"drug_name": "Test"})
    assert patch_other.status_code == 404

    # 6. Unauthenticated request -> 401 Unauthorized
    unauth_resp = client.get(f"/api/v1/prescriptions/{rx_a_id}")
    assert unauth_resp.status_code == 401

    # 7. Malformed token -> 401 Unauthorized
    bad_resp = client.get(f"/api/v1/prescriptions/{rx_a_id}", headers={"Authorization": "Bearer bad.token.garbage"})
    assert bad_resp.status_code == 401


def test_staff_role_audited_patient_data_access(client: TestClient):
    """Staff roles (reviewer, admin) can access patient prescription, with mandatory audit event."""
    tokens = get_configured_tokens()
    rev_tok = next((t for t, r in tokens.items() if r == "reviewer"), "")
    hdr_reviewer = {"Authorization": f"Bearer {rev_tok}"}

    # Query User A's prescription with reviewer staff token
    rx_a_id = "rx-user-a-secret-001"
    resp_staff = client.get(f"/api/v1/prescriptions/{rx_a_id}", headers=hdr_reviewer)
    assert resp_staff.status_code == 200
    assert resp_staff.json()["prescription_id"] == rx_a_id

    # Verify audit event was recorded in audit_events table
    db = get_db_session()
    audit_row = db.query(AuditEventModel).filter(
        AuditEventModel.document_uid == rx_a_id,
        AuditEventModel.event_type == "STAFF_PATIENT_ACCESS",
    ).order_by(AuditEventModel.created_at.desc()).first()
    assert audit_row is not None
    assert audit_row.status == "AUDITED"
    db.close()
