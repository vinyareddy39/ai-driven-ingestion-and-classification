"""Generic Key-Value Extractor.

Parses line-based "Label: value" pairs and maps variant labels
to canonical schema fields using fuzzy string matching and token similarity.
Extracts strictly from the provided text; returns None with confidence 0.0
when a field cannot be located.
"""

import difflib
import re
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_SYNONYMS: Dict[str, Dict[str, List[str]]] = {
    "invoice": {
        "invoice_number": ["invoice number", "invoice no", "inv #", "bill no", "billing ref", "billing identifier", "reference folio", "document no", "invoice #", "inv no"],
        "invoice_date": ["invoice date", "billing date", "date of issue", "issue date", "billing timestamp", "date of invoicing", "issued date", "date"],
        "total_amount": ["total amount", "balance due", "grand total", "total due", "remittance total", "net due", "amount payable", "total"],
        "vendor_name": ["vendor name", "billed by", "supplier name", "vendor organization", "payee / supplier", "payee", "supplier", "remit to", "vendor"],
    },
    "contract": {
        "contract_id": ["contract id", "agreement ref", "contract no", "agreement no", "covenant reference #", "contract tracking code", "instrument number", "contract #", "covenant reference"],
        "effective_date": ["effective date", "commencement date", "execution date", "effective covenant date", "execution date", "date"],
        "parties": ["principal signatories", "counterparties", "engaged parties", "parties", "first party", "party one", "disclosing entity"],
        "party_one": ["party one", "first party", "disclosing entity", "principal signatories", "counterparties", "engaged parties"],
        "party_two": ["party two", "second party", "receiving entity"],
    },
    "kyc_form": {
        "customer_name": ["subject full legal name", "applicant complete name", "full identity name", "customer name", "full name", "legal name", "applicant name", "name"],
        "full_name": ["subject full legal name", "applicant complete name", "full identity name", "customer name", "full name", "legal name", "applicant name", "name"],
        "id_number": ["legal passport serial", "national passport no", "identification travel passport #", "passport #", "passport no", "id number", "document id", "national identity", "national id", "national passport"],
        "date_of_birth": ["birthdate", "birth registration date", "date of birth (dob)", "date of birth", "dob", "birth date"],
        "nationality": ["nationality", "country of citizenship", "citizenship", "nationality attestation"],
    },
    "bank_statement": {
        "account_number": ["account reference code", "depository ledger identifier", "settlement account #", "account number", "acct #", "account no", "acct number"],
        "statement_period": ["reporting interval", "accounting interval", "reporting timeframe", "statement period", "reporting cycle", "period"],
        "opening_balance": ["opening balance", "starting balance", "beginning balance", "initial balance"],
        "closing_balance": ["closing settlement balance", "closing period ledger", "ending depository balance", "closing balance", "ending balance", "final balance"],
    },
    "medical_report": {
        "patient_id": ["patient clinical identifier", "patient id", "medical record #", "patient medical id", "medical record no", "mrn", "patient ref"],
        "diagnosis": ["primary clinical findings", "clinical findings", "primary diagnosis", "clinician evaluation / diagnosis", "assessment / impression", "impression", "diagnosis", "assessment"],
        "doctor_name": ["attending clinician", "lead physician", "attending physician", "practitioner", "doctor", "physician", "provider attestation", "attending"],
        "report_date": ["date of service", "report date", "exam date", "date of consultation", "clinical assessment timestamp", "date"],
    },
    "purchase_order": {
        "po_number": ["po reference no", "po reference #", "reference no", "procurement tracking #", "order slip code", "requisition tracking folio", "po number", "order number", "p.o. #", "po #"],
        "order_date": ["issuance date", "requisition date", "purchase date", "procurement authorization date", "po date", "order date", "date"],
        "po_date": ["issuance date", "requisition date", "purchase date", "procurement authorization date", "po date", "order date", "date"],
        "vendor_name": ["vendor name", "authorized vendor", "supplier entity", "supplier organization", "supplier name", "supplier", "vendor"],
        "total_amount": ["aggregate commitment", "authorized requisition sum", "total purchase value", "aggregate requisition value", "order total", "total cost", "total purchase amount", "total"],
        "order_total": ["aggregate commitment", "authorized requisition sum", "total purchase value", "aggregate requisition value", "order total", "total cost", "total purchase amount", "total"],
    },
    "letter": {
        "sender": ["transmitted by", "originator / from", "from", "sender", "originator", "dispatched by"],
        "recipient": ["deliver to", "recipient / to", "to", "recipient", "addressee"],
        "date": ["dispatch date", "correspondence date", "date", "date of notice"],
        "letter_date": ["dispatch date", "correspondence date", "date", "date of notice"],
        "subject": ["subject header", "re / in reference to", "subject", "re", "subject matter", "regarding"],
    },
    "claim_form": {
        "claim_id": ["policy claim docket", "claim record id", "claim reference #", "claim id", "claim no", "claim #"],
        "incident_date": ["loss occurrence date", "incident date", "date of loss", "date of occurrence"],
        "claimant_name": ["claimant full name", "claimant name", "policyholder / claimant", "claimant", "insured party", "applicant"],
        "claim_amount": ["settlement demand", "claimed compensation", "total claimed amount", "claim amount", "claimed loss amount", "requested amount"],
    },
}

FIELD_SYNONYMS = SCHEMA_SYNONYMS

COLON_RE = re.compile(r'[:;]')

def clean_ocr_field_text(text: Optional[str]) -> Optional[str]:
    """Clean OCR noise and artifacts from extracted textual fields."""
    if not text:
        return None
    val = text.strip()
    val = val.strip("`'\"‘“”—-=[](){}:;,.*")
    val = re.sub(r"\s+", " ", val).strip()
    return val if val else None

def clean_ocr_date(val: Optional[str]) -> Optional[str]:
    """Clean and standardize date strings (YYYY-MM-DD) or date ranges."""
    if not val:
        return None
    val = val.strip().strip("`'\"‘“”—-=[](){}:;,")
    # Date range first
    m_range = re.search(r'(\d{4}[./-]\d{1,2}[./-]\d{1,2}\s*(?:to|-)\s*\d{4}[./-]\d{1,2}[./-]\d{1,2})', val, re.I)
    if m_range:
        return m_range.group(1).strip()
    # Single date
    m = re.search(r"\b(\d{4})[./-](\d{1,2})[./-](\d{1,2})\b", val)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return None

def clean_ocr_amount(val: Optional[str]) -> Optional[float]:
    """Clean monetary amounts with OCR digit confusion tolerance."""
    if not val:
        return None
    val = val.strip().strip("`'\"‘“”—-=[](){}:;,")
    m = re.search(r'[$S§]?\s*([0-9,]+(?:\.[0-9]{2})?)', val)
    if m:
        amt_str = m.group(1).replace(',', '')
        try:
            return float(amt_str)
        except ValueError:
            pass
    trans = str.maketrans({
        'O': '0', 'o': '0',
        'I': '1', 'l': '1', '|': '1',
        'S': '5', 's': '5',
        'B': '8', 'Z': '2', 'z': '2',
        'A': '4'
    })
    translated = val.translate(trans)
    translated = re.sub(r"(\d+)\s+(\d{2})\b", r"\1.\2", translated)
    cleaned = re.sub(r"[^\d.]", "", translated)
    if cleaned.count(".") > 1:
        parts = cleaned.split(".")
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(cleaned)
    except ValueError:
        return None


class GenericKeyValueExtractor:
    """Line-based key-value extractor with fuzzy label matching and boundary stopping."""

    def __init__(self):
        self.synonyms = SCHEMA_SYNONYMS

    def extract(self, text: str, doc_type: str) -> Tuple[Dict[str, Any], Dict[str, float]]:
        schema_map = self.synonyms.get(doc_type, {})
        syn_to_field: Dict[str, str] = {}
        for fld, syn_list in schema_map.items():
            for syn in syn_list:
                norm = re.sub(r'[^a-z0-9#]', '', syn.lower())
                syn_to_field[norm] = fld

        colons = [m.start() for m in COLON_RE.finditer(text)]
        if not colons:
            return {}, {}

        all_labels = []
        for cp in colons:
            preceding = text[:cp].strip()
            words = preceding.split()
            if not words:
                continue
            best_fld = None
            best_score = 0.0
            best_phrase = None
            for k in range(min(6, len(words)), 0, -1):
                phrase = " ".join(words[-k:])
                norm = re.sub(r'[^a-z0-9#]', '', phrase.lower())
                if norm in syn_to_field:
                    best_fld = syn_to_field[norm]
                    best_score = 1.0 + 0.05 * k
                    best_phrase = phrase
                    break
                for ref_norm, fld in syn_to_field.items():
                    if len(ref_norm) >= 4 and (ref_norm in norm or norm in ref_norm):
                        ratio = min(len(ref_norm), len(norm)) / max(len(ref_norm), len(norm))
                        score = 0.80 + 0.15 * ratio
                        if score > best_score:
                            best_score = score
                            best_fld = fld
                            best_phrase = phrase
            if not best_phrase:
                best_phrase = " ".join(words[-min(2, len(words)):])
            lbl_start = text.rfind(best_phrase, 0, cp)
            if lbl_start != -1:
                all_labels.append((lbl_start, cp + 1, best_fld, best_score, best_phrase))

        all_labels.sort(key=lambda x: x[0])
        pruned = []
        last_end = -1
        for start, cp, fld, score, phrase in all_labels:
            if start >= last_end:
                pruned.append((start, cp, fld, score, phrase))
                last_end = cp

        extracted: Dict[str, Any] = {}
        confs: Dict[str, float] = {}

        for i in range(len(pruned)):
            start, val_start, fld, score, phrase = pruned[i]
            val_end = pruned[i+1][0] if i + 1 < len(pruned) else len(text)
            val = text[val_start:val_end].strip()
            if '\n' in val:
                val = val.split('\n')[0].strip()
            val = re.split(r'\s+[|]\s+', val)[0].strip()

            if fld:
                if 'date' in fld or 'period' in fld:
                    cleaned = clean_ocr_date(val)
                elif any(x in fld for x in ['amount', 'total', 'balance']):
                    cleaned = clean_ocr_amount(val)
                else:
                    cleaned = clean_ocr_field_text(val)
                    if cleaned:
                        if 'id' in fld or 'number' in fld or 'folio' in fld:
                            tokens = cleaned.split() if cleaned else []
                            cleaned = tokens[0] if tokens else cleaned
                        elif 'name' in fld or 'doctor' in fld or 'claimant' in fld or 'sender' in fld or 'recipient' in fld:
                            cleaned = re.sub(r'\s+(?:Clinician|Medical|License|State|Contact|Telephone|Phone|Emergency|Direct|Email|Anti-Money|Loss|Settlement).*$', '', cleaned, flags=re.I).strip()

                if cleaned is not None and confs.get(fld, 0.0) < score:
                    extracted[fld] = cleaned
                    confs[fld] = round(min(0.95, score), 3)

        # Sync canonical aliases
        if "full_name" in extracted and "customer_name" not in extracted:
            extracted["customer_name"] = extracted["full_name"]
            confs["customer_name"] = confs["full_name"]
        if "customer_name" in extracted and "full_name" not in extracted:
            extracted["full_name"] = extracted["customer_name"]
            confs["full_name"] = confs["customer_name"]
        if "po_date" in extracted and "order_date" not in extracted:
            extracted["order_date"] = extracted["po_date"]
            confs["order_date"] = confs["po_date"]
        if "order_date" in extracted and "po_date" not in extracted:
            extracted["po_date"] = extracted["order_date"]
            confs["po_date"] = confs["order_date"]
        if "letter_date" in extracted and "date" not in extracted:
            extracted["date"] = extracted["letter_date"]
            confs["date"] = confs["letter_date"]
        if "date" in extracted and "letter_date" not in extracted:
            extracted["letter_date"] = extracted["date"]
            confs["letter_date"] = confs["date"]
        if "order_total" in extracted and "total_amount" not in extracted:
            extracted["total_amount"] = extracted["order_total"]
            confs["total_amount"] = confs["order_total"]
        if "total_amount" in extracted and "order_total" not in extracted:
            extracted["order_total"] = extracted["total_amount"]
            confs["order_total"] = confs["total_amount"]
        if "party_one" in extracted and "parties" not in extracted:
            extracted["parties"] = extracted["party_one"]
            confs["parties"] = confs["party_one"]
        if "parties" in extracted and "party_one" not in extracted:
            extracted["party_one"] = extracted["parties"]
            confs["party_one"] = confs["parties"]

        return extracted, confs
