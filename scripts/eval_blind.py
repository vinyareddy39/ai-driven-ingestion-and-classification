import json
import time
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.ocr import get_ocr_engine
from app.adapters.pii import match_pii_entity
from app.workers.stages import (
    stage_classify, stage_extract_fields, stage_pii_detect,
    stage_decision_gate, stage_audit_record
)

ALL_CLASSES = [
    "invoice", "contract", "kyc_form", "bank_statement",
    "medical_report", "purchase_order", "letter", "claim_form", "unknown"
]

def run_blind_evaluation():
    blind_dir = Path("C:/ml/data/blind")
    if not blind_dir.exists():
        print(f"Error: Blind directory {blind_dir} does not exist.")
        return

    # Discover candidate files without prior inspection
    supported_exts = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
    doc_files = sorted([f for f in blind_dir.iterdir() if f.suffix.lower() in supported_exts])
    
    print("=" * 80)
    print("BLIND EVALUATION HARNESS: C:\\ml\\data\\blind\\")
    print("=" * 80)
    print(f"Discovered {len(doc_files)} document assets in blind directory.")
    if not doc_files:
        print("No documents found to evaluate. Please place files in C:\\ml\\data\\blind\\.")
        return

    # Check for ground truth manifest or sidecars
    manifest_path = blind_dir / "manifest.json"
    metadata_path = blind_dir / "metadata.jsonl"
    gt_map = {}
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        gt_map[item.get("file_name", item.get("doc_id"))] = item
                elif isinstance(data, dict):
                    gt_map = data.get("documents", data)
        except Exception as e:
            print(f"Warning: Failed loading manifest: {e}")
    elif metadata_path.exists():
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        item = json.loads(line)
                        gt_map[item.get("file_name", item.get("doc_id"))] = item
        except Exception as e:
            print(f"Warning: Failed loading metadata.jsonl: {e}")

    # Process all documents through the full pipeline
    ocr_engine = get_ocr_engine()
    print(f"Using OCR Engine: {ocr_engine.engine_name} {ocr_engine.engine_version}")
    
    t0 = time.time()
    results = []
    
    for idx, doc_file in enumerate(doc_files, 1):
        with open(doc_file, "rb") as f:
            file_bytes = f.read()
        ext = doc_file.suffix.lower().lstrip(".")
        
        # 1. OCR
        ocr_res = ocr_engine.extract_text(file_bytes, ext)
        text = ocr_res.full_text
        
        # 2. Classification
        cls_res = stage_classify(text)
        pred_cls = cls_res["predicted_class"]
        conf = cls_res["confidence"]
        
        # 3. Field Extraction
        ext_fields, field_confs, is_valid = stage_extract_fields(text, pred_cls)
        
        # 4. PII Detection
        pii_res = stage_pii_detect(text)
        
        # 5. Decision Gate
        decision = stage_decision_gate(pred_cls, conf, pii_res, extraction_valid=is_valid)
        
        # 6. Audit Record
        audit = stage_audit_record(
            uid=doc_file.stem,
            sha256_hash="hash_" + doc_file.stem,
            decision=decision,
            metadata_fields={
                "ocr_engine": ocr_res.engine_name,
                "ocr_version": ocr_res.engine_version,
                "predicted_class": pred_cls,
                "confidence": conf
            }
        )
        
        sidecar = blind_dir / f"{doc_file.stem}.json"
        gt = None
        if sidecar.exists():
            try:
                with open(sidecar, "r", encoding="utf-8") as sf:
                    gt = json.load(sf)
            except Exception:
                gt = None
        elif doc_file.name in gt_map:
            gt = gt_map[doc_file.name]
        elif doc_file.stem in gt_map:
            gt = gt_map[doc_file.stem]
            
        results.append({
            "doc_id": doc_file.stem,
            "file_name": doc_file.name,
            "gt": gt,
            "pred_cls": pred_cls,
            "confidence": conf,
            "extracted_fields": ext_fields,
            "field_confs": field_confs,
            "pii_res": pii_res,
            "decision": decision,
            "audit": audit
        })
        
        if idx % 20 == 0 or idx == len(doc_files):
            print(f"Processed {idx}/{len(doc_files)} blind documents ({time.time()-t0:.1f}s)...")

    # Metrics computation
    has_ground_truth = any(r["gt"] is not None for r in results)
    
    print("\n" + "=" * 80)
    print("BLIND EVALUATION RESULTS SUMMARY")
    print("=" * 80)
    print(f"Total Evaluated Documents: {len(results)}")
    print(f"Total Processing Time:     {time.time()-t0:.2f}s ({len(results)/(time.time()-t0):.2f} docs/sec)")
    
    auto_accepted = sum(1 for r in results if r["decision"].action == "AUTO_ACCEPT")
    stp_rate = (auto_accepted / len(results)) * 100
    print(f"Auto-Accepted (STP):       {auto_accepted} / {len(results)} ({stp_rate:.2f}%)")
    print(f"Routed to Manual Review:   {len(results) - auto_accepted} / {len(results)} ({100-stp_rate:.2f}%)")
    
    # Review reasons breakdown
    reasons = defaultdict(int)
    for r in results:
        if r["decision"].action != "AUTO_ACCEPT":
            reasons[r["decision"].reason] += 1
    if reasons:
        print("\nReview Reasons Breakdown:")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  - {reason}: {count}")

    # Class distribution
    class_dist = defaultdict(int)
    for r in results:
        class_dist[r["pred_cls"]] += 1
    print("\nPredicted Class Distribution:")
    for cls in ALL_CLASSES:
        if cls in class_dist:
            print(f"  - {cls:<16}: {class_dist[cls]} ({class_dist[cls]/len(results)*100:.1f}%)")

    if has_ground_truth:
        print("\n--- GROUND TRUTH VERIFICATION ---")
        y_true = [r["gt"].get("doc_type", r["gt"].get("class", "unknown")) for r in results if r["gt"]]
        y_pred = [r["pred_cls"] for r in results if r["gt"]]
        correct = sum(1 for yt, yp in zip(y_true, y_pred) if yt == yp)
        acc = (correct / len(y_true)) * 100
        print(f"Overall Classification Accuracy: {correct}/{len(y_true)} ({acc:.2f}%)")
        
        # Per class stats
        print(f"\n{'Class':<18} | {'Support':<8} | {'Correct':<8} | {'Recall (%)':<10}")
        print("-" * 52)
        per_cls_supp = defaultdict(int)
        per_cls_corr = defaultdict(int)
        for yt, yp in zip(y_true, y_pred):
            per_cls_supp[yt] += 1
            if yt == yp:
                per_cls_corr[yt] += 1
        for cls in ALL_CLASSES:
            if cls in per_cls_supp:
                supp = per_cls_supp[cls]
                corr = per_cls_corr[cls]
                rec = (corr / supp) * 100 if supp > 0 else 0.0
                print(f"{cls:<18} | {supp:<8} | {corr:<8} | {rec:<10.2f}")
    print("=" * 80)

if __name__ == "__main__":
    run_blind_evaluation()
