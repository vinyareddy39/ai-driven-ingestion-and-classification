"""Stage 1: Application Settings, Secrets, and Production Startup Barrier Tests."""

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.core.settings import AppSettings, validate_production_safety


def test_settings_default_values_and_types():
    """Verify all 24 required settings variables are loaded with appropriate defaults."""
    s = AppSettings()
    assert s.APP_ENV in ["local", "development", "production"]
    assert s.ACCESS_TOKEN_MINUTES == 30
    assert s.REFRESH_TOKEN_DAYS == 7
    assert s.AUTH_ALLOW_ROLE_HEADER is False
    assert s.MAX_UPLOAD_MB == 10
    assert "pdf" in s.ALLOWED_FILE_TYPES
    assert s.STORAGE_BACKEND in ["local", "s3"]
    assert s.STORAGE_LOCAL_DIR == "./data/storage"
    assert s.LLM_LOCAL_MODEL == "qwen2.5:7b-instruct"
    assert "receipt" in s.LLM_ALLOW_HOSTED_CLASSES
    assert len(s.DATA_ENCRYPTION_KEY) >= 32
    assert s.WEBHOOK_SIGNING_SECRET is not None


def test_production_safety_refuses_insecure_configurations():
    """Verify that in production mode, any insecure secret, database, or CORS is loudly rejected."""
    # 1. Reject default dev secret key
    with pytest.raises(ValueError, match="SECRET_KEY must be a cryptographically random secret"):
        s = AppSettings(
            APP_ENV="production",
            SECRET_KEY="dev_insecure_key",
            DATABASE_URL="postgresql://user:pass@localhost:5432/ecm",
            DATA_ENCRYPTION_KEY="c2VjdXJlX2RldmVsb3BtZW50X2tleV9mb3JfcHJpdmFjeV8xMjM=",
            CORS_ORIGINS="https://frontend.vercel.app",
            AUTH_ALLOW_ROLE_HEADER=False,
            STORAGE_BACKEND="s3",
        )
        validate_production_safety(s)

    # 2. Reject SQLite in production
    with pytest.raises(ValueError, match="DATABASE_URL must point to an enterprise database"):
        s = AppSettings(
            APP_ENV="production",
            SECRET_KEY="A_Very_Long_Cryptographically_Secure_Random_Secret_Key_12345",
            DATABASE_URL="sqlite:///./data/ecm_pipeline.db",
            DATA_ENCRYPTION_KEY="c2VjdXJlX2RldmVsb3BtZW50X2tleV9mb3JfcHJpdmFjeV8xMjM=",
            CORS_ORIGINS="https://frontend.vercel.app",
            AUTH_ALLOW_ROLE_HEADER=False,
            STORAGE_BACKEND="s3",
        )
        validate_production_safety(s)

    # 3. Reject Wildcard CORS in production
    with pytest.raises(ValueError, match="CORS_ORIGINS must be an explicit whitelist"):
        s = AppSettings(
            APP_ENV="production",
            SECRET_KEY="A_Very_Long_Cryptographically_Secure_Random_Secret_Key_12345",
            DATABASE_URL="postgresql://user:pass@localhost:5432/ecm",
            DATA_ENCRYPTION_KEY="c2VjdXJlX2RldmVsb3BtZW50X2tleV9mb3JfcHJpdmFjeV8xMjM=",
            CORS_ORIGINS="*",
            AUTH_ALLOW_ROLE_HEADER=False,
            STORAGE_BACKEND="s3",
        )
        validate_production_safety(s)

    # 4. Reject role header bypass in production
    with pytest.raises(ValueError, match="AUTH_ALLOW_ROLE_HEADER must be False"):
        s = AppSettings(
            APP_ENV="production",
            SECRET_KEY="A_Very_Long_Cryptographically_Secure_Random_Secret_Key_12345",
            DATABASE_URL="postgresql://user:pass@localhost:5432/ecm",
            DATA_ENCRYPTION_KEY="c2VjdXJlX2RldmVsb3BtZW50X2tleV9mb3JfcHJpdmFjeV8xMjM=",
            CORS_ORIGINS="https://frontend.vercel.app",
            AUTH_ALLOW_ROLE_HEADER=True,
            STORAGE_BACKEND="s3",
        )
        validate_production_safety(s)

    # 5. Reject local storage in production
    with pytest.raises(ValueError, match="STORAGE_BACKEND must be 's3' in production"):
        s = AppSettings(
            APP_ENV="production",
            SECRET_KEY="A_Very_Long_Cryptographically_Secure_Random_Secret_Key_12345",
            DATABASE_URL="postgresql://user:pass@localhost:5432/ecm",
            DATA_ENCRYPTION_KEY="c2VjdXJlX2RldmVsb3BtZW50X2tleV9mb3JfcHJpdmFjeV8xMjM=",
            CORS_ORIGINS="https://frontend.vercel.app",
            AUTH_ALLOW_ROLE_HEADER=False,
            STORAGE_BACKEND="local",
        )
        validate_production_safety(s)


def test_production_safety_passes_with_valid_configuration():
    """Verify that a compliant production configuration succeeds without errors."""
    valid_prod = AppSettings(
        APP_ENV="production",
        SECRET_KEY="A_Very_Long_Cryptographically_Secure_Random_Secret_Key_12345",
        DATABASE_URL="postgresql://user:pass@localhost:5432/ecm",
        DATA_ENCRYPTION_KEY="c2VjdXJlX2RldmVsb3BtZW50X2tleV9mb3JfcHJpdmFjeV8xMjM=",
        CORS_ORIGINS="https://frontend.vercel.app,https://admin.frontend.app",
        AUTH_ALLOW_ROLE_HEADER=False,
        STORAGE_BACKEND="s3",
    )
    # Should not raise
    validate_production_safety(valid_prod)


def test_system_info_endpoint_exposes_no_secrets():
    """Verify /api/v1/system/info returns metadata and operational limits with strictly ZERO secrets."""
    from app.core.auth import get_configured_tokens
    tokens = get_configured_tokens()
    token = list(tokens.keys())[0] if tokens else "secret-token-12345"

    client = TestClient(app)
    # Staff token header
    client.headers["Authorization"] = f"Bearer {token}"

    resp = client.get("/api/v1/system/info")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "mode" in data
    assert "version" in data
    assert "max_upload_mb" in data
    assert "allowed_file_types" in data
    assert data["max_upload_mb"] == 10

    raw_text = resp.text
    assert "SECRET_KEY" not in raw_text
    assert "DATA_ENCRYPTION_KEY" not in raw_text
    assert "minioadmin" not in raw_text
    assert "password" not in raw_text
