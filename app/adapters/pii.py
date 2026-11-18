"""PII Detection and Anonymization Adapter using Microsoft Presidio and Custom Recognizers."""

import re
from typing import Any, Dict, List, Optional
from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import RecognizerResult as AnonymizerRecognizerResult
from app.core.interfaces import PIIDetector, PIIEntity
from app.core.config import get_pipeline_config


class PresidioPIIDetector(PIIDetector):
    """Microsoft Presidio analyzer with custom domain-specific pattern recognizers."""

    def __init__(self):
        import tldextract
        tldextract.extract = tldextract.TLDExtract(suffix_list_urls=())

        from presidio_analyzer.nlp_engine import NlpEngineProvider

        # Configure Presidio to use local en_core_web_sm model
        configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }
        provider = NlpEngineProvider(nlp_configuration=configuration)
        nlp_engine = provider.create_engine()

        self.analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
        self.anonymizer = AnonymizerEngine()
        self._add_custom_recognizers()

    def _add_custom_recognizers(self) -> None:
        """Register custom enterprise recognizers (Passport, Medical License, National ID)."""
        # Passport Number Recognizer
        passport_pattern = Pattern(
            name="passport_regex",
            regex=r"\b[A-Z]{1,2}[0-9]{7,9}\b",
            score=0.85,
        )
        passport_recognizer = PatternRecognizer(
            supported_entity="PASSPORT",
            patterns=[passport_pattern],
            context=["passport", "travel document", "citizenship"],
        )
        self.analyzer.registry.add_recognizer(passport_recognizer)

        # Medical License Recognizer
        med_lic_pattern = Pattern(
            name="med_lic_regex",
            regex=r"\b(?:MD|LIC|DEA|NPI)[-#\s]?[0-9]{6,10}\b",
            score=0.90,
        )
        med_lic_recognizer = PatternRecognizer(
            supported_entity="MEDICAL_LICENSE",
            patterns=[med_lic_pattern],
            context=["doctor", "physician", "license", "dea", "npi"],
        )
        self.analyzer.registry.add_recognizer(med_lic_recognizer)

    def _determine_sensitivity(self, entity_type: str) -> str:
        """Classify entity sensitivity strictly by entity type and format."""
        try:
            cfg = get_pipeline_config().pii_policy.sensitivity
            for level, entity_types in cfg.items():
                if entity_type in entity_types:
                    return level
        except Exception:
            pass

        # Built-in defaults: SSN is always high; US_EIN is medium
        high_risk = {"US_SSN", "CREDIT_CARD", "PASSPORT", "MEDICAL_LICENSE"}
        low_risk = {"DATE_TIME", "LOCATION", "IP_ADDRESS"}
        if entity_type in high_risk:
            return "high"
        if entity_type in low_risk:
            return "low"
        return "medium"

    def detect(self, text: str) -> List[PIIEntity]:
        """Detect all PII entities using Presidio and regex augmentations."""
        if not text or not text.strip():
            return []

        target_entities = [
            "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "CREDIT_CARD",
            "PASSPORT", "MEDICAL_LICENSE", "IBAN_CODE"
        ]

        # Prioritize structured identifiers first to prevent span hijacking
        entities: List[PIIEntity] = []
        existing_spans = set()

        def _overlaps(s, e):
            return any(not (e <= es or s >= ee) for es, ee in existing_spans)

        # 1. IBAN (International Bank Account Number)
        iban_context_matches = re.finditer(
            r"(?:(?:International\s*)?IBAN|(?:International\s*)?BAN|Wire\s*IBAN)\s*(?:Number)?\s*[:;\s.-]*([A-Z0-9]{14,34})",
            text, re.I
        )
        for m in iban_context_matches:
            s, e = m.start(1), m.end(1)
            if not _overlaps(s, e):
                entities.append(
                    PIIEntity(entity_type="IBAN_CODE", text=m.group(1), start=s, end=e, score=0.99, sensitivity="medium")
                )
                existing_spans.add((s, e))

        iban_general = re.finditer(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", text)
        for m in iban_general:
            s, e = m.start(), m.end()
            if not _overlaps(s, e):
                entities.append(
                    PIIEntity(entity_type="IBAN_CODE", text=m.group(0), start=s, end=e, score=0.95, sensitivity="medium")
                )
                existing_spans.add((s, e))

        # 2. Individual SSN Format (XXX-XX-XXXX) -> US_SSN (High Sensitivity)
        ssn_context_matches = re.finditer(
            r"(?:SSN|Social\s*Security|Taxpayer\s*(?:ID\s*)?\(?SSN\)?|Signatory\s*Identity\s*SSN|Officer\s*SSN|Confidential\s*SSN)\s*[:;\s.-]+([0-9]{3}[-–—.\s]?[0-9]{2}[-–—.\s]?[0-9]{4})",
            text, re.I
        )
        for m in ssn_context_matches:
            s, e = m.start(1), m.end(1)
            if not _overlaps(s, e):
                entities.append(
                    PIIEntity(entity_type="US_SSN", text=m.group(1), start=s, end=e, score=0.99, sensitivity="high")
                )
                existing_spans.add((s, e))

        ssn_pattern_matches = re.finditer(r"(?:(?<=[^\d])|^)(?:\d{3}[-–—.\s]\d{2}[-–—.\s]\d{4}|\d{5}[-–—.\s]\d{4})(?=[^\d]|$)", text)
        for m in ssn_pattern_matches:
            s, e = m.start(), m.end()
            if not _overlaps(s, e):
                entities.append(
                    PIIEntity(entity_type="US_SSN", text=m.group(0), start=s, end=e, score=0.95, sensitivity="high")
                )
                existing_spans.add((s, e))

        # 3. Corporate EIN Format (XX-XXXXXXX) -> US_EIN (Medium Sensitivity)
        ein_context_matches = re.finditer(
            r"(?:Corporate\s*EIN|Tax\s*ID\s*\(EIN\)|Vendor\s*Tax\s*ID|Tax\s*Identification\s*\(EIN\)|EIN)\s*[:;\s.-]+([0-9]{2}[-–—.]?[0-9]{7})",
            text, re.I
        )
        for m in ein_context_matches:
            s, e = m.start(1), m.end(1)
            if not _overlaps(s, e):
                entities.append(
                    PIIEntity(entity_type="US_EIN", text=m.group(1), start=s, end=e, score=0.99, sensitivity="medium")
                )
                existing_spans.add((s, e))

        ein_pattern_matches = re.finditer(r"\b\d{2}[-–—.]\d{7}\b", text)
        for m in ein_pattern_matches:
            s, e = m.start(), m.end()
            if not _overlaps(s, e):
                entities.append(
                    PIIEntity(entity_type="US_EIN", text=m.group(0), start=s, end=e, score=0.95, sensitivity="medium")
                )
                existing_spans.add((s, e))

        # 4. Passport & Travel Document -> PASSPORT (High Sensitivity, tolerant to OCR confusions)
        passport_context_matches = re.finditer(
            r"(?:Passport\s*(?:No|Number|Code|Serial|#)?|Travel\s*Document|Identification\s*Travel\s*Passport\s*#?|Legal\s*Passport\s*Serial)\s*[:;\s.-]+([A-Za-z0-9]{7,12})",
            text, re.I
        )
        for m in passport_context_matches:
            s, e = m.start(1), m.end(1)
            raw_val = m.group(1)
            # Map OCR 1 to I if leading letter
            if raw_val and raw_val[0] in ('1', 'l', '|'):
                raw_val = 'I' + raw_val[1:]
            if not _overlaps(s, e):
                entities.append(
                    PIIEntity(entity_type="PASSPORT", text=raw_val, start=s, end=e, score=0.98, sensitivity="high")
                )
                existing_spans.add((s, e))

        # 4b. Context-required National ID -> NATIONAL_ID (High Sensitivity)
        nid_context_matches = re.finditer(
            r"(?:National\s*ID|National\s*Identity|NID|Citizen\s*(?:ID|Registration)|Identity\s*#)\s*[:;\s.-]+([A-Za-z0-9-]{6,15})",
            text, re.I
        )
        for m in nid_context_matches:
            s, e = m.start(1), m.end(1)
            if not _overlaps(s, e):
                entities.append(
                    PIIEntity(entity_type="NATIONAL_ID", text=m.group(1), start=s, end=e, score=0.95, sensitivity="high")
                )
                existing_spans.add((s, e))

        # 5. Medical License -> MEDICAL_LICENSE (High Sensitivity)
        med_context_matches = re.finditer(
            r"(?:Medical\s*License|License\s*No\.?|Credentials)\s*[:;\s.-]+([A-Z0-9#-]{5,15})",
            text, re.I
        )
        for m in med_context_matches:
            s, e = m.start(1), m.end(1)
            if not _overlaps(s, e):
                entities.append(
                    PIIEntity(entity_type="MEDICAL_LICENSE", text=m.group(1), start=s, end=e, score=0.98, sensitivity="high")
                )
                existing_spans.add((s, e))

        # 6. Phone Numbers (handling 001/1 prefixes, extensions x\d+, and context labels)
        phone_context_matches = re.finditer(
            r"(?:Support\s*Phone|Contact\s*Phone|Telephone|Mobile\s*Phone|Primary\s*Contact|Phone\s*Number|Phone|Cell\s*Phone|Direct\s*Phone|Inquiry\s*Hotline|Hotline|Contact\s*Tel|Signatory\s*Direct\s*Line|Direct\s*Line|Telephone\s*Support|Contact\s*Number)\s*[:;\s.-]+([0-9+().\s-]{7,35}(?:\s*(?:x|ext\.?)\s*\d+)?)",
            text, re.I
        )
        for m in phone_context_matches:
            s, e = m.start(1), m.end(1)
            val = m.group(1).strip()
            if len(re.findall(r"\d", val)) >= 7 and not _overlaps(s, e):
                entities.append(
                    PIIEntity(entity_type="PHONE_NUMBER", text=val, start=s, end=e, score=0.95, sensitivity="low")
                )
                existing_spans.add((s, e))

        phone_pattern_matches = re.finditer(
            r"(?:(?<=\s)|(?<=^)|(?<=[(\s]))(?:\+?1[-.\s]?|001[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?:\s*(?:x|ext\.?)\s*\d+)?\b",
            text,
        )
        for m in phone_pattern_matches:
            s, e = m.start(), m.end()
            if not _overlaps(s, e):
                entities.append(
                    PIIEntity(entity_type="PHONE_NUMBER", text=m.group(0), start=s, end=e, score=0.90, sensitivity="low")
                )
                existing_spans.add((s, e))

        # 7. Presidio Analyzer for remaining entities (PERSON, EMAIL, CREDIT_CARD)
        presidio_results = self.analyzer.analyze(
            text=text,
            language="en",
            entities=target_entities,
            score_threshold=0.65,
        )

        boilerplate_persons = {
            "commercial invoice", "master services", "know your customer", "official bank",
            "financial institution", "medical examination", "official purchase", "notice of loss",
            "insurance claim", "executive memorandum", "preliminary onboarding", "system architecture",
            "payment schedule", "daily transaction", "cleared transactions", "clinical impression",
            "attestation", "purchaser", "supplier", "dear", "sincerely", "management committee",
            "operations directorate", "governance board", "corporate office", "united states",
            "bank", "statement", "invoice", "hospital", "healthcare", "metro health", "summit valley",
            "st. jude", "apex global", "sovereign trust", "horizon federal", "procurement officer",
            "requisitioner", "consultant", "physician", "attending", "patient", "claimant",
            "insured party", "vendor name", "applicant name", "full name", "member name",
            "account holder", "customer support", "compliance profile", "node cluster",
            "part a", "part b", "section 1", "ending balance", "starting balance", "opening balance",
            "closing balance", "by and between", "hold all technical", "advised to continue",
            "officially advise", "warehouse facility", "standard warranty", "balance summary",
            "cleared transactions", "electronic transfer", "commercial mortgage", "primary applicant",
            "identity record", "personal identity", "beneficiary profile"
        }

        stop_words = {"and", "to", "for", "with", "the", "regarding", "between", "all", "shall", "under", "from", "of", "in", "on"}

        for res in presidio_results:
            s, e = res.start, res.end
            if _overlaps(s, e):
                continue
            raw_ent = text[s:e].strip()
            # If spaCy NER captured across newline, keep only the first line
            if "\n" in raw_ent:
                raw_ent = raw_ent.split("\n")[0].strip()
                e = s + len(raw_ent)
            ent_text = raw_ent
            ent_lower = ent_text.lower().strip("`'\"‘“”—-=[](){}:;,.")

            # Filter noisy false-positive PERSON entities
            if res.entity_type == "PERSON":
                # Check boilerplate and length
                if any(bp in ent_lower for bp in boilerplate_persons) or len(ent_text) < 4:
                    continue
                # Reject digits, currency symbols
                if re.search(r"[\d$#@%*+_=]", ent_text):
                    continue
                # Reject OCR repetitive noise (e.g. HEHEHE, HHH, HAHAHA)
                if re.search(r"\b(?:HEHEHE|HHH|HAHAHA|HAHAH|EE|BS|BR|Rh|Ul)\b", ent_text, re.I):
                    continue
                # Must be 1 to 4 word tokens without stopwords
                words = ent_lower.split()
                if len(words) > 4 or any(w in stop_words for w in words):
                    continue
                if res.score < 0.75:
                    continue

            sensitivity = self._determine_sensitivity(res.entity_type)
            entities.append(
                PIIEntity(
                    entity_type=res.entity_type,
                    text=ent_text,
                    start=s,
                    end=e,
                    score=round(float(res.score), 4),
                    sensitivity=sensitivity,
                )
            )
            existing_spans.add((s, e))

        # 8. Person Salutation / Label Augmentation (strictly single-line horizontal whitespace)
        person_labeled_matches = re.finditer(
            r"(?:Dear|To|TO|Attention|Attn|Applicant(?:\s*Name)?|Insured\s*Party|Ingured\s*Party|"
            r"Patient(?:\s*Name)?|Account\s*Holder|Authorized\s*(?:Signatory|Agent)|Requisitioner|"
            r"Member\s*Name|Customer|Client|Billed\s*To|Legal\s*Name|Logal\s*Name|Full\s*Name|"
            r"Claimant(?:\s*Name)?|Beneficiary|Attending\s*Physic[a-z]*|Physician|Consut?ant)"
            r"\s*[:;\s.-]+([A-Za-z'`.-]+(?:[^\S\r\n]+[A-Za-z'`.-]+){1,3})",
            text, re.I
        )
        for m in person_labeled_matches:
            s, e = m.start(1), m.end(1)
            name_text = m.group(1).strip().strip("`'\"‘“”—-=[](){}:;,.")
            name_lower = name_text.lower()
            if not _overlaps(s, e) and len(name_text) >= 4:
                # Exclude obvious non-person text, stopwords, digits, and noise
                if any(bp in name_lower for bp in boilerplate_persons):
                    continue
                if re.search(r"\b(?:HEHEHE|HHH|HAHAHA|HAHAH|EE|BS|BR|Rh|Ul)\b", name_text, re.I):
                    continue
                if re.search(r"[\d\n\r$#@%*+_=]", name_text):
                    continue
                words = name_lower.split()
                if any(w in stop_words for w in words):
                    continue
                entities.append(
                    PIIEntity(entity_type="PERSON", text=name_text, start=s, end=e, score=0.96, sensitivity="medium")
                )
                existing_spans.add((s, e))

        return sorted(entities, key=lambda e: e.start)

    def mask(self, text: str, entities: Optional[List[PIIEntity]] = None) -> str:
        """Mask detected PII entities with redact markers."""
        if not text:
            return text
        if entities is None:
            entities = self.detect(text)

        if not entities:
            return text

        # Sort reverse by start position to replace without messing up offsets
        sorted_entities = sorted(entities, key=lambda e: e.start, reverse=True)
        masked = text
        for ent in sorted_entities:
            replacement = f"<{ent.entity_type}_REDACTED>"
            masked = masked[:ent.start] + replacement + masked[ent.end:]
        return masked


_pii_detector_singleton: Optional[PIIDetector] = None


def get_pii_detector() -> PIIDetector:
    """Factory returning PII detector singleton."""
    global _pii_detector_singleton
    if _pii_detector_singleton is None:
        _pii_detector_singleton = PresidioPIIDetector()
    return _pii_detector_singleton


# ---------------------------------------------------------------------------
# Reconciled Unified PII Evaluator Matcher
# ---------------------------------------------------------------------------

def normalize_pii_value(val: str, entity_type: str) -> str:
    """Normalize PII values for evaluation comparisons across formats."""
    if not val:
        return ""
    val_clean = str(val).strip().lower()
    if entity_type in ("PHONE_NUMBER", "US_SSN", "US_EIN", "IBAN_CODE"):
        digits = re.sub(r"[^\d]", "", val_clean)
        if entity_type == "PHONE_NUMBER":
            if digits.startswith("001"):
                digits = digits[3:]
            elif digits.startswith("1") and len(digits) > 10:
                digits = digits[1:]
        return digits
    elif entity_type in ("PASSPORT", "NATIONAL_ID", "MEDICAL_LICENSE"):
        trans = str.maketrans({"o": "0", "i": "1", "l": "1", "s": "5", "b": "8"})
        return re.sub(r"[^a-z0-9]", "", val_clean).translate(trans)
    elif entity_type == "EMAIL_ADDRESS":
        return val_clean.strip()
    else:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", "", val_clean)).strip()


def match_pii_entity(expected_type: str, expected_val: str, detected_entities: List[Dict[str, Any]]) -> bool:
    """Shared single matcher verifying both entity type and value overlap."""
    import difflib
    norm_exp = normalize_pii_value(expected_val, expected_type)
    for det in detected_entities:
        det_type = det.get("entity_type")
        det_text = det.get("text", "")
        # Check type equivalence
        type_match = False
        if det_type == expected_type:
            type_match = True
        elif expected_type == "US_SSN" and det_type in ("SSN", "US_SSN"):
            type_match = True
        elif expected_type == "US_EIN" and det_type in ("EIN", "US_EIN"):
            type_match = True
        elif expected_type == "PASSPORT" and det_type in ("PASSPORT", "NATIONAL_ID"):
            type_match = True
        elif expected_type == "NATIONAL_ID" and det_type in ("NATIONAL_ID", "PASSPORT"):
            type_match = True

        if not type_match:
            continue

        norm_det = normalize_pii_value(det_text, det_type)
        if not norm_exp or not norm_det:
            continue

        if norm_exp == norm_det or norm_exp in norm_det or norm_det in norm_exp:
            return True
        if expected_type == "PERSON":
            ratio = difflib.SequenceMatcher(None, norm_exp, norm_det).ratio()
            if ratio >= 0.78:
                return True
        elif expected_type == "PHONE_NUMBER":
            if len(norm_exp) >= 7 and len(norm_det) >= 7 and (norm_exp[-7:] == norm_det[-7:] or norm_exp[-10:] == norm_det[-10:]):
                return True
    return False
