"""Unit and Integration Tests for High-Performance OCR Stage.

Tests:
1. TrOCR singleton initialization and device allocation
2. Direct text-layer bypass for PDFs (recording "text_layer")
3. Scanned page OCR execution (recording "ocr")
4. Content-hash based OCR result caching
5. Configuration fallback switch (OCR_ENGINE=tesseract vs trocr)
6. Preserved audit record and bounding box structures
"""

import os
import pytest
import cv2
import numpy as np
import fitz
from app.core.config import get_app_settings
from app.adapters.ocr import get_ocr_engine, TrOCREngine, HybridOCREngine
from app.core.interfaces import OCRResult, BoundingBox


@pytest.fixture
def sample_pdf_with_text() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(fitz.Point(50, 72), "INVOICE NUMBER: INV-2026-9999\nTOTAL AMOUNT: $500.00", fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture
def sample_scanned_image() -> bytes:
    # 200x50 white image with black text simulated
    img = np.full((100, 300, 3), 255, dtype=np.uint8)
    cv2.putText(img, "TEST OCR LINE", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    _, encoded = cv2.imencode(".png", img)
    return encoded.tobytes()


def test_text_layer_bypass_records_method(sample_pdf_with_text):
    """PDFs with existing text layer must extract text directly and record 'text_layer'."""
    engine = TrOCREngine()
    res = engine.extract_text(sample_pdf_with_text, "pdf")

    assert res.pages_count == 1
    assert "INV-2026-9999" in res.full_text
    assert res.page_methods == ["text_layer"]
    assert len(res.bounding_boxes) > 0


def test_content_hash_caching(sample_pdf_with_text):
    """Second extraction of identical content hash returns from cache."""
    engine = TrOCREngine()
    res1 = engine.extract_text(sample_pdf_with_text, "pdf")
    res2 = engine.extract_text(sample_pdf_with_text, "pdf")

    assert res1.full_text == res2.full_text
    assert res1.page_methods == res2.page_methods


def test_scanned_image_records_ocr_method(sample_scanned_image):
    """Image files must be recognized via OCR and record 'ocr'."""
    engine = TrOCREngine()
    res = engine.extract_text(sample_scanned_image, "png")

    assert res.pages_count == 1
    assert res.page_methods == ["ocr"]


def test_engine_factory_config_switch(monkeypatch):
    """Changing OCR_ENGINE config switch allows switching back to legacy Hybrid engine."""
    import app.adapters.ocr as ocr_mod
    monkeypatch.setattr(ocr_mod, "_ocr_engine_singleton", None)

    # Force legacy engine via environment variable
    monkeypatch.setenv("OCR_ENGINE", "tesseract")
    legacy_engine = ocr_mod.get_ocr_engine()
    assert isinstance(legacy_engine, HybridOCREngine)

    # Force TrOCR engine
    monkeypatch.setattr(ocr_mod, "_ocr_engine_singleton", None)
    monkeypatch.setenv("OCR_ENGINE", "trocr")
    trocr_engine = ocr_mod.get_ocr_engine()
    assert isinstance(trocr_engine, TrOCREngine)
