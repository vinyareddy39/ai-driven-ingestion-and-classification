import os
import sys
import json
import time
import requests
from unittest.mock import patch
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "backend"))

# Keys empty and external AI OFF
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GROQ_API_KEY", None)
os.environ.pop("OPENROUTER_API_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["ENABLE_EXTERNAL_AI"] = "false"
os.environ["OCR_ENGINE"] = "hybrid"

outbound_requests = []

original_requests_post = requests.post
def intercepted_post(url, *args, **kwargs):
    outbound_requests.append({
        "url": url,
        "method": "POST",
        "has_data": "json" in kwargs or "data" in kwargs or "files" in kwargs,
    })
    return original_requests_post(url, *args, **kwargs)

print("=" * 80)
print("INTERCEPTING OUTBOUND TRAFFIC DURING DOCUMENT INGESTION")
print("=" * 80)

from app.core.generalized_pipeline import GeneralizedDocumentPipeline
pipeline = GeneralizedDocumentPipeline()

with patch("requests.post", side_effect=intercepted_post):
    res_pdf = pipeline.process_file(str(BASE_DIR / "tests-data/synthetic_tests/syn_01_clean_digital.pdf"))
    res_img = pipeline.process_file(str(BASE_DIR / "tests-data/audit_inputs/doc02_receipt.png"))

print(f"Total outbound external HTTP requests recorded: {len(outbound_requests)}")
external_leaks = [r for r in outbound_requests if not any(local in r["url"] for local in ["127.0.0.1", "localhost"])]
print(f"External non-local HTTP requests: {len(external_leaks)}")

evidence_dir = BASE_DIR / "evidence" / "network_traffic_capture"
evidence_dir.mkdir(parents=True, exist_ok=True)
with open(evidence_dir / "outbound_network_capture.json", "w", encoding="utf-8") as f:
    json.dump({
        "total_requests": len(outbound_requests),
        "external_leaks_count": len(external_leaks),
        "requests": outbound_requests,
        "zero_content_leaked": len(external_leaks) == 0,
    }, f, indent=2)

print("Saved traffic capture to evidence/network_traffic_capture/outbound_network_capture.json")
