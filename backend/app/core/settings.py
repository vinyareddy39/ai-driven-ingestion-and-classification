"""Central Application Settings & Production Startup Validation via Pydantic-Settings."""

import os
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Unified application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment & Logging
    APP_ENV: str = Field(default="local", description="Deployment environment: local | production")
    LOG_LEVEL: str = Field(default="INFO")

    @property
    def ENVIRONMENT(self) -> str:
        return self.APP_ENV


    # Database
    DATABASE_URL: str = Field(
        default="sqlite:///./data/ecm_pipeline.db",
        description="Database connection URL (PostgreSQL in production, SQLite in local)",
    )

    # JWT Authentication & Tokens
    SECRET_KEY: str = Field(
        default="",
        description="Secret key for signing RFC 7519 JWT tokens (read from environment or .env)",
    )
    ACCESS_TOKEN_MINUTES: int = Field(default=30, description="Access token expiration window in minutes")
    REFRESH_TOKEN_DAYS: int = Field(default=7, description="Refresh token expiration window")
    AUTH_TOKENS: str = Field(
        default="",
        description="Static staff bearer token mappings formatted as token:role,token:role",
    )
    AUTH_ALLOW_ROLE_HEADER: bool = Field(
        default=False,
        description="Whether to permit X-User-Role header bypass. MUST be False in production.",
    )

    # Security & CORS
    CORS_ORIGINS: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        description="Comma-separated list of allowed CORS browser origins",
    )
    DATA_ENCRYPTION_KEY: str = Field(
        default="c2VjdXJlX2RldmVsb3BtZW50X2tleV9mb3JfcHJpdmFjeV8xMjM=",
        description="Base64 or 32-byte secret for column-level health data encryption at rest",
    )

    # File Storage
    STORAGE_BACKEND: str = Field(default="local", description="Object storage backend: local | s3")
    STORAGE_LOCAL_DIR: str = Field(default="./data/storage", description="Directory path for local storage")
    S3_ENDPOINT_URL: Optional[str] = Field(default=None, description="Custom S3 endpoint (e.g. MinIO, Cloudflare R2)")
    S3_BUCKET: str = Field(default="ecm-raw-assets", description="S3 bucket name")
    S3_ACCESS_KEY: Optional[str] = Field(default=None, description="S3 access key ID")
    S3_SECRET_KEY: Optional[str] = Field(default=None, description="S3 secret access key")
    S3_REGION: str = Field(default="us-east-1", description="S3 region name")

    # AI & LLM Backend
    LLM_LOCAL_BASE_URL: str = Field(
        default="http://localhost:11434/v1",
        description="OpenAI-compatible local endpoint (e.g. Ollama)",
    )
    LLM_LOCAL_MODEL: str = Field(default="qwen2.5:7b-instruct", description="Local model name")
    LLM_HOSTED_PROVIDER: Optional[str] = Field(default=None, description="Hosted LLM provider name")
    LLM_HOSTED_API_KEY: Optional[str] = Field(default=None, description="API key for hosted provider")
    LLM_HOSTED_MODEL: Optional[str] = Field(default=None, description="Hosted model name")
    LLM_ALLOW_HOSTED_CLASSES: str = Field(
        default="receipt,invoice,unknown",
        description="Comma-separated low-risk classes permitted on hosted LLMs. Medical/KYC/PII strictly excluded.",
    )

    # Notifications & SMTP
    SMTP_HOST: Optional[str] = Field(default=None, description="SMTP server hostname for reminders")
    SMTP_PORT: int = Field(default=587, description="SMTP port")
    SMTP_USERNAME: Optional[str] = Field(default=None, description="SMTP username")
    SMTP_PASSWORD: Optional[str] = Field(default=None, description="SMTP password")
    SMTP_FROM_EMAIL: str = Field(default="notifications@ecm.local", description="Sender email address")

    # Outbound Webhook Distribution
    WEBHOOK_SIGNING_SECRET: str = Field(
        default="default_webhook_hmac_signing_secret_123",
        description="Secret key for signing outbound JSON webhook payloads with HMAC-SHA256",
    )
    OUTBOUND_WEBHOOK_URL: str = Field(
        default="",
        description="Target endpoint for outbound event webhooks",
    )

    # Upload & Operational Limits
    MAX_UPLOAD_MB: int = Field(default=200, description="Maximum single file upload limit in megabytes")
    ALLOWED_FILE_TYPES: str = Field(
        default="image/jpeg,image/png,image/jpg,application/pdf",
        description="Comma-separated MIME types allowed for ingestion",
    )
    ALLOW_LOCAL_EXPORT: bool = Field(
        default=True,
        description="Whether to permit zip export of classified documents in non-production environments",
    )

    # Queue & Other Adapters
    QUEUE_BACKEND: str = Field(default="memory", description="Queue backend: memory | redis | postgres")
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    SEARCH_BACKEND: str = Field(default="memory")
    OPENSEARCH_URL: str = Field(default="http://localhost:9200")
    OPENSEARCH_INDEX: str = Field(default="ecm_documents")
    OCR_ENGINE: str = Field(default="hybrid", description="OCR engine backend: hybrid | tesseract | trocr")
    OCR_BATCH_SIZE: int = Field(default=8, description="OCR inference batch size")
    OCR_USE_GPU: bool = Field(default=False, description="Whether to utilize CUDA acceleration for OCR")
    OCR_MODEL: str = Field(default="microsoft/trocr-base-printed", description="HuggingFace model id for TrOCR if enabled")
    OCR_DPI: int = Field(default=200, description="DPI resolution for PDF page rendering")
    OCR_CACHE_ENABLED: bool = Field(default=True, description="Whether to cache OCR results by file sha256 hash")
    CONFIG_PATH: str = Field(default="./config/pipeline_config.yaml")
    SCANNER_WATCH_DIR: str = Field(default="./data/scanner_watch")
    MODEL_ARTIFACTS_DIR: str = Field(default="./data/models")
    VIRUS_SCANNER_BACKEND: str = Field(default="mock")
    ALLOW_LOCAL_EXPORT: bool = Field(default=True, description="Permit local export of restricted document classes in development")
    DOWNLOAD_EXPIRY_HOURS: int = Field(default=24, description="Hours before temporary export zip archives expire and are cleaned up")
    DELETE_UPLOAD_AFTER_PROCESSING: bool = Field(default=True, description="Delete temporary file from ephemeral local disk after processing")


class ProductionSecurityError(ValueError):
    """Raised when application configuration violates production security standards."""
    pass


def validate_production_safety(settings: AppSettings) -> bool:
    """Enforce strict security barriers when operating in production mode.
    
    Refuses startup if secrets are missing, defaults are used, or insecure
    configurations (wildcard CORS, role header bypass, local disk) are enabled.
    """
    if settings.APP_ENV.lower() != "production":
        return True

    errors: List[str] = []

    # 1. JWT Secret Key
    if not settings.SECRET_KEY or "dev_" in settings.SECRET_KEY or len(settings.SECRET_KEY) < 32:
        errors.append("SECRET_KEY must be a cryptographically random secret with at least 32 characters in production.")

    # 2. Database URL
    if not settings.DATABASE_URL or settings.DATABASE_URL.startswith("sqlite"):
        errors.append("DATABASE_URL must point to an enterprise database (PostgreSQL) in production; SQLite is rejected.")

    # 3. Data Encryption Key
    if not settings.DATA_ENCRYPTION_KEY or len(settings.DATA_ENCRYPTION_KEY) < 32:
        errors.append("DATA_ENCRYPTION_KEY must be configured with a 32-byte secret for column-level encryption in production.")

    # 4. CORS Origins
    if not settings.CORS_ORIGINS or "*" in settings.CORS_ORIGINS:
        errors.append("CORS_ORIGINS must be an explicit whitelist of domains in production; wildcard ('*') is rejected.")

    # 5. Role Header Bypass
    if settings.AUTH_ALLOW_ROLE_HEADER:
        errors.append("AUTH_ALLOW_ROLE_HEADER must be False in production (prevents unauthenticated privilege escalation).")

    # 6. Storage Backend
    if settings.STORAGE_BACKEND == "local":
        errors.append("STORAGE_BACKEND must be 's3' in production because cloud container disks are ephemeral; STORAGE_BACKEND='local' is forbidden.")

    # 7. Demo role selector & static tokens
    if getattr(settings, "ENABLE_DEMO_TOKENS", False) or os.getenv("ENABLE_DEMO_TOKENS", "false").lower() in ("true", "1"):
        errors.append("Demo role selector and static demo tokens must be disabled in production mode.")

    if errors:
        msg = "PRODUCTION STARTUP REFUSED:\n  - " + "\n  - ".join(errors)
        raise ProductionSecurityError(msg)
    return True


_cached_settings: Optional[AppSettings] = None


def get_app_settings() -> AppSettings:
    """Retrieve cached application settings instance."""
    global _cached_settings
    if _cached_settings is None:
        _cached_settings = AppSettings()
    return _cached_settings
