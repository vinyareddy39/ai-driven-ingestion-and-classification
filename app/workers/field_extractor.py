import re
import difflib
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, Optional, List

CLASS_SCHEMAS: Dict[str, Dict[str, Dict[str, str]]] = {
    "invoice": {
        "invoice_number": {"type": "id", "desc": "invoice number billing identifier folio document code"},
        "invoice_date": {"type": "date", "desc": "invoice date billing date issue date issued timestamp"},
        "total_amount": {"type": "float", "desc": "total amount balance due grand total remittance payable"},
        "vendor_name": {"type": "string", "desc": "vendor name supplier organization remit to company"}
    },
    "contract": {
        "contract_id": {"type": "id", "desc": "contract id agreement reference covenant tracking code instrument"},
        "effective_date": {"type": "date", "desc": "effective date commencement execution date"},
        "parties": {"type": "string", "desc": "contracting legal parties principal signatories counterparties"}
    },
    "kyc_form": {
        "customer_name": {"type": "string", "desc": "customer name applicant complete name subject legal identity name"},
        "date_of_birth": {"type": "date", "desc": "date of birth birthdate birth registration dob"},
        "id_number": {"type": "id", "desc": "passport serial national passport no identification number travel document"}
    },
    "bank_statement": {
        "account_number": {"type": "id", "desc": "account reference code settlement account number depository ledger"},
        "statement_period": {"type": "string", "desc": "statement period reporting interval accounting timeframe cycle"},
        "closing_balance": {"type": "float", "desc": "closing balance ending depository balance final balance summary"}
    },
    "medical_report": {
        "patient_id": {"type": "id", "desc": "patient id clinical identifier medical record number mrn"},
        "diagnosis": {"type": "string", "desc": "primary clinical findings diagnosis assessment impression evaluation"},
        "doctor_name": {"type": "string", "desc": "doctor name attending clinician lead physician practitioner"}
    },
    "purchase_order": {
        "po_number": {"type": "id", "desc": "po reference number order slip code procurement tracking"},
        "order_date": {"type": "date", "desc": "order date issuance date requisition date purchase date"},
        "total_amount": {"type": "float", "desc": "total purchase value aggregate commitment authorized requisition sum"},
        "vendor_name": {"type": "string", "desc": "vendor name supplier entity authorized vendor organization"}
    },
    "letter": {
        "sender": {"type": "string", "desc": "sender transmitted by originator from dispatched by"},
        "recipient": {"type": "string", "desc": "recipient deliver to recipient to addressee attention"},
        "date": {"type": "date", "desc": "date correspondence date dispatch date notice"},
        "subject": {"type": "string", "desc": "subject subject header re reference regarding memorandum"}
    },
    "claim_form": {
        "claim_id": {"type": "id", "desc": "claim id claim record id policy claim docket reference"},
        "incident_date": {"type": "date", "desc": "incident date loss occurrence date date of loss"},
        "claimant_name": {"type": "string", "desc": "claimant name claimant full name policyholder claimant"},
        "claim_amount": {"type": "float", "desc": "claim amount claimed compensation total claimed amount settlement demand"}
    }
}


class FieldExtractor(ABC):
    @abstractmethod
    def extract(
        self, ocr_text: str, doc_class: str, schema: Optional[Dict[str, Any]] = None
    ) -> Tuple[Dict[str, Any], Dict[str, float], bool]:
        pass


class SemanticGroundedExtractor(FieldExtractor):
    def __init__(self, fallback_extractor=None):
        self.fallback = fallback_extractor
        self.latency_records = []
        self.grounding_failures = 0
        self.total_extractions = 0

    def _is_grounded(self, val: Any, ocr_text: str) -> bool:
        if val is None:
            return False
        val_str = str(val).strip().lower()
        if not val_str:
            return False
        ocr_lower = ocr_text.lower()
        if val_str in ocr_lower:
            return True
        clean_val = re.sub(r"[\s$,:]", "", val_str)
        clean_ocr = re.sub(r"[\s$,:]", "", ocr_lower)
        if clean_val and clean_val in clean_ocr:
            return True
        try:
            num = float(re.sub(r"[^\d.]", "", val_str))
            if f"{num:.2f}" in ocr_lower or str(int(num)) in ocr_lower:
                return True
        except ValueError:
            pass
        tokens = [t for t in val_str.split() if len(t) > 2]
        if tokens:
            matches = sum(1 for t in tokens if t in ocr_lower)
            if matches / len(tokens) >= 0.70:
                return True
        return False

    def extract(
        self, ocr_text: str, doc_class: str, schema: Optional[Dict[str, Any]] = None
    ) -> Tuple[Dict[str, Any], Dict[str, float], bool]:
        t0 = time.time()
        if schema is None:
            schema = CLASS_SCHEMAS.get(doc_class, {})

        fields: Dict[str, Any] = {}
        confidences: Dict[str, float] = {}

        if not ocr_text or not schema:
            return fields, confidences, False

        # 1. Parse line-based and column-based Key: Value pairs
        lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
        kv_pairs = []
        for line in lines:
            m = re.match(r"^([^:;|~]+?)[:;|~]\s*(.+)$", line)
            if m:
                kv_pairs.append((m.group(1).strip(), m.group(2).strip()))
            sub_pairs = re.findall(r"([A-Za-z /]+)[:]\s*([A-Za-z0-9$. -]+?)(?=[A-Za-z /]+:|$)", line)
            for sp in sub_pairs:
                kv_pairs.append((sp[0].strip(), sp[1].strip()))

        # 2. Match each schema field
        for field_name, spec in schema.items():
            self.total_extractions += 1
            ftype = spec.get("type", "string")
            fdesc = spec.get("desc", field_name)
            desc_tokens = set(fdesc.lower().split() + field_name.split("_"))

            best_val = None
            best_score = 0.0

            for k_text, v_text in kv_pairs:
                k_clean = k_text.lower()
                k_tokens = set(re.findall(r"\b[a-z]{3,}\b", k_clean))
                overlap = len(desc_tokens.intersection(k_tokens))
                ratio = difflib.SequenceMatcher(None, field_name.replace("_", " "), k_clean).ratio()
                score = (overlap * 0.45) + (ratio * 0.55)

                # Type-specific validation
                if ftype == "float":
                    # Must contain a dollar sign or decimal point or amount number, and not be an account/tax id
                    if "-" in v_text and not "$" in v_text:
                        continue
                    num_m = re.search(r"\$?\s*([0-9]+(?:\.[0-9]{2}))", v_text)
                    if not num_m:
                        continue
                elif ftype == "date":
                    if not re.search(r"\b\d{4}[-/.]\d{2}[-/.]\d{2}\b|\b\d{2}[-/.]\d{2}[-/.]\d{4}\b", v_text):
                        continue
                elif ftype == "id":
                    if not re.search(r"\b[A-Za-z0-9-]{4,25}\b", v_text):
                        continue

                if score > best_score:
                    best_score = score
                    best_val = v_text

            parsed_val = None
            if best_val and best_score >= 0.40:
                # Clean adjacent labels
                next_lbl = re.search(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*:", best_val)
                if next_lbl:
                    best_val = best_val[:next_lbl.start()].strip()

                if ftype == "float":
                    m = re.search(r"\$?\s*([0-9]+(?:\.[0-9]{2}))", best_val.replace(",", ""))
                    if m:
                        try:
                            parsed_val = float(m.group(1))
                        except ValueError:
                            pass
                elif ftype == "date":
                    m = re.search(r"\b(\d{4}[-/.]\d{2}[-/.]\d{2})\b|\b(\d{2}[-/.]\d{2}[-/.]\d{4})\b", best_val)
                    if m:
                        d_str = m.group(1) or m.group(2)
                        parsed_val = d_str.replace("/", "-").replace(".", "-")
                elif ftype == "id":
                    m = re.search(r"\b([A-Za-z0-9-]{4,25})\b", best_val)
                    if m:
                        parsed_val = m.group(1)
                else:
                    clean_s = re.sub(r"^[^\w]+|[^\w]+$", "", best_val)
                    if len(clean_s) >= 2:
                        parsed_val = clean_s

            if parsed_val is not None:
                if self._is_grounded(parsed_val, ocr_text):
                    fields[field_name] = parsed_val
                    confidences[field_name] = round(min(0.99, max(0.65, best_score)), 2)
                else:
                    self.grounding_failures += 1
                    fields[field_name] = None
                    confidences[field_name] = 0.0
            else:
                fields[field_name] = None
                confidences[field_name] = 0.0

        # Fallback to regex extractor
        if self.fallback:
            missing_fields = [k for k, v in fields.items() if v is None]
            if missing_fields:
                fb_res = self.fallback.extract(ocr_text, doc_class)
                fb_fields = fb_res[0] if isinstance(fb_res, tuple) else fb_res
                for mf in missing_fields:
                    fb_val = fb_fields.get(mf)
                    if fb_val is not None and self._is_grounded(fb_val, ocr_text):
                        fields[mf] = fb_val
                        confidences[mf] = 0.85

        is_valid = all(fields.get(k) is not None for k in schema.keys())
        self.latency_records.append(time.time() - t0)
        return fields, confidences, is_valid
