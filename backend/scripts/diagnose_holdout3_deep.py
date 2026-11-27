import json
import re
import difflib
from pathlib import Path
from collections import defaultdict, Counter
import joblib
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.workers.stages import (
    stage_classify, stage_extract_fields, stage_pii_detect
)

ALL_CLASSES = [
    "invoice", "contract", "kyc_form", "bank_statement",
    "medical_report", "purchase_order", "letter", "claim_form", "unknown"
]

def main():
    print("=" * 80)
    print("DEEP DIAGNOSIS ON HOLDOUT 3 (SEED 20261120)")
    print("=" * 80)

    # Load Holdout 3 and OCR Cache
    holdout_dir = Path("data/dataset/holdout3")
    json_files = sorted([jf for jf in holdout_dir.glob("*.json") if jf.name != "manifest.json"])
    cache_file = Path("data/ocr_cache_holdout3.json")
    with open(cache_file, "r", encoding="utf-8") as f:
        ocr_cache = json.load(f)

    # Load Classifier model & vocabulary
    model_artifact = joblib.load("data/models/classifier_v1.joblib")
    pipeline = model_artifact["pipeline"]
    vectorizer = pipeline.named_steps["tfidf"]
    train_vocab = set(vectorizer.vocabulary_.keys())

    # --------------------------------------------------------------------------
    # B.5 Classifier Diagnosis: contract and bank_statement
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("B.5 CLASSIFIER DIAGNOSIS: CONTRACT AND BANK_STATEMENT RECALL")
    print("=" * 80)

    for target_class in ["contract", "bank_statement"]:
        class_files = [jf for jf in json_files if f"h3_{target_class}_" in jf.name]
        print(f"\nTarget Class: {target_class.upper()} ({len(class_files)} documents)")
        confidences = []
        pred_classes = Counter()
        ood_words_counter = Counter()

        for jf in class_files:
            did = jf.stem
            ocr_rec = ocr_cache[did]
            eval_text = ocr_rec["full_text"]

            # Classify
            res = stage_classify(eval_text)
            pred = res["predicted_class"]
            conf = res["confidence"]
            confidences.append(conf)
            pred_classes[pred] += 1

            # Extract words and check OOD
            doc_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", eval_text.lower()))
            for w in doc_words:
                if w not in train_vocab:
                    ood_words_counter[w] += 1

        print(f"Prediction Breakdown: {dict(pred_classes)}")
        print(f"Confidence Stats: Min={min(confidences):.4f}, Mean={sum(confidences)/len(confidences):.4f}, Max={max(confidences):.4f}")
        bins = {"<0.50": 0, "0.50-0.60": 0, "0.60-0.70": 0, "0.70-0.85": 0, ">=0.85": 0}
        for c in confidences:
            if c < 0.50: bins["<0.50"] += 1
            elif c < 0.60: bins["0.50-0.60"] += 1
            elif c < 0.70: bins["0.60-0.70"] += 1
            elif c < 0.85: bins["0.70-0.85"] += 1
            else: bins[">=0.85"] += 1
        print(f"Confidence Distribution: {bins}")
        print("Top 25 OOD Vocabulary Words (Missing from Training Vocabulary):")
        for word, count in ood_words_counter.most_common(25):
            print(f"  - '{word}': in {count}/{len(class_files)} documents")

    # --------------------------------------------------------------------------
    # B.6 Field Extraction Failures Per Class
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("B.6 FIELD EXTRACTION FAILURES PER CLASS WITH 3 EXAMPLES")
    print("=" * 80)

    per_class_field_fails = defaultdict(lambda: defaultdict(list))

    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            gt = json.load(f)
        doc_type = gt["doc_type"]
        if doc_type == "unknown":
            continue
        did = gt["doc_id"]
        gt_fields = gt.get("fields", {})
        ocr_rec = ocr_cache[did]
        eval_text = ocr_rec["full_text"]

        # Run extraction with true class to isolate field extraction from classification errors
        ext_fields, f_confs, is_valid = stage_extract_fields(eval_text, doc_type)

        for fk, fv in gt_fields.items():
            ext_val = ext_fields.get(fk)
            match = False
            if ext_val is not None:
                if str(ext_val).lower().strip() == str(fv).lower().strip():
                    match = True
                elif isinstance(fv, float) and isinstance(ext_val, (int, float)) and abs(ext_val - fv) < 0.05:
                    match = True
                elif difflib.SequenceMatcher(None, str(ext_val).lower().strip(), str(fv).lower().strip()).ratio() >= 0.80:
                    match = True

            if not match:
                # Classify failure cause
                # Check if expected value is present in OCR text
                str_fv = str(fv).strip()
                val_in_ocr = str_fv.lower() in eval_text.lower()
                
                # Check if label synonyms are present in OCR text
                # Categorize failure label:
                if not val_in_ocr:
                    # check if distorted by OCR
                    words = str_fv.split()
                    if any(w.lower() in eval_text.lower() for w in words):
                        cause = "OCR error"
                    else:
                        cause = "field absent"
                else:
                    if ext_val is None:
                        cause = "label not found"
                    else:
                        cause = "value format"

                per_class_field_fails[doc_type][fk].append({
                    "doc_id": did,
                    "expected": fv,
                    "extracted": ext_val,
                    "cause": cause,
                    "text_snippet": eval_text[:200].replace("\n", " | ")
                })

    for c in sorted(per_class_field_fails.keys()):
        print(f"\nClass: {c.upper()}")
        for field, failures in sorted(per_class_field_fails[c].items(), key=lambda x: len(x[1]), reverse=True):
            print(f"  Field: '{field}' (Failures: {len(failures)}/40)")
            for i, ex in enumerate(failures[:3], 1):
                print(f"    Example {i} [{ex['cause']}]:")
                print(f"      Expected:  {ex['expected']}")
                print(f"      Extracted: {ex['extracted']}")
                print(f"      OCR text:  {ex['text_snippet'][:130]}...")

    # --------------------------------------------------------------------------
    # B.7 PII Misses: PHONE (68), EMAIL (18), PASSPORT (7)
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("B.7 PII MISSES: PHONE_NUMBER, EMAIL_ADDRESS, PASSPORT")
    print("=" * 80)

    target_pii_types = ["PHONE_NUMBER", "EMAIL_ADDRESS", "PASSPORT"]
    pii_misses = defaultdict(list)

    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            gt = json.load(f)
        did = gt["doc_id"]
        gt_pii = gt.get("pii_entities", [])
        ocr_rec = ocr_cache[did]
        eval_text = ocr_rec["full_text"]

        pii_res = stage_pii_detect(eval_text)
        pred_entities = pii_res["entities"]

        for p in gt_pii:
            pt = p["type"]
            if pt in target_pii_types:
                val = p.get("value", "")
                # Check if detected
                matched = any(pe["entity_type"] == pt and (val.lower() in pe["text"].lower() or pe["text"].lower() in val.lower()) for pe in pred_entities)
                if not matched:
                    # Find location in OCR text for context snippet
                    idx = eval_text.lower().find(val.lower()[:8])
                    if idx != -1:
                        snippet = eval_text[max(0, idx-20):min(len(eval_text), idx+60)].replace("\n", " ")
                    else:
                        snippet = eval_text[:100].replace("\n", " ")
                    pii_misses[pt].append({
                        "doc_id": did,
                        "value": val,
                        "ocr_snippet": snippet
                    })

    for pt in target_pii_types:
        misses = pii_misses[pt]
        print(f"\nEntity Type: {pt} (Misses: {len(misses)})")
        for i, m in enumerate(misses[:5], 1):
            print(f"  Miss {i} [Doc: {m['doc_id']}]: Expected='{m['value']}' | OCR Context: '{m['ocr_snippet']}'")

if __name__ == "__main__":
    main()
