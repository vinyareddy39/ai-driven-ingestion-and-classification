"""Cache OCR text for val-v3 using UB-Mannheim Tesseract in 4 threads."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.ocr import get_ocr_engine

def main():
    ocr_engine = get_ocr_engine()
    val_dir = Path("data/dataset/val_v3")
    pdf_files = sorted(list(val_dir.glob("*.pdf")))
    cache_path = Path("data/ocr_cache_val_v3.json")

    print(f"Extracting OCR for {len(pdf_files)} val-v3 PDFs using {ocr_engine.engine_name}...")
    t0 = time.time()
    cache = {}

    def process(p):
        with open(p, "rb") as f:
            b = f.read()
        res = ocr_engine.extract_text(b, "pdf")
        return p.stem, {"full_text": res.full_text}

    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, (stem, data) in enumerate(ex.map(process, pdf_files), 1):
            cache[stem] = data
            if i % 50 == 0 or i == len(pdf_files):
                print(f"  OCR progress: {i}/{len(pdf_files)} done ({time.time()-t0:.1f}s)...", flush=True)

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    print(f"OCR cache saved to {cache_path} in {time.time()-t0:.1f}s.")

if __name__ == "__main__":
    main()
