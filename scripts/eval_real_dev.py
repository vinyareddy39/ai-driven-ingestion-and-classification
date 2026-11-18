import json
import time
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.ocr import get_ocr_engine
from app.workers.stages import (
    stage_classify, stage_extract_fields, stage_pii_detect,
    stage_decision_gate, stage_audit_record
)

OCR_CACHE_REAL = Path("data/real_funsd/ocr_cache_dev.json")

def get_real_ocr_cache(dev_docs):
    cache = {}
    if OCR_CACHE_REAL.exists():
        try:
            with open(OCR_CACHE_REAL, "r", encoding="utf-8") as f:
                cache = json.load(f)
            print(f"Loaded {len(cache)} cached real doc OCR records.", flush=True)
        except Exception:
            cache = {}
            
    missing = [d for d in dev_docs if d["doc_id"] not in cache]
    if missing:
        print(f"Extracting OCR for {len(missing)} real FUNSD documents using UB-Mannheim Tesseract 5.4.0 (4 threads)...", flush=True)
        ocr_engine = get_ocr_engine()
        t0 = time.time()
        
        def worker(d):
            img_path = Path(d["image_path"])
            with open(img_path, "rb") as pf:
                b = pf.read()
            res = ocr_engine.extract_text(b, "png")
            return d["doc_id"], {
                "full_text": res.full_text,
                "engine_name": res.engine_name,
                "engine_version": res.engine_version
            }

        with ThreadPoolExecutor(max_workers=4) as ex:
            for i, (did, rec) in enumerate(ex.map(worker, missing), 1):
                cache[did] = rec
                if i % 25 == 0 or i == len(missing):
                    print(f"  Real OCR progress: {i}/{len(missing)} done ({time.time()-t0:.1f}s)...", flush=True)
                    
        with open(OCR_CACHE_REAL, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        print(f"Real OCR cache saved to {OCR_CACHE_REAL}", flush=True)
        
    return cache

def run_real_dev_eval():
    with open("data/real_funsd/splits.json", "r", encoding="utf-8") as f:
        splits = json.load(f)
        
    dev_doc_ids = set(splits["dev_doc_ids"])
    
    funsd_root = Path("data/real_funsd/dataset")
    dev_docs = []
    for split in ["training_data", "testing_data"]:
        img_dir = funsd_root / split / "images"
        ann_dir = funsd_root / split / "annotations"
        for img_file in sorted(img_dir.glob("*.png")):
            if img_file.stem in dev_doc_ids:
                dev_docs.append({
                    "doc_id": img_file.stem,
                    "image_path": str(img_file),
                    "annotation_path": str(ann_dir / f"{img_file.stem}.json")
                })
                
    print("=" * 80)
    print("REAL DOCUMENT BASELINE EVALUATION: FUNSD DEV SET (99 DOCUMENTS)")
    print("=" * 80)
    print(f"Dataset: {splits['dataset']}")
    print(f"Source:  {splits['source']}")
    print(f"License: {splits['license']}")
    print(f"Total dev documents: {len(dev_docs)}")
    
    ocr_cache = get_real_ocr_cache(dev_docs)
    
    class_counts = defaultdict(int)
    class_confs = defaultdict(list)
    auto_accepted = 0
    manual_review = 0
    review_reasons = defaultdict(int)
    extracted_fields_total = 0
    pii_found_total = 0
    pii_types_detected = defaultdict(int)
    
    for d in dev_docs:
        did = d["doc_id"]
        ocr_rec = ocr_cache[did]
        text = ocr_rec["full_text"]
        
        # 1. Classification
        cls_res = stage_classify(text)
        pred_cls = cls_res["predicted_class"]
        conf = cls_res["confidence"]
        class_counts[pred_cls] += 1
        class_confs[pred_cls].append(conf)
        
        # 2. Generic Field Extraction
        ext_fields, field_confs, is_valid = stage_extract_fields(text, pred_cls)
        extracted_fields_total += len([k for k, v in ext_fields.items() if v is not None])
        
        # 3. PII Detection
        pii_res = stage_pii_detect(text)
        entities = pii_res["entities"]
        pii_found_total += len(entities)
        for e in entities:
            pii_types_detected[e["entity_type"]] += 1
            
        # 4. Decision Gate
        decision = stage_decision_gate(pred_cls, conf, pii_res, extraction_valid=is_valid)
        if decision.action == "AUTO_ACCEPT":
            auto_accepted += 1
        else:
            manual_review += 1
            review_reasons[decision.reason] += 1

    print("\n--- CLASSIFICATION DISTRIBUTION ON REAL SCANNED DOCUMENTS ---")
    print(f"{'Class':<20} | {'Count':<6} | {'Pct (%)':<8} | {'Mean Conf':<10}")
    print("-" * 50)
    for c in sorted(class_counts.keys()):
        cnt = class_counts[c]
        pct = cnt / len(dev_docs) * 100
        mean_c = sum(class_confs[c]) / cnt if cnt > 0 else 0.0
        print(f"{c:<20} | {cnt:<6} | {pct:<8.1f} | {mean_c:<10.3f}")

    print("\n--- ROUTING & STRAIGHT-THROUGH PROCESSING (STP) ---")
    print(f"Total Evaluated:        {len(dev_docs)}")
    print(f"Auto-Accepted (STP):    {auto_accepted} ({auto_accepted/len(dev_docs)*100:.2f}%)")
    print(f"Routed to Review:       {manual_review} ({manual_review/len(dev_docs)*100:.2f}%)")
    print("\nReview Reasons Breakdown:")
    for r, count in sorted(review_reasons.items(), key=lambda x: -x[1]):
        print(f"  - {r}: {count}")

    print("\n--- REAL DOCUMENT EXTRACTION & PII SUMMARY ---")
    print(f"Total Fields Extracted by Generic Extractor: {extracted_fields_total} ({extracted_fields_total/len(dev_docs):.1f} fields/doc)")
    print(f"Total PII Entities Detected:                 {pii_found_total} across 99 docs")
    print("PII Types Detected in Real Scans:")
    for pt, count in sorted(pii_types_detected.items(), key=lambda x: -x[1]):
        print(f"  - {pt}: {count}")
    print("=" * 80)

if __name__ == "__main__":
    run_real_dev_eval()
