"""Ablation experiment on SemanticGroundedExtractor.
Ablates the description token overlap feature:
Baseline: score = (overlap * 0.45) + (ratio * 0.55)
Ablated:  score = ratio (pure character Levenshtein without token semantics)
"""

import difflib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.workers.field_extractor import SemanticGroundedExtractor, CLASS_SCHEMAS
from app.workers.generic_extractor import GenericKeyValueExtractor

def evaluate_with_overlap(use_overlap: bool):
    with open("data/ocr_cache_holdout3.json", "r", encoding="utf-8") as f:
        ocr_cache_h3 = json.load(f)
    holdout3_dir = Path("data/dataset/holdout3")
    json_files = sorted([jf for jf in holdout3_dir.glob("*.json") if jf.name != "manifest.json"])

    total_expected = 0
    total_accurate = 0

    fallback = GenericKeyValueExtractor()
    extractor = SemanticGroundedExtractor(fallback_extractor=fallback)

    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            gt = json.load(f)
        did = gt["doc_id"]
        doc_cls = gt["doc_type"]
        if doc_cls == "unknown":
            continue
        gt_fields = gt.get("fields", {})
        ocr_rec = ocr_cache_h3.get(did, {})
        text = ocr_rec.get("full_text", "")

        # Extract lines
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        kv_pairs = []
        for line in lines:
            m = re.match(r"^([^:;|~]+?)[:;|~]\s*(.+)$", line)
            if m:
                kv_pairs.append((m.group(1).strip(), m.group(2).strip()))

        schema = CLASS_SCHEMAS.get(doc_cls, {})
        fields = {}

        for field_name, spec in schema.items():
            if field_name not in gt_fields:
                continue
            ftype = spec.get("type", "string")
            fdesc = spec.get("desc", field_name)
            desc_tokens = set(fdesc.lower().split() + field_name.split("_"))

            best_val = None
            best_score = 0.0

            for k_text, v_text in kv_pairs:
                k_clean = k_text.lower()
                k_tokens = set(re.findall(r"\b[a-z]{3,}\b", k_clean))
                overlap = len(desc_tokens.intersection(k_tokens))
                ratio = difflib.SequenceMatcher(None, field_name.replace("_", " "), k_clean).ratio()

                if use_overlap:
                    score = (overlap * 0.45) + (ratio * 0.55)
                else:
                    score = ratio  # ABLATED: Token overlap disabled!

                if ftype == "float" and not re.search(r"\$?\s*([0-9]+(?:\.[0-9]{2}))", v_text):
                    continue
                if ftype == "date" and not re.search(r"\b\d{4}[-/.]\d{2}[-/.]\d{2}\b|\b\d{2}[-/.]\d{2}[-/.]\d{4}\b", v_text):
                    continue

                if score > best_score:
                    best_score = score
                    best_val = v_text

            if best_val and best_score >= 0.40:
                fields[field_name] = best_val

        for fk, fv in gt_fields.items():
            total_expected += 1
            ext_val = fields.get(fk)
            if ext_val is not None:
                exp_s = str(fv).strip().lower()
                ext_s = str(ext_val).strip().lower()
                if exp_s in ext_s or ext_s in exp_s:
                    total_accurate += 1

    acc = (total_accurate / total_expected * 100) if total_expected > 0 else 0.0
    return total_accurate, total_expected, acc

def main():
    print("=" * 80)
    print("FEATURE ABLATION AUDIT: TOKEN OVERLAP SEMANTIC WEIGHT")
    print("Ablated feature: Description Token Overlap (overlap * 0.45)")
    print("=" * 80)

    acc1, exp1, pct1 = evaluate_with_overlap(use_overlap=True)
    acc2, exp2, pct2 = evaluate_with_overlap(use_overlap=False)

    print(f"1. Baseline Model (Token Overlap + Levenshtein): {acc1} / {exp1} ({pct1:.2f}%)")
    print(f"2. Ablated Model  (Pure Levenshtein without token semantics): {acc2} / {exp2} ({pct2:.2f}%)")
    print(f"Accuracy Drop: -{pct1 - pct2:.2f}%")

if __name__ == "__main__":
    main()
