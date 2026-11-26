"""Config-Driven Sensitive Data Detector.

Evaluates patterns, mathematical checksums (Luhn, Mod97, Verhoeff),
and surrounding label context to avoid false positives and calculate real confidence.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from app.core.config_loader import ConfigLoader


# ---------------------------------------------------------------------------
# Checksum Algorithms
# ---------------------------------------------------------------------------

def validate_luhn(card_number: str) -> bool:
    """Validate credit card number using Luhn formula (ISO/IEC 7812)."""
    digits = [int(c) for c in card_number if c.isdigit()]
    if len(digits) < 12 or len(digits) > 19:
        return False
    checksum = 0
    reverse_digits = digits[::-1]
    for i, d in enumerate(reverse_digits):
        if i % 2 == 1:
            doubled = d * 2
            checksum += doubled - 9 if doubled > 9 else doubled
        else:
            checksum += d
    return checksum % 10 == 0


def validate_mod97(iban: str) -> bool:
    """Validate IBAN using ISO 7064 Mod 97-10."""
    clean = re.sub(r"\s+", "", iban).upper()
    if len(clean) < 14 or len(clean) > 34:
        return False
    # Move first 4 characters to the end
    rearranged = clean[4:] + clean[:4]
    # Replace letters with digits: A=10, B=11, ... Z=35
    digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    try:
        return int(digits) % 97 == 1
    except ValueError:
        return False


def validate_verhoeff(num_str: str) -> bool:
    """Validate Aadhaar 12-digit number using Verhoeff check digit algorithm."""
    clean = re.sub(r"\s+", "", num_str)
    if not clean.isdigit() or len(clean) != 12:
        return False

    d_table = [
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
        [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
        [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
        [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
        [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
        [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
        [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
        [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
        [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
    ]
    p_table = [
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
        [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
        [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
        [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
        [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
        [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
        [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
    ]
    c = 0
    for i, item in enumerate(reversed(clean)):
        c = d_table[c][p_table[i % 8][int(item)]]
    return c == 0


CHECKSUM_VALIDATORS = {
    "luhn": validate_luhn,
    "mod97": validate_mod97,
    "verhoeff": validate_verhoeff,
}


# ---------------------------------------------------------------------------
# Sensitive Data Detector
# ---------------------------------------------------------------------------

class ConfigDrivenSensitiveDetector:
    """Finds PII and sensitive entities in document text using config-driven rules."""

    def __init__(self, config_loader: Optional[ConfigLoader] = None):
        self.loader = config_loader or ConfigLoader.get_instance()

    def _mask_value(self, val: str, mask_format: str, detector_type: str) -> str:
        """Format masked representation based on detector config."""
        clean_val = val.strip()
        last4 = clean_val[-4:] if len(clean_val) >= 4 else clean_val
        first4 = clean_val[:4] if len(clean_val) >= 4 else clean_val

        if "{last4}" in mask_format and "{first4}" in mask_format:
            return mask_format.replace("{first4}", first4).replace("{last4}", last4)
        elif "{last4}" in mask_format:
            return mask_format.replace("{last4}", last4)
        elif "{user_initial}" in mask_format and "@" in clean_val:
            parts = clean_val.split("@")
            user = parts[0]
            domain = parts[1] if len(parts) > 1 else ""
            user_init = user[0] if user else "u"
            return mask_format.replace("{user_initial}", user_init).replace("{domain}", domain)
        elif "{user_initial}" in mask_format:
            words = clean_val.split()
            initials = "".join(w[0] for w in words if w)
            return mask_format.replace("{user_initial}", initials[:1])
        return mask_format

    def detect_in_field(
        self,
        label: str,
        value: str,
        page: int = 1,
        bbox: Optional[List[float]] = None,
    ) -> List[Dict[str, Any]]:
        """Detect sensitive findings in an extracted label-value pair."""
        findings = []
        detectors = self.loader.detectors
        label_lower = label.lower().strip()
        val_clean = value.strip()

        for det_key, det_cfg in detectors.items():
            pattern_str = det_cfg.get("pattern")
            if not pattern_str:
                continue

            try:
                matches = list(re.finditer(pattern_str, val_clean, re.IGNORECASE))
            except re.error:
                continue

            for match in matches:
                matched_text = match.group(0)

                # 1. Checksum validation
                checksum_type = det_cfg.get("checksum", "none")
                if checksum_type in CHECKSUM_VALIDATORS:
                    validator = CHECKSUM_VALIDATORS[checksum_type]
                    if not validator(matched_text):
                        # Failed mathematical checksum -> reject to prevent false positive
                        continue

                # 2. Context evaluation using surrounding label
                base_conf = float(det_cfg.get("base_confidence", 0.85))
                pos_cues = det_cfg.get("positive_context", [])
                neg_cues = det_cfg.get("negative_context", [])

                has_pos_cue = any(cue.lower() in label_lower for cue in pos_cues)
                has_neg_cue = any(cue.lower() in label_lower for cue in neg_cues)

                confidence = base_conf
                needs_review = False

                if has_pos_cue:
                    confidence = min(0.99, confidence + float(det_cfg.get("context_boost", 0.10)))
                elif has_neg_cue:
                    confidence = max(0.10, confidence - float(det_cfg.get("contradiction_penalty", 0.40)))
                    needs_review = True
                elif label_lower:
                    # Unrelated label: slightly reduce confidence and flag for human review
                    confidence = max(0.40, confidence - 0.20)
                    needs_review = True

                # If confidence is too degraded, flag for review rather than blindly accepting
                if confidence < 0.60:
                    needs_review = True

                mask_format = det_cfg.get("mask_format", "[RESTRICTED]")
                masked_val = self._mask_value(matched_text, mask_format, det_cfg.get("type", "SENSITIVE"))

                findings.append({
                    "detector": det_key,
                    "type": det_cfg.get("type", "SENSITIVE"),
                    "name": det_cfg.get("name", det_key),
                    "category": det_cfg.get("category", "PII"),
                    "sensitivity": det_cfg.get("sensitivity", "medium"),
                    "raw_value": matched_text,
                    "masked_value": masked_val,
                    "confidence": round(confidence, 4),
                    "needs_review": needs_review,
                    "location": {
                        "page": page,
                        "bbox": bbox,
                        "label": label,
                        "start": match.start(),
                        "end": match.end(),
                    },
                })

        return findings

    def get_detector_count(self) -> int:
        return len(self.loader.detectors)

    def detect_in_document(
        self,
        text: str,
        fields: List[Dict[str, Any]],
        table_rows: Optional[List[Dict[str, Any]]] = None,
        text_blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Run all detectors across fields, table rows, paragraphs, and raw document text."""
        all_findings = []
        seen_spans = set()
        detectors = self.loader.detectors
        detector_count = len(detectors)

        # 1. Structured fields
        for fld in fields:
            lbl = fld.get("label", "")
            val = str(fld.get("value", ""))
            page = fld.get("page", 1)
            bbox = fld.get("bbox")
            field_findings = self.detect_in_field(lbl, val, page=page, bbox=bbox)
            for ff in field_findings:
                span_key = (ff["type"], ff["raw_value"])
                if span_key not in seen_spans:
                    seen_spans.add(span_key)
                    all_findings.append(ff)

        # 2. Table rows (cells)
        if table_rows:
            for r_idx, row in enumerate(table_rows):
                cells_list = row.get("cells") or row.get("columns") or []
                if isinstance(cells_list, list):
                    for cell_val in cells_list:
                        c_val_str = str(cell_val).strip()
                        if not c_val_str:
                            continue
                        cell_findings = self.detect_in_field("table_cell", c_val_str, page=row.get("page", 1))
                        for cf in cell_findings:
                            span_key = (cf["type"], cf["raw_value"])
                            if span_key not in seen_spans:
                                seen_spans.add(span_key)
                                cf["location"]["table_row"] = r_idx
                                all_findings.append(cf)
                elif isinstance(row, dict):
                    for col_name, cell_val in row.items():
                        if col_name in ["confidence", "bbox", "page", "cells", "columns", "row_text"]:
                            continue
                        c_val_str = str(cell_val).strip()
                        if not c_val_str:
                            continue
                        cell_findings = self.detect_in_field(str(col_name), c_val_str, page=row.get("page", 1))
                        for cf in cell_findings:
                            span_key = (cf["type"], cf["raw_value"])
                            if span_key not in seen_spans:
                                seen_spans.add(span_key)
                                cf["location"]["table_row"] = r_idx
                                all_findings.append(cf)

        # 3. Free-text paragraphs / blocks
        if text_blocks:
            for tb in text_blocks:
                tb_text = tb.get("text", "")
                tb_page = tb.get("page", 1)
                for det_key, det_cfg in detectors.items():
                    pattern_str = det_cfg.get("pattern")
                    if not pattern_str:
                        continue
                    for match in re.finditer(pattern_str, tb_text, re.IGNORECASE):
                        m_text = match.group(0)
                        span_key = (det_cfg.get("type", "SENSITIVE"), m_text)
                        if span_key in seen_spans:
                            continue
                        
                        checksum_type = det_cfg.get("checksum", "none")
                        if checksum_type in CHECKSUM_VALIDATORS:
                            if not CHECKSUM_VALIDATORS[checksum_type](m_text):
                                continue

                        conf = float(det_cfg.get("base_confidence", 0.85))
                        mask_format = det_cfg.get("mask_format", "[RESTRICTED]")
                        masked_val = self._mask_value(m_text, mask_format, det_cfg.get("type", "SENSITIVE"))

                        seen_spans.add(span_key)
                        all_findings.append({
                            "detector": det_key,
                            "type": det_cfg.get("type", "SENSITIVE"),
                            "name": det_cfg.get("name", det_key),
                            "category": det_cfg.get("category", "PII"),
                            "sensitivity": det_cfg.get("sensitivity", "medium"),
                            "raw_value": m_text,
                            "masked_value": masked_val,
                            "confidence": round(conf, 4),
                            "needs_review": False,
                            "location": {
                                "page": tb_page,
                                "bbox": tb.get("bbox"),
                                "label": "Paragraph Text",
                                "start": match.start(),
                                "end": match.end(),
                            },
                        })

        # 4. Check full text for any unlabelled standalone sensitive entities
        for det_key, det_cfg in detectors.items():
            pattern_str = det_cfg.get("pattern")
            if not pattern_str:
                continue
            for match in re.finditer(pattern_str, text, re.IGNORECASE):
                matched_text = match.group(0)
                span_key = (det_cfg.get("type", "SENSITIVE"), matched_text)
                if span_key in seen_spans:
                    continue

                checksum_type = det_cfg.get("checksum", "none")
                if checksum_type in CHECKSUM_VALIDATORS:
                    if not CHECKSUM_VALIDATORS[checksum_type](matched_text):
                        continue

                # Context around the match in raw text (30 chars before/after)
                start_ctx = max(0, match.start() - 30)
                end_ctx = min(len(text), match.end() + 30)
                surrounding = text[start_ctx:end_ctx].lower()

                pos_cues = det_cfg.get("positive_context", [])
                neg_cues = det_cfg.get("negative_context", [])
                has_pos = any(c.lower() in surrounding for c in pos_cues)
                has_neg = any(c.lower() in surrounding for c in neg_cues)

                base_conf = float(det_cfg.get("base_confidence", 0.85))
                conf = base_conf
                needs_review = False
                if has_pos:
                    conf = min(0.99, conf + float(det_cfg.get("context_boost", 0.10)))
                elif has_neg:
                    conf = max(0.10, conf - float(det_cfg.get("contradiction_penalty", 0.40)))
                    needs_review = True
                else:
                    conf = max(0.50, conf - 0.15)
                    needs_review = True

                mask_format = det_cfg.get("mask_format", "[RESTRICTED]")
                masked_val = self._mask_value(matched_text, mask_format, det_cfg.get("type", "SENSITIVE"))

                seen_spans.add(span_key)
                all_findings.append({
                    "detector": det_key,
                    "type": det_cfg.get("type", "SENSITIVE"),
                    "name": det_cfg.get("name", det_key),
                    "category": det_cfg.get("category", "PII"),
                    "sensitivity": det_cfg.get("sensitivity", "medium"),
                    "raw_value": matched_text,
                    "masked_value": masked_val,
                    "confidence": round(conf, 4),
                    "needs_review": needs_review,
                    "location": {
                        "page": 1,
                        "bbox": None,
                        "label": "",
                        "start": match.start(),
                        "end": match.end(),
                    },
                })

        return all_findings, detector_count

        return all_findings
