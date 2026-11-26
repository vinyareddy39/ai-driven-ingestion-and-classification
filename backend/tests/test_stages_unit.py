"""Unit tests for individual pipeline stages."""

import os
from pathlib import Path
import pytest
from app.adapters.virus import EICAR_SIGNATURE
from app.workers.stages import (
    stage_classify,
    stage_dedupe,
    stage_extract_fields,
    stage_ocr,
    stage_pii_detect,
    stage_preprocess,
    stage_split_document,
    stage_virus_scan,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "dataset"
SPECIAL_DIR = DATA_DIR / "special"


def test_stage_virus_scan():
    clean_bytes = b"%PDF-1.4 sample clean document bytes"
    res_clean = stage_virus_scan("clean_hash", clean_bytes)
    assert res_clean["status"] == "CLEAN"

    infected_bytes = EICAR_SIGNATURE + b"malware content"
    res_infected = stage_virus_scan("infected_hash", infected_bytes)
    assert res_infected["status"] == "INFECTED"
    assert res_infected["action"] == "QUARANTINE"


def test_stage_preprocess_corrupt():
    corrupt_file = SPECIAL_DIR / "special_corrupt.pdf"
    if corrupt_file.exists():
        with open(corrupt_file, "rb") as f:
            bytes_data = f.read()
        res = stage_preprocess(bytes_data, "special_corrupt.pdf")
        assert res["status"] == "CORRUPT"
        assert res["action"] == "QUARANTINE"


def test_stage_preprocess_password_protected():
    pwd_file = SPECIAL_DIR / "special_password_protected.pdf"
    if pwd_file.exists():
        with open(pwd_file, "rb") as f:
            bytes_data = f.read()
        res = stage_preprocess(bytes_data, "special_password_protected.pdf")
        assert res["status"] == "PASSWORD_PROTECTED"
        assert res["action"] == "QUARANTINE"


def test_stage_ocr_and_classification():
    sample_train = DATA_DIR / "train" / "invoice_0001.pdf"
    if sample_train.exists():
        with open(sample_train, "rb") as f:
            bytes_data = f.read()
        ocr_res = stage_ocr(bytes_data, "invoice_0001.pdf")
        assert len(ocr_res["full_text"]) > 20
        assert ocr_res["page_count"] >= 1

        cls_res = stage_classify(ocr_res["full_text"])
        assert cls_res["predicted_class"] == "invoice"
        assert cls_res["confidence"] > 0.80


def test_stage_extract_fields_schema_validation():
    text = """
    COMMERCIAL INVOICE
    Invoice Number: INV-998877
    Invoice Date: 2026-02-15
    Vendor Name: Apex Global Logistics
    Total Amount: $4500.50
    """
    fields, confs, is_valid = stage_extract_fields(text, "invoice")
    assert is_valid is True
    assert fields["invoice_number"] == "INV-998877"
    assert fields["total_amount"] == 4500.50
    assert fields["vendor_name"] == "Apex Global Logistics"


def test_stage_pii_detection():
    sample_text = "Patient SSN is 111-22-3333 and phone is 555-019-2834, Passport P12345678."
    pii_res = stage_pii_detect(sample_text)
    assert pii_res["pii_detected"] is True
    assert "US_SSN" in pii_res["pii_types"]
    assert pii_res["has_high_sensitivity"] is True


def test_stage_split_multi_document():
    multi_file = SPECIAL_DIR / "special_100_page_mixed.pdf"
    if multi_file.exists():
        with open(multi_file, "rb") as f:
            bytes_data = f.read()
        split_parts = stage_split_document(bytes_data, "special_100_page_mixed.pdf")
        # Assert the 100-page file was split on the separator pages
        assert len(split_parts) >= 10
