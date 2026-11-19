"""Benchmark script for OCR and pipeline stages.

Measures seconds per page separately for:
1. Page render (PDF rendering / image load)
2. Text-line detection (OpenCV morphological layout analysis)
3. TrOCR text recognition (CPU or GPU, unbatched or batched, fp32 or fp16)
4. Rest of pipeline (Classification, field extraction, PII detection)

Outputs formatted timing tables and baseline metrics to docs/ocr-perf.md.
"""

import argparse
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Prevent OpenMP/MKL thread contention on Windows
os.environ["OMP_NUM_THREADS"] = "4"
os.environ["MKL_NUM_THREADS"] = "4"

import cv2
import fitz  # PyMuPDF
import numpy as np
from PIL import Image
import torch

torch.set_num_threads(4)
from transformers import TrOCRProcessor, VisionEncoderDecoderModel

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.workers.stages import stage_classify, stage_extract_fields, stage_pii_detect


# ---------------------------------------------------------------------------
# Global Singleton Cache for Models
# ---------------------------------------------------------------------------
_MODEL_CACHE: Dict[str, Tuple[TrOCRProcessor, VisionEncoderDecoderModel]] = {}


def get_trocr_model(
    model_name: str,
    device: str = "cpu",
    fp16: bool = False,
) -> Tuple[TrOCRProcessor, VisionEncoderDecoderModel]:
    cache_key = f"{model_name}_{device}_{fp16}"
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    processor = TrOCRProcessor.from_pretrained(model_name, local_files_only=True)
    model = VisionEncoderDecoderModel.from_pretrained(model_name, local_files_only=True)
    model.eval()

    if device == "cuda" and torch.cuda.is_available():
        model.to("cuda")
        if fp16:
            model.half()
    else:
        model.to("cpu")

    _MODEL_CACHE[cache_key] = (processor, model)
    return processor, model


# ---------------------------------------------------------------------------
# Stage 1: Line Detection
# ---------------------------------------------------------------------------
def detect_text_lines(image_bgr: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """Detect text line bounding boxes using morphological dilation."""
    if len(image_bgr.shape) == 3:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_bgr

    # Otsu thresholding
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

    # Dilate horizontally to connect characters in the same line
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 5))
    dilated = cv2.dilate(thresh, kernel, iterations=1)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        # Filter out tiny noise
        if w > 20 and h > 8:
            boxes.append((x, y, w, h))

    # Sort boxes top to bottom
    boxes.sort(key=lambda b: (b[1], b[0]))
    return boxes


# ---------------------------------------------------------------------------
# Stage 2: TrOCR Recognition
# ---------------------------------------------------------------------------
def run_trocr_on_crops(
    crops: List[Image.Image],
    processor: TrOCRProcessor,
    model: VisionEncoderDecoderModel,
    device: str = "cpu",
    batch_size: int = 1,
    max_new_tokens: int = 30,
    fp16: bool = False,
) -> List[str]:
    """Recognize text in line crops using TrOCR with configurable batching."""
    if not crops:
        return []

    results = []
    target_device = "cuda" if (device == "cuda" and torch.cuda.is_available()) else "cpu"

    for i in range(0, len(crops), batch_size):
        batch = crops[i : i + batch_size]
        pixel_values = processor(batch, return_tensors="pt").pixel_values.to(target_device)
        if target_device == "cuda" and fp16:
            pixel_values = pixel_values.half()

        with torch.inference_mode():
            generated_ids = model.generate(
                pixel_values,
                max_new_tokens=max_new_tokens,
                num_beams=1,  # greedy decoding
            )
        texts = processor.batch_decode(generated_ids, skip_special_tokens=True)
        results.extend(texts)

    return results


# ---------------------------------------------------------------------------
# Benchmark Engine
# ---------------------------------------------------------------------------
def benchmark_file(
    file_path: str,
    device: str = "cpu",
    batch_size: int = 1,
    fp16: bool = False,
    dpi: int = 300,
    model_name: str = "microsoft/trocr-base-printed",
    skip_text_layer: bool = False,
    max_pages: Optional[int] = None,
) -> Dict[str, Any]:
    file_name = os.path.basename(file_path)
    ext = os.path.splitext(file_name)[1].lower()

    processor, model = get_trocr_model(model_name, device=device, fp16=fp16)

    pages_render_time = 0.0
    lines_detect_time = 0.0
    trocr_time = 0.0
    page_methods = []
    extracted_full_text = []

    # 1. Render pages
    rendered_images: List[np.ndarray] = []
    pdf_doc = None
    total_pages = 1

    if ext == ".pdf":
        t0 = time.perf_counter()
        pdf_doc = fitz.open(file_path)
        total_pages = len(pdf_doc)
        pages_to_process = min(total_pages, max_pages) if max_pages else total_pages

        for page_idx in range(pages_to_process):
            page = pdf_doc[page_idx]
            pix = page.get_pixmap(dpi=dpi)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
            if pix.n == 4:
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
            elif pix.n == 1:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
            rendered_images.append(img)
        pages_render_time = time.perf_counter() - t0
    else:
        t0 = time.perf_counter()
        img = cv2.imread(file_path)
        if img is None:
            raise ValueError(f"Could not read image {file_path}")
        rendered_images.append(img)
        pages_render_time = time.perf_counter() - t0
        total_pages = 1
        pages_to_process = 1

    # 2. Process each page
    for idx, img in enumerate(rendered_images):
        # Step 1 logic: check if text layer exists in PDF and skip_text_layer is enabled
        has_direct_text = False
        direct_text = ""
        if skip_text_layer and pdf_doc is not None and idx < len(pdf_doc):
            text_extracted = pdf_doc[idx].get_text().strip()
            if len(text_extracted) > 25:
                has_direct_text = True
                direct_text = text_extracted

        if has_direct_text:
            page_methods.append("text_layer")
            extracted_full_text.append(direct_text)
            print(f"    Page {idx+1}/{len(rendered_images)}: extracted via text_layer (0.0s)", flush=True)
            continue

        page_methods.append("ocr")

        # Line detection
        t0 = time.perf_counter()
        boxes = detect_text_lines(img)
        t_detect = time.perf_counter() - t0
        lines_detect_time += t_detect

        # Crop lines
        crops = []
        for x, y, w, h in boxes:
            # Skip tiny or empty crops
            if w < 10 or h < 6:
                continue
            crop_np = img[y : y + h, x : x + w]
            crops.append(Image.fromarray(crop_np))

        # TrOCR recognition
        t0 = time.perf_counter()
        page_lines = run_trocr_on_crops(
            crops,
            processor=processor,
            model=model,
            device=device,
            batch_size=batch_size,
            fp16=fp16,
        )
        t_trocr = time.perf_counter() - t0
        trocr_time += t_trocr
        extracted_full_text.append("\n".join(page_lines))
        print(f"    Page {idx+1}/{len(rendered_images)}: {len(crops)} lines -> detect={t_detect:.3f}s, trocr={t_trocr:.3f}s", flush=True)

    if pdf_doc:
        pdf_doc.close()

    # 3. Rest of Pipeline (Classify, Extract, PII)
    combined_text = "\n\n".join(extracted_full_text)
    t0 = time.perf_counter()
    cls_res = stage_classify(combined_text)
    doc_class = cls_res["predicted_class"]
    stage_extract_fields(combined_text, doc_class)
    stage_pii_detect(combined_text)
    rest_pipeline_time = time.perf_counter() - t0

    # Calculate per-page averages
    num_processed = len(rendered_images)
    render_per_page = pages_render_time / num_processed
    detect_per_page = lines_detect_time / num_processed
    trocr_per_page = trocr_time / num_processed
    rest_per_page = rest_pipeline_time / num_processed
    total_per_page = render_per_page + detect_per_page + trocr_per_page + rest_per_page

    return {
        "file_name": file_name,
        "total_pages": total_pages,
        "pages_measured": num_processed,
        "render_sec_page": render_per_page,
        "detect_sec_page": detect_per_page,
        "trocr_sec_page": trocr_per_page,
        "rest_sec_page": rest_per_page,
        "total_sec_page": total_per_page,
        "total_elapsed_sec": pages_render_time + lines_detect_time + trocr_time + rest_pipeline_time,
        "methods": page_methods,
        "sample_text_len": len(combined_text),
    }


def run_benchmark_suite(
    test_dir: str = "data/test",
    device: str = "cpu",
    batch_size: int = 1,
    fp16: bool = False,
    dpi: int = 300,
    model_name: str = "microsoft/trocr-base-printed",
    skip_text_layer: bool = False,
    max_pages_large: int = 3,
) -> List[Dict[str, Any]]:
    files = [
        "1page_sample.pdf",
        "3page_sample.pdf",
        "10page_sample.pdf",
        "100page_sample.pdf",
        "scan_sample.png",
    ]

    results = []
    print(f"\n{'='*95}")
    print(f"OCR BENCHMARK RUN: device={device.upper()}, batch_size={batch_size}, fp16={fp16}, dpi={dpi}")
    print(f"model={model_name}, skip_text_layer={skip_text_layer}")
    print(f"{'='*95}\n")

    for fname in files:
        fpath = os.path.join(test_dir, fname)
        if not os.path.exists(fpath):
            print(f"File {fpath} not found, skipping...", flush=True)
            continue

        # For large files in baseline CPU mode, limit measured pages to prevent excessive runtimes
        limit_pages = max_pages_large if (fname in ["10page_sample.pdf", "100page_sample.pdf"] and device == "cpu") else None

        print(f"Benchmarking {fname} (measuring {'all' if not limit_pages else limit_pages} pages)...", flush=True)
        res = benchmark_file(
            fpath,
            device=device,
            batch_size=batch_size,
            fp16=fp16,
            dpi=dpi,
            model_name=model_name,
            skip_text_layer=skip_text_layer,
            max_pages=limit_pages,
        )
        results.append(res)
        print(
            f"  -> Render: {res['render_sec_page']:.3f}s/p | Detect: {res['detect_sec_page']:.3f}s/p | "
            f"TrOCR: {res['trocr_sec_page']:.3f}s/p | Rest: {res['rest_sec_page']:.3f}s/p | "
            f"Total: {res['total_sec_page']:.3f}s/p"
        )

    return results


def format_markdown_table(results: List[Dict[str, Any]], title: str = "Benchmark Results") -> str:
    md = f"### {title}\n\n"
    md += "| File | Pages | Render (s/p) | Detect (s/p) | TrOCR (s/p) | Rest Pipeline (s/p) | Total (s/p) | Extrapolated Doc Total |\n"
    md += "|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n"

    for r in results:
        doc_total = r["total_sec_page"] * r["total_pages"]
        doc_total_str = f"{doc_total:.2f}s" if doc_total < 60 else f"{doc_total/60:.2f} min"
        md += (
            f"| `{r['file_name']}` | {r['total_pages']} | "
            f"{r['render_sec_page']:.4f} | {r['detect_sec_page']:.4f} | "
            f"**{r['trocr_sec_page']:.4f}** | {r['rest_sec_page']:.4f} | "
            f"{r['total_sec_page']:.4f} | {doc_total_str} |\n"
        )

    return md


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OCR Pipeline Benchmark")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--fp16", action="store_true")
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--model-name", default="microsoft/trocr-base-printed")
    parser.add_argument("--skip-text-layer", action="store_true")
    parser.add_argument("--output-markdown", default=None)
    parser.add_argument("--max-pages-large", type=int, default=3)
    args = parser.parse_args()

    results = run_benchmark_suite(
        device=args.device,
        batch_size=args.batch_size,
        fp16=args.fp16,
        dpi=args.dpi,
        model_name=args.model_name,
        skip_text_layer=args.skip_text_layer,
        max_pages_large=args.max_pages_large,
    )

    table_md = format_markdown_table(results, title=f"OCR Pipeline Performance ({args.device.upper()}, batch={args.batch_size})")
    print("\n" + table_md)

    if args.output_markdown:
        os.makedirs(os.path.dirname(args.output_markdown), exist_ok=True)
        with open(args.output_markdown, "a", encoding="utf-8") as f:
            f.write("\n" + table_md + "\n")
        print(f"Appended results to {args.output_markdown}")
