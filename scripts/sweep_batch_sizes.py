"""Sweep batch sizes on NVIDIA GeForce RTX 4050 (6GB VRAM) to find optimal OCR_BATCH_SIZE.

Evaluates batch sizes: 1, 4, 8, 16, 32, 64 with TrOCR Base and TrOCR Small (fp16, 200 DPI).
Measures:
- Latency per page
- Throughput (lines per second)
- Peak GPU VRAM allocated (MB)
"""

import os
import sys
import time
import torch
import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.bench_ocr import detect_text_lines, get_trocr_model, run_trocr_on_crops


def sweep_batch_sizes():
    if not torch.cuda.is_available():
        print("CUDA is not available, skipping sweep.")
        return

    img_bgr = cv2.imread("data/test/scan_sample.png")
    # Resize to 200 DPI scale (200 / 300 = 0.667)
    h, w = img_bgr.shape[:2]
    img_200dpi = cv2.resize(img_bgr, (int(w * 200 / 300), int(h * 200 / 300)))
    boxes = detect_text_lines(img_200dpi)

    crops = []
    for x, y, bw, bh in boxes:
        if bw < 10 or bh < 6:
            continue
        crop = img_200dpi[y : y + bh, x : x + bw]
        crops.append(Image.fromarray(crop))

    print(f"Total lines on test page: {len(crops)}")

    models = [
        ("microsoft/trocr-base-printed", "TrOCR-Base"),
        ("microsoft/trocr-small-printed", "TrOCR-Small"),
    ]
    batch_sizes = [1, 4, 8, 16, 32, 40]

    results = []

    for model_id, model_label in models:
        print(f"\n--- Model: {model_label} ({model_id}) ---")
        processor, model = get_trocr_model(model_id, device="cuda", fp16=True)

        for bs in batch_sizes:
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()

            # Warmup
            _ = run_trocr_on_crops(crops[:bs], processor, model, device="cuda", batch_size=bs, fp16=True)

            # Benchmark 3 repetitions
            times = []
            for _ in range(3):
                t0 = time.perf_counter()
                texts = run_trocr_on_crops(crops, processor, model, device="cuda", batch_size=bs, fp16=True)
                times.append(time.perf_counter() - t0)

            avg_time = sum(times) / len(times)
            lines_per_sec = len(crops) / avg_time
            peak_vram_mb = torch.cuda.max_memory_allocated() / (1024 * 1024)

            print(
                f"Batch Size: {bs:2d} | Page Time: {avg_time:.3f}s | "
                f"Throughput: {lines_per_sec:.1f} lines/s | Peak VRAM: {peak_vram_mb:.1f} MB"
            )
            results.append({
                "model": model_label,
                "batch_size": bs,
                "page_time": avg_time,
                "lines_per_sec": lines_per_sec,
                "peak_vram_mb": peak_vram_mb,
            })

    return results


if __name__ == "__main__":
    sweep_batch_sizes()
