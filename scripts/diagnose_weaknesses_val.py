import json
import difflib
from pathlib import Path
from collections import Counter, defaultdict
import re

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.ocr import get_ocr_engine
from app.workers.stages import (
    stage_classify, stage_extract_fields, stage_pii_detect,
    stage_decision_gate, stage_audit_record
)

def main():
    val_dir = Path("data/dataset/val")
    json_files = sorted(list(val_dir.glob("*.json")))
    cache_path = Path("data/ocr_cache_val.json")
    
    with open(cache_path, "r", encoding="utf-8") as f:
        ocr_cache = json.load(f)
        
    print("=" * 80)
    print("DIAGNOSIS ON VALIDATION SET (val only)")
    print("=" * 80)
    
    # 1. NATIONAL_ID & PERSON false positives
    nat_id_fps = []
    person_fps = []
    field_failures = defaultdict(list)
    conflict_docs = []
    
    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            gt = json.load(f)
        did = gt["doc_id"]
        doc_type = gt["doc_type"]
        gt_fields = gt.get("fields", {})
        gt_pii = gt.get("pii_entities", [])
        
        ocr_text = ocr_cache[did]["full_text"]
        
        # Classification
        cls_res = stage_classify(ocr_text)
        pred_class = cls_res["predicted_class"]
        confidence = cls_res["confidence"]
        
        # PII
        pii_res = stage_pii_detect(ocr_text)
        pred_entities = pii_res["entities"]
        
        # Check Decision
        decision = stage_decision_gate(pred_class, confidence, pii_res)
        if "Classifier/PII Conflict" in decision.reason:
            conflict_docs.append((did, doc_type, pred_class, decision.reason))
            
        # PII FP analysis
        gt_types = set(p["type"] for p in gt_pii)
        gt_persons = [str(p.get("value", "")).lower().strip() for p in gt_pii if p["type"] == "PERSON"]
        
        for pe in pred_entities:
            et = pe["entity_type"]
            txt = pe["text"].strip()
            if et == "NATIONAL_ID":
                nat_id_fps.append((did, txt, ocr_text[:100].replace("\n", " ")))
            elif et == "PERSON":
                # Check if matches any GT person
                matched = False
                for gp in gt_persons:
                    if gp and (gp in txt.lower() or txt.lower() in gp or difflib.SequenceMatcher(None, gp, txt.lower()).ratio() >= 0.75):
                        matched = True
                        break
                if not matched:
                    person_fps.append(txt)

        # Field Extraction analysis for letter, bank_statement, medical_report
        if doc_type in ["letter", "bank_statement", "medical_report"]:
            ext_fields, field_confs, is_valid = stage_extract_fields(ocr_text, pred_class)
            for fk, fv in gt_fields.items():
                ext_val = ext_fields.get(fk)
                matched = False
                if ext_val is not None:
                    if str(ext_val).lower().strip() == str(fv).lower().strip():
                        matched = True
                    elif isinstance(fv, float) and isinstance(ext_val, (int, float)) and abs(ext_val - fv) < 0.05:
                        matched = True
                    elif difflib.SequenceMatcher(None, str(ext_val).lower().strip(), str(fv).lower().strip()).ratio() >= 0.80:
                        matched = True
                if not matched:
                    field_failures[doc_type].append({
                        "doc_id": did,
                        "field": fk,
                        "expected": fv,
                        "extracted": ext_val,
                        "ocr_sample": ocr_text[:200].replace("\n", " | ")
                    })

    # Print B.2 NATIONAL_ID
    print("\n" + "-" * 80)
    print("B.2 NATIONAL_ID FALSE POSITIVE TEXTS (Sample 10)")
    print("-" * 80)
    print(f"Total NATIONAL_ID FPs found: {len(nat_id_fps)}")
    for did, txt, snip in nat_id_fps[:10]:
        print(f"  Doc: {did} | Triggered Text: '{txt}' | Context: {snip}")

    # Print B.3 PERSON top 20 triggering strings
    print("\n" + "-" * 80)
    print("B.3 PERSON TOP 20 FALSE POSITIVE TRIGGERING STRINGS")
    print("-" * 80)
    print(f"Total PERSON FPs found: {len(person_fps)}")
    top_person_fps = Counter(person_fps).most_common(25)
    for txt, cnt in top_person_fps[:20]:
        print(f"  '{txt}': {cnt} times")

    # Print B.4 Failures for letter, bank_statement, medical_report
    print("\n" + "-" * 80)
    print("B.4 FIELD EXTRACTION FAILURES (5 examples each for letter, bank_statement, medical_report)")
    print("-" * 80)
    for c in ["letter", "bank_statement", "medical_report"]:
        print(f"\nClass: {c} (Total failures: {len(field_failures[c])})")
        for i, ex in enumerate(field_failures[c][:5], 1):
            print(f"  Ex {i} [{ex['field']}]: Expected={ex['expected']!r} | Extracted={ex['extracted']!r}")
            print(f"       OCR Text: {ex['ocr_sample']}")

    # Print B.5 Classifier / PII Conflict breakdown
    print("\n" + "-" * 80)
    print("B.5 CLASSIFIER / PII CONFLICTS BREAKDOWN")
    print("-" * 80)
    conflict_by_class = Counter(c[1] for c in conflict_docs)
    print(f"Total Conflict Documents: {len(conflict_docs)}")
    for cls_name, cnt in conflict_by_class.items():
        print(f"  Class '{cls_name}': {cnt} documents ({cnt/len(conflict_docs)*100:.1f}%)")
    if conflict_docs:
        print(f"  Sample Conflict Document: {conflict_docs[0]}")

if __name__ == "__main__":
    main()
