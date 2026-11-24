"""Baseline Benchmark for Step 1.

Runs 60 distinct documents through the extraction pipeline with force_fresh=True (zero cache hits).
Measures:
- Total execution time
- Latency (p50 / p95)
- Per-stage breakdown (hash, queue_wait, text_layer_check, render, deskew, ocr, model_call, db_write)
- 429 rate-limit count and retries
- Extraction accuracy against ground truth
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
import numpy as np
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.db import init_db, UserModel, BatchModel, FileModel, FieldModel
from app.api.routes_documents import process_file_background, compute_sha256

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("benchmark_step1")

BENCHMARK_DIR = os.path.abspath("data/benchmark_60")
GT_FILE = os.path.join(BENCHMARK_DIR, "ground_truth.json")
REPORT_FILE = os.path.abspath("data/benchmark_step1_baseline.json")


def run_benchmark():
    engine = init_db()
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    db = Session()

    with open(GT_FILE, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    # 1. Setup Benchmark User & Batch
    user = db.query(UserModel).filter(UserModel.email == "bench_user@example.com").first()
    if not user:
        user = UserModel(name="Benchmark Runner", email="bench_user@example.com", password_hash="dummy")
        db.add(user)
        db.commit()
        db.refresh(user)

    batch = BatchModel(user_id=user.id, name=f"Step 1 Baseline Benchmark - 60 Files")
    db.add(batch)
    db.commit()
    db.refresh(batch)
    batch_id = batch.id

    # 2. Ingest 60 Files into Batch
    file_records = []
    files_list = sorted([fn for fn in os.listdir(BENCHMARK_DIR) if fn.endswith(".pdf")])
    assert len(files_list) == 60, f"Expected 60 files, found {len(files_list)}"

    for fn in files_list:
        fpath = os.path.join(BENCHMARK_DIR, fn)
        with open(fpath, "rb") as fp:
            content = fp.read()
        sha = compute_sha256(content)
        file_rec = FileModel(
            batch_id=batch.id,
            original_name=fn,
            stored_path=fpath,
            sha256=sha,
            status="queued",
            stage="queued",
        )
        db.add(file_rec)
        file_records.append(file_rec)

    db.commit()
    for fr in file_records:
        db.refresh(fr)

    file_ids = [fr.id for fr in file_records]
    db.close()

    print(f"Starting processing of {len(file_ids)} unique documents (force_fresh=True, cache bypass)...")
    batch_start = time.perf_counter()

    # Process all 60 files concurrently through 4 workers
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(process_file_background, fid, None, True) for fid in file_ids]
        concurrent.futures.wait(futures)

    batch_total_time = round(time.perf_counter() - batch_start, 3)
    print(f"All 60 files completed in {batch_total_time}s.")

    # 3. Analyze Results and Compute Metrics
    db = Session()
    processed_files = db.query(FileModel).filter(FileModel.batch_id == batch_id).all()

    total_latencies = []
    stage_breakdown = {
        "hash_ms": [],
        "queue_wait_ms": [],
        "text_layer_check_ms": [],
        "render_ms": [],
        "deskew_ms": [],
        "ocr_ms": [],
        "model_call_ms": [],
        "db_write_ms": [],
    }
    total_429s = 0
    total_retries = 0
    total_failures = 0
    accuracy_matches = 0
    accuracy_total_expected = 0

    for pf in processed_files:
        if pf.status == "failed" or pf.stage == "Failed":
            total_failures += 1

        if pf.stage_timings:
            try:
                t = json.loads(pf.stage_timings)
                tot = t.get("total_ms", 0)
                if tot > 0:
                    total_latencies.append(tot)
                for k in stage_breakdown:
                    stage_breakdown[k].append(t.get(k, 0.0))
                total_429s += t.get("count_429", 0)
                total_retries += t.get("retries", 0)
            except Exception:
                pass

        # Evaluate extraction accuracy
        gt_entry = ground_truth.get(pf.original_name)
        if gt_entry and "expected_fields" in gt_entry:
            extracted_dict = {fld.label.lower(): fld.value for fld in pf.fields}
            for exp_k, exp_v in gt_entry["expected_fields"].items():
                accuracy_total_expected += 1
                matched = False
                for ek, ev in extracted_dict.items():
                    if exp_k.lower() in ek or ek in exp_k.lower():
                        if str(exp_v).lower() in str(ev).lower() or str(ev).lower() in str(exp_v).lower():
                            matched = True
                            break
                if matched:
                    accuracy_matches += 1

    db.close()

    p50_latency = float(np.percentile(total_latencies, 50)) if total_latencies else 0.0
    p95_latency = float(np.percentile(total_latencies, 95)) if total_latencies else 0.0
    mean_latency = float(np.mean(total_latencies)) if total_latencies else 0.0
    accuracy_pct = round((accuracy_matches / accuracy_total_expected * 100), 2) if accuracy_total_expected > 0 else 0.0

    stage_means = {k: round(float(np.mean(v)), 2) if v else 0.0 for k, v in stage_breakdown.items()}
    stage_p95s = {k: round(float(np.percentile(v, 95)), 2) if v else 0.0 for k, v in stage_breakdown.items()}

    benchmark_report = {
        "benchmark_name": "STEP_1_BASELINE_BEFORE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_documents": len(file_ids),
        "total_batch_time_seconds": batch_total_time,
        "throughput_docs_per_sec": round(len(file_ids) / batch_total_time, 2),
        "p50_per_file_ms": round(p50_latency, 2),
        "p95_per_file_ms": round(p95_latency, 2),
        "mean_per_file_ms": round(mean_latency, 2),
        "count_429": total_429s,
        "total_retries": total_retries,
        "total_failures": total_failures,
        "accuracy": {
            "expected_fields": accuracy_total_expected,
            "matched_fields": accuracy_matches,
            "accuracy_percentage": accuracy_pct,
        },
        "per_stage_timing_ms": {
            "mean": stage_means,
            "p95": stage_p95s,
        }
    }

    with open(REPORT_FILE, "w", encoding="utf-8") as rf:
        json.dump(benchmark_report, rf, indent=2)

    print("\n================ STEP 1 BASELINE BENCHMARK REPORT ================")
    print(json.dumps(benchmark_report, indent=2))
    print("===================================================================\n")
    return benchmark_report


if __name__ == "__main__":
    run_benchmark()
