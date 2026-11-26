"""Unit test for context-required NATIONAL_ID pattern."""

import pytest
from app.adapters.pii import get_pii_detector

def test_national_id_detection_with_context():
    detector = get_pii_detector()
    
    # 1. Context present -> Must detect NATIONAL_ID
    text_with_context = "Subject submitted National ID: NID-84920485 for identity attestation."
    entities = detector.detect(text_with_context)
    nid_entities = [e for e in entities if e.entity_type == "NATIONAL_ID"]
    assert len(nid_entities) == 1
    assert nid_entities[0].text == "NID-84920485"
    assert nid_entities[0].sensitivity == "high"

    # 2. Context variations
    text_alt_context = "Citizen Registration: CR-9921441 verified by compliance officer."
    entities_alt = detector.detect(text_alt_context)
    nid_alt = [e for e in entities_alt if e.entity_type == "NATIONAL_ID"]
    assert len(nid_alt) == 1
    assert nid_alt[0].text == "CR-9921441"

def test_national_id_no_false_positives_without_context():
    detector = get_pii_detector()
    
    # Isolated ID or non-national ID context must NOT be detected as NATIONAL_ID
    text_no_context = "Invoice number INV-84920485 total amount $450.00."
    entities = detector.detect(text_no_context)
    nid_entities = [e for e in entities if e.entity_type == "NATIONAL_ID"]
    assert len(nid_entities) == 0
