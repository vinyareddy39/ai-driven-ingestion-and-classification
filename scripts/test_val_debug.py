import json
import difflib
import time
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import traceback

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

def process_doc(jf):
    try:
        val_dir = Path("data/dataset/val")
        ocr_engine = get_ocr_engine()
        with open(jf, "r", encoding="utf-8") as f:
            gt = json.load(f)
        did = gt["doc_id"]
        pdf_path = val_dir / gt["file_name"]
        with open(pdf_path, "rb") as pf:
            b = pf.read()
        res = ocr_engine.extract_text(b, "pdf")
        return did, gt, res.full_text, res.engine_name, res.engine_version
    except Exception as e:
        print(f"ERROR in {jf}: {e}\n{traceback.format_exc()}", flush=True)
        raise

if __name__ == "__main__":
    val_dir = Path("data/dataset/val")
    json_files = sorted(list(val_dir.glob("*.json")))[:5]
    print(f"Testing process_doc on {len(json_files)} docs...")
    for jf in json_files:
        t0 = time.time()
        res = process_doc(jf)
        print(f"  {res[0]}: length={len(res[2])} in {time.time()-t0:.2f}s")
