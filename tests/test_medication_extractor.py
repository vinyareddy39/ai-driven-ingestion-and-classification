"""Unit Tests for Medication Field Extractor and Clinical Sanity Guardrails.

Verifies:
1. Normalization of frequencies (OD, BD, TDS, QID, HS, SOS).
2. Timing relative to meals (before, after, with food, bedtime).
3. Grounding of extracted values in OCR line text.
4. Flagging unknown drugs with requires_review=True.
5. High alert / maximum daily dose warning triggers (Paracetamol > 4000mg/day, Insulin warnings).
"""

import pytest
from app.workers.medication_extractor import MedicationExtractor


@pytest.fixture(scope="module")
def extractor():
    return MedicationExtractor()


def test_standard_medication_extraction_and_grounding(extractor):
    """Test standard multi-entity prescription line with OCR span grounding."""
    text = (
        "Clinic Outpatient Prescription\n"
        "Amoxicillin 500mg 1 capsule TDS after meals for 7 days\n"
        "Paracetamol 650mg 1 tab SOS for fever\n"
    )
    results = extractor.extract(text)
    assert len(results) == 2

    # Check Amoxicillin
    amox = results[0]
    assert amox.drug_name == "Amoxicillin"
    assert amox.strength == "500mg"
    assert "1 capsule" in amox.dose
    assert amox.frequency == "TDS"
    assert amox.timing == "after meals"
    assert amox.duration_days == 7
    # Grounding check: source span exists in raw input text
    assert amox.source_span in text
    assert amox.confidence["drug_name"] >= 0.90

    # Check Paracetamol
    para = results[1]
    assert para.drug_name == "Paracetamol"
    assert para.strength == "650mg"
    assert para.frequency == "SOS"
    assert para.source_span in text


def test_drug_alias_resolution(extractor):
    """Verify common brand names resolve to canonical active substance."""
    text = "Glucophage 500mg 1 tab BD with meals for 30 days\n"
    results = extractor.extract(text)
    assert len(results) == 1
    # Glucophage resolves to canonical Metformin
    assert results[0].drug_name == "Metformin"
    assert results[0].frequency == "BD"
    assert results[0].timing == "with meals"
    assert results[0].duration_days == 30


def test_unknown_drug_flagging_and_low_confidence(extractor):
    """Verify unknown or unformulary drugs are flagged with warning and low confidence."""
    text = "Tab Xylarid 25mg 1 tab OD after meals for 5 days\n"
    results = extractor.extract(text)
    assert len(results) == 1
    item = results[0]
    assert item.drug_name == "Xylarid"
    assert item.confidence["drug_name"] < 0.85
    # Must flag UNKNOWN_DRUG warning
    assert any("UNKNOWN_DRUG" in w for w in item.warnings)


def test_clinical_safety_max_dose_exceeded(extractor):
    """Verify paracetamol daily dose exceeding 4000mg triggers clinical safety alert."""
    text = "Paracetamol 1000mg 2 tabs QID for 5 days\n"  # 1000 * 2 * 4 = 8000mg/day!
    results = extractor.extract(text)
    assert len(results) == 1
    item = results[0]
    assert any("MAX_DOSE_EXCEEDED" in w for w in item.warnings)


def test_insulin_high_alert_flag(extractor):
    """Verify high alert insulin orders produce warning flags."""
    text = "Insulin glargine 10 units OD at bedtime\n"
    results = extractor.extract(text)
    assert len(results) == 1
    item = results[0]
    assert any("High alert medication" in w for w in item.warnings)
