"""Benchmark runner executing the sample test files across all document edge cases.

Cases evaluated:
1. Invoice (clean digital PDF)
2. KYC Form (compliance document)
3. Medical Report (stricter decision threshold & PII)
4. Scan (noisy, skewed page requiring deskew)
5. Mixed / Scanned Case (scanned document)
6. Multi-document bundle (multi-page split)
7. Exact Duplicate (instant link reference creation)
8. Blank page (blank page filtering & quarantine/handling)
9. Password-protected (integrity gate & security quarantine)
10. Corrupt file (poison file isolation & DLQ alerting)

Measures and reports per-stage timings:
- virus_scan
- dedupe
- preprocess
- ocr
- classify
- extract_fields
- pii_detect
- decision_gate
- ecm_write
- search_index
- audit
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.adapters.storage import get_storage_adapter
from app.models.db import init_db
from app.workers.pipeline import process_document_payload


def run_sample_benchmark():
    init_db()
    storage = get_storage_adapter()

    test_cases = [
        {
            "category": "Invoice (Digital)",
            "path": BASE_DIR / "data" / "benchmark_60" / "bench_01_invoice.pdf",
            "name": "sample_invoice.pdf",
        },
        {
            "category": "KYC Form (Identity)",
            "path": BASE_DIR / "data" / "benchmark_60" / "bench_16_kyc.pdf",
            "name": "sample_kyc_form.pdf",
        },
        {
            "category": "Medical Report (Health / Strict Gate)",
            "path": BASE_DIR / "test_files" / "trap_02_lab_report.pdf",
            "name": "trap_02_lab_report.pdf",
        },
        {
            "category": "Scan (Noisy / Skewed)",
            "path": BASE_DIR / "test_files" / "trap_05_noisy_skewed.pdf",
            "name": "trap_05_noisy_skewed.pdf",
        },
        {
            "category": "Scan / Mixed Case",
            "path": BASE_DIR / "test_files" / "trap_03_mixed_case.pdf",
            "name": "trap_03_mixed_case.pdf",
        },
        {
            "category": "Multi-Document Bundle",
            "path": BASE_DIR / "data" / "dataset" / "special" / "special_100_page_mixed.pdf",
            "name": "special_100_page_mixed.pdf",
        },
        {
            "category": "Duplicate (of trap_05)",
            "path": BASE_DIR / "test_files" / "trap_06_duplicate_of_05.pdf",
            "name": "trap_06_duplicate_of_05.pdf",
        },
        {
            "category": "Blank Page Document",
            "path": BASE_DIR / "data" / "dataset" / "special" / "special_blank_page.pdf",
            "name": "special_blank_page.pdf",
        },
        {
            "category": "Password-Protected File",
            "path": BASE_DIR / "data" / "dataset" / "special" / "special_password_protected.pdf",
            "name": "special_password_protected.pdf",
        },
        {
            "category": "Corrupt / Poison File",
            "path": BASE_DIR / "data" / "dataset" / "special" / "special_corrupt.pdf",
            "name": "special_corrupt.pdf",
        },
    ]

    results = []

    print("\n" + "=" * 90)
    print("RUNNING DOCUMENT INGESTION & CLASSIFICATION PIPELINE BENCHMARK")
    print("=" * 90)

    for tc in test_cases:
        p = tc["path"]
        name = tc["name"]
        cat = tc["category"]

        if not p.exists():
            print(f"Skipping {cat}: {p} not found")
            continue

        with open(p, "rb") as f:
            raw_bytes = f.read()

        sha = hashlib.sha256(raw_bytes).hexdigest()
        storage.save(sha, raw_bytes)
        uid = f"bench-{sha[:10]}"

        payload = {
            "uid": uid,
            "sha256": sha,
            "file_name": name,
            "storage_path": f"storage/{sha}",
            "is_reprocess": False,
        }

        t_start = time.perf_counter()
        res = process_document_payload(payload)
        t_total = time.perf_counter() - t_start

        decision = res.get("decision", {})
        action = decision.get("action", res.get("status", "UNKNOWN"))
        doc_type = decision.get("doc_type", res.get("reason", "unknown"))

        record = {
            "category": cat,
            "file_name": name,
            "file_size_kb": round(len(raw_bytes) / 1024, 1),
            "status": res.get("status", "UNKNOWN"),
            "action": action,
            "detected_type": doc_type,
            "total_time_sec": round(t_total, 3),
            "target_budget_sec": 120.0,
            "under_budget": t_total < 120.0,
        }
        results.append(record)

        print(
            f"[{record['status']:<16}] {cat:<32} | Time: {record['total_time_sec']:>6.3f}s | "
            f"Action: {action:<18} | Size: {record['file_size_kb']:>6.1f} KB"
        )

    from app.workers.pipeline import STAGE_LATENCY_METRICS
    import numpy as np

    stage_summary = {}
    for stage_name, lats in STAGE_LATENCY_METRICS.items():
        if lats:
            stage_summary[stage_name] = {
                "count": len(lats),
                "mean_ms": round(float(np.mean(lats)) * 1000, 2),
                "p95_ms": round(float(np.percentile(lats, 95)) * 1000, 2),
                "max_ms": round(float(np.max(lats)) * 1000, 2),
            }

    benchmark_output = {
        "files_processed": results,
        "stage_timings": stage_summary,
    }

    out_file = BASE_DIR / "data" / "sample_benchmark_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(benchmark_output, f, indent=2)

    print("\n" + "=" * 90)
    print("STAGE LATENCY TIMING SUMMARY (Mean and p95 across all files):")
    for s_name, s_data in stage_summary.items():
        print(f"  Stage: {s_name:<16} | Mean: {s_data['mean_ms']:>8.2f} ms | p95: {s_data['p95_ms']:>8.2f} ms | Max: {s_data['max_ms']:>8.2f} ms")
    print(f"\nSaved summary to {out_file}")
    print("=" * 90 + "\n")
    return benchmark_output


if __name__ == "__main__":
    run_sample_benchmark()
