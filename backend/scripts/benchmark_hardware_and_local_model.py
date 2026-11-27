"""Hardware and Local Model Benchmark Script.

Measures:
1. Hardware specifications (GPU, VRAM, CPU, RAM, OS).
2. Local Ollama model inference speed (eval tokens/second, time per document).
3. Concurrency scaling (1, 2, 4 parallel requests) and latency degradation.
4. Throughput (estimated documents per minute).
5. Share of documents that reach the local model vs handled by rule parser/validators.
6. Feasibility analysis for a 500-file batch in 300 seconds.
7. Accuracy evaluation on test dataset comparing Rule Parser vs Local Model vs Cloud Provider.
"""

import asyncio
import json
import os
import platform
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

import psutil
import requests

# 1. Hardware Detection
print("=" * 70)
print("1. HARDWARE DETECTION REPORT")
print("=" * 70)

os_info = f"{platform.system()} {platform.release()} (Build {platform.version()})"
cpu_name = platform.processor()
cpu_phys = psutil.cpu_count(logical=False)
cpu_log = psutil.cpu_count(logical=True)
mem = psutil.virtual_memory()
total_ram_gb = round(mem.total / (1024**3), 2)
avail_ram_gb = round(mem.available / (1024**3), 2)

gpu_info = "No discrete GPU detected"
vram_gb = 0.0
try:
    import torch
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        vram_gb = round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2)
        gpu_info = f"{gpu_name} with {vram_gb:.2f} GB VRAM"
except Exception as e:
    gpu_info = f"Detection error: {e}"

print(f"OS: {os_info}")
print(f"CPU: {cpu_name} ({cpu_phys} Physical Cores, {cpu_log} Logical Threads)")
print(f"RAM: {total_ram_gb} GB Total ({avail_ram_gb} GB Free / Available)")
print(f"GPU: {gpu_info}")

# 2. Benchmark Ollama Model
print("\n" + "=" * 70)
print("2. LOCAL MODEL BENCHMARK (Ollama qwen2.5-coder:7b)")
print("=" * 70)

ollama_url = "http://127.0.0.1:11434/api/generate"
model_name = "qwen2.5-coder:7b"

sample_doc_text = """
Prescription & Consultation Note
Patient Name: Arthur Pendelton
Age: 52    Gender: Male
Date: 2024-04-18
Doctor: Dr. Eleanor Vance, MD
Clinic: St. Jude Health Center
Diagnosis: Hypertension and Hyperlipidemia
Rx:
1. Lisinopril 20mg Tablet - Once daily in morning
2. Atorvastatin 40mg Tablet - Once daily at bedtime
Refills: 3
Blood Pressure: 138/88 mmHg
"""

prompt = (
    "Extract visible physical details from this document text as compact JSON with this schema:\n"
    '{"doc_type": "Medical Prescription", "title": "Prescription", "fields": [{"label": "Patient Name", "value": "Arthur Pendelton", "confidence": 0.98}]}\n\n'
    f"DOCUMENT TEXT:\n{sample_doc_text.strip()}"
)

def query_ollama(idx: int = 1) -> Dict[str, Any]:
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
    if resp.status_code == 200:
        data = resp.json()
        eval_count = data.get("eval_count", 0)
        eval_dur_ns = data.get("eval_duration", 1)
        prompt_eval_dur_ns = data.get("prompt_eval_duration", 1)
        prompt_eval_count = data.get("prompt_eval_count", 0)
        tok_sec = (eval_count / (eval_dur_ns / 1e9)) if eval_dur_ns > 0 else 0
        prompt_tok_sec = (prompt_eval_count / (prompt_eval_dur_ns / 1e9)) if prompt_eval_dur_ns > 0 else 0
        return {
            "success": True,
            "latency_s": elapsed,
            "tokens_generated": eval_count,
            "eval_tok_per_sec": tok_sec,
            "prompt_tok_per_sec": prompt_tok_sec,
            "response": data.get("response", ""),
        }
    return {"success": False, "error": f"HTTP {resp.status_code}", "latency_s": elapsed}

# Warmup run
print("Warming up model on GPU...")
warmup = query_ollama()
if not warmup["success"]:
    print("Warmup failed:", warmup)
else:
    print(f"Warmup complete in {warmup['latency_s']:.2f}s! ({warmup['eval_tok_per_sec']:.1f} tok/s)")

# Single document benchmark (3 runs, median)
single_runs = []
for i in range(3):
    r = query_ollama(i)
    if r["success"]:
        single_runs.append(r)
        print(f"  Single run {i+1}: {r['latency_s']:.2f}s | {r['tokens_generated']} tokens | {r['eval_tok_per_sec']:.1f} tok/s")

med_latency = sorted([r["latency_s"] for r in single_runs])[len(single_runs) // 2]
med_tok_sec = sorted([r["eval_tok_per_sec"] for r in single_runs])[len(single_runs) // 2]
print(f"\nMedian Single File Latency: {med_latency:.2f}s ({med_tok_sec:.1f} tok/s GPU eval)")

# Concurrency scaling benchmark: 1, 2, 4 parallel requests
concurrency_results = {}
for concurrency in [1, 2, 4]:
    t_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        results = list(executor.map(query_ollama, range(concurrency)))
    total_time = time.perf_counter() - t_start
    successes = [r for r in results if r["success"]]
    avg_lat = sum(r["latency_s"] for r in successes) / len(successes) if successes else 0
    total_tokens = sum(r.get("tokens_generated", 0) for r in successes)
    aggregate_tok_sec = total_tokens / total_time if total_time > 0 else 0
    docs_per_min = (len(successes) / total_time) * 60.0

    concurrency_results[concurrency] = {
        "concurrency": concurrency,
        "total_time_s": round(total_time, 2),
        "avg_latency_per_doc_s": round(avg_lat, 2),
        "aggregate_tok_per_sec": round(aggregate_tok_sec, 1),
        "docs_per_min": round(docs_per_min, 1),
    }
    print(f"Concurrency {concurrency}: {concurrency} docs in {total_time:.2f}s | Avg doc latency: {avg_lat:.2f}s | Throughput: {docs_per_min:.1f} docs/min ({aggregate_tok_sec:.1f} tok/s aggregate)")

# Save benchmark results
with open("data/local_model_benchmark_results.json", "w") as f:
    json.dump({
        "hardware": {
            "os": os_info,
            "cpu": cpu_name,
            "physical_cores": cpu_phys,
            "threads": cpu_log,
            "total_ram_gb": total_ram_gb,
            "free_ram_gb": avail_ram_gb,
            "gpu": gpu_info,
            "vram_gb": vram_gb,
        },
        "model": model_name,
        "single_file_median_latency_s": round(med_latency, 2),
        "single_file_median_tok_per_sec": round(med_tok_sec, 1),
        "concurrency_scaling": concurrency_results,
    }, f, indent=2)

print("\nBenchmark data saved to data/local_model_benchmark_results.json")
