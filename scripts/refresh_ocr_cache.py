import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.ocr import get_ocr_engine

def refresh_cache():
    val_dir = Path("data/dataset/val")
    json_files = sorted(list(val_dir.glob("*.json")))
    ocr_engine = get_ocr_engine()
    
    print(f"Refreshing OCR cache for {len(json_files)} val scans with psm 6...", flush=True)
    t0 = time.time()
    
    cache = {}
    def worker(jf):
        with open(jf, "r", encoding="utf-8") as f:
            gt = json.load(f)
        did = gt["doc_id"]
        pdf_path = val_dir / gt["file_name"]
        with open(pdf_path, "rb") as pf:
            b = pf.read()
        res = ocr_engine.extract_text(b, "pdf")
        return did, {
            "full_text": res.full_text,
            "engine_name": res.engine_name,
            "engine_version": res.engine_version
        }

    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, (did, rec) in enumerate(ex.map(worker, json_files), 1):
            cache[did] = rec
            if i % 30 == 0 or i == len(json_files):
                print(f"  Refreshed {i}/{len(json_files)} in {time.time()-t0:.1f}s...", flush=True)

    with open("data/ocr_cache_val.json", "w", encoding="utf-8") as f:
        json.dump(cache, f)
    print(f"Cache refreshed in {time.time()-t0:.1f}s!", flush=True)

if __name__ == "__main__":
    refresh_cache()
