"""Diagnose PII Misses and False Positives on Holdout 3
Outputs:
1. Top 20 False Positives for PERSON
2. Top 20 Misses for PERSON with raw OCR text
3. All misses for PHONE_NUMBER (13) with raw OCR text
4. All misses for EMAIL_ADDRESS (8) with raw OCR text (check if ground truth email is in OCR text)
5. All misses for PASSPORT (7) with raw OCR text
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.pii import get_pii_detector

TYPE_MAP = {
    "EMAIL": "EMAIL_ADDRESS",
    "EMAIL_ADDRESS": "EMAIL_ADDRESS",
    "PHONE": "PHONE_NUMBER",
    "PHONE_NUMBER": "PHONE_NUMBER",
    "SSN": "US_SSN",
    "US_SSN": "US_SSN",
    "EIN": "US_EIN",
    "US_EIN": "US_EIN",
    "PASSPORT": "PASSPORT",
    "US_PASSPORT": "PASSPORT",
    "IBAN": "IBAN_CODE",
    "IBAN_CODE": "IBAN_CODE",
    "MEDICAL_LICENSE": "MEDICAL_LICENSE",
    "PERSON": "PERSON"
}

def clean_val(v: str) -> str:
    return re.sub(r"[\s\-\(\)\.,:]", "", str(v).lower())

def main():
    detector = get_pii_detector()

    with open("data/ocr_cache_holdout3.json", "r", encoding="utf-8") as f:
        ocr_cache = json.load(f)

    holdout3_dir = Path("data/dataset/holdout3")
    json_files = sorted([jf for jf in holdout3_dir.glob("*.json") if jf.name != "manifest.json"])

    person_fps = Counter()
    person_misses = []
    phone_misses = []
    email_misses = []
    passport_misses = []

    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            gt = json.load(f)
        did = gt["doc_id"]
        gt_entities = gt.get("pii_entities", [])
        ocr_text = ocr_cache.get(did, {}).get("full_text", "")

        detected = detector.detect(ocr_text)

        # Group GT by type
        gt_by_type = defaultdict(list)
        for e in gt_entities:
            raw_t = e.get("type") or e.get("entity_type")
            raw_v = e.get("value") or e.get("text")
            c_type = TYPE_MAP.get(raw_t.upper(), raw_t.upper())
            gt_by_type[c_type].append(raw_v)

        # Group detected by type
        det_by_type = defaultdict(list)
        for d in detected:
            c_type = TYPE_MAP.get(d.entity_type.upper(), d.entity_type.upper())
            det_by_type[c_type].append(d.text)

        # Check PERSON
        gt_person = [p for p in gt_by_type.get("PERSON", [])]
        det_person = [p for p in det_by_type.get("PERSON", [])]
        matched_gt_p = set()
        matched_det_p = set()

        for di, dp in enumerate(det_person):
            c_dp = clean_val(dp)
            found = False
            for gi, gp in enumerate(gt_person):
                if gi in matched_gt_p:
                    continue
                c_gp = clean_val(gp)
                if c_dp == c_gp or c_gp in c_dp or c_dp in c_gp:
                    matched_gt_p.add(gi)
                    matched_det_p.add(di)
                    found = True
                    break
            if not found:
                person_fps[dp.strip()] += 1

        for gi, gp in enumerate(gt_person):
            if gi not in matched_gt_p:
                person_misses.append({"doc_id": did, "val": gp, "ocr": ocr_text[:300]})

        # Check PHONE
        gt_phone = gt_by_type.get("PHONE_NUMBER", [])
        det_phone = det_by_type.get("PHONE_NUMBER", [])
        matched_phone = set()
        for gp in gt_phone:
            c_gp = clean_val(gp)[-7:]
            found = False
            for dp in det_phone:
                c_dp = clean_val(dp)[-7:]
                if c_gp == c_dp or c_gp in c_dp or c_dp in c_gp:
                    found = True
                    break
            if not found:
                phone_misses.append({"doc_id": did, "val": gp, "ocr": ocr_text[:350]})

        # Check EMAIL
        gt_email = gt_by_type.get("EMAIL_ADDRESS", [])
        det_email = det_by_type.get("EMAIL_ADDRESS", [])
        for ge in gt_email:
            c_ge = clean_val(ge)
            found = any(c_ge == clean_val(de) for de in det_email)
            if not found:
                in_ocr = ge.lower() in ocr_text.lower()
                email_misses.append({"doc_id": did, "val": ge, "in_ocr": in_ocr, "ocr": ocr_text[:350]})

        # Check PASSPORT
        gt_pass = gt_by_type.get("PASSPORT", [])
        det_pass = det_by_type.get("PASSPORT", [])
        for gpa in gt_pass:
            c_gpa = clean_val(gpa)
            found = any(c_gpa == clean_val(dpa) for dpa in det_pass)
            if not found:
                passport_misses.append({"doc_id": did, "val": gpa, "ocr": ocr_text[:350]})

    print("=" * 80)
    print("TOP 20 PERSON FALSE POSITIVES (Total FP count: 126)")
    print("=" * 80)
    for term, count in person_fps.most_common(20):
        print(f"  {term:<35}: {count} occurrences")

    print("\n" + "=" * 80)
    print(f"ALL PERSON MISSES (Total Misses: {len(person_misses)})")
    print("=" * 80)
    for i, m in enumerate(person_misses, 1):
        print(f"#{i} Doc: {m['doc_id']} | Missed: '{m['val']}' | OCR context: {repr(m['ocr'])}")

    print("\n" + "=" * 80)
    print(f"ALL PHONE MISSES (Total Misses: {len(phone_misses)})")
    print("=" * 80)
    for i, m in enumerate(phone_misses, 1):
        print(f"#{i} Doc: {m['doc_id']} | Missed: '{m['val']}' | OCR context: {repr(m['ocr'])}")

    print("\n" + "=" * 80)
    print(f"ALL EMAIL MISSES (Total Misses: {len(email_misses)})")
    print("=" * 80)
    for i, m in enumerate(email_misses, 1):
        print(f"#{i} Doc: {m['doc_id']} | Missed: '{m['val']}' | Present in OCR text?: {m['in_ocr']} | OCR: {repr(m['ocr'])}")

    print("\n" + "=" * 80)
    print(f"ALL PASSPORT MISSES (Total Misses: {len(passport_misses)})")
    print("=" * 80)
    for i, m in enumerate(passport_misses, 1):
        print(f"#{i} Doc: {m['doc_id']} | Missed: '{m['val']}' | OCR: {repr(m['ocr'])}")

if __name__ == "__main__":
    main()
