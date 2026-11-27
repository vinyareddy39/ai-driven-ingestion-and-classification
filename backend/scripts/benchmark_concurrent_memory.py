import os
import sys
import time
import json
import psutil
import concurrent.futures
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "backend"))

os.environ["OCR_ENGINE"] = "hybrid"
os.environ["ENABLE_EXTERNAL_AI"] = "false"

from app.core.generalized_pipeline import GeneralizedDocumentPipeline

process = psutil.Process(os.getpid())
pipeline = GeneralizedDocumentPipeline()

# Select 10 distinct files across digital PDFs, image-only PDFs, and clean/noisy images
test_files = [
    "tests-data/synthetic_tests/syn_01_clean_digital.pdf",
    "tests-data/synthetic_tests/syn_02_clean_image.png",
    "tests-data/synthetic_tests/syn_05_multipage_two_documents.pdf",
    "tests-data/synthetic_tests/syn_06_table_many_columns.pdf",
    "tests-data/audit_inputs/doc01_invoice.pdf",
    "tests-data/audit_inputs/doc02_receipt.png",
    "tests-data/audit_inputs/doc04_bank_statement.pdf",
    "tests-data/audit_inputs/doc05_tax_w2.png",
    "tests-data/audit_inputs/doc07_employment_agreement.pdf",
    "tests-data/audit_inputs/doc15_shipping_waybill.png",
]

initial_rss_mb = round(process.memory_info().rss / (1024 * 1024), 2)
print("=" * 80)
print(f"BENCHMARKING MEMORY RSS UNDER 10 CONCURRENT UPLOADS (BASELINE RSS: {initial_rss_mb} MB)")
print("=" * 80)

peak_rss_mb = initial_rss_mb
file_durations = {}

def process_single_file(frel: str):
    fpath = BASE_DIR / frel
    t0 = time.perf_counter()
    res = pipeline.process_file(str(fpath))
    dur = round(time.perf_counter() - t0, 3)
    return frel, dur, len(res.get("fields", []))

t_start = time.perf_counter()

# Concurrent execution with 4 worker threads (matching backend threadpool)
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(process_single_file, f) for f in test_files]

    # Monitor RSS while futures are running
    while any(not fut.done() for fut in futures):
        current_rss = round(process.memory_info().rss / (1024 * 1024), 2)
        if current_rss > peak_rss_mb:
            peak_rss_mb = current_rss
        time.sleep(0.05)

    for fut in concurrent.futures.as_completed(futures):
        frel, dur, n_fields = fut.result()
        file_durations[frel] = {"duration_seconds": dur, "extracted_fields": n_fields}
        print(f"  Processed {frel}: {dur}s ({n_fields} fields)")

final_rss_mb = round(process.memory_info().rss / (1024 * 1024), 2)
total_time = round(time.perf_counter() - t_start, 2)
avg_time_per_file = round(sum(v["duration_seconds"] for v in file_durations.values()) / len(file_durations), 3)

report = {
    "initial_rss_mb": initial_rss_mb,
    "peak_rss_mb": peak_rss_mb,
    "final_rss_mb": final_rss_mb,
    "total_batch_duration_seconds": total_time,
    "average_duration_per_file_seconds": avg_time_per_file,
    "free_tier_512mb_limit_percent": round((peak_rss_mb / 512.0) * 100, 2),
    "concurrency": 4,
    "total_files": len(test_files),
    "file_durations": file_durations,
}

print("\n" + "=" * 80)
print(f"BENCHMARK COMPLETE: Peak RSS: {peak_rss_mb} MB ({report['free_tier_512mb_limit_percent']}% of 512MB)")
print(f"Total Time: {total_time}s | Avg Time Per File: {avg_time_per_file}s")
print("=" * 80)

out_dir = BASE_DIR / "evidence" / "memory_benchmark"
out_dir.mkdir(parents=True, exist_ok=True)
with open(out_dir / "memory_benchmark_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)

print(f"Saved memory benchmark evidence to evidence/memory_benchmark/memory_benchmark_report.json")
