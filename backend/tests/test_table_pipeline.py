import os
import pytest
from pathlib import Path
from app.core.generalized_pipeline import GeneralizedDocumentPipeline

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
TABLE_DIR = None
for cand in [
    WORKSPACE_ROOT / "tests-data" / "table_eval_suite",
    Path("tests-data/table_eval_suite").resolve(),
    Path("../tests-data/table_eval_suite").resolve(),
    Path("table_eval_suite").resolve()
]:
    if cand.exists():
        TABLE_DIR = cand
        break
if TABLE_DIR is None:
    TABLE_DIR = WORKSPACE_ROOT / "tests-data" / "table_eval_suite"

def test_table_grid_detection_and_structure():
    pdf_path = str(TABLE_DIR / "inputs" / "doc_01_invoice_3col_ruled.pdf")
    pipeline = GeneralizedDocumentPipeline()
    res = pipeline.process_file(pdf_path)
    
    assert res is not None
    tables = res.get("tables", [])
    assert len(tables) >= 1
    
    tbl = tables[0]
    assert tbl["headers"] == ["Description", "Qty", "Amount"]
    assert len(tbl["rows"]) == 3
    assert tbl["rows"][0]["cells"]["Qty"] == "2"
    assert tbl["rows"][0]["cells"]["Amount"] == "340.00"

def test_table_arithmetic_verification():
    pdf_path = str(TABLE_DIR / "inputs" / "doc_02_invoice_4col_unruled.pdf")
    pipeline = GeneralizedDocumentPipeline()
    res = pipeline.process_file(pdf_path)
    
    tables = res.get("tables", [])
    assert len(tables) >= 1
    tbl = tables[0]
    
    checks = tbl.get("arithmetic_checks", [])
    assert len(checks) >= 1
    # Check that product formulas and column sum verified
    verified = [c for c in checks if c.get("status") == "verified" or c.get("valid")]
    assert len(verified) >= 1

def test_same_line_pairing():
    pdf_path = str(TABLE_DIR / "inputs" / "doc_01_invoice_3col_ruled.pdf")
    pipeline = GeneralizedDocumentPipeline()
    res = pipeline.process_file(pdf_path)
    
    fields = res.get("fields", [])
    # Verify same-line pairs were extracted as single fields
    expedited = next((f for f in fields if "Expedited Freight Surcharge" in f["label"]), None)
    assert expedited is not None
    assert expedited["value"] == "$45.00"

def test_no_table_cell_leakage_and_confidence_integrity():
    pdf_path = str(TABLE_DIR / "inputs" / "doc_01_invoice_3col_ruled.pdf")
    pipeline = GeneralizedDocumentPipeline()
    res = pipeline.process_file(pdf_path)
    
    fields = res.get("fields", [])
    tables = res.get("tables", [])
    tbl = tables[0]
    
    # Confirm table headers are not loose values
    field_values = [f["value"].lower() for f in fields]
    for h in tbl["headers"]:
        assert h.lower() not in field_values
        
    # Confirm no fixed 0.90 or 0.50 confidences
    for f in fields:
        assert f.get("value_confidence") != 0.50
        if not f.get("label", "").strip():
            assert f.get("label_confidence") is None
        else:
            assert f.get("label_confidence") != 0.90
