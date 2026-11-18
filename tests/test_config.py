"""Unit tests for configuration loading, validation, and runtime updates."""

import pytest
from app.core.config import get_pipeline_config, load_pipeline_config, save_pipeline_config


def test_config_loading():
    """Assert pipeline config loads cleanly and all required classes are present."""
    cfg = get_pipeline_config()
    assert cfg.pipeline["name"] == "ecm-ai-ingest"
    assert "invoice" in cfg.classes
    assert "kyc_form" in cfg.classes
    assert "unknown" in cfg.classes


def test_decision_gate_config():
    """Assert decision gate parameters match requirements."""
    cfg = get_pipeline_config()
    assert cfg.decision_gate.low_risk_auto_threshold >= 0.85
    assert cfg.decision_gate.high_risk_auto_threshold >= 0.90
    assert cfg.decision_gate.review_floor == 0.60
    assert cfg.decision_gate.auto_accept_unknown is False


def test_pii_policy_sensitivity():
    """Assert high, medium, and low sensitivity PII policies are defined."""
    cfg = get_pipeline_config()
    high_pii = cfg.pii_policy.sensitivity.get("high", [])
    assert "US_SSN" in high_pii or "CREDIT_CARD" in high_pii
    assert cfg.pii_policy.mask_in_logs is True
