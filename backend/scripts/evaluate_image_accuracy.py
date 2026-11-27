import os
import sys
import json
import time
from pathlib import Path

# Ensure backend and root paths are in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "backend"))

# Make sure all external API keys are unset
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GROQ_API_KEY", None)
os.environ.pop("OPENROUTER_API_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["ENABLE_EXTERNAL_AI"] = "false"
os.environ["OCR_ENGINE"] = "hybrid"

from app.core.generalized_pipeline import GeneralizedDocumentPipeline
from app.adapters.ocr import HybridOCREngine

pipeline = GeneralizedDocumentPipeline()
ocr_engine = HybridOCREngine()

# Image test files with answer keys
IMAGE_TEST_CASES = [
    {
        "file": "tests-data/audit_inputs/doc02_receipt.png",
        "expected_json": "tests-data/audit_inputs/doc02_receipt.expected.json",
        "alias": "c_02.png (doc02_receipt)",
    },
    {
        "file": "tests-data/audit_inputs/doc05_tax_w2.png",
        "expected_json": "tests-data/audit_inputs/doc05_tax_w2.expected.json",
        "alias": "c_05.png (doc05_tax_w2)",
    },
    {
        "file": "tests-data/audit_inputs/doc11_resignation_letter.png",
        "expected_json": "tests-data/audit_inputs/doc11_resignation_letter.expected.json",
        "alias": "doc11_resignation_letter.png",
    },
    {
        "file": "tests-data/audit_inputs/doc15_shipping_waybill.png",
        "expected_json": "tests-data/audit_inputs/doc15_shipping_waybill.expected.json",
        "alias": "doc15_shipping_waybill.png",
    },
    {
        "file": "tests-data/audit_inputs/doc19_vendor_price_notice.png",
        "expected_json": "tests-data/audit_inputs/doc19_vendor_price_notice.expected.json",
        "alias": "doc19_vendor_price_notice.png",
    },
    {
        "file": "tests-data/audit_inputs/doc26_maintenance_inspection.png",
        "expected_json": "tests-data/audit_inputs/doc26_maintenance_inspection.expected.json",
        "alias": "doc26_maintenance_inspection.png",
    },
    {
        "file": "tests-data/synthetic_tests/syn_02_clean_image.png",
        "expected_json": None,
        "alias": "syn_02_clean_image.png",
    },
]

results = []

print("=" * 80)
print("EVALUATING IMAGE READING ACCURACY (HYBRID OCR, NO EXTERNAL KEYS)")
print("=" * 80)

for tc in IMAGE_TEST_CASES:
    fpath = BASE_DIR / tc["file"]
    if not fpath.exists():
        print(f"Skipping missing: {tc['file']}")
        continue

    t0 = time.perf_counter()
    res = pipeline.process_file(str(fpath))
    dur_ms = round((time.perf_counter() - t0) * 1000, 2)

    extracted_fields = res.get("fields", [])
    extracted_text = res.get("raw_text", "")

    # Compare against expected answer key if present
    expected_data = {}
    if tc["expected_json"]:
        exp_path = BASE_DIR / tc["expected_json"]
        if exp_path.exists():
            with open(exp_path, "r", encoding="utf-8") as f:
                expected_data = json.load(f)

    exp_kvs = expected_data.get("key_values", {})
    matched_count = 0
    total_expected = len(exp_kvs)

    # Fuzzy match extracted values against answer key
    ext_vals_lower = " ".join([str(f.get("value", "")).lower() for f in extracted_fields])
    for k, v in exp_kvs.items():
        v_str = str(v).lower().strip("$")
        # Check if key numbers/names appear in extracted values
        if any(part in ext_vals_lower for part in v_str.split() if len(part) > 2):
            matched_count += 1

    acc = round((matched_count / total_expected * 100), 1) if total_expected > 0 else 100.0

    entry = {
        "alias": tc["alias"],
        "file": tc["file"],
        "duration_ms": dur_ms,
        "extracted_fields_count": len(extracted_fields),
        "expected_fields_count": total_expected,
        "matched_fields": matched_count,
        "accuracy_pct": acc,
        "sample_fields": [
            {"label": f.get("label"), "value": f.get("value"), "confidence": f.get("confidence")}
            for f in extracted_fields[:4]
        ],
    }
    results.append(entry)
    print(f"[{tc['alias']}] Fields: {len(extracted_fields)} | Expected: {total_expected} | Matched: {matched_count} ({acc}%) | Time: {dur_ms}ms")

# Save results
out_dir = BASE_DIR / "evidence" / "image_reading_evaluation"
out_dir.mkdir(parents=True, exist_ok=True)
with open(out_dir / "image_accuracy_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print("\nSaved image accuracy report to evidence/image_reading_evaluation/image_accuracy_results.json")
