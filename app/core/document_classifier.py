"""Holistic Document Classifier over Config-Driven Taxonomy.

Evaluates whole document structure, language patterns, and extracted field concepts.
Returns calibrated real confidence, detects close/ambiguous classes, and routes
uncertain documents to 'unknown' with needs_review flag.
"""

import math
import re
from typing import Any, Dict, List, Optional, Tuple
from app.core.config_loader import ConfigLoader


class GeneralizedDocumentClassifier:
    """Classifies documents using whole-document evidence and taxonomy config."""

    def __init__(self, config_loader: Optional[ConfigLoader] = None):
        self.loader = config_loader or ConfigLoader.get_instance()

    def classify(
        self,
        full_text: str,
        fields: List[Dict[str, Any]],
        table_rows: List[Any],
        has_dates: bool = False,
        has_title_block: bool = False,
    ) -> Dict[str, Any]:
        """Classify document using holistic structural and linguistic evidence."""
        taxonomy = self.loader.taxonomy
        metadata = self.loader.taxonomy_metadata

        min_conf = float(metadata.get("minimum_confidence", 0.50))
        ambiguity_margin = float(metadata.get("ambiguity_margin", 0.15))
        default_class = str(metadata.get("default_class", "unknown"))

        if not taxonomy or not full_text or len(full_text.strip().split()) < 3:
            return {
                "type": default_class,
                "type_confidence": 0.0,
                "top_candidates": [],
                "top_candidate": default_class,
                "scores": {},
                "needs_review": True,
                "review_reasons": ["Insufficient text content to classify with confidence."],
                "reason": "Insufficient text content to classify with confidence.",
            }

        text_lower = full_text.lower()
        extracted_labels = [f.get("label", "").lower().strip() for f in fields if f.get("label")]

        raw_scores: Dict[str, float] = {}

        # -------------------------------------------------------------------
        # Multi-factor Holistic Scoring for Each Class in Taxonomy
        # -------------------------------------------------------------------
        for class_name, class_def in taxonomy.items():
            score = 0.0

            # 1. Linguistic & Vocabulary Evidence
            keywords = class_def.get("keywords", [])
            kw_hits = 0
            for kw in keywords:
                kw_str = kw.lower().strip()
                if kw_str.endswith(":"):
                    pattern = r"\b" + re.escape(kw_str[:-1]) + r"\s*:"
                else:
                    pattern = r"\b" + re.escape(kw_str) + r"\b"
                matches = len(re.findall(pattern, text_lower))
                if matches > 0:
                    kw_hits += 1
                    score += 1.0 + min(2.0, matches * 0.5)

            # Keyword density factor
            kw_coverage = (kw_hits / len(keywords)) if keywords else 0.0
            score += kw_coverage * 5.0

            # 1b. Negative Evidence Evaluation (e.g. 'not an invoice', 'quotation only')
            negative_keywords = class_def.get("negative_keywords", [])
            for n_kw in negative_keywords:
                n_kw_str = n_kw.lower().strip()
                if n_kw_str in text_lower:
                    # Explicit negative evidence severely discounts class
                    score -= 15.0
                    break

            # 2. Extracted Field Concept Alignment
            field_concepts = class_def.get("field_concepts", [])
            concept_hits = 0
            for concept in field_concepts:
                concept_words = concept.replace("_", " ").lower()
                for el in extracted_labels:
                    if concept_words in el or el in concept_words:
                        concept_hits += 1
                        score += 3.0
                        break

            # 3. Structural Cues Alignment
            structural = class_def.get("structural_cues", {})
            if structural.get("has_line_items") and len(table_rows) > 0:
                score += 2.5
            if structural.get("has_totals_summary"):
                if any(w in text_lower for w in ["total", "subtotal", "balance", "amount due"]):
                    score += 2.0
            if structural.get("has_signature_block"):
                if any(w in text_lower for w in ["signature", "signed", "in witness whereof", "authorized by"]):
                    score += 3.0
            if structural.get("has_clinical_sections"):
                if any(w in text_lower for w in ["specimen", "impression", "history", "vital signs", "lab report"]):
                    score += 3.5
            if structural.get("has_transaction_table") and len(table_rows) > 0:
                score += 2.5

            raw_scores[class_name] = max(0.01, score)

        # -------------------------------------------------------------------
        # Probability Normalization via Softmax with Temperature
        # -------------------------------------------------------------------
        temperature = 3.0  # Smoothing temperature
        exp_scores = {k: math.exp(v / temperature) for k, v in raw_scores.items()}
        sum_exp = sum(exp_scores.values())
        probs = {k: float(v / sum_exp) for k, v in exp_scores.items()}

        sorted_classes = sorted(probs.items(), key=lambda x: x[1], reverse=True)
        top_class, top_conf = sorted_classes[0]
        second_class, second_conf = sorted_classes[1] if len(sorted_classes) > 1 else ("", 0.0)

        # Top 3 Candidates with Scores
        top_candidates = [
            {"type": k, "score": round(v, 4)}
            for k, v in sorted_classes[:3]
        ]

        # -------------------------------------------------------------------
        # Ambiguity and Floor Evaluation
        # -------------------------------------------------------------------
        needs_review = False
        final_type = top_class
        final_conf = top_conf
        review_reasons = []

        # Rule: If confidence is below review floor -> flag for review
        if top_conf < min_conf:
            needs_review = True
            review_reasons.append(f"Top candidate '{top_class}' confidence ({top_conf:.2f}) below threshold ({min_conf:.2f}).")
            if top_conf < 0.25:
                final_type = default_class

        # Rule: If two types are close (top-2 margin rule) -> forces review
        if (top_conf - second_conf) < ambiguity_margin:
            needs_review = True
            review_reasons.append(
                f"Classification margin between top 2 candidates is close (< {ambiguity_margin:.2f}): "
                f"'{top_class}' ({top_conf:.2f}) vs '{second_class}' ({second_conf:.2f})."
            )

        return {
            "type": final_type,
            "type_confidence": round(final_conf, 4),
            "top_candidates": top_candidates,
            "top_candidate": top_class,
            "scores": {k: round(v, 4) for k, v in sorted_classes},
            "needs_review": needs_review,
            "review_reasons": review_reasons,
        }

