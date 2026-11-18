"""Table-driven unit tests for every rule in the Decision Gate."""

import pytest
from app.workers.stages import stage_decision_gate


# Table-driven test cases covering every gate rule and edge condition
DECISION_GATE_TEST_CASES = [
    # 1. Low-risk auto-accept
    {
        "name": "low_risk_high_conf_auto_accept",
        "predicted_type": "invoice",
        "confidence": 0.96,
        "pii_info": {"has_high_sensitivity": False},
        "expected_action": "AUTO_ACCEPT",
        "expected_status": "auto_accepted",
        "expected_acl": "CONFIDENTIAL_FINANCE",
    },
    # 2. High-risk auto-accept
    {
        "name": "high_risk_high_conf_auto_accept",
        "predicted_type": "kyc_form",
        "confidence": 0.98,
        "pii_info": {"has_high_sensitivity": True},  # High risk class allows high sensitivity
        "expected_action": "AUTO_ACCEPT",
        "expected_status": "auto_accepted",
        "expected_acl": "RESTRICTED_KYC",
    },
    # 3. Low-risk below threshold -> Review
    {
        "name": "low_risk_borderline_review",
        "predicted_type": "invoice",
        "confidence": 0.75,
        "pii_info": {"has_high_sensitivity": False},
        "expected_action": "ROUTE_TO_REVIEW",
        "expected_status": "pending_review",
        "expected_acl": "RESTRICTED_REVIEW",
    },
    # 4. High-risk below threshold -> Review
    {
        "name": "high_risk_borderline_review",
        "predicted_type": "medical_report",
        "confidence": 0.88,
        "pii_info": {"has_high_sensitivity": False},
        "expected_action": "ROUTE_TO_REVIEW",
        "expected_status": "pending_review",
        "expected_acl": "RESTRICTED_REVIEW",
    },
    # 5. Mandatory rule: Unknown is NEVER auto-accepted even with high confidence
    {
        "name": "unknown_never_auto_accepted",
        "predicted_type": "unknown",
        "confidence": 0.99,
        "pii_info": {"has_high_sensitivity": False},
        "expected_action": "ROUTE_TO_REVIEW",
        "expected_status": "pending_review",
        "expected_acl": "RESTRICTED_REVIEW",
    },
    # 6. Classifier/PII conflict: low-risk class containing unexpected high-risk PII -> stricter review outcome
    {
        "name": "classifier_pii_conflict_stricter_outcome",
        "predicted_type": "letter",
        "confidence": 0.94,
        "pii_info": {"has_high_sensitivity": True},  # Unexpected high sensitivity in general letter
        "expected_action": "ROUTE_TO_REVIEW",
        "expected_status": "pending_review",
        "expected_acl": "RESTRICTED_REVIEW",
    },
    # 7. Sub-floor confidence (< 0.60) -> Triage review as unknown
    {
        "name": "sub_floor_confidence_triage",
        "predicted_type": "purchase_order",
        "confidence": 0.42,
        "pii_info": {"has_high_sensitivity": False},
        "expected_action": "ROUTE_TO_REVIEW",
        "expected_status": "pending_review",
        "expected_acl": "RESTRICTED_REVIEW",
    },
]


@pytest.mark.parametrize("case", DECISION_GATE_TEST_CASES, ids=lambda c: c["name"])
def test_decision_gate_table_driven(case):
    """Execute decision gate against parameterized rule table."""
    decision = stage_decision_gate(
        predicted_type=case["predicted_type"],
        confidence=case["confidence"],
        pii_info=case["pii_info"],
    )

    assert decision.action == case["expected_action"], f"Failed action for {case['name']}"
    assert decision.review_status == case["expected_status"], f"Failed status for {case['name']}"
    assert decision.acl == case["expected_acl"], f"Failed ACL for {case['name']}"
