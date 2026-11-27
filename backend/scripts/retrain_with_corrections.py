"""Simulate Human Review corrections export as JSONL, retrain the classifier,
and evaluate classification accuracy before vs after on the held-out validation set.
"""

import json
import os
import sys
from pathlib import Path
from sklearn.metrics import accuracy_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.classifier_train import load_split_data
from app.adapters.classifier import get_classifier
import joblib

def main():
    print("=" * 80)
    print("PHASE 3: ACTIVE-LEARNING RETRAINING FROM HUMAN CORRECTIONS")
    print("=" * 80)

    # 1. Export 3 sample JSONL correction records from the review desk
    corrections_export = [
        {
            "uid": "corr-invoice-8801",
            "sha256": "8f8a123bc89a7d320912384aedc091237a891234bc5678ef0123456789abcdef",
            "verified_type": "invoice",
            "verified_fields": {"invoice_number": "INV-2026-CORR", "total_amount": 1450.50, "vendor_name": "Apex Global Services"},
            "reviewer": "compliance-officer-01",
            "verified_at": "2026-11-18T18:30:00Z"
        },
        {
            "uid": "corr-contract-8802",
            "sha256": "4b7c891de0123456789abcdef0123456789abcdef0123456789abcdef0123456",
            "verified_type": "contract",
            "verified_fields": {"contract_id": "CNT-LEGAL-772", "effective_date": "2026-06-01", "parties": "Global Tech Corp & Delta Logistics"},
            "reviewer": "legal-reviewer-02",
            "verified_at": "2026-11-18T18:32:15Z"
        },
        {
            "uid": "corr-kyc-8803",
            "sha256": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b",
            "verified_type": "kyc_form",
            "verified_fields": {"customer_name": "Dr. Sarah Jenkins", "date_of_birth": "1984-11-23", "id_number": "P88921034"},
            "reviewer": "kyc-compliance-lead",
            "verified_at": "2026-11-18T18:35:40Z"
        }
    ]

    print("--- 3 RAW EXPORTED HUMAN-VERIFIED JSONL RECORDS ---")
    for rec in corrections_export:
        print(json.dumps(rec))

    # 2. Evaluate current baseline classifier on validation set
    val_texts, val_labels, _ = load_split_data(Path("data/dataset/val"))
    baseline_clf = get_classifier()
    
    preds_before = [baseline_clf.predict(t).predicted_class for t in val_texts]
    acc_before = accuracy_score(val_labels, preds_before) * 100.0

    print(f"\nBaseline Classifier Accuracy on Validation Split: {acc_before:.2f}% ({sum(1 for y, p in zip(val_labels, preds_before) if y == p)} / {len(val_labels)})")

    # 3. Retrain with corrections injected
    train_texts, train_labels, _ = load_split_data(Path("data/dataset/train"))
    
    # Inject corrected samples
    for c in corrections_export:
        synthetic_text = f"Document Type: {c['verified_type']}\nReference: {c['uid']}\nFields: {json.dumps(c['verified_fields'])}"
        train_texts.append(synthetic_text)
        train_labels.append(c["verified_type"])

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    retrained_pipe = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), max_features=10000, sublinear_tf=True)),
        ("clf", LogisticRegression(C=5.0, max_iter=1000, class_weight="balanced", random_state=42))
    ])
    retrained_pipe.fit(train_texts, train_labels)

    preds_after = retrained_pipe.predict(val_texts)
    acc_after = accuracy_score(val_labels, preds_after) * 100.0

    print(f"Retrained Classifier Accuracy on Validation Split: {acc_after:.2f}% ({sum(1 for y, p in zip(val_labels, preds_after) if y == p)} / {len(val_labels)})")
    print(f"Active Learning Impact on Held-Out Validation Split: {acc_after - acc_before:+.2f}%")
    print("=" * 80)

if __name__ == "__main__":
    main()
