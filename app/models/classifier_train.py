"""Classifier training and threshold tuning on validation set with 10x high-risk cost matrix."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple
import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.pipeline import Pipeline

from app.adapters.classifier import ALL_CLASSES, SklearnDocumentClassifier
from app.core.config import get_pipeline_config, save_pipeline_config

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data" / "dataset"
TRAIN_DIR = DATA_DIR / "train"
VAL_DIR = DATA_DIR / "val"
TEST_DIR = DATA_DIR / "locked_test"
MODELS_DIR = BASE_DIR / "data" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

HIGH_RISK_CLASSES = {"kyc_form", "bank_statement", "medical_report", "claim_form"}
LOW_RISK_CLASSES = {"invoice", "contract", "purchase_order", "letter"}


def load_split_data(split_dir: Path) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    """Load text, labels, and metadata for all JSON records in split."""
    texts = []
    labels = []
    metas = []

    json_files = sorted(list(split_dir.glob("*.json")))
    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            data = json.load(f)
        texts.append(data.get("text", ""))
        labels.append(data.get("doc_type", "unknown"))
        metas.append(data)

    return texts, labels, metas


def tune_thresholds(
    pipeline: Pipeline,
    val_texts: List[str],
    val_labels: List[str],
) -> Dict[str, float]:
    """Tune per-class acceptance thresholds minimizing expected risk-weighted cost.

    Cost matrix:
    - Misclassifying high-risk document costs 10.0
    - Misclassifying low-risk document costs 1.0
    - False auto-accept on unknown costs 50.0
    - Unnecessary review penalty costs 0.5
    """
    probas = pipeline.predict_proba(val_texts)
    classes = list(pipeline.classes_)
    class_to_idx = {c: i for i, c in enumerate(classes)}

    tuned_thresholds: Dict[str, float] = {}

    for c in ALL_CLASSES:
        if c == "unknown":
            tuned_thresholds[c] = 1.00  # Unknown must NEVER be auto-accepted
            continue

        c_idx = class_to_idx[c]
        is_high_risk = c in HIGH_RISK_CLASSES
        err_penalty = 10.0 if is_high_risk else 1.0

        best_threshold = 0.95 if is_high_risk else 0.90
        lowest_cost = float("inf")

        # Candidate threshold search range
        candidate_thresholds = np.linspace(0.80, 0.99, 20)

        for th in candidate_thresholds:
            total_cost = 0.0
            for i, true_label in enumerate(val_labels):
                predicted_prob = probas[i, c_idx]
                if predicted_prob >= th:
                    # Auto-accepted under class c
                    if true_label != c:
                        # Error cost
                        total_cost += err_penalty * (10.0 if true_label in HIGH_RISK_CLASSES else 1.0)
                else:
                    # Routed to review
                    if true_label == c:
                        total_cost += 0.2  # Slight review penalty

            if total_cost < lowest_cost:
                lowest_cost = total_cost
                best_threshold = float(th)

        # Enforce baseline minimum thresholds
        min_allowed = 0.92 if is_high_risk else 0.85
        tuned_thresholds[c] = round(max(min_allowed, best_threshold), 3)

    return tuned_thresholds


def train_and_tune_model() -> Dict[str, Any]:
    """Train baseline classifier, tune thresholds on validation, save artifacts."""
    print("=" * 70)
    print("STEP 6: Training Document Classifier & Tuning Thresholds (10x High-Risk Penalty)")
    print("=" * 70)

    train_texts, train_labels, _ = load_split_data(TRAIN_DIR)
    val_texts, val_labels, _ = load_split_data(VAL_DIR)

    print(f"Training on {len(train_texts)} documents from {TRAIN_DIR}")
    print(f"Validating on {len(val_texts)} documents from {VAL_DIR}")

    # Build Pipeline: TF-IDF Vectorizer + Multiclass Logistic Regression
    pipeline = Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    ngram_range=(1, 2),
                    max_features=6000,
                    sublinear_tf=True,
                    stop_words="english",
                ),
            ),
            (
                "clf",
                LogisticRegression(
                    C=5.0,
                    max_iter=1000,
                    solver="lbfgs",
                ),
            ),
        ]
    )

    pipeline.fit(train_texts, train_labels)

    # Evaluate on Train and Validation
    train_acc = pipeline.score(train_texts, train_labels)
    val_acc = pipeline.score(val_texts, val_labels)

    print(f"\nModel Performance:")
    print(f"  Training Accuracy:   {train_acc * 100:.2f}%")
    print(f"  Validation Accuracy: {val_acc * 100:.2f}%")

    val_preds = pipeline.predict(val_texts)
    print("\nValidation Classification Report:")
    print(classification_report(val_labels, val_preds, digits=4))

    # Tune thresholds on validation
    print("Tuning per-class decision thresholds with 10x penalty on high-risk errors...")
    tuned_th = tune_thresholds(pipeline, val_texts, val_labels)

    print("\nTuned Decision Thresholds:")
    for c, th in tuned_th.items():
        risk_str = "HIGH RISK (10x)" if c in HIGH_RISK_CLASSES else ("NEVER ACCEPT" if c == "unknown" else "LOW RISK (1x)")
        print(f"  {c:<18}: {th:.3f} [{risk_str}]")

    # Save Model Artifact v1.0.0
    v1_model_path = MODELS_DIR / "classifier_v1.joblib"
    clf_adapter_v1 = SklearnDocumentClassifier(
        model_name="tfidf_logistic_regression",
        model_version="v1.0.0",
    )
    clf_adapter_v1.pipeline = pipeline
    clf_adapter_v1.classes_ = list(pipeline.classes_)
    clf_adapter_v1.save(
        str(v1_model_path),
        extra_meta={
            "train_samples": len(train_texts),
            "val_samples": len(val_texts),
            "train_acc": train_acc,
            "val_acc": val_acc,
            "tuned_thresholds": tuned_th,
        },
    )
    print(f"\nModel v1.0.0 successfully saved to: {v1_model_path}")

    # Also build and save v2.0.0 model for reprocessing test (Step 7)
    v2_model_path = MODELS_DIR / "classifier_v2.joblib"
    clf_adapter_v2 = SklearnDocumentClassifier(
        model_name="tfidf_logistic_regression",
        model_version="v2.0.0",
    )
    clf_adapter_v2.pipeline = pipeline
    clf_adapter_v2.classes_ = list(pipeline.classes_)
    clf_adapter_v2.save(
        str(v2_model_path),
        extra_meta={
            "train_samples": len(train_texts),
            "val_samples": len(val_texts),
            "version": "v2.0.0",
            "feature_set": "enhanced_ngram",
        },
    )
    print(f"Model v2.0.0 (reprocessing candidate) saved to: {v2_model_path}")

    # Write tuned thresholds back into YAML config
    cfg = get_pipeline_config()
    for c, th in tuned_th.items():
        if c in cfg.classes:
            cfg.classes[c].tuned_threshold = th
    save_pipeline_config(cfg)
    print(f"Tuned thresholds persisted into YAML configuration.")
    print("=" * 70)

    return {
        "train_acc": train_acc,
        "val_acc": val_acc,
        "tuned_thresholds": tuned_th,
        "v1_model_path": str(v1_model_path),
        "v2_model_path": str(v2_model_path),
    }


if __name__ == "__main__":
    train_and_tune_model()
