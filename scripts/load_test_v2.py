"""Enterprise load test benchmarking 500+ completely unique documents across all 9 document classes.

Labeled: [LOCAL MODE ONLY]
Measures warm-up, end-to-end latency percentiles (p50, p90, p95, p99),
per-class throughput, and per-stage latency breakdown.
"""

import hashlib
import os
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Any

import fitz
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.storage import get_storage_adapter
from app.workers.pipeline import STAGE_LATENCY_METRICS, process_document_payload
from data.synthetic_generator import (
    generate_invoice_content, generate_contract_content, generate_kyc_content,
    generate_bank_statement_content, generate_medical_report_content,
    generate_purchase_order_content, generate_letter_content, generate_claim_form_content,
    generate_unknown_content
)

CLASSES = [
    "invoice", "contract", "kyc_form", "bank_statement",
    "medical_report", "purchase_order", "letter", "claim_form", "unknown"
]

GENERATOR_MAP = {
    "invoice": generate_invoice_content,
    "contract": generate_contract_content,
    "kyc_form": generate_kyc_content,
    "bank_statement": generate_bank_statement_content,
    "medical_report": generate_medical_report_content,
    "purchase_order": generate_purchase_order_content,
    "letter": generate_letter_content,
    "claim_form": generate_claim_form_content,
    "unknown": generate_unknown_content,
}


def render_digital_pdf(text: str) -> bytes:
    """Render text to a standards-compliant digital PDF with layout stream."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    lines = text.split("\n")
    y = 50
    for line in lines[:48]:
        page.insert_text(fitz.Point(40, y), line, fontsize=10, fontname="helv")
        y += 16
    return doc.tobytes()


def generate_unique_doc(doc_type: str, index: int) -> tuple[bytes, str]:
    """Generate a completely unique document payload with unique text, bytes, and sha256."""
    gen_func = GENERATOR_MAP[doc_type]
    text, _, _ = gen_func(index + 100000)
    # Append unique entropy token to ensure 100% unique SHA256 (no deduplication bypass)
    entropy = f"\nUnique-Tracking-Nonce: {uuid.uuid4().hex}-{time.time_ns()}\nAudit-Hash-Salt: {index:06d}"
    text += entropy
    pdf_bytes = render_digital_pdf(text)
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    return pdf_bytes, sha256


def run_load_test(docs_per_class: int = 60, warmup_count: int = 10):
    print("=" * 80, flush=True)
    print("ENTERPRISE LOAD TEST BENCHMARK [LOCAL MODE ONLY]", flush=True)
    print("=" * 80, flush=True)
    print("Target: 500+ completely unique documents across all 9 classes (no reused payloads)", flush=True)
    print("Execution Environment: Windows 11 | Local In-Memory Adapters | Python 3.11", flush=True)
    print(f"Document Classes: {', '.join(CLASSES)}", flush=True)
    print(f"Configuration: {docs_per_class} docs/class * 9 classes = {docs_per_class * len(CLASSES)} total documents\n", flush=True)

    storage = get_storage_adapter()

    # 1. Warm-Up Phase
    print("-" * 80, flush=True)
    print(f"PHASE 1: SYSTEM WARM-UP ({warmup_count} documents)", flush=True)
    print("-" * 80, flush=True)
    warmup_start = time.perf_counter()
    warmup_latencies = []
    for w in range(warmup_count):
        cls = CLASSES[w % len(CLASSES)]
        raw_pdf, sha = generate_unique_doc(cls, 900000 + w)
        storage.save(sha, raw_pdf)
        payload = {
            "uid": f"warmup-{w:04d}",
            "sha256": sha,
            "file_name": f"warmup_{cls}_{w:04d}.pdf",
            "storage_path": f"storage/{sha}",
            "is_reprocess": False,
        }
        t0 = time.perf_counter()
        res = process_document_payload(payload)
        t_el = time.perf_counter() - t0
        warmup_latencies.append(t_el)
        print(f"  Warm-up doc {w+1:2d}/{warmup_count} ({cls:<15}): {t_el*1000:6.1f} ms -> {res.get('status')}", flush=True)

    warmup_duration = time.perf_counter() - warmup_start
    print(f"\nWarm-up complete: {warmup_count} documents processed in {warmup_duration:.2f}s "
          f"({warmup_count / warmup_duration:.2f} docs/sec). Models and caches primed.\n", flush=True)

    # Clear STAGE_LATENCY_METRICS collected during warm-up
    for stage_k in STAGE_LATENCY_METRICS:
        STAGE_LATENCY_METRICS[stage_k].clear()

    # 2. Main Benchmark Phase (500+ unique documents)
    total_docs = docs_per_class * len(CLASSES)
    print("-" * 80, flush=True)
    print(f"PHASE 2: MAIN SUSTAINED LOAD TEST ({total_docs} COMPLETELY UNIQUE DOCUMENTS)", flush=True)
    print("-" * 80, flush=True)

    print(f"Pre-generating {total_docs} distinct PDF payloads with unique SHA256 hashes...", flush=True)
    doc_queue = []
    doc_idx = 0
    gen_t0 = time.perf_counter()
    for cls in CLASSES:
        for i in range(docs_per_class):
            doc_idx += 1
            raw_pdf, sha = generate_unique_doc(cls, doc_idx)
            storage.save(sha, raw_pdf)
            doc_queue.append({
                "uid": f"load-test-{cls}-{i:04d}-{sha[:8]}",
                "sha256": sha,
                "file_name": f"load_{cls}_{i:04d}.pdf",
                "storage_path": f"storage/{sha}",
                "doc_type": cls,
                "is_reprocess": False,
            })
    print(f"Payload generation complete: {len(doc_queue)} unique assets ready ({time.perf_counter()-gen_t0:.2f}s).\n", flush=True)

    # Execute processing loop
    latencies: List[float] = []
    per_class_latencies = defaultdict(list)
    per_class_counts = defaultdict(int)
    status_counts = defaultdict(int)

    benchmark_start = time.perf_counter()

    for idx, item in enumerate(doc_queue, 1):
        cls = item["doc_type"]
        t_start = time.perf_counter()
        result = process_document_payload(item)
        t_elapsed = time.perf_counter() - t_start

        latencies.append(t_elapsed)
        per_class_latencies[cls].append(t_elapsed)
        per_class_counts[cls] += 1
        status_counts[result.get("status", "UNKNOWN")] += 1

        if idx % 90 == 0 or idx == total_docs:
            elapsed_so_far = time.perf_counter() - benchmark_start
            rate = idx / elapsed_so_far
            print(f"  Processed {idx:3d}/{total_docs} unique docs | Elapsed: {elapsed_so_far:5.1f}s | "
                  f"Throughput: {rate:5.2f} docs/sec | Current Class: {cls}", flush=True)

    total_benchmark_duration = time.perf_counter() - benchmark_start
    overall_throughput = total_docs / total_benchmark_duration

    # 3. Comprehensive Metric Reporting
    print("\n" + "=" * 80, flush=True)
    print("LOAD TEST RESULTS SUMMARY [LOCAL MODE ONLY]", flush=True)
    print("=" * 80, flush=True)
    print(f"Total Unique Documents Processed: {total_docs}", flush=True)
    print(f"Total Wall-Clock Time:            {total_benchmark_duration:.2f} seconds", flush=True)
    print(f"Overall Throughput:               {overall_throughput:.2f} documents/sec", flush=True)
    print(f"Hourly Equivalent:                {overall_throughput * 3600:,.0f} documents/hour", flush=True)
    print(f"Daily Equivalent (24h sustained): {overall_throughput * 86400:,.0f} documents/day", flush=True)
    req_50k_rate = 50000 / 86400.0
    print(f"Requirement Check (50,000 docs/day = {req_50k_rate:.2f} docs/sec): "
          f"{'PASS (Exceeds requirement by ' + f'{overall_throughput/req_50k_rate:.1f}x)' if overall_throughput >= req_50k_rate else 'FAIL'}", flush=True)

    print("\n" + "-" * 80, flush=True)
    print("END-TO-END DOCUMENT LATENCY PERCENTILES", flush=True)
    print("-" * 80, flush=True)
    lat_arr = np.array(latencies) * 1000.0  # convert to ms
    print(f"Mean Latency:   {np.mean(lat_arr):7.2f} ms", flush=True)
    print(f"Median (p50):   {np.percentile(lat_arr, 50):7.2f} ms", flush=True)
    print(f"p90 Latency:    {np.percentile(lat_arr, 90):7.2f} ms", flush=True)
    print(f"p95 Latency:    {np.percentile(lat_arr, 95):7.2f} ms", flush=True)
    print(f"p99 Latency:    {np.percentile(lat_arr, 99):7.2f} ms", flush=True)
    print(f"Min Latency:    {np.min(lat_arr):7.2f} ms", flush=True)
    print(f"Max Latency:    {np.max(lat_arr):7.2f} ms", flush=True)

    print("\n" + "-" * 80, flush=True)
    print("PER-CLASS SAMPLE COUNTS & THROUGHPUT", flush=True)
    print("-" * 80, flush=True)
    print(f"{'Class':<20} {'Count':<8} {'Total Time (s)':<16} {'Throughput (docs/s)':<22} {'Mean Latency (ms)':<18}", flush=True)
    for cls in CLASSES:
        cls_lats = np.array(per_class_latencies[cls])
        cls_count = per_class_counts[cls]
        cls_time = np.sum(cls_lats)
        cls_rate = cls_count / max(0.001, cls_time)
        print(f"{cls:<20} {cls_count:<8} {cls_time:<16.2f} {cls_rate:<22.2f} {np.mean(cls_lats)*1000:<18.2f}", flush=True)

    print("\n" + "-" * 80, flush=True)
    print("PER-STAGE LATENCY BREAKDOWN (PERCENTILES)", flush=True)
    print("-" * 80, flush=True)
    print(f"{'Stage Name':<28} {'Samples':<10} {'p50 (ms)':<12} {'p90 (ms)':<12} {'p95 (ms)':<12} {'p99 (ms)':<12}", flush=True)
    for stage_name, s_lats in STAGE_LATENCY_METRICS.items():
        if s_lats:
            arr = np.array(s_lats) * 1000.0
            p50 = np.percentile(arr, 50)
            p90 = np.percentile(arr, 90)
            p95 = np.percentile(arr, 95)
            p99 = np.percentile(arr, 99)
            print(f"{stage_name:<28} {len(s_lats):<10} {p50:<12.2f} {p90:<12.2f} {p95:<12.2f} {p99:<12.2f}", flush=True)

    print("\n" + "-" * 80, flush=True)
    print("PIPELINE STATUS BREAKDOWN", flush=True)
    print("-" * 80, flush=True)
    for stat, cnt in status_counts.items():
        print(f"  {stat}: {cnt} ({cnt/total_docs*100:.1f}%)", flush=True)
    print("=" * 80 + "\n", flush=True)


if __name__ == "__main__":
    run_load_test(docs_per_class=60, warmup_count=10)
