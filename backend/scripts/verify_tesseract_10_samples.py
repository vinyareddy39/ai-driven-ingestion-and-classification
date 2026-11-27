"""Verify Tesseract OCR execution on 10 sample assets across classes and degradation types."""

from pathlib import Path
from app.adapters.ocr import get_ocr_engine

BASE_DIR = Path(__file__).resolve().parent.parent
VAL_DIR = BASE_DIR / "data" / "dataset" / "val"

def verify_10_samples():
    print("=" * 75)
    print("OCR ENGINE VERIFICATION ON 10 SAMPLE SCANNED ASSETS")
    print("=" * 75)

    engine = get_ocr_engine()
    sample_files = [
        "invoice_0121.pdf",
        "contract_0122.pdf",
        "kyc_form_0123.pdf",
        "bank_statement_0124.pdf",
        "medical_report_0125.pdf",
        "purchase_order_0126.pdf",
        "letter_0127.pdf",
        "claim_form_0128.pdf",
        "unknown_0129.pdf",
        "invoice_0130.pdf",
    ]

    for idx, fname in enumerate(sample_files, 1):
        fpath = VAL_DIR / fname
        assert fpath.exists(), f"Sample file {fpath} does not exist!"
        with open(fpath, "rb") as f:
            pdf_bytes = f.read()

        ocr_res = engine.extract_text(pdf_bytes, "pdf")
        snippet = ocr_res.full_text.strip().replace("\n", " ")[:60]
        print(f"Sample {idx:02d}: File: {fname:<25} | Engine: {ocr_res.engine_name} ({ocr_res.engine_version}) | Chars: {len(ocr_res.full_text):<4} | Snippet: {snippet}...")
        assert "Tesseract" in ocr_res.engine_name, f"Engine {ocr_res.engine_name} did not use Tesseract!"

    print("-" * 75)
    print("Result: 10/10 scanned assets (100.0%) executed through Tesseract-OCR engine.")
    print("=" * 75)

if __name__ == "__main__":
    verify_10_samples()
