"""Compliance audit sample: extract 10 random assets and answer why they were classified, retained, and restricted."""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.db import DocumentModel, get_db_session

def audit_10_random_assets():
    print("=" * 80)
    print("COMPLIANCE AUDIT VERIFICATION: 10 RANDOM ASSETS")
    print("Answering: 'Why was this document classified, retained, and restricted this way?'")
    print("=" * 80)
    
    db = get_db_session()
    try:
        docs = db.query(DocumentModel).all()
        if not docs:
            print("No documents found in database.")
            return
            
        sample_size = min(10, len(docs))
        sample_docs = random.sample(docs, sample_size)
        
        for idx, doc in enumerate(sample_docs, 1):
            print(f"\n--- ASSET AUDIT SAMPLE #{idx} (UID: {doc.uid}) ---")
            print(f"  SHA-256 Digest:         {doc.sha256}")
            print(f"  Predicted Doc Type:     {doc.doc_type} (Confidence: {doc.confidence:.4f})")
            print(f"  Assigned Retention:     {doc.retention_class}")
            print(f"  Assigned Security ACL:  {doc.acl}")
            print(f"  Review / Auto-Accept:   {doc.review_status}")
            print(f"  Decision Gate Reason:   {doc.decision_reason}")
            print(f"  OCR Engine & Version:   {doc.ocr_engine} v{doc.ocr_version}")
            print(f"  Model & Version:        {doc.classifier_model} {doc.classifier_version}")
            print(f"  Detected PII Types:     {doc.pii_types_json}")
            print(f"  Processed At:           {doc.created_at}")
            
            # Compliance Verification Check
            has_reason = bool(doc.decision_reason and doc.decision_reason.strip())
            has_acl = bool(doc.acl and doc.acl.strip())
            has_retention = bool(doc.retention_class and doc.retention_class.strip())
            has_model_ver = bool(doc.classifier_version and doc.classifier_version.strip())
            
            is_compliant = has_reason and has_acl and has_retention and has_model_ver
            print(f"  Compliance Completeness: {'PASS (100% Self-Contained Audit Trail)' if is_compliant else 'FAIL'}")
            
    finally:
        db.close()

if __name__ == "__main__":
    audit_10_random_assets()
