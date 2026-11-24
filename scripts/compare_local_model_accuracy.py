"""Compare Local Model vs Rule Parser on Holdout Documents.
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.abspath("."))
import requests
from scripts.evaluate_accuracy_and_routing import (
    compute_field_metrics,
    evaluate_rule_parser,
    load_dataset_samples,
    normalize_val,
)

samples = load_dataset_samples(max_samples=5)
ollama_url = "http://127.0.0.1:11434/api/generate"
model_name = "qwen2.5-coder:7b"

local_tp = 0
local_fp = 0
local_fn = 0
latencies = []

print("Running Local Model (qwen2.5-coder:7b) on holdout samples...")
for idx, s in enumerate(samples):
    text = s.get("ocr_text", "")
    expected_fields = s.get("fields", {})
    doc_type = s.get("doc_type", "Document")

    prompt = (
        "Extract physical key-value fields from this document text as JSON:\n"
        '{"doc_type": "string", "fields": [{"label": "string", "value": "string"}]}\n\n'
        f"DOCUMENT TEXT:\n{text[:2000]}"
    )

    t0 = time.perf_counter()
    resp = requests.post(
        ollama_url,
        json={
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0, "num_ctx": 2048},
        },
        timeout=60,
    )
    elapsed = time.perf_counter() - t0
    latencies.append(elapsed)

    extracted_fields = []
    if resp.status_code == 200:
        data = resp.json()
        match = re.search(r"\{.*\}", data.get("response", ""), re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                extracted_fields = parsed.get("fields", [])
            except Exception:
                pass

    tp, fp, fn = compute_field_metrics(extracted_fields, expected_fields)
    local_tp += tp
    local_fp += fp
    local_fn += fn
    print(f"Doc {idx+1} ({doc_type}): {elapsed:.2f}s | Expected: {len(expected_fields)} | Extracted: {len(extracted_fields)} | Matched TP: {tp}")

loc_prec = local_tp / (local_tp + local_fp) if (local_tp + local_fp) > 0 else 0
loc_rec = local_tp / (local_tp + local_fn) if (local_tp + local_fn) > 0 else 0
loc_f1 = (2 * loc_prec * loc_rec) / (loc_rec + loc_prec) if (loc_rec + loc_prec) > 0 else 0
avg_lat = sum(latencies) / len(latencies) if latencies else 0

print("=" * 60)
print(f"LOCAL MODEL (qwen2.5-coder:7b) ACCURACY ON HOLDOUT SAMPLES:")
print(f"  Field Precision: {loc_prec * 100:.1f}%")
print(f"  Field Recall:    {loc_rec * 100:.1f}%")
print(f"  Field F1-Score:  {loc_f1 * 100:.1f}%")
print(f"  Avg Latency per doc: {avg_lat:.2f}s")
print("=" * 60)
