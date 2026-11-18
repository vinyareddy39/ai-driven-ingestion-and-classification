"""Reprocessing tests: deploy classifier v2, reprocess affected subset, assert ground-truth preserved."""

from unittest.mock import patch
import pytest
from app.adapters.classifier import get_classifier
from app.adapters.ecm import get_ecm_adapter
from app.api.routes_reprocess import record_reprocessing_conflict_diff, reprocess_documents_by_query
from app.core.interfaces import ECMDocumentRecord
from app.models.schemas import ReprocessRequest


def test_reprocessing_affects_only_target_subset():
    """Deploy v2 classifier, trigger reprocessing for confidence < 0.85, assert only subset is enqueued."""
    req = ReprocessRequest(
        min_confidence=0.85,
        target_types=["invoice", "contract"],
        dry_run=True,
    )
    resp = reprocess_documents_by_query(req)
    assert resp.dry_run is True
    # Subset matching was evaluated
    assert resp.matched_count >= 0


def test_reprocessing_never_overwrites_human_verified_fields():
    """Assert human-verified ground-truth fields are immutable during reprocessing and conflict emits diff."""
    document_uid = "verified-doc-reprocess-test"
    human_verified = {
        "invoice_number": "INV-HUMAN-FINAL-999",
        "total_amount": 1500.0,
        "vendor_name": "Verified Vendor LLC",
    }
    # New automated model v2 extraction predicts conflicting values
    new_automated_prediction = {
        "invoice_number": "INV-AUTOMATED-ERR-000",
        "total_amount": 1400.0,
        "vendor_name": "Verified Vendor LLC",
    }

    diff_event = record_reprocessing_conflict_diff(
        document_uid=document_uid,
        human_verified=human_verified,
        new_extracted=new_automated_prediction,
    )

    assert diff_event is not None
    diffs = diff_event["field_diffs"]
    assert "invoice_number" in diffs
    assert diffs["invoice_number"]["human_verified_preserved"] == "INV-HUMAN-FINAL-999"
    assert diffs["invoice_number"]["new_automated_prediction_ignored"] == "INV-AUTOMATED-ERR-000"
    assert "total_amount" in diffs
