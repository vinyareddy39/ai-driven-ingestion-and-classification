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

CACHE_FILE = Path("data/ocr_cache_holdout2.json")

def get_or_build_ocr_cache(holdout_dir: Path, json_files: list) -> dict:
    cache = {}
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            print(f"Loaded {len(cache)} cached Holdout 2 OCR records from {CACHE_FILE}", flush=True)
        except Exception:
            cache = {}
            
    missing_files = [jf for jf in json_files if jf.stem not in cache]
    if missing_files:
        print(f"Extracting OCR for {len(missing_files)} Holdout 2 documents with 4 threads using UB-Mannheim Tesseract 5.4.0...", flush=True)
        ocr_engine = get_ocr_engine()
        t0 = time.time()
        
        def ocr_worker(jf):
            with open(jf, "r", encoding="utf-8") as f:
                gt = json.load(f)
            did = gt["doc_id"]
            pdf_path = holdout_dir / gt["file_name"]
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
                if i % 40 == 0 or i == len(missing_files):
                    print(f"  Holdout 2 OCR progress: {i}/{len(missing_files)} done ({time.time()-t0:.1f}s)...", flush=True)
                    
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        print(f"Holdout 2 OCR cache saved to {CACHE_FILE}", flush=True)
        
    return cache

def run_holdout2_eval():
    holdout_dir = Path("data/dataset/holdout2")
    json_files = sorted(list(holdout_dir.glob("*.json")))
    print("=" * 80)
    print("EVALUATING LOCKED FRESH HOLDOUT 2 (Seed 20261119) - SINGLE UNSEEN PASS")
    print("=" * 80)
    print(f"Total Holdout 2 Documents: {len(json_files)}")
    
    ocr_cache = get_or_build_ocr_cache(holdout_dir, json_files)

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
        
        ocr_rec = ocr_cache[did]
        eval_text = ocr_rec["full_text"]
        ocr_engine_name = ocr_rec["engine_name"]
        ocr_engine_ver = ocr_rec["engine_version"]
        
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
    overall_acc = sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true) * 100
    field_acc = (total_fields_correct / total_fields_expected * 100.0) if total_fields_expected else 0.0
    stp_rate = (auto_accepted_count / total_docs * 100.0) if total_docs else 0.0
    pii_recall = (pii_tp / (pii_tp + pii_fn) * 100.0) if (pii_tp + pii_fn) else 0.0
    pii_precision = (pii_tp / (pii_tp + pii_fp) * 100.0) if (pii_tp + pii_fp) else 0.0
    audit_rate = (audit_complete_count / total_docs * 100.0) if total_docs else 0.0

    print("\n" + "=" * 80)
    print("HOLDOUT 2 TARGET COMPLIANCE SUMMARY (LOCAL MODE ONLY)")
    print("=" * 80)
    print(f"Classification Accuracy (Auto-Accepted): {class_acc_accepted:6.2f}% ({correct_accepted}/{len(auto_accepted_true)}) [Target >= 95%] -> {'PASS' if class_acc_accepted >= 95 else 'FAIL'}")
    print(f"Overall Classification Accuracy:        {overall_acc:6.2f}% ({sum(1 for t, p in zip(y_true, y_pred) if t == p)}/{len(y_true)})")
    print(f"Field Extraction Accuracy:               {field_acc:6.2f}% ({total_fields_correct}/{total_fields_expected}) [Target >= 90%] -> {'PASS' if field_acc >= 90 else 'FAIL'}")
    print(f"PII Recall:                              {pii_recall:6.2f}% ({pii_tp}/{pii_tp+pii_fn}) [Target >= 98%] -> {'PASS' if pii_recall >= 98 else 'FAIL'}")
    print(f"PII Precision:                           {pii_precision:6.2f}% ({pii_tp}/{pii_tp+pii_fp}) [Target >= 80%] -> {'PASS' if pii_precision >= 80 else 'FAIL'}")
    print(f"Straight-Through Processing (STP) Rate:  {stp_rate:6.2f}% ({auto_accepted_count}/{total_docs}) [Target >= 70%] -> {'PASS' if stp_rate >= 70 else 'FAIL'}")
    print(f"Audit Trail Completeness:                {audit_rate:6.2f}% ({audit_complete_count}/{total_docs}) [Target 100%] -> {'PASS' if audit_rate == 100 else 'FAIL'}")

    print("\n" + "-" * 80)
    print("CONFUSION MATRIX (True \\ Predicted)")
    print("-" * 80)
    header = f"{'':<16}" + "".join(f"{c[:7]:>8}" for c in ALL_CLASSES)
    print(header)
    conf_mat = defaultdict(lambda: defaultdict(int))
    for t, p in zip(y_true, y_pred):
        conf_mat[t][p] += 1
    for t in ALL_CLASSES:
        row = f"{t:<16}" + "".join(f"{conf_mat[t][p]:>8}" for p in ALL_CLASSES)
        print(row)

    print("\n" + "-" * 80)
    print("PER-CLASS CLASSIFICATION PRECISION & RECALL")
    print("-" * 80)
    print(f"{'Class':<18}{'Precision':>12}{'Recall':>12}{'F1-Score':>12}{'Support':>10}")
    for c in ALL_CLASSES:
        tp = conf_mat[c][c]
        pred_total = sum(conf_mat[other][c] for other in ALL_CLASSES)
        true_total = sum(conf_mat[c][other] for other in ALL_CLASSES)
        p_c = tp / pred_total * 100 if pred_total > 0 else 0.0
        r_c = tp / true_total * 100 if true_total > 0 else 0.0
        f1_c = 2 * p_c * r_c / (p_c + r_c) if (p_c + r_c) > 0 else 0.0
        print(f"{c:<18}{p_c:>11.2f}%{r_c:>11.2f}%{f1_c:>11.2f}%{true_total:>10}")

    print("\n" + "-" * 80)
    print("PER-CLASS FIELD EXTRACTION ACCURACY")
    print("-" * 80)
    print(f"{'Class':<20}{'Extracted':>12}{'Expected':>12}{'Accuracy':>12}")
    for c in ALL_CLASSES:
        if c == "unknown":
            continue
        st = per_class_fields[c]
        acc_c = st["correct"] / st["expected"] * 100 if st["expected"] > 0 else 0.0
        print(f"{c:<20}{st['correct']:>12}{st['expected']:>12}{acc_c:>11.2f}%")

    print("\n" + "-" * 80)
    print("PII ENTITY PERFORMANCE (Recall & Precision)")
    print("-" * 80)
    print(f"{'Entity Type':<20}{'TP':>8}{'FN':>8}{'FP':>8}{'Recall':>12}{'Precision':>12}")
    for etype in sorted(pii_entity_stats.keys()):
        st = pii_entity_stats[etype]
        rec = st["tp"] / (st["tp"] + st["fn"]) * 100 if (st["tp"] + st["fn"]) > 0 else 0.0
        prec = st["tp"] / (st["tp"] + st["fp"]) * 100 if (st["tp"] + st["fp"]) > 0 else 0.0
        print(f"{etype:<20}{st['tp']:>8}{st['fn']:>8}{st['fp']:>8}{rec:>11.2f}%{prec:>11.2f}%")

    print("\n" + "-" * 80)
    print("ROUTING & REVIEW DECISION BREAKDOWN")
    print("-" * 80)
    print(f"Auto-Accepted Documents: {auto_accepted_count} ({stp_rate:.2f}%)")
    print(f"Sent to Human Review:     {review_count} ({100-stp_rate:.2f}%)")
    print("Review Reasons Breakdown:")
    for reason, cnt in sorted(review_reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {reason}: {cnt}")

    return {
        "auto_acc_acc": class_acc_accepted,
        "overall_acc": overall_acc,
        "field_acc": field_acc,
        "pii_recall": pii_recall,
        "pii_precision": pii_precision,
        "stp_rate": stp_rate,
        "audit_completeness": audit_rate
    }

if __name__ == "__main__":
    run_holdout2_eval()
