"""Tests verifying that extractors NEVER return hardcoded fallbacks and all extracted values derive from source OCR text."""

import pytest
from app.workers.stages import stage_extract_fields, stage_decision_gate

DOCUMENT_TYPES = [
    "invoice",
    "contract",
    "kyc_form",
    "bank_statement",
    "medical_report",
    "purchase_order",
    "letter",
    "claim_form",
]

HARDCODED_FALLBACK_VALUES = [
    "INV-0000",
    "2026-01-01",
    100.00,
    "Standard Vendor Inc",
    "CNT-0000",
    "Acme Corporation",
    "Global Services LLC",
    "John Doe",
    "ID-12345678",
    "1990-01-01",
    "United States",
    "ACC-9999",
    "2026-01-01 to 2026-01-31",
    1000.00,
    1500.00,
    "PAT-0001",
    "Routine physical examination",
    "Dr. Alice Smith",
    "PO-0000",
    "Supplier Ltd",
    250.00,
    "Corporate Office",
    "Valued Customer",
    "General Correspondence",
    "CLM-0000",
    "Jane Doe",
    500.00,
]


def test_empty_text_returns_null_and_zero_confidence():
    """Empty or unparseable text must return None with confidence 0.0 for all fields."""
    gibberish_text = "Corrupted unreadable scan artifact lorem ipsum blur #!@$%"
    for doc_type in DOCUMENT_TYPES:
        extracted, confidences, is_valid = stage_extract_fields(gibberish_text, doc_type)
        assert not is_valid, f"Schema should be invalid for empty/corrupted text in {doc_type}"
        for fld, val in extracted.items():
            assert val is None, f"Field '{fld}' in {doc_type} returned fallback value '{val}' instead of None!"
            assert confidences.get(fld, 0.0) == 0.0, f"Confidence for '{fld}' in {doc_type} should be 0.0"


def test_no_hardcoded_fallback_constants_returned():
    """Ensure no hardcoded dummy constants are ever returned on random inputs."""
    random_texts = [
        "",
        "   \n\t  ",
        "UNRECOGNIZED NOISE 9999999999",
        "Just a random letter without any invoice labels or amounts",
    ]
    for text in random_texts:
        for doc_type in DOCUMENT_TYPES:
            extracted, confidences, is_valid = stage_extract_fields(text, doc_type)
            for fld, val in extracted.items():
                assert val not in HARDCODED_FALLBACK_VALUES or val is None, (
                    f"Doc type '{doc_type}' returned hardcoded fallback '{val}' for field '{fld}'!"
                )


def test_extracted_values_exist_in_source_text():
    """Any non-null string value extracted must be grounded in the source text."""
    sample_text = (
        "OFFICIAL PROCUREMENT REQUISITION\n"
        "Procurement Tracking #: PO-987654\n"
        "Requisition Date: 2026-05-15\n"
        "Authorized Vendor: Apex Global Logistics\n"
        "Authorized Requisition Sum: $12,450.75\n"
    )
    extracted, confs, is_valid = stage_extract_fields(sample_text, "purchase_order")
    assert is_valid is True
    assert extracted["po_number"] == "PO-987654"
    assert extracted["vendor_name"] == "Apex Global Logistics"
    assert extracted["total_amount"] == 12450.75 or extracted.get("order_total") == 12450.75

    for fld, val in extracted.items():
        if isinstance(val, str):
            assert val.lower() in sample_text.lower(), f"Extracted value '{val}' for '{fld}' not found in source text!"


def test_decision_gate_routes_to_review_on_invalid_extraction():
    """If field extraction fails schema validation, document must route to review."""
    decision = stage_decision_gate(
        predicted_type="invoice",
        confidence=0.99,
        pii_info={"has_high_sensitivity": False, "entities": []},
        extraction_valid=False,
    )
    assert decision.action == "ROUTE_TO_REVIEW"
    assert decision.review_status == "pending_review"
