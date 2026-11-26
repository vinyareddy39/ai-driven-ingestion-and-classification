"""Learned Label & Document Registry.

Manages document types, label normalization, suggestion generation,
and grows dynamically from reviewer corrections without hardcoding.
"""

import os
import re
import yaml
import json
from typing import Dict, List, Any, Optional, Tuple
from collections import Counter, defaultdict


class LearnedRegistry:
    """Config-driven and database-backed registry for document taxonomy and labels."""

    _instance = None

    def __init__(self, config_dir: Optional[str] = None):
        self.config_dir = config_dir or os.path.join(os.path.dirname(__file__), "..", "..", "config")
        self.version = "2.3.0"
        self.taxonomy: Dict[str, Any] = {}
        self.label_registry: Dict[str, List[str]] = defaultdict(list)
        self.canonical_map: Dict[str, str] = {}
        self.reload()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = LearnedRegistry()
        return cls._instance

    def reload(self):
        """Reload taxonomy and routing configuration from YAML files."""
        tax_path = os.path.join(self.config_dir, "taxonomy.yaml")
        if os.path.exists(tax_path):
            try:
                with open(tax_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    self.taxonomy = data.get("taxonomy", {})
            except Exception:
                self.taxonomy = {}

        # Populate initial label registry from taxonomy field_concepts
        for doc_t, t_info in self.taxonomy.items():
            concepts = t_info.get("field_concepts", [])
            for c in concepts:
                norm_lbl = c.replace("_", " ").title()
                if norm_lbl not in self.label_registry[doc_t]:
                    self.label_registry[doc_t].append(norm_lbl)
                # Build canonical map
                clean_k = re.sub(r"[^a-z0-9]", "", norm_lbl.lower())
                self.canonical_map[clean_k] = norm_lbl

        # Also load past corrections from database if accessible
        try:
            from app.models.db import get_db_session, CorrectionModel
            db = get_db_session()
            corrs = db.query(CorrectionModel).all()
            for c in corrs:
                doc_t = (c.doc_type or "unknown").lower()
                lbl = (c.new_label or c.label or "").strip()
                if lbl:
                    norm_lbl = self.normalize_label(lbl, doc_t)
                    if norm_lbl not in self.label_registry[doc_t]:
                        self.label_registry[doc_t].append(norm_lbl)
            db.close()
        except Exception:
            pass

    def record_feedback(self, doc_type: str, original_label: str, new_label: str, value: str):
        """Grow registry dynamically when a human reviewer corrects or verifies a label."""
        doc_t = (doc_type or "unknown").lower()
        clean_lbl = new_label.strip()
        if not clean_lbl:
            return

        norm_lbl = self.normalize_label(clean_lbl, doc_t)
        if norm_lbl not in self.label_registry[doc_t]:
            self.label_registry[doc_t].append(norm_lbl)

        clean_k = re.sub(r"[^a-z0-9]", "", norm_lbl.lower())
        self.canonical_map[clean_k] = norm_lbl

    def normalize_label(self, raw_label: str, doc_type: str = "") -> str:
        """Normalize labels so identical concepts share canonical naming."""
        if not raw_label:
            return ""
        s = raw_label.strip()
        # Remove trailing colons, dashes
        s = re.sub(r"[:\-=]+$", "", s).strip()

        # Check canonical mapping (e.g. 'inv #', 'invoice no' -> 'Invoice Number')
        clean_k = re.sub(r"[^a-z0-9]", "", s.lower())
        if clean_k in self.canonical_map:
            return self.canonical_map[clean_k]

        # Common business abbreviations
        abbrev_map = {
            "inv": "Invoice",
            "no": "Number",
            "num": "Number",
            "po": "Purchase Order",
            "qty": "Quantity",
            "amt": "Amount",
            "tot": "Total",
            "bal": "Balance",
            "dt": "Date",
            "desc": "Description",
            "addr": "Address",
            "cust": "Customer",
            "tel": "Phone",
            "ph": "Phone",
            "ssn": "SSN",
            "ein": "EIN",
            "dob": "Date of Birth",
        }
        words = s.split()
        norm_words = []
        for w in words:
            w_lower = re.sub(r"[^a-z0-9]", "", w.lower())
            if w_lower in abbrev_map:
                norm_words.append(abbrev_map[w_lower])
            else:
                norm_words.append(w.capitalize())
        
        normalized = " ".join(norm_words)
        self.canonical_map[clean_k] = normalized
        return normalized

    def generate_label_for_detail(
        self,
        value: str,
        context_before: str = "",
        context_after: str = "",
        position_style: Optional[Dict[str, Any]] = None,
        doc_summary: str = "",
        doc_type: str = "unknown",
    ) -> Dict[str, Any]:
        """Generate a short noun phrase (1-4 words) describing a detail when no printed label exists.
        
        Returns:
            suggested_label: str
            alternatives: List[str] (up to 2)
            label_confidence: float
            reason: str
            source: 'generated'
        """
        val_clean = str(value).strip()
        ctx_before_low = context_before.lower()
        ctx_after_low = context_after.lower()
        combined_ctx = f"{ctx_before_low} {val_clean.lower()} {ctx_after_low}"
        style = position_style or {}
        doc_t = (doc_type or "unknown").lower()
        registry_labels = self.label_registry.get(doc_t, []) + self.label_registry.get("unknown", [])

        suggested = ""
        alternatives = []
        confidence = 0.50
        reason = "Deduced from value pattern and layout position"

        # 1. Currency / Amount
        if re.search(r"^\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})?$", val_clean) or "total" in combined_ctx or "amount" in combined_ctx:
            if "total" in combined_ctx:
                suggested = "Total Amount"
                alternatives = ["Subtotal", "Balance Due"]
                confidence = 0.92
                reason = "Currency amount following total summary context"
            elif "subtotal" in combined_ctx:
                suggested = "Subtotal"
                alternatives = ["Total Amount", "Net Amount"]
                confidence = 0.88
                reason = "Amount preceding subtotal marker"
            elif "tax" in combined_ctx:
                suggested = "Tax Amount"
                alternatives = ["Total Amount", "Duty Amount"]
                confidence = 0.87
                reason = "Currency following tax rate context"
            else:
                suggested = "Amount"
                alternatives = ["Total Amount", "Unit Price"]
                confidence = 0.78
                reason = "Numeric currency format"

        # 2. Date Pattern
        elif re.search(r"\b(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})\b", val_clean):
            if "due" in combined_ctx:
                suggested = "Due Date"
                alternatives = ["Invoice Date", "Payment Date"]
                confidence = 0.93
                reason = "Date adjacent to payment due term"
            elif "effective" in combined_ctx or "agreement" in combined_ctx:
                suggested = "Effective Date"
                alternatives = ["Execution Date", "Document Date"]
                confidence = 0.90
                reason = "Date in agreement execution clause"
            elif "birth" in combined_ctx or "dob" in combined_ctx:
                suggested = "Date of Birth"
                alternatives = ["Issue Date", "Expiry Date"]
                confidence = 0.94
                reason = "Date adjacent to personal identity markers"
            else:
                suggested = "Document Date"
                alternatives = ["Date", "Issue Date"]
                confidence = 0.82
                reason = "Calendar date in document body"

        # 3. Document Identifier / Code
        elif re.search(r"^[A-Z0-9]{3,}-[A-Z0-9]{3,}(?:-[A-Z0-9]+)?$", val_clean) or re.search(r"^(INV|PO|NDA|EMP|MEDU|CLM|TCK|EXP|LSE)-\d+", val_clean):
            prefix = val_clean.split("-")[0].upper()
            if prefix in ["INV", "INVOICE"]:
                suggested = "Invoice Number"
                alternatives = ["Reference Number", "Order Number"]
                confidence = 0.96
                reason = "Alphanumeric invoice identifier structure"
            elif prefix in ["PO"]:
                suggested = "Purchase Order Number"
                alternatives = ["Order Reference", "Requisition Number"]
                confidence = 0.95
                reason = "PO identifier code"
            elif prefix in ["CLM"]:
                suggested = "Claim Number"
                alternatives = ["Policy Number", "Incident Reference"]
                confidence = 0.94
                reason = "Claim alphanumeric code"
            elif prefix in ["TCK"]:
                suggested = "Ticket Number"
                alternatives = ["Case Reference", "Inquiry ID"]
                confidence = 0.92
                reason = "Service ticket tracking format"
            else:
                suggested = "Reference Identifier"
                alternatives = ["Tracking Number", "Document ID"]
                confidence = 0.85
                reason = "Hyphenated business reference code"

        # 4. Social Security Number or EIN
        elif re.search(r"^\d{3}-\d{2}-\d{4}$", val_clean):
            suggested = "Social Security Number"
            alternatives = ["Tax ID", "National ID"]
            confidence = 0.98
            reason = "Standard 9-digit SSN format"
        elif re.search(r"^\d{2}-\d{7}$", val_clean):
            suggested = "Employer Identification Number"
            alternatives = ["Tax ID", "Federal EIN"]
            confidence = 0.96
            reason = "Standard 9-digit EIN format"

        # 5. Prominent Title / Company Name
        elif style.get("font_size", 10.0) >= 14.0 or style.get("is_bold") and style.get("y", 100) < 150:
            suggested = "Issuer Name"
            alternatives = ["Document Title", "Organization"]
            confidence = 0.86
            reason = "Prominent bold text at top of document"

        # 6. Email or Phone
        elif "@" in val_clean and "." in val_clean:
            suggested = "Contact Email"
            alternatives = ["Customer Email", "Recipient Email"]
            confidence = 0.95
            reason = "Standard email address structure"
        elif re.search(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", val_clean):
            suggested = "Phone Number"
            alternatives = ["Contact Phone", "Mobile Number"]
            confidence = 0.92
            reason = "Telephone number format"

        # 7. Fallback to similar Registry Label if available
        else:
            for reg_l in registry_labels:
                if reg_l.lower() in combined_ctx:
                    suggested = reg_l
                    confidence = 0.72
                    reason = f"Matched concept in learned registry for {doc_t}"
                    break

        if not suggested:
            # Low confidence weak guess -> will be presented with placeholder 'needs label'
            words = val_clean.split()
            suggested = "Detail"
            alternatives = ["Value", "Specification"]
            confidence = 0.45
            reason = "Insufficient contextual cues to establish definitive label"

        return {
            "suggested_label": suggested,
            "alternatives": alternatives[:2],
            "label_confidence": round(confidence, 4),
            "reason": reason,
            "source": "generated",
        }
