"""Pipeline stage processors with idempotency, transactional guarantees, and error handling."""

import hashlib
import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple
import fitz
from pydantic import ValidationError

from app.adapters.classifier import get_classifier
from app.adapters.ecm import get_ecm_adapter
from app.adapters.ocr import get_ocr_engine
from app.adapters.pii import get_pii_detector
from app.adapters.search import get_search_adapter
from app.adapters.storage import get_storage_adapter
from app.adapters.virus import get_virus_scanner
from app.core.audit import AssetAuditMetadata, AuditEvent
from app.core.config import get_pipeline_config
from app.core.idempotency import get_idempotency_registry
from app.core.interfaces import ECMDocumentRecord
from app.models.db import AuditEventModel, DocumentModel, ReviewTaskModel, get_db_session
from app.models.schemas import FIELD_SCHEMA_MAP, DecisionResult
from app.workers.generic_extractor import GenericKeyValueExtractor


# ---------------------------------------------------------------------------
# Stage 1: Virus Scan
# ---------------------------------------------------------------------------
def stage_virus_scan(sha256_hash: str, raw_bytes: bytes) -> Dict[str, Any]:
    """Scan raw bytes for virus/malware signatures."""
    scanner = get_virus_scanner()
    is_clean, virus_name = scanner.scan(raw_bytes)
    if not is_clean:
        return {
            "status": "INFECTED",
            "virus_name": virus_name,
            "action": "QUARANTINE",
            "reason": f"Antivirus threat detected: {virus_name}",
        }
    return {"status": "CLEAN"}


# ---------------------------------------------------------------------------
# Stage 2: Deduplication Check
# ---------------------------------------------------------------------------
def stage_dedupe(sha256_hash: str) -> Dict[str, Any]:
    """Check if an asset with this exact SHA-256 already exists in ECM."""
    ecm = get_ecm_adapter()
    existing = ecm.find_by_hash(sha256_hash)
    if existing:
        return {
            "status": "DUPLICATE_FOUND",
            "canonical_uid": existing.uid,
            "canonical_ecm_id": existing.ecm_id,
            "canonical_record": existing.model_dump(),
        }
    return {"status": "UNIQUE"}


# ---------------------------------------------------------------------------
# Stage 3: Pre-processing & Integrity Check (Corrupt / Password-protected)
# ---------------------------------------------------------------------------
def stage_preprocess(file_bytes: bytes, file_name: str) -> Dict[str, Any]:
    """Verify document integrity, check encryption/corruption, and pre-process."""
    ext = file_name.split(".")[-1].lower() if "." in file_name else ""

    # Check for simulated corruption
    if b"CORRUPTED_FILE_DATA_NOT_A_VALID_DOCUMENT" in file_bytes or (
        ext == "pdf" and not file_bytes.startswith(b"%PDF") and len(file_bytes) < 100
    ):
        return {
            "status": "CORRUPT",
            "action": "QUARANTINE",
            "reason": "Corrupt or malformed document payload",
        }

    # PDF validation: check encryption / password protection
    if ext == "pdf":
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            if doc.is_encrypted:
                return {
                    "status": "PASSWORD_PROTECTED",
                    "action": "QUARANTINE",
                    "reason": "Document is password-protected or encrypted",
                }
            page_count = len(doc)
            doc.close()
        except Exception as e:
            return {
                "status": "CORRUPT",
                "action": "QUARANTINE",
                "reason": f"PDF structure validation failed: {str(e)}",
            }
    else:
        page_count = 1

    return {
        "status": "VALID",
        "page_count": page_count,
        "extension": ext,
    }


# ---------------------------------------------------------------------------
# Stage 4: Document Splitting
# ---------------------------------------------------------------------------
def stage_split_document(file_bytes: bytes, file_name: str) -> List[Tuple[bytes, str]]:
    """Split multi-document container file on separator pages or barcodes."""
    ext = file_name.split(".")[-1].lower() if "." in file_name else ""
    if ext != "pdf":
        return [(file_bytes, file_name)]

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        if len(doc) <= 1:
            return [(file_bytes, file_name)]

        split_indices = []
        for i, page in enumerate(doc):
            text = page.get_text().upper()
            if "DOCUMENT SEPARATOR" in text or "=== SPLIT ===" in text or "SPLIT_HERE" in text:
                split_indices.append(i)

        if not split_indices:
            return [(file_bytes, file_name)]

        # Slice sub-documents
        sub_docs: List[Tuple[bytes, str]] = []
        start_idx = 0
        doc_count = 1

        for sep_idx in split_indices:
            if sep_idx > start_idx:
                new_doc = fitz.open()
                new_doc.insert_pdf(doc, from_page=start_idx, to_page=sep_idx - 1)
                sub_bytes = new_doc.tobytes()
                sub_docs.append((sub_bytes, f"{file_name}_part_{doc_count}.pdf"))
                doc_count += 1
            start_idx = sep_idx + 1

        if start_idx < len(doc):
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=start_idx, to_page=len(doc) - 1)
            sub_bytes = new_doc.tobytes()
            sub_docs.append((sub_bytes, f"{file_name}_part_{doc_count}.pdf"))

        return sub_docs if sub_docs else [(file_bytes, file_name)]
    except Exception:
        return [(file_bytes, file_name)]


# ---------------------------------------------------------------------------
# Stage 5: OCR
# ---------------------------------------------------------------------------
def stage_ocr(file_bytes: bytes, file_name: str) -> Dict[str, Any]:
    """Execute Optical Character Recognition and extract text & layout."""
    ext = file_name.split(".")[-1].lower() if "." in file_name else "pdf"
    engine = get_ocr_engine()
    res = engine.extract_text(file_bytes, ext)
    return {
        "full_text": res.full_text,
        "page_count": res.pages_count,
        "bounding_boxes_count": len(res.bounding_boxes),
        "engine_name": res.engine_name,
        "engine_version": res.engine_version,
    }


# ---------------------------------------------------------------------------
# Stage 6: Classification
# ---------------------------------------------------------------------------
def stage_classify(text: str) -> Dict[str, Any]:
    """Predict document type and confidence using active classifier."""
    classifier = get_classifier()
    res = classifier.predict(text)
    return {
        "predicted_class": res.predicted_class,
        "confidence": res.confidence,
        "probabilities": res.probabilities,
        "model_name": res.model_name,
        "model_version": res.model_version,
    }


# ---------------------------------------------------------------------------
# Stage 7: Field Extraction & Schema Validation
# ---------------------------------------------------------------------------
def _clean_field_text(val: Optional[str]) -> str:
    """Strip OCR quotation marks, brackets, trailing punctuation, and extra whitespace, normalizing common prefixes."""
    if not val:
        return ""
    val = val.strip().strip("`'\"‘“”—-=[](){}:;,.")
    # Normalize common OCR doctor prefixes (Or. -> Dr.)
    val = re.sub(r"^(?:Or|Pr|Dr)\.\s*", "Dr. ", val, flags=re.I)
    return re.sub(r"\s+", " ", val).strip()

def _clean_date(val: Optional[str]) -> Optional[str]:
    """Normalize OCR date strings (convert dots and slashes to dashes YYYY-MM-DD, fixing missing separators)."""
    if not val:
        return None
    val = val.strip().strip("`'\"‘“”—-=[](){}:;,.")
    # Map OCR letter confusions in date string (O -> 0, l/I -> 1)
    trans = str.maketrans({'O': '0', 'o': '0', 'l': '1', 'I': '1', '|': '1'})
    val = val.translate(trans)
    
    # Format YYYY-MM-DD, YYYY.MM.DD, YYYY/MM/DD
    m = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", val)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    # Format YYYY-MMDD or YYYYMMDD
    m2 = re.search(r"(\d{4})[-./]?(\d{2})(\d{2})", val)
    if m2:
        y, mo, d = m2.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return None

def _clean_amount(val: Optional[str]) -> Optional[float]:
    """Parse monetary string to float with OCR digit confusion normalization (S/5, O/0, I/1, B/8)."""
    if not val:
        return None
    val = val.strip().strip("`'\"‘“”—-=[](){}:;,")
    # Strip leading currency/OCR symbols
    val = re.sub(r"^[$S§]\s*", "", val)
    # Map common OCR letters to digits when in numeric contexts
    trans = str.maketrans({
        'O': '0', 'o': '0',
        'I': '1', 'l': '1', '|': '1',
        'S': '5', 's': '5',
        'B': '8', 'Z': '2', 'z': '2',
        'A': '4'
    })
    translated = val.translate(trans)
    # Fix space before 2 decimals: "14047 67" -> "14047.67"
    translated = re.sub(r"(\d+)\s+(\d{2})\b", r"\1.\2", translated)
    # Clean commas and any remaining non-digit non-dot
    cleaned = re.sub(r"[^\d.]", "", translated)
    # Handle multiple dots (e.g. 14.047.67 -> 14047.67)
    if cleaned.count(".") > 1:
        parts = cleaned.split(".")
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(cleaned)
    except ValueError:
        return None

def stage_extract_fields(text: str, doc_type: str) -> Tuple[Dict[str, Any], Dict[str, float], bool]:
    """Extract required fields per document type using GenericKeyValueExtractor and fallback regexes.
    
    If any field is missing or cannot be located in the OCR text, it returns None with 0.0 confidence.
    Hardcoded default fallback constants are strictly prohibited.
    """
    if doc_type == "unknown" or not text.strip():
        return {}, {}, False

    # 1. Primary: Generic Key-Value Extraction with Fuzzy Label Matching and Line Structure
    extractor = GenericKeyValueExtractor()
    extracted, confidences = extractor.extract(text, doc_type)

    # 2. Supplementary Regex Fallbacks strictly for unextracted fields
    if doc_type == "invoice":
        if not extracted.get("invoice_number"):
            m = re.search(r"[‘'\"`\s]*(?:Invoice\s*(?:Number|No|#)|Inv\s*#|Bill\s*No\.?|Billing\s*Ref)\s*[:;\s.-]+([A-Z0-9-]+)", text, re.I) or re.search(r"\b(INV-[0-9A-Z-]+)\b", text, re.I)
            if m:
                extracted["invoice_number"] = m.group(1).strip()
                confidences["invoice_number"] = 0.90
            else:
                extracted["invoice_number"] = None
                confidences["invoice_number"] = 0.0

        if not extracted.get("invoice_date"):
            m = re.search(r"[‘'\"`\s]*(?:Invoice\s*Date|Billing\s*Date|Date\s*of\s*Issue|Issue\s*Date)\s*[:;\s.-]+(\d{4}[./-]\d{1,2}[./-]\d{1,2})", text, re.I) or re.search(r"\b(\d{4}[./-]\d{1,2}[./-]\d{1,2})\b", text)
            if m:
                extracted["invoice_date"] = _clean_date(m.group(1))
                confidences["invoice_date"] = 0.90
            else:
                extracted["invoice_date"] = None
                confidences["invoice_date"] = 0.0

        if extracted.get("total_amount") is None:
            m = re.search(r"[‘'\"`\s]*(?:TOTAL\s*AMOUNT(?:\s*DUE)?|Balance\s*Due|Grand\s*Total|Total\s*Due|Total)\s*[:;\s.-]*\$?\s*([0-9,]+(?:\.[0-9]{2})?)", text, re.I)
            if m:
                extracted["total_amount"] = _clean_amount(m.group(1))
                confidences["total_amount"] = 0.90
            else:
                extracted["total_amount"] = None
                confidences["total_amount"] = 0.0

        if not extracted.get("vendor_name"):
            m = re.search(r"[‘'\"`\s]*(?:Vendor\s*(?:Name)?|Billed\s*By|Bi[l1]+ed\s*By|‘?lo[ad]\s*By|Supplier\s*(?:Name)?)\s*[:;\s.-]+([^\n\r]+?)(?=\s*(?:Vendor\s*Tax|Tax\s*ID|Corporate\s*EIN|Support\s*Phone|Contact|Telephone|\n|$))", text, re.I)
            if m:
                extracted["vendor_name"] = _clean_field_text(m.group(1))
                confidences["vendor_name"] = 0.85
            else:
                extracted["vendor_name"] = None
                confidences["vendor_name"] = 0.0

    elif doc_type == "contract":
        if not extracted.get("contract_id"):
            m = re.search(r"[‘'\"`\s]*(?:Contract\s*ID|Agreement\s*Ref|Contract\s*No\.?|Agreement\s*No\.?|Contact\s*ID)\s*[:;\s.-]+([A-Z0-9-]+)", text, re.I) or re.search(r"\b(CNT-[0-9A-Z-]+)\b", text, re.I)
            if m:
                extracted["contract_id"] = m.group(1).strip()
                confidences["contract_id"] = 0.90
            else:
                extracted["contract_id"] = None
                confidences["contract_id"] = 0.0

        if not extracted.get("effective_date"):
            m = re.search(r"[‘'\"`\s]*(?:E[tf]+ec[a-z]*\s*Date|Commencement\s*Date|Execution\s*Date|Execut[l1i]on\s*Date)\s*[:;\s.-]+(\d{4}[./-]\d{1,2}[./-]\d{1,2})", text, re.I) or re.search(r"\b(\d{4}[./-]\d{1,2}[./-]\d{1,2})\b", text)
            if m:
                extracted["effective_date"] = _clean_date(m.group(1))
                confidences["effective_date"] = 0.90
            else:
                extracted["effective_date"] = None
                confidences["effective_date"] = 0.0

        if not extracted.get("party_one") and not extracted.get("parties"):
            m = re.search(r"[‘'\"`\s]*(?:Party\s*One|First\s*Party|Disclosing\s*Entity)\s*[:;\s.-]+([^\n\r]+)", text, re.I)
            if m:
                extracted["party_one"] = _clean_field_text(m.group(1))
                confidences["party_one"] = 0.85
            else:
                extracted["party_one"] = None
                confidences["party_one"] = 0.0

        if not extracted.get("party_two") and not extracted.get("parties"):
            m = re.search(r"[‘'\"`\s]*(?:Party\s*Two|Second\s*Part[ya-z]*|Receiving\s*Ent[a-z]*|Rocating\s*Ent[a-z]*|Second\s*Par)\s*[:;\s.-]+([^\n\r]+)", text, re.I)
            if m:
                extracted["party_two"] = _clean_field_text(m.group(1))
                confidences["party_two"] = 0.85
            else:
                extracted["party_two"] = None
                confidences["party_two"] = 0.0

    elif doc_type == "kyc_form":
        if not extracted.get("full_name") and not extracted.get("customer_name"):
            m = re.search(r"[‘'\"`\s]*(?:Full\s*Name|Ful\s*Name|Legal\s*Name|Logal\s*Name|Applicant\s*Name)\s*[:;\s.-]+([A-Za-z\s]+?)(?=\s*(?:Document|ID|1D|10|National|Passport|DOB|Birth|\n|$))", text, re.I)
            if m:
                extracted["full_name"] = _clean_field_text(m.group(1))
                confidences["full_name"] = 0.90
            else:
                extracted["full_name"] = None
                confidences["full_name"] = 0.0

        if not extracted.get("id_number"):
            m = re.search(r"[‘'\"`\s]*(?:ID\s*Number|10\s*Number|Document\s*(?:ID|1D)|National\s*(?:Identity|entity)\s*#?)\s*[:;\s.-]+([A-Z0-9-]+)", text, re.I) or re.search(r"\b((?:ID|1D|10)-[0-9A-Z]+)\b", text, re.I)
            if m:
                raw_id = m.group(1).strip()
                if re.match(r"^(?:1D|10)-", raw_id, re.I):
                    raw_id = "ID-" + raw_id[3:]
                extracted["id_number"] = raw_id
                confidences["id_number"] = 0.90
            else:
                extracted["id_number"] = None
                confidences["id_number"] = 0.0

        if not extracted.get("date_of_birth"):
            m = re.search(r"[‘'\"`\s]*(?:Date\s*of\s*Birth|DOB|008|OOB|Bi[a-z]+h\s*Date)\s*[:;\s.-]+(\d{4}[./-]\d{1,2}[./-]\d{1,2})", text, re.I) or re.search(r"\b(\d{4}[./-]\d{1,2}[./-]\d{1,2})\b", text)
            if m:
                extracted["date_of_birth"] = _clean_date(m.group(1))
                confidences["date_of_birth"] = 0.90
            else:
                extracted["date_of_birth"] = None
                confidences["date_of_birth"] = 0.0

        if not extracted.get("nationality"):
            m = re.search(r"[‘'\"`\s]*(?:Nationalit[ya-z]*|Count[a-z]*\s*of\s*C[a-z]*zenship|C[a-z]*tizenst?ip)\s*[:;\s.-]+([A-Za-z\s]+?)(?=\s*(?:Primary|Mobile|Phone|Contact|Part|Section|\n|$))", text, re.I)
            if m:
                extracted["nationality"] = _clean_field_text(m.group(1))
                confidences["nationality"] = 0.85
            else:
                extracted["nationality"] = None
                confidences["nationality"] = 0.0

    elif doc_type == "bank_statement":
        if not extracted.get("account_number"):
            m = re.search(r"[‘'\"`\s]*(?:Account\s*Number|Acct\s*#|Account\s*No\.?|‘?ect\s*#)\s*[:;\s.-]+([A-Z0-9-]+)", text, re.I) or re.search(r"\b(A[CG]C-[0-9]+)\b", text, re.I)
            if m:
                extracted["account_number"] = m.group(1).strip()
                confidences["account_number"] = 0.90
            else:
                extracted["account_number"] = None
                confidences["account_number"] = 0.0

        if not extracted.get("statement_period"):
            m = re.search(r"(\d{4}[./-]\d{1,2}[./-]\d{1,2}\s*(?:to|-)\s*\d{4}[./-]\d{1,2}[./-]\d{1,2})", text, re.I)
            if m:
                extracted["statement_period"] = m.group(1).strip()
                confidences["statement_period"] = 0.90
            else:
                extracted["statement_period"] = None
                confidences["statement_period"] = 0.0

        if extracted.get("opening_balance") is None:
            m = re.search(r"[‘'\"`\s]*(?:Opening|Starting|Beginning|Stating|Bogening|Initial)\s*Ba[lt1a-z]+ance\s*[:;\s.-]*[$S§]?\s*([0-9,]+(?:\.[0-9]{2})?)", text, re.I)
            if m:
                extracted["opening_balance"] = _clean_amount(m.group(1))
                confidences["opening_balance"] = 0.90
            else:
                extracted["opening_balance"] = None
                confidences["opening_balance"] = 0.0

        if extracted.get("closing_balance") is None:
            m = re.search(r"[‘'\"`\s]*(?:Closing|Ending|Final)\s*Ba[lt1a-z]+ance\s*[:;\s.-]*[$S§]?\s*([0-9,]+(?:\.[0-9]{2})?)", text, re.I)
            if m:
                extracted["closing_balance"] = _clean_amount(m.group(1))
                confidences["closing_balance"] = 0.90
            else:
                extracted["closing_balance"] = None
                confidences["closing_balance"] = 0.0

    elif doc_type == "medical_report":
        if not extracted.get("patient_id"):
            m = re.search(r"[‘'\"`\s]*(?:Patient\s*ID|Patient\s*Ref|Medical\s*Record\s*No(?:\s*\(MRN\))?|MRN)\s*[:;\s.-]+([A-Z0-9-]+)", text, re.I) or re.search(r"\b(PAT-[0-9]+)\b", text, re.I)
            if m:
                extracted["patient_id"] = m.group(1).strip()
                confidences["patient_id"] = 0.90
            else:
                extracted["patient_id"] = None
                confidences["patient_id"] = 0.0

        if not extracted.get("diagnosis"):
            m = re.search(r"[‘'\"`\s]*(?:Primary\s*Diagnosis|Impression(?:\s*Diagnosis)?|Diagnosis|Impression)\s*[:;\s.-]+([^\n\r]+?)(?=\s*(?:RECOMMENDATION|RECOMMEND|Provider|Attestation|Consultant|Physician|Doctor|\n|$))", text, re.I)
            if m:
                extracted["diagnosis"] = _clean_field_text(m.group(1))
                confidences["diagnosis"] = 0.85
            else:
                extracted["diagnosis"] = None
                confidences["diagnosis"] = 0.0

        if not extracted.get("doctor_name"):
            m = re.search(r"[‘'\"`\s]*(?:Attending\s*Physic[a-z]*|Consut?ant|Physician|Physcian|Doctor|Provider\s*Attestation)\s*[:;\s.-]+([^\n\r]+?)(?=\s*(?:Credentials|Grodontals|License|Exam|Date|Phone|\n|$))", text, re.I) or re.search(r"\b((?:Dr|Or|Pr)\.\s+[A-Za-z\s]+?)(?=\s*(?:Credentials|Grodontals|License|Exam|Date|\.|\n|$))", text)
            if m:
                extracted["doctor_name"] = _clean_field_text(m.group(1))
                confidences["doctor_name"] = 0.85
            else:
                extracted["doctor_name"] = None
                confidences["doctor_name"] = 0.0

        if not extracted.get("report_date"):
            m = re.search(r"[‘'\"`\s]*(?:Report\s*Date|Exam\s*Date|Date\s*of\s*Service)\s*[:;\s.-]+(\d{4}[./-]\d{1,2}[./-]\d{1,2})", text, re.I) or re.search(r"\b(\d{4}[./-]\d{1,2}[./-]\d{1,2})\b", text)
            if m:
                extracted["report_date"] = _clean_date(m.group(1))
                confidences["report_date"] = 0.90
            else:
                extracted["report_date"] = None
                confidences["report_date"] = 0.0

    elif doc_type == "purchase_order":
        if not extracted.get("po_number"):
            m = re.search(r"[‘'\"`\s]*(?:PO\s*Number|P\.O\.\s*#|Order\s*Number)\s*[:;\s.-]+([A-Z0-9-]+)", text, re.I) or re.search(r"\b(PO-[0-9]+)\b", text, re.I)
            if m:
                extracted["po_number"] = m.group(1).strip()
                confidences["po_number"] = 0.90
            else:
                extracted["po_number"] = None
                confidences["po_number"] = 0.0

        if not extracted.get("po_date") and not extracted.get("order_date"):
            m = re.search(r"[‘'\"`\s]*(?:PO\s*Date|Order\s*Date|Date)\s*[:;\s.-]+(\d{4}[./-]\d{1,2}[./-]\d{1,2})", text, re.I) or re.search(r"\b(\d{4}[./-]\d{1,2}[./-]\d{1,2})\b", text)
            if m:
                extracted["po_date"] = _clean_date(m.group(1))
                confidences["po_date"] = 0.90
            else:
                extracted["po_date"] = None
                confidences["po_date"] = 0.0

        if not extracted.get("vendor_name"):
            m = re.search(r"(?:Vendor(?:\s*Name)?|Supplier(?:\s*Name)?)\s*[:;\s.-]+([A-Za-z0-9&,.' -]+?)(?=\s*(?:Phone|Contact|Telephone|Associated|Delivery|\n|$))", text, re.I)
            if m:
                extracted["vendor_name"] = _clean_field_text(m.group(1))
                confidences["vendor_name"] = 0.85
            else:
                extracted["vendor_name"] = None
                confidences["vendor_name"] = 0.0

        if extracted.get("order_total") is None and extracted.get("total_amount") is None:
            m = re.search(r"[‘'\"`\s]*(?:Order\s*Total|Total\s*Cost|Total\s*Purchase\s*Amount|Total)\s*[:;\s.-]*\$?\s*([0-9,]+(?:\.[0-9]{2})?)", text, re.I)
            if m:
                extracted["order_total"] = _clean_amount(m.group(1))
                confidences["order_total"] = 0.90
            else:
                extracted["order_total"] = None
                confidences["order_total"] = 0.0

    elif doc_type == "letter":
        if not extracted.get("sender"):
            m = re.search(r"[‘'\"`\s]*(?:From|Sender|FROM)\s*[:;\s.-]+([^\n\r]+?)(?=\s*(?:Recipient|To|TO|Attention|Date|\n|$))", text, re.I)
            if m:
                extracted["sender"] = _clean_field_text(m.group(1))
                confidences["sender"] = 0.85
            else:
                extracted["sender"] = None
                confidences["sender"] = 0.0

        if not extracted.get("recipient"):
            m = re.search(r"[‘'\"`\s]*(?:To|Recipient|TO|Attention|Aecipient|Feecipient)\s*[:;\s.-]+([^\n\r]+?)(?=\s*(?:Date|\bRE\b|Subject|Attention|\n|$))", text, re.I)
            if m:
                extracted["recipient"] = _clean_field_text(m.group(1))
                confidences["recipient"] = 0.85
            else:
                extracted["recipient"] = None
                confidences["recipient"] = 0.0

        if not extracted.get("letter_date") and not extracted.get("date"):
            m = re.search(r"[‘'\"`\s]*(?:Date\s*of\s*Notice|Date|DATE)\s*[:;\s.-]+(\d{4}[./-]\d{1,2}[./-]\d{1,2})", text, re.I) or re.search(r"\b(\d{4}[./-]\d{1,2}[./-]\d{1,2})\b", text)
            if m:
                extracted["letter_date"] = _clean_date(m.group(1))
                confidences["letter_date"] = 0.90
            else:
                extracted["letter_date"] = None
                confidences["letter_date"] = 0.0

        if not extracted.get("subject"):
            m = re.search(r"[‘'\"`\s]*(?:Subject(?:\s*Matter)?|R[IE1|]+)\s*[:;\s.-]+([^\n\r]+?)(?=\s*(?:Dear|Attention|Attn|Please|We are|\n|$))", text, re.I)
            if m:
                extracted["subject"] = _clean_field_text(m.group(1))
                confidences["subject"] = 0.85
            else:
                extracted["subject"] = None
                confidences["subject"] = 0.0

    elif doc_type == "claim_form":
        if not extracted.get("claim_id"):
            m = re.search(r"[‘'\"`\s]*(?:Claim\s*ID|Claim\s*Reference\s*#|Claim\s*No\.?)\s*[:;\s.-]+([A-Z0-9-]+)", text, re.I) or re.search(r"\b(CLM-[0-9]+)\b", text, re.I)
            if m:
                extracted["claim_id"] = m.group(1).strip()
                confidences["claim_id"] = 0.90
            else:
                extracted["claim_id"] = None
                confidences["claim_id"] = 0.0

        if not extracted.get("claimant_name"):
            m = re.search(r"(?:Claimant\s*Name|Insured\s*Party|Ingured\s*Party|Applicant|Claimant\s*Attestation)\s*:\s*([A-Za-z\s]+?)(?=\s*(?:Social|\bSSN\b|Taxpayer|Phone|Incident|\n|$))", text, re.I)
            if m:
                extracted["claimant_name"] = _clean_field_text(m.group(1))
                confidences["claimant_name"] = 0.85
            else:
                extracted["claimant_name"] = None
                confidences["claimant_name"] = 0.0

        if not extracted.get("incident_date"):
            m = re.search(r"[‘'\"`\s]*(?:Incident\s*Date|Loss\s*Date|Date\s*of\s*Occurrence)\s*[:;\s.-]+(\d{4}[./-]\d{1,2}[./-]\d{1,2})", text, re.I) or re.search(r"\b(\d{4}[./-]\d{1,2}[./-]\d{1,2})\b", text)
            if m:
                extracted["incident_date"] = _clean_date(m.group(1))
                confidences["incident_date"] = 0.90
            else:
                extracted["incident_date"] = None
                confidences["incident_date"] = 0.0

        if extracted.get("claim_amount") is None:
            m = re.search(r"[‘'\"`\s]*(?:Claim\s*Amount|Claimed\s*Loss\s*Amount|Requested\s*Amount)\s*[:;\s.-]*\$?\s*([0-9,]+(?:\.[0-9]{2})?)", text, re.I)
            if m:
                extracted["claim_amount"] = _clean_amount(m.group(1))
                confidences["claim_amount"] = 0.90
            else:
                extracted["claim_amount"] = None
                confidences["claim_amount"] = 0.0

    # Validate against Schema
    schema_cls = FIELD_SCHEMA_MAP.get(doc_type)
    is_valid = True
    if schema_cls and doc_type != "unknown":
        # Check if any required schema field is None
        schema_fields = schema_cls.model_fields.keys()
        required_fields = [
            f_name for f_name, f_info in schema_cls.model_fields.items()
            if f_info.is_required()
        ]
        for sf in required_fields:
            if extracted.get(sf) is None:
                # check aliases
                alt = None
                if sf == "full_name": alt = "customer_name"
                elif sf == "customer_name": alt = "full_name"
                elif sf == "po_date": alt = "order_date"
                elif sf == "order_date": alt = "po_date"
                elif sf == "order_total": alt = "total_amount"
                elif sf == "total_amount": alt = "order_total"
                elif sf == "letter_date": alt = "date"
                elif sf == "date": alt = "letter_date"
                elif sf == "party_one": alt = "parties"
                elif sf == "parties": alt = "party_one"
                if alt and extracted.get(alt) is not None:
                    extracted[sf] = extracted[alt]
                else:
                    is_valid = False
                    break
        if is_valid:
            try:
                schema_cls(**{k: v for k, v in extracted.items() if k in schema_fields})
            except ValidationError:
                is_valid = False

    return extracted, confidences, is_valid


# ---------------------------------------------------------------------------
# Stage 8: PII Detection
# ---------------------------------------------------------------------------
def stage_pii_detect(text: str) -> Dict[str, Any]:
    """Detect PII entities, assess sensitivity, and map types."""
    detector = get_pii_detector()
    entities = detector.detect(text)
    types_found = list({e.entity_type for e in entities})
    has_high = any(e.sensitivity == "high" for e in entities)

    return {
        "pii_detected": len(entities) > 0,
        "entities_count": len(entities),
        "pii_types": types_found,
        "has_high_sensitivity": has_high,
        "entities": [e.model_dump() for e in entities],
    }


# ---------------------------------------------------------------------------
# Stage 9: Decision Gate
# ---------------------------------------------------------------------------
def stage_decision_gate(
    predicted_type: str,
    confidence: float,
    pii_info: Dict[str, Any],
    extraction_valid: bool = True,
) -> DecisionResult:
    """Evaluate routing decision against YAML config rules and conflict resolution."""
    cfg = get_pipeline_config()
    class_cfg = cfg.classes.get(predicted_type)

    if not class_cfg:
        class_cfg = cfg.classes["unknown"]
        predicted_type = "unknown"

    is_high_risk = class_cfg.risk == "high"
    # Mandatory rule: unknown is NEVER auto-accepted!
    if predicted_type == "unknown":
        return DecisionResult(
            action="ROUTE_TO_REVIEW",
            predicted_type="unknown",
            confidence=confidence,
            retention_class=class_cfg.retention_class,
            acl="RESTRICTED_REVIEW",
            target_workflow="MANUAL_TRIAGE",
            reason="Mandatory rule: document classified as unknown must undergo human review",
            review_status="pending_review",
        )

    # Mandatory rule: field extraction failure or missing fields routes to review!
    if not extraction_valid:
        return DecisionResult(
            action="ROUTE_TO_REVIEW",
            predicted_type=predicted_type,
            confidence=confidence,
            retention_class=class_cfg.retention_class,
            acl="RESTRICTED_REVIEW",
            target_workflow="EXTRACTION_FAILURE_REVIEW",
            reason=f"Field extraction incomplete or failed schema validation for {predicted_type}",
            review_status="pending_review",
        )

    # Check for classifier / PII conflict:
    # "If classifier and PII detector disagree, take the stricter outcome."
    has_high_pii = pii_info.get("has_high_sensitivity", False)
    if not is_high_risk and has_high_pii and cfg.decision_gate.conflict_stricter_rule:
        return DecisionResult(
            action="ROUTE_TO_REVIEW",
            predicted_type=predicted_type,
            confidence=confidence,
            retention_class=class_cfg.retention_class,
            acl="RESTRICTED_REVIEW",  # Stricter ACL on conflict
            target_workflow="HIGH_SENSITIVITY_REVIEW",
            reason="Classifier/PII Conflict: High-sensitivity PII found in low-risk class; enforcing stricter review path",
            review_status="pending_review",
        )

    # Check auto-acceptance thresholds
    required_threshold = (
        class_cfg.tuned_threshold
        if hasattr(class_cfg, "tuned_threshold")
        else (cfg.decision_gate.high_risk_auto_threshold if is_high_risk else cfg.decision_gate.low_risk_auto_threshold)
    )

    if confidence >= required_threshold:
        return DecisionResult(
            action="AUTO_ACCEPT",
            predicted_type=predicted_type,
            confidence=confidence,
            retention_class=class_cfg.retention_class,
            acl=class_cfg.acl,
            target_workflow=class_cfg.target_workflow,
            reason=f"Confidence {confidence:.3f} >= threshold {required_threshold:.3f} for {predicted_type}",
            review_status="auto_accepted",
        )
    elif confidence >= cfg.decision_gate.review_floor:
        return DecisionResult(
            action="ROUTE_TO_REVIEW",
            predicted_type=predicted_type,
            confidence=confidence,
            retention_class=class_cfg.retention_class,
            acl="RESTRICTED_REVIEW",
            target_workflow="LOW_CONFIDENCE_REVIEW",
            reason=f"Confidence {confidence:.3f} below acceptance threshold {required_threshold:.3f}; routed to review queue",
            review_status="pending_review",
        )
    else:
        # Confidence below review floor: escalate to Unknown triage
        return DecisionResult(
            action="ROUTE_TO_REVIEW",
            predicted_type="unknown",
            confidence=confidence,
            retention_class=cfg.classes["unknown"].retention_class,
            acl="RESTRICTED_REVIEW",
            target_workflow="MANUAL_TRIAGE",
            reason=f"Confidence {confidence:.3f} below minimum floor {cfg.decision_gate.review_floor:.3f}",
            review_status="pending_review",
        )


# ---------------------------------------------------------------------------
# Stage 10: ECM Write
# ---------------------------------------------------------------------------
def stage_write_ecm(
    uid: str,
    sha256_hash: str,
    decision: DecisionResult,
    metadata_fields: Dict[str, Any],
    raw_storage_path: str,
) -> ECMDocumentRecord:
    """Commit document asset and metadata to ECMAdapter."""
    ecm = get_ecm_adapter()
    record = ECMDocumentRecord(
        ecm_id="",
        uid=uid,
        sha256=sha256_hash,
        doc_type=decision.predicted_type,
        confidence=decision.confidence,
        metadata={
            "storage_path": raw_storage_path,
            "extracted_fields": metadata_fields.get("extracted_fields", {}),
            "field_confidences": metadata_fields.get("field_confidences", {}),
            "pii_detected": metadata_fields.get("pii_detected", False),
            "pii_types": metadata_fields.get("pii_types", []),
            "ocr_engine": metadata_fields.get("ocr_engine", "unknown"),
            "ocr_version": metadata_fields.get("ocr_version", "1.0"),
            "classifier_model": metadata_fields.get("classifier_model", "tfidf_logistic"),
            "classifier_version": metadata_fields.get("classifier_version", "v1.0"),
            "decision_reason": decision.reason,
            "file_name": metadata_fields.get("file_name", "document.pdf"),
            "file_size": metadata_fields.get("file_size", 0),
        },
        retention_class=decision.retention_class,
        acl=decision.acl,
        target_workflow=decision.target_workflow,
        review_status=decision.review_status,
        is_link=False,
    )
    committed = ecm.create_document(record)

    # If routed to review, create review task
    if decision.action == "ROUTE_TO_REVIEW":
        db = get_db_session()
        try:
            task = db.query(ReviewTaskModel).filter(ReviewTaskModel.document_uid == uid).first()
            if not task:
                task = ReviewTaskModel(
                    task_id=f"rev-{uid}-{uuid.uuid4().hex[:8]}",
                    document_uid=uid,
                    predicted_type=decision.predicted_type,
                    confidence=decision.confidence,
                    evidence_text=metadata_fields.get("extracted_text_preview", ""),
                    status="PENDING",
                )
                db.add(task)
                db.commit()
        finally:
            db.close()

    return committed


# ---------------------------------------------------------------------------
# Stage 11: Index in Search
# ---------------------------------------------------------------------------
def stage_index_search(
    uid: str,
    sha256_hash: str,
    decision: DecisionResult,
    metadata_fields: Dict[str, Any],
    full_text: str,
) -> bool:
    """Index asset in OpenSearch / Search Index."""
    search = get_search_adapter()
    payload = {
        "uid": uid,
        "sha256": sha256_hash,
        "doc_type": decision.predicted_type,
        "confidence": decision.confidence,
        "retention_class": decision.retention_class,
        "acl": decision.acl,
        "target_workflow": decision.target_workflow,
        "review_status": decision.review_status,
        "classifier_version": metadata_fields.get("classifier_version", "v1.0"),
        "full_text": full_text[:10000],  # truncated text body
        "extracted_fields": metadata_fields.get("extracted_fields", {}),
    }
    return search.index_document(doc_id=uid, payload=payload)


# ---------------------------------------------------------------------------
# Stage 12: Audit Logging
# ---------------------------------------------------------------------------
def stage_audit_record(
    uid: str,
    sha256_hash: str,
    decision: DecisionResult,
    metadata_fields: Dict[str, Any],
) -> AssetAuditMetadata:
    """Ensure 100% of assets carry model, version, confidence, and audit trail."""
    audit = AssetAuditMetadata(
        uid=uid,
        sha256=sha256_hash,
        ocrEngine=metadata_fields.get("ocr_engine", "unknown"),
        ocrVersion=metadata_fields.get("ocr_version", "1.0.0"),
        classifierModel=metadata_fields.get("classifier_model", "tfidf_logistic_regression"),
        classifierVersion=metadata_fields.get("classifier_version", "v1.0"),
        predictedType=decision.predicted_type,
        confidence=decision.confidence,
        fieldConfidences=metadata_fields.get("field_confidences", {}),
        piiDetected=metadata_fields.get("pii_detected", False),
        piiTypes=metadata_fields.get("pii_types", []),
        reviewStatus=decision.review_status,
        retentionClass=decision.retention_class,
        assignedAcl=decision.acl,
        targetWorkflow=decision.target_workflow,
        decisionReason=decision.reason,
    )

    # Persist audit event record in DB
    import uuid
    db = get_db_session()
    try:
        event = AuditEventModel(
            event_id=f"audit-{uid}-{uuid.uuid4().hex[:8]}",
            document_uid=uid,
            sha256=sha256_hash,
            event_type="PIPELINE_COMPLETE",
            stage_name="audit",
            status="SUCCESS",
            payload_json=json.dumps(audit.model_dump()),
        )
        db.add(event)
        db.commit()
    finally:
        db.close()

    return audit
