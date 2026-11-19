"""Re-score Direction 2 (Holdout 2 evaluated with v2-tuned schema)
Using a schema-driven alias map.
Separates 'wrong value' from 'key mismatch'.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.workers.stages import stage_extract_fields

ALIAS_MAP = {
    # Contract parties aliases
    "party_one": ["first_party", "parties"],
    "party_two": ["second_party", "parties"],
    "parties": ["party_one", "party_two"],
    # Identity / Name aliases
    "full_name": ["customer_name", "applicant_name"],
    "customer_name": ["full_name"],
    # Date aliases
    "letter_date": ["date"],
    "date": ["letter_date"],
    "po_date": ["order_date"],
    "order_date": ["po_date"],
    # Financial total aliases
    "order_total": ["total_amount"],
    "total_amount": ["order_total"],
    "buyer_name": ["customer_name", "recipient"],
}

def clean_val(v):
    if v is None:
        return ""
    return re.sub(r"[\s$,:\-.]", "", str(v).lower())

def main():
    with open("data/ocr_cache_holdout2.json", "r", encoding="utf-8") as f:
        ocr_cache = json.load(f)

    h2_dir = Path("data/dataset/holdout2")
    json_files = sorted([f for f in h2_dir.glob("*.json") if f.name != "manifest.json"])

    total_fields = 0
    direct_correct = 0
    alias_correct = 0
    wrong_value = 0
    key_mismatch = 0

    class_stats = {}

    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            gt = json.load(f)
        did = gt["doc_id"]
        dt = gt["doc_type"]
        if dt not in class_stats:
            class_stats[dt] = {"total": 0, "correct": 0, "wrong_val": 0, "key_mismatch": 0}

        gt_fields = gt.get("fields", {})
        text = ocr_cache.get(did, {}).get("full_text", "")
        extracted, confs, _ = stage_extract_fields(text, dt)

        for k, v in gt_fields.items():
            total_fields += 1
            class_stats[dt]["total"] += 1
            gt_c = clean_val(v)

            # 1. Direct key match
            if k in extracted and extracted[k] is not None:
                ext_c = clean_val(extracted[k])
                if ext_c == gt_c or gt_c in ext_c or ext_c in gt_c:
                    direct_correct += 1
                    class_stats[dt]["correct"] += 1
                else:
                    wrong_value += 1
                    class_stats[dt]["wrong_val"] += 1
                continue

            # 2. Check alias map
            aliases = ALIAS_MAP.get(k, [])
            matched_alias = False
            for ak in aliases:
                if ak in extracted and extracted[ak] is not None:
                    # Special handling for parties: party_one & party_two combined
                    if ak == "parties" and k in ["party_one", "party_two"]:
                        p_str = str(extracted[ak])
                        parts = [p.strip() for p in p_str.split("&")]
                        if k == "party_one" and len(parts) >= 1:
                            cand_c = clean_val(parts[0])
                        elif k == "party_two" and len(parts) >= 2:
                            cand_c = clean_val(parts[1])
                        else:
                            cand_c = clean_val(p_str)
                    else:
                        cand_c = clean_val(extracted[ak])

                    if cand_c == gt_c or gt_c in cand_c or cand_c in gt_c:
                        alias_correct += 1
                        class_stats[dt]["correct"] += 1
                        matched_alias = True
                        break
                    else:
                        wrong_value += 1
                        class_stats[dt]["wrong_val"] += 1
                        matched_alias = True
                        break

            if not matched_alias:
                # Key was completely absent in extracted output
                key_mismatch += 1
                class_stats[dt]["key_mismatch"] += 1

    total_correct = direct_correct + alias_correct
    print("=" * 80)
    print("DIRECTION 2 RE-SCORING WITH SCHEMA ALIAS MAP (Holdout 2 / Family v1)")
    print("=" * 80)
    print(f"Total Evaluated Fields: {total_fields}")
    print(f"Total Correct:          {total_correct} ({total_correct / total_fields * 100:.2f}%)")
    print(f"  - Direct Key Matches: {direct_correct} ({direct_correct / total_fields * 100:.2f}%)")
    print(f"  - Alias Key Matches:  {alias_correct} ({alias_correct / total_fields * 100:.2f}%)")
    print(f"Total Failures:         {total_fields - total_correct} ({(total_fields - total_correct) / total_fields * 100:.2f}%)")
    print(f"  - Wrong Value:        {wrong_value} ({wrong_value / total_fields * 100:.2f}%)")
    print(f"  - Key Mismatch:       {key_mismatch} ({key_mismatch / total_fields * 100:.2f}%)")
    print("\nPER CLASS BREAKDOWN:")
    for dt, s in sorted(class_stats.items()):
        acc = s["correct"] / s["total"] * 100 if s["total"] else 0.0
        print(f"  {dt:<18}: Correct={s['correct']}/{s['total']} ({acc:.2f}%) | WrongVal={s['wrong_val']} | KeyMismatch={s['key_mismatch']}")

if __name__ == "__main__":
    main()
