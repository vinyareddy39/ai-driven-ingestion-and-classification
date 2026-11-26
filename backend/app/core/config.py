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


class ComplianceFloorsConfig(BaseModel):
    """Compliance floor limits below which class thresholds cannot be lowered."""
    high_risk_floor: float = 0.95
    low_risk_floor: float = 0.90


class PipelineYAMLConfig(BaseModel):
    """Full pipeline configuration loaded from YAML."""
    pipeline: Dict[str, Any]
    classes: Dict[str, DocumentClassConfig]
    decision_gate: DecisionGateConfig
    pii_policy: PIIPolicyConfig
    queues: QueuesConfig
    reprocessing: ReprocessingConfig
    compliance_floors: Optional[ComplianceFloorsConfig] = Field(default_factory=ComplianceFloorsConfig)


from app.core.settings import AppSettings, get_app_settings, validate_production_safety

_runtime_config: Optional[PipelineYAMLConfig] = None


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
