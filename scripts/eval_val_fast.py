import json
import difflib
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

ALL_CLASSES = [
    "invoice", "contract", "kyc_form", "bank_statement",
    "medical_report", "purchase_order", "letter", "claim_form", "unknown"
]

CACHE_FILE = Path("data/ocr_cache_val.json")

def get_or_build_ocr_cache(val_dir: Path, json_files: list) -> dict:
    cache = {}
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            print(f"Loaded {len(cache)} cached OCR records from {CACHE_FILE}", flush=True)
        except Exception:
            cache = {}
            
    missing_files = [jf for jf in json_files if jf.stem not in cache]
    if missing_files:
        print(f"Extracting OCR for {len(missing_files)} remaining documents with 4 threads...", flush=True)
        ocr_engine = get_ocr_engine()
        t0 = time.time()
        
        def ocr_worker(jf):
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
            for i, (did, rec) in enumerate(ex.map(ocr_worker, missing_files), 1):
                cache[did] = rec
                if i % 30 == 0 or i == len(missing_files):
                    print(f"  OCR progress: {i}/{len(missing_files)} done ({time.time()-t0:.1f}s)...", flush=True)
                    
        # Save cache
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        print(f"OCR cache saved to {CACHE_FILE}", flush=True)
        
    return cache

def run_val_eval():
    val_dir = Path("data/dataset/val")
    json_files = sorted(list(val_dir.glob("*.json")))
    
    ocr_cache = get_or_build_ocr_cache(val_dir, json_files)

    y_true = []
    y_pred = []
    auto_accepted_true = []
    auto_accepted_pred = []

    total_fields_expected = 0
    total_fields_correct = 0
    per_class_fields = {c: {"expected": 0, "correct": 0} for c in ALL_CLASSES}
    per_field_stats = defaultdict(lambda: {"expected": 0, "correct": 0})

    pii_tp = 0
    pii_fn = 0
    pii_fp = 0
    pii_entity_stats = defaultdict(lambda: {"tp": 0, "fn": 0, "fp": 0})
    pii_fp_examples = []
    pii_miss_examples = []

    auto_accepted_count = 0
    review_count = 0
    audit_complete_count = 0
    review_reasons = defaultdict(int)

    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            gt = json.load(f)
        did = gt["doc_id"]
        doc_type = gt["doc_type"]
        gt_fields = gt.get("fields", {})
        gt_pii = gt.get("pii_entities", [])
        sha256_hash = gt.get("sha256", "hash")

        rec = ocr_cache[did]
        eval_text = rec["full_text"]
        ocr_engine_name = rec["engine_name"]
        ocr_engine_ver = rec["engine_version"]

        # 1. Classification
        cls_res = stage_classify(eval_text)
        pred_class = cls_res["predicted_class"]
        confidence = cls_res["confidence"]

        y_true.append(doc_type)
        y_pred.append(pred_class)

        # 2. Field Extraction
        ext_fields, field_confs, is_valid = stage_extract_fields(eval_text, pred_class)
        for fk, fv in gt_fields.items():
            total_fields_expected += 1
            per_class_fields[doc_type]["expected"] += 1
            per_field_stats[fk]["expected"] += 1
            ext_val = ext_fields.get(fk)
            match = False
            if ext_val is not None:
                if str(ext_val).lower().strip() == str(fv).lower().strip():
                    match = True
                elif isinstance(fv, float) and isinstance(ext_val, (int, float)) and abs(ext_val - fv) < 0.05:
                    match = True
                elif difflib.SequenceMatcher(None, str(ext_val).lower().strip(), str(fv).lower().strip()).ratio() >= 0.80:
                    match = True

            if match:
                total_fields_correct += 1
                per_class_fields[doc_type]["correct"] += 1
                per_field_stats[fk]["correct"] += 1

        # 3. PII Detection
        pii_res = stage_pii_detect(eval_text)
        pred_entities = pii_res["entities"]
        
        for p in gt_pii:
            pt = p["type"]
            matched = any(pe["entity_type"] == pt for pe in pred_entities)
            if matched:
                pii_tp += 1
                pii_entity_stats[pt]["tp"] += 1
            else:
                pii_fn += 1
                pii_entity_stats[pt]["fn"] += 1
                if len(pii_miss_examples) < 10:
                    pii_miss_examples.append({
                        "doc_id": did,
                        "type": pt,
                        "expected_val": p.get("value"),
                        "snippet": eval_text[:120].replace("\n", " ")
                    })

        for pe in pred_entities:
            pt = pe["entity_type"]
            matched = any(p["type"] == pt for p in gt_pii)
            if not matched:
                pii_fp += 1
                pii_entity_stats[pt]["fp"] += 1
                if len(pii_fp_examples) < 10:
                    pii_fp_examples.append({
                        "doc_id": did,
                        "type": pt,
                        "text": pe.get("text", ""),
                        "snippet": eval_text[:120].replace("\n", " ")
                    })

        # 4. Decision Gate
        decision = stage_decision_gate(pred_class, confidence, pii_res)
        if decision.action == "AUTO_ACCEPT":
            auto_accepted_count += 1
            auto_accepted_true.append(doc_type)
            auto_accepted_pred.append(pred_class)
        else:
            review_count += 1
            review_reasons[decision.reason] += 1

        # 5. Audit Completeness
        audit = stage_audit_record(
            uid=did,
            sha256_hash=sha256_hash,
            decision=decision,
            metadata_fields={
                "ocr_engine": ocr_engine_name,
                "ocr_version": ocr_engine_ver,
                "classifier_model": cls_res["model_name"],
                "classifier_version": cls_res["model_version"],
                "field_confidences": field_confs,
                "pii_detected": pii_res["pii_detected"],
                "pii_types": pii_res["pii_types"],
            },
        )
        if audit.validate_audit_completeness():
            audit_complete_count += 1

    total_docs = len(json_files)
    correct_accepted = sum(1 for yt, yp in zip(auto_accepted_true, auto_accepted_pred) if yt == yp)
    class_acc_accepted = (correct_accepted / len(auto_accepted_true) * 100.0) if auto_accepted_true else 0.0
    field_acc = (total_fields_correct / total_fields_expected * 100.0) if total_fields_expected else 0.0
    stp_rate = (auto_accepted_count / total_docs * 100.0) if total_docs else 0.0
    pii_recall = (pii_tp / (pii_tp + pii_fn) * 100.0) if (pii_tp + pii_fn) else 0.0
    pii_precision = (pii_tp / (pii_tp + pii_fp) * 100.0) if (pii_tp + pii_fp) else 0.0
    audit_rate = (audit_complete_count / total_docs * 100.0) if total_docs else 0.0

    print("=" * 80)
    print("VALIDATION SET RESULTS (Tuning on val only)")
    print("=" * 80)
    print(f"Classification Accuracy (Auto-Accepted): {class_acc_accepted:6.2f}% ({correct_accepted}/{len(auto_accepted_true)})")
    print(f"Field Extraction Accuracy:               {field_acc:6.2f}% ({total_fields_correct}/{total_fields_expected})")
    print(f"PII Detection Recall:                    {pii_recall:6.2f}% ({pii_tp}/{pii_tp + pii_fn})")
    print(f"PII Detection Precision:                 {pii_precision:6.2f}% ({pii_tp}/{pii_tp + pii_fp})")
    print(f"Straight-Through Rate (STP):             {stp_rate:6.2f}% ({auto_accepted_count}/{total_docs})")
    print(f"Audit Metadata Completeness:             {audit_rate:6.2f}% ({audit_complete_count}/{total_docs})\n")

    print("-" * 80)
    print("PII Recall & Precision Per Entity Type on Val:")
    print("-" * 80)
    for etype in sorted(pii_entity_stats.keys()):
        stats = pii_entity_stats[etype]
        rec = stats["tp"] / (stats["tp"] + stats["fn"]) * 100.0 if (stats["tp"] + stats["fn"]) else 0.0
        prec = stats["tp"] / (stats["tp"] + stats["fp"]) * 100.0 if (stats["tp"] + stats["fp"]) else 0.0
        print(f"  {etype:<18}: Recall = {rec:6.2f}% ({stats['tp']}/{stats['tp']+stats['fn']}) | Precision = {prec:6.2f}% ({stats['tp']}/{stats['tp']+stats['fp']})")

    print("\nTop 5 Sources of PII Misses (FN):")
    for ex in pii_miss_examples[:5]:
        print(f"  [{ex['doc_id']}] Type: {ex['type']} | Expected: '{ex['expected_val']}' | Context: {ex['snippet']}...")

    print("\nTop 5 Sources of PII False Positives (FP):")
    for ex in pii_fp_examples[:5]:
        print(f"  [{ex['doc_id']}] Type: {ex['type']} | Detected: '{ex['text']}' | Context: {ex['snippet']}...")

    print("\n" + "-" * 80)
    print("Per-Class Field Accuracy on Val:")
    print("-" * 80)
    for c in sorted(per_class_fields.keys()):
        if c == "unknown": continue
        stats = per_class_fields[c]
        cacc = stats["correct"] / stats["expected"] * 100.0 if stats["expected"] else 0.0
        print(f"  {c:<16}: {stats['correct']:3d}/{stats['expected']:3d} ({cacc:6.2f}%)")

    # Confusion matrix & classification report
    print("\n" + "-" * 80)
    print("Classification Confusion Matrix & Per-Class Metrics:")
    print("-" * 80)
    class_indices = {c: i for i, c in enumerate(ALL_CLASSES)}
    conf_matrix = [[0] * len(ALL_CLASSES) for _ in range(len(ALL_CLASSES))]
    for yt, yp in zip(y_true, y_pred):
        conf_matrix[class_indices[yt]][class_indices[yp]] += 1
        
    print(f"{'True \\ Pred':<16} " + " ".join(f"{c[:5]:>5}" for c in ALL_CLASSES))
    for i, c in enumerate(ALL_CLASSES):
        row = " ".join(f"{conf_matrix[i][j]:5d}" for j in range(len(ALL_CLASSES)))
        print(f"{c:<16} {row}")
        
    print("\nPer-Class Precision / Recall:")
    for j, c in enumerate(ALL_CLASSES):
        tp = conf_matrix[j][j]
        fn = sum(conf_matrix[j][k] for k in range(len(ALL_CLASSES))) - tp
        fp = sum(conf_matrix[k][j] for k in range(len(ALL_CLASSES))) - tp
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / (tp + fn) if (tp + fn) else 0.0
        print(f"  {c:<16}: Precision = {p*100:6.2f}% | Recall = {r*100:6.2f}%")

    print("\nReview Reasons Breakdown:")
    for r, cnt in sorted(review_reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"  {cnt:3d} docs: {r}")

    print("=" * 80)

if __name__ == "__main__":
    run_val_eval()
