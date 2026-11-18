"""Weekly confidence and class-mix drift monitoring report."""

from collections import Counter
import json
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.db import DocumentModel, get_db_session

BASELINE_CLASS_DISTRIBUTION = {
    "invoice": 0.15,
    "purchase_order": 0.15,
    "contract": 0.10,
    "letter": 0.10,
    "bank_statement": 0.10,
    "kyc_form": 0.10,
    "medical_report": 0.10,
    "claim_form": 0.10,
    "unknown": 0.10
}

def generate_drift_report():
    print("=" * 80)
    print("ECM PIPELINE DRIFT MONITORING REPORT")
    print("=" * 80)
    
    db = get_db_session()
    try:
        docs = db.query(DocumentModel).all()
        if not docs:
            print("No documents found for drift analysis.")
            return
            
        total_docs = len(docs)
        classes = [d.doc_type for d in docs]
        confidences = [d.confidence for d in docs]
        class_counts = Counter(classes)
        
        print(f"Total Evaluated Assets:     {total_docs}")
        print(f"Mean Pipeline Confidence:   {np.mean(confidences):.4f}")
        print(f"Median Confidence (p50):    {np.median(confidences):.4f}")
        print(f"p10 Confidence:             {np.percentile(confidences, 10):.4f}")
        print("\n--- CLASS DISTRIBUTION & SHIFT AUDIT ---")
        print(f"{'Class Name':<20} {'Count':<8} {'Observed Share':<16} {'Baseline Share':<16} {'Drift Delta':<12}")
        print("-" * 72)
        
        alerts = []
        for cls, count in class_counts.most_common():
            obs_share = count / total_docs
            base_share = BASELINE_CLASS_DISTRIBUTION.get(cls, 0.10)
            delta = obs_share - base_share
            print(f"{cls:<20} {count:<8} {obs_share*100:>6.2f}%         {base_share*100:>6.2f}%         {delta*100:>+6.2f}%")
            
            if abs(delta) > 0.15:
                alerts.append(f"CLASS SHIFT ALERT: Class '{cls}' shifted by {delta*100:+.2f}% from baseline expectation!")
                
        if np.mean(confidences) < 0.85:
            alerts.append(f"CONFIDENCE DRIFT ALERT: Overall mean confidence ({np.mean(confidences):.4f}) dropped below 0.8500!")
            
        print("\n--- DRIFT STATUS SUMMARY ---")
        if alerts:
            print(f"Status: WARNING ({len(alerts)} alerts triggered)")
            for a in alerts:
                print(f"  [!] {a}")
        else:
            print("Status: HEALTHY (All class distributions and confidence levels within tolerance)")
            
    finally:
        db.close()

if __name__ == "__main__":
    generate_drift_report()
