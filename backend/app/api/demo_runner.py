"""Demo runner for AI-driven document ingestion and classification pipeline.

Ingests a representative sample batch into the pipeline, writes results to FakeECM
and SQLite, and provides instructions to inspect the HTMX review UI at /review.
"""

import hashlib
import os
import sys
import time
import uuid
from pathlib import Path

# Ensure root directory is on python path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.core.config import get_pipeline_config
from app.adapters.storage import get_storage_adapter
from app.workers.pipeline import process_document_payload
from app.models.db import get_db_session, DocumentModel


def run_demo():
    print("=" * 75)
    print("  AI-DRIVEN DOCUMENT INGESTION & CLASSIFICATION - PIPELINE DEMO")
    print("=" * 75)
    
    test_dir = BASE_DIR / "data" / "dataset" / "locked_test"
    if not test_dir.exists():
        print(f"Error: test directory not found at {test_dir}. Run 'make generate-data' first.")
        return

    # Select representative sample files
    sample_types = ["invoice", "contract", "medical_report", "unknown", "claim_form"]
    sample_files = []
    for st in sample_types:
        matches = list(test_dir.glob(f"{st}_*.pdf")) + list(test_dir.glob(f"{st}_*.png"))
        if matches:
            sample_files.append((st, matches[0]))

    # Also include the conflict special document if present
    special_dir = BASE_DIR / "data" / "dataset" / "special"
    conflict_doc = special_dir / "special_conflict_document.pdf"
    if conflict_doc.exists():
        sample_files.append(("conflict_doc", conflict_doc))

    print(f"\n[1] Initializing Storage and Database...")
    storage = get_storage_adapter()
    
    print(f"[2] Ingesting {len(sample_files)} diverse documents into pipeline:")
    results = []
    for label, filepath in sample_files:
        with open(filepath, "rb") as f:
            content = f.read()
        filename = filepath.name
        sha256_hash = hashlib.sha256(content).hexdigest()
        storage.save(sha256_hash, content)
        
        uid = f"demo-{label}-{uuid.uuid4().hex[:8]}"
        payload = {
            "uid": uid,
            "sha256": sha256_hash,
            "file_name": filename,
            "storage_path": f"documents/{sha256_hash}",
        }
        print(f"    --> Processing {filename} ({label})...")
        res = process_document_payload(payload)
        results.append(res)
        dec = res.get("decision", {})
        action = dec.get("action", res.get("status"))
        pred_type = dec.get("predicted_class", "unknown")
        conf = dec.get("confidence", 0.0)
        rev_status = dec.get("review_status", "quarantined" if res.get("status") == "QUARANTINED" else "unknown")
        print(f"        Status: {res.get('status')} | Action: {action} | Type: {pred_type} | Confidence: {conf} | Review Status: {rev_status}")

    print("\n[3] Ingestion Summary:")
    print(f"    Current Batch Processed: {len(results)}")
    
    # Query database for overall pipeline & review queue status
    db = get_db_session()
    try:
        total_db = db.query(DocumentModel).count()
        auto_accepted_db = db.query(DocumentModel).filter(DocumentModel.review_status == "auto_accepted").count()
        pending_review_db = db.query(DocumentModel).filter(DocumentModel.review_status == "pending_review").count()
        quarantined_db = db.query(DocumentModel).filter(DocumentModel.review_status == "quarantined").count()
        links_db = db.query(DocumentModel).filter(DocumentModel.is_link == True).count()
        print(f"    Total Repository Documents: {total_db}")
        print(f"    Auto-Accepted (STP):       {auto_accepted_db}")
        print(f"    Pending Human Review:      {pending_review_db}")
        print(f"    Quarantined / Security:    {quarantined_db}")
        print(f"    Deduplicated Links:        {links_db}")
    finally:
        db.close()

    print("\n[4] Review Queue & API Endpoints:")
    print("    * HTMX Human Review UI: http://127.0.0.1:8000/review")
    print("    * Prometheus Metrics:   http://127.0.0.1:8000/metrics")
    print("    * Health Readiness:     http://127.0.0.1:8000/health/ready")
    print("    * Reprocess API:        POST http://127.0.0.1:8000/reprocess")
    print("=" * 75)
    print("To launch the interactive FastAPI server and explore the Review UI:")
    print("    python -m uvicorn app.api.app:app --host 0.0.0.0 --port 8000 --reload")
    print("=" * 75)


if __name__ == "__main__":
    run_demo()
