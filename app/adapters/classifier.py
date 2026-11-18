"""Document Classifier Adapter implementing Classifier interface using scikit-learn."""

import os
from pathlib import Path
from typing import Dict, List, Optional
import joblib
import numpy as np
from app.core.interfaces import ClassificationResult, Classifier
from app.core.config import get_app_settings

ALL_CLASSES = [
    "invoice",
    "contract",
    "kyc_form",
    "bank_statement",
    "medical_report",
    "purchase_order",
    "letter",
    "claim_form",
    "unknown",
]


class SklearnDocumentClassifier(Classifier):
    """Scikit-Learn TF-IDF + Logistic Regression document classifier."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        model_name: str = "tfidf_logistic_regression",
        model_version: str = "v1.0.0",
    ):
        self.model_name = model_name
        self.model_version = model_version
        self.pipeline = None
        self.classes_ = ALL_CLASSES
        self.model_path = model_path
        if model_path and os.path.exists(model_path):
            self.load(model_path)

    def load(self, path: str) -> None:
        """Load trained model pipeline and metadata from joblib."""
        data = joblib.load(path)
        if isinstance(data, dict):
            self.pipeline = data.get("pipeline")
            self.model_name = data.get("model_name", self.model_name)
            self.model_version = data.get("model_version", self.model_version)
            self.classes_ = data.get("classes", ALL_CLASSES)
        else:
            self.pipeline = data
        self.model_path = path

    def save(self, path: str, extra_meta: Optional[Dict] = None) -> None:
        """Save model pipeline and version metadata."""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        payload = {
            "pipeline": self.pipeline,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "classes": self.classes_,
            "metadata": extra_meta or {},
        }
        joblib.dump(payload, path)
        self.model_path = path

    # -----------------------------------------------------------------------
    # Fallback heuristic prediction when no trained model is saved yet
    # -----------------------------------------------------------------------
    def _heuristic_predict(self, text: str) -> ClassificationResult:
        text_lower = text.lower()
        scores = {c: 0.05 for c in ALL_CLASSES}

        if "invoice" in text_lower or "total amount" in text_lower or "due date" in text_lower:
            scores["invoice"] += 0.85
        if "agreement" in text_lower or "parties" in text_lower or "hereby agree" in text_lower or "contract" in text_lower:
            scores["contract"] += 0.85
        if "kyc" in text_lower or "customer identification" in text_lower or "passport" in text_lower or "nationality" in text_lower:
            scores["kyc_form"] += 0.88
        if "bank statement" in text_lower or "account number" in text_lower or "opening balance" in text_lower or "closing balance" in text_lower:
            scores["bank_statement"] += 0.88
        if "medical report" in text_lower or "patient id" in text_lower or "diagnosis" in text_lower or "physician" in text_lower:
            scores["medical_report"] += 0.88
        if "purchase order" in text_lower or "po number" in text_lower or "vendor" in text_lower:
            scores["purchase_order"] += 0.85
        if "dear" in text_lower or "sincerely" in text_lower or "subject:" in text_lower or "to whom it may concern" in text_lower:
            scores["letter"] += 0.80
        if "insurance claim" in text_lower or "claimant" in text_lower or "incident date" in text_lower or "claim amount" in text_lower:
            scores["claim_form"] += 0.88

        # Normalize to probability distribution
        total = sum(scores.values())
        probs = {k: float(v / total) for k, v in scores.items()}
        best_class = max(probs, key=probs.get)
        best_conf = probs[best_class]

        # If top confidence is low or text is too short/generic, classify as unknown
        if best_conf < 0.45 or len(text.strip().split()) < 5:
            best_class = "unknown"
            probs["unknown"] = 0.90
            best_conf = 0.90

        return ClassificationResult(
            predicted_class=best_class,
            confidence=round(best_conf, 4),
            probabilities={k: round(v, 4) for k, v in probs.items()},
            model_name=self.model_name,
            model_version=self.model_version,
        )

    # -----------------------------------------------------------------------
    # Public Classifier API
    # -----------------------------------------------------------------------

    def predict(self, text: str) -> ClassificationResult:
        if self.pipeline is None:
            return self._heuristic_predict(text)

        cleaned_text = [text if text.strip() else "unknown document text"]
        probas = self.pipeline.predict_proba(cleaned_text)[0]
        classes = list(self.pipeline.classes_)

        prob_dict = {str(c): float(p) for c, p in zip(classes, probas)}
        # Ensure all standard classes exist in dict
        for c in ALL_CLASSES:
            if c not in prob_dict:
                prob_dict[c] = 0.0

        best_class = max(prob_dict, key=prob_dict.get)
        confidence = float(prob_dict[best_class])

        # If highest confidence is below uncertainty threshold, escalate to unknown
        if confidence < 0.40:
            best_class = "unknown"
            confidence = max(0.60, prob_dict.get("unknown", 0.60))

        return ClassificationResult(
            predicted_class=best_class,
            confidence=round(confidence, 4),
            probabilities={k: round(v, 4) for k, v in prob_dict.items()},
            model_name=self.model_name,
            model_version=self.model_version,
        )

    def predict_proba(self, text: str) -> Dict[str, float]:
        res = self.predict(text)
        return res.probabilities

    def get_model_info(self) -> Dict[str, str]:
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "model_path": self.model_path or "heuristic_in_memory",
        }


_classifier_singleton: Optional[Classifier] = None


def get_classifier(model_version: Optional[str] = None) -> Classifier:
    """Factory returning configured or versioned classifier."""
    global _classifier_singleton
    settings = get_app_settings()
    model_dir = Path(settings.MODEL_ARTIFACTS_DIR)

    if model_version:
        target_path = model_dir / f"classifier_{model_version}.joblib"
        if target_path.exists():
            return SklearnDocumentClassifier(
                model_path=str(target_path),
                model_version=model_version,
            )

    if _classifier_singleton is None:
        default_model_path = model_dir / "classifier_v1.joblib"
        if default_model_path.exists():
            _classifier_singleton = SklearnDocumentClassifier(model_path=str(default_model_path))
        else:
            _classifier_singleton = SklearnDocumentClassifier()
    return _classifier_singleton
