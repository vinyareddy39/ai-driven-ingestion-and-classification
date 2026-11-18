"""Runtime configuration loader and settings validation."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from pydantic import BaseModel, Field
class DocumentClassConfig(BaseModel):
    """Configuration for a specific document class."""
    risk: str = "low"  # low or high
    default_threshold: float = 0.90
    tuned_threshold: float = 0.90
    retention_class: str
    acl: str
    target_workflow: str


class DecisionGateConfig(BaseModel):
    """Configuration for decision gate routing thresholds."""
    low_risk_auto_threshold: float = 0.90
    high_risk_auto_threshold: float = 0.95
    review_floor: float = 0.60
    conflict_stricter_rule: bool = True
    auto_accept_unknown: bool = False


class PIIPolicyConfig(BaseModel):
    """PII policy and sensitivity classification."""
    sensitivity: Dict[str, List[str]] = Field(default_factory=dict)
    mask_in_logs: bool = True
    mask_char: str = "*"
    conflict_trigger_sensitivity: str = "high"


class QueuesConfig(BaseModel):
    """Message queue configuration."""
    live_queue: str = "ecm:queue:live"
    bulk_queue: str = "ecm:queue:bulk"
    dlq_queue: str = "ecm:queue:dlq"
    bulk_rate_limit_per_second: int = 50


class ReprocessingConfig(BaseModel):
    """Reprocessing worker settings."""
    max_concurrency: int = 4
    preserve_human_verified: bool = True
    emit_conflict_diff: bool = True


class PipelineYAMLConfig(BaseModel):
    """Full pipeline configuration loaded from YAML."""
    pipeline: Dict[str, Any]
    classes: Dict[str, DocumentClassConfig]
    decision_gate: DecisionGateConfig
    pii_policy: PIIPolicyConfig
    queues: QueuesConfig
    reprocessing: ReprocessingConfig


class AppSettings(BaseModel):
    """Environment and runtime application settings."""
    ENVIRONMENT: str = Field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    LOG_LEVEL: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    # Storage
    STORAGE_BACKEND: str = Field(default_factory=lambda: os.getenv("STORAGE_BACKEND", "local"))
    MINIO_ENDPOINT: str = Field(default_factory=lambda: os.getenv("MINIO_ENDPOINT", "localhost:9000"))
    MINIO_ACCESS_KEY: str = Field(default_factory=lambda: os.getenv("MINIO_ACCESS_KEY", "minioadmin"))
    MINIO_SECRET_KEY: str = Field(default_factory=lambda: os.getenv("MINIO_SECRET_KEY", "minioadmin"))
    MINIO_BUCKET: str = Field(default_factory=lambda: os.getenv("MINIO_BUCKET", "ecm-raw-assets"))
    MINIO_SECURE: bool = Field(default_factory=lambda: os.getenv("MINIO_SECURE", "false").lower() == "true")

    # Database
    DATABASE_URL: str = Field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./data/ecm_pipeline.db"))

    # Queue
    QUEUE_BACKEND: str = Field(default_factory=lambda: os.getenv("QUEUE_BACKEND", "memory"))
    REDIS_URL: str = Field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    # Search Index
    SEARCH_BACKEND: str = Field(default_factory=lambda: os.getenv("SEARCH_BACKEND", "memory"))
    OPENSEARCH_URL: str = Field(default_factory=lambda: os.getenv("OPENSEARCH_URL", "http://localhost:9200"))
    OPENSEARCH_INDEX: str = Field(default_factory=lambda: os.getenv("OPENSEARCH_INDEX", "ecm_documents"))

    # Antivirus
    VIRUS_SCANNER_BACKEND: str = Field(default_factory=lambda: os.getenv("VIRUS_SCANNER_BACKEND", "mock"))
    CLAMAV_HOST: str = Field(default_factory=lambda: os.getenv("CLAMAV_HOST", "localhost"))
    CLAMAV_PORT: int = Field(default_factory=lambda: int(os.getenv("CLAMAV_PORT", "3310")))

    # ECM
    ECM_ADAPTER_BACKEND: str = Field(default_factory=lambda: os.getenv("ECM_ADAPTER_BACKEND", "fake"))
    NUXEO_REST_URL: str = Field(default_factory=lambda: os.getenv("NUXEO_REST_URL", "http://localhost:8080/nuxeo/site/api/v1"))
    NUXEO_USERNAME: str = Field(default_factory=lambda: os.getenv("NUXEO_USERNAME", "Administrator"))
    NUXEO_PASSWORD: str = Field(default_factory=lambda: os.getenv("NUXEO_PASSWORD", "Administrator"))

    # OCR
    OCR_ENGINE: str = Field(default_factory=lambda: os.getenv("OCR_ENGINE", "tesseract"))

    # Paths
    CONFIG_PATH: str = Field(default_factory=lambda: os.getenv("CONFIG_PATH", "./config/pipeline_config.yaml"))
    SCANNER_WATCH_DIR: str = Field(default_factory=lambda: os.getenv("SCANNER_WATCH_DIR", "./data/scanner_watch"))
    MODEL_ARTIFACTS_DIR: str = Field(default_factory=lambda: os.getenv("MODEL_ARTIFACTS_DIR", "./data/models"))


_runtime_config: Optional[PipelineYAMLConfig] = None
_app_settings: Optional[AppSettings] = None


def get_app_settings() -> AppSettings:
    """Retrieve application settings from environment."""
    global _app_settings
    if _app_settings is None:
        _app_settings = AppSettings()
    return _app_settings


def load_pipeline_config(config_path: Optional[str] = None) -> PipelineYAMLConfig:
    """Load and validate pipeline configuration from YAML file."""
    global _runtime_config
    if config_path is None:
        config_path = get_app_settings().CONFIG_PATH

    path = Path(config_path)
    if not path.is_absolute():
        base_dir = Path(__file__).resolve().parent.parent.parent
        path = base_dir / config_path

    if not path.exists():
        raise FileNotFoundError(f"Pipeline config YAML not found at: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    _runtime_config = PipelineYAMLConfig(**data)
    return _runtime_config


def get_pipeline_config() -> PipelineYAMLConfig:
    """Retrieve currently active runtime pipeline config."""
    global _runtime_config
    if _runtime_config is None:
        _runtime_config = load_pipeline_config()
    return _runtime_config


def save_pipeline_config(config: PipelineYAMLConfig, config_path: Optional[str] = None) -> None:
    """Persist updated pipeline config back to YAML (e.g. after parameter tuning)."""
    global _runtime_config
    if config_path is None:
        config_path = get_app_settings().CONFIG_PATH

    path = Path(config_path)
    if not path.is_absolute():
        base_dir = Path(__file__).resolve().parent.parent.parent
        path = base_dir / config_path

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config.model_dump(), f, default_flow_style=False, sort_keys=False)

    _runtime_config = config
