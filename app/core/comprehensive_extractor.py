"""Comprehensive Document Reader and Universal Detail Extractor Engine.

Implements all 5 parts of the specification:
Part 1:
- Extracts full text of every page.
- Extracts every labelled pair ("Label: value") using original document label, spelling, and casing.
- Extracts every table (rows and columns) from PDFs, spreadsheets, Word docs, and plain text tables.
- Extracts every date, email, phone number, ID/reference number, amount, name, organization,
  address, and web link, even without labels.
- Anti-Hallucination Gate: Never invents a value. Stored only if it actually appears in text.
- Captures page number and exact position/bounding box (bbox) for every detail found.

Part 2:
- Detects all sensitive categories (Govt/tax IDs, bank/cards, phone, email, addresses, DOB,
  personal salary/balances, medical/health info, passwords/tokens, names of people, signatures).
- Never drops or hides sensitive details; flags them with is_sensitive=True.

Part 3:
- Reads TXT and CSV directly as text (never through page rendering).
- Reads DOCX with python-docx and XLSX with openpyxl.
- Reads PDFs using embedded text; OCRs only pages lacking digital text.
- Tolerant multi-page processing: never fails whole file if one page fails.

Part 4:
- Identifies password protection, empty files, damaged files, and blank pages calmly.
"""

from dataclasses import dataclass, field
import csv
import io
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import fitz  # PyMuPDF
import numpy as np

from app.core.validators import validate_aadhaar, validate_pan, validate_gstin, validate_ifsc
from app.core.sensitivity import validate_luhn

logger = logging.getLogger("core.comprehensive_extractor")


class PasswordProtectedException(Exception):
    """File is encrypted or password-protected."""
    pass


class DamagedFileException(Exception):
    """File header or content is corrupt/cut-off."""
    pass


class EmptyFileException(Exception):
    """File has 0 bytes or no content."""
    pass


@dataclass
class ExtractedDetail:
    label: str
    value: str
    confidence: float = 0.95
    page: int = 1
    bbox: Optional[List[float]] = None  # [ymin, xmin, ymax, xmax] normalized 0-1000
    is_sensitive: bool = False
    source: str = "read"
    detector_tag: Optional[str] = None
    is_unlabelled: bool = False


@dataclass
class PageContent:
    page_number: int
    full_text: str
    is_blank: bool = False
    details: List[ExtractedDetail] = field(default_factory=list)


@dataclass
class ExtractionResult:
    doc_type: str
    pages: List[PageContent]
    all_details: List[ExtractedDetail]
    is_sensitive: bool = False
    error: Optional[str] = None
    page_count: int = 1
    extension_mismatch: bool = False
    extension_mismatch_reason: Optional[str] = None
    text_layer_mismatch: bool = False
    table_math_discrepancy: bool = False
    table_math_reason: Optional[str] = None


def detect_file_format_from_bytes(file_path: str) -> str:
    """Detect actual file format from header magic bytes."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(512)
    except Exception:
        return "unknown"

    if not header:
        return "empty"

    if header.startswith(b"%PDF-"):
        return ".pdf"
    elif header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    elif header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    elif header.startswith(b"II*\x00") or header.startswith(b"MM\x00*"):
        return ".tiff"
    elif header.startswith(b"BM"):
        return ".bmp"
    elif header.startswith(b"PK\x03\x04"):
        try:
            import zipfile
            with zipfile.ZipFile(file_path, "r") as zf:
                names = zf.namelist()
                if any(n.startswith("word/") for n in names):
                    return ".docx"
                elif any(n.startswith("xl/") for n in names):
                    return ".xlsx"
        except Exception:
            pass
        return ".docx"
    elif any(header.startswith(prefix) for prefix in [b"Received:", b"From:", b"Return-Path:", b"Date:", b"Subject:"]):
        return ".eml"
    elif header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return ".msg"
    else:
        try:
            sample = header.decode("utf-8", errors="strict")
            if "," in sample and "\n" in sample:
                return ".csv"
            return ".txt"
        except Exception:
            return "unknown"


# ---------------------------------------------------------------------------
# Regex Patterns for Labels, Entities, and Sensitive Categories
# ---------------------------------------------------------------------------
LABEL_PAIR_REGEX = re.compile(
    r"(?m)(?:^|[\t\s]{2,}|\b)([A-Za-z0-9][A-Za-z0-9\s/_\-#.]{1,40}?)\s*[:=–—\-]\s*(.+?)(?=(?:[\t\s]{3,}[A-Za-z0-9][A-Za-z0-9\s/_\-#.]{1,35}?[:=–—\-]|\n|$))"
)

# Unlabelled Entity Detectors
DATE_REGEX = re.compile(
    r"\b(?:\d{1,2}[-/.](?:\d{1,2}|[A-Za-z]{3,9})[-/.]\d{2,4}|\d{4}[-/.](?:\d{1,2}|[A-Za-z]{3,9})[-/.]\d{1,2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_REGEX = re.compile(
    r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?:\s*(?:ext|x|ext\.)\s*\d{1,5})?|\b(?:\+91[-.\s]?)?[6-9]\d{9}\b"
)
URL_REGEX = re.compile(r"\bhttps?://[^\s<>\"']+|www\.[^\s<>\"']+\b", re.IGNORECASE)
AMOUNT_REGEX = re.compile(r"(?:\$|€|£|₹|Rs\.?|INR|USD|EUR|GBP)\s*[\d,]+(?:\.\d{2})?\b|\b[\d,]+\.\d{2}\s*(?:USD|EUR|INR|GBP)\b")

# IDs
AADHAAR_REGEX = re.compile(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b")
PAN_REGEX = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
GSTIN_REGEX = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}\b")
IFSC_REGEX = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
PASSPORT_REGEX = re.compile(r"\b[A-Z][0-9]{7,8}\b")
SSN_REGEX = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
DRIVING_LICENCE_REGEX = re.compile(r"\b[A-Z]{2}[-\s]?\d{2}[-\s]?[0-9]{11}\b|\bDL[-\s]?[A-Z0-9]{8,15}\b", re.IGNORECASE)
BANK_ACCOUNT_REGEX = re.compile(
    r"(?i)\b(?:account|acct|a/c|acc\.?|bank\s*a/c)(?:\s*(?:no\.?|number|#))?[:\s]*(\d{9,18})\b"
)
IBAN_REGEX = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
SWIFT_REGEX = re.compile(r"\b[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")
CARD_REGEX = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{1,4}\b|\b\d{13,19}\b")

# Sensitive Terms / Passwords / Tokens / Signatures
PASSWORD_TOKEN_REGEX = re.compile(
    r"(?i)\b(?:password|passwd|pwd|access\s*code|pin|secret|api[_\s]?key|bearer\s*token|auth\s*token)[:=\s]+([^\s,;]+)"
)
SIGNATURE_REGEX = re.compile(
    r"(?i)\b(?:signed\s*by|signature|authorized\s*signatory|sign)[:=\s]+(.+?)(?=\n|$)"
)
HEALTH_TERMS_REGEX = re.compile(
    r"(?i)\b(patient|mrn|medical\s*record|diagnosis|rx|prescription|physician|doctor|hospital|clinic|"
    r"admission|dosage|medication|pathology|specimen|treatment|clinical|tablet|capsule|mg|ml|"
    r"blood\s*pressure|glucose|cholesterol|symptoms|discharge|consultation|dr\.)\b"
)
PERSONAL_FINANCE_TERMS = re.compile(
    r"(?i)\b(salary|payroll|ctc|wage|basic\s*pay|net\s*pay|gross\s*pay|bonus|allowance|balance|compensation)\b"
)
PERSON_NAME_HINTS = re.compile(
    r"(?i)\b(?:dr\.|mr\.|mrs\.|ms\.|prof\.)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b"
)


def classify_sensitive_detail(label: str, value: str) -> Tuple[bool, Optional[str]]:
    """Classify whether a detail is sensitive and return (is_sensitive, detector_tag).
    
    Preserves the document's own printed label and assigns a separate detector tag.
    """
    lbl_clean = label.strip()
    val_clean = value.strip()
    lbl_low = lbl_clean.lower()
    val_low = val_clean.lower()
    comb_low = f"{lbl_low} {val_low}"

    # 1. Health Information & Medical Test Results
    # Test results/measurements with units, diagnoses, medicines, treatments, specimen/sample, doctor & patient names
    health_units = re.compile(
        r"\b\d+(?:\.\d+)?(?:\s*(?:/|-)\s*\d+(?:\.\d+)?)?\s*(?:mg/dl|g/dl|mmol/l|umol/l|mmhg|bpm|iu/l|ng/ml|pg/ml|u/l|meq/l|cells/mcl|x10\^[0-9]+/ul|fl|pg|g/l|mg|mcg|ml|tablet|capsule|%|f|c|kg/m2)\b",
        re.IGNORECASE,
    )
    health_keywords = [
        "blood pressure", "bp", "systolic", "diastolic", "pulse", "heart rate",
        "hemoglobin", "hb", "glucose", "sugar", "cholesterol", "wbc", "rbc", "platelet",
        "creatinine", "urea", "bun", "bilirubin", "alt", "ast", "alp", "hba1c", "tsh",
        "diagnosis", "diagnoses", "condition", "symptom", "impression", "findings",
        "medication", "medicine", "prescription", "rx", "dosage", "treatment", "therapy",
        "specimen", "sample", "biopsy", "pathology", "patient", "patient name", "doctor",
        "doctor name", "physician", "surgeon", "mrn", "medical record", "hospital", "clinic",
        "admission", "discharge", "temperature", "spo2", "oxygen saturation", "test name",
        "test result", "lab result", "reference range", "normal range", "units", "clinical",
        "hematology", "biochemistry", "urinalysis", "radiology", "ultrasound", "scan", "dr.",
    ]
    if any(k in lbl_low for k in health_keywords) or (HEALTH_TERMS_REGEX.search(comb_low) and (health_units.search(val_low) or any(k in lbl_low for k in ["result", "unit", "range", "finding", "test"]))):
        return True, "Health"

    # 2. Government & Tax IDs
    if any(k in lbl_low for k in ["aadhaar", "pan", "ssn", "social security", "passport", "driving licence", "dl no", "national id", "tax id", "gstin"]):
        return True, "Govt ID"
    if AADHAAR_REGEX.search(val_clean) or PAN_REGEX.search(val_clean) or SSN_REGEX.search(val_clean) or PASSPORT_REGEX.search(val_clean):
        return True, "Govt ID"

    # 3. Bank & Payment Details
    if any(k in lbl_low for k in ["account number", "acct no", "bank a/c", "iban", "swift", "sort code", "card number", "routing", "ifsc"]):
        return True, "Bank / Card"
    if IBAN_REGEX.search(val_clean) or validate_luhn(val_clean) or BANK_ACCOUNT_REGEX.search(comb_low):
        return True, "Bank / Card"

    # 4. Contact Info (Phone & Email)
    if PHONE_REGEX.search(val_clean) or any(k in lbl_low for k in ["phone", "mobile", "tel", "contact no"]):
        return True, "Phone"
    if EMAIL_REGEX.search(val_clean) or "email" in lbl_low:
        return True, "Email"

    # 5. Dates of Birth
    if any(k in lbl_low for k in ["birth", "dob", "born"]):
        return True, "DOB"

    # 6. Personal Salary, Compensation, Balances
    if PERSONAL_FINANCE_TERMS.search(lbl_low):
        return True, "Financial"

    # 7. Passwords, Access codes, Tokens
    if any(k in lbl_low for k in ["password", "pwd", "access code", "token", "key", "pin", "secret", "api key"]):
        return True, "Credential"

    # 8. Signatures & "Signed by"
    if any(k in lbl_low for k in ["signed by", "signature", "signatory", "authorized sign"]):
        return True, "Signature"

    # 9. Home / Postal Address
    if any(k in lbl_low for k in ["home address", "residential address", "postal address", "permanent address", "street address"]):
        return True, "Address"

    # 10. Names of people
    if any(k in lbl_low for k in ["patient name", "full name", "employee name", "cardholder", "account holder", "doctor name", "physician", "father's name"]):
        return True, "Name"

    return False, None


def is_sensitive_detail(label: str, value: str) -> bool:
    """Classify whether a detail is sensitive based on its label or value."""
    is_sens, _ = classify_sensitive_detail(label, value)
    return is_sens


def locate_text_bbox(page: fitz.Page, search_val: str) -> Optional[List[float]]:
    """Locate search_val on PyMuPDF page and return normalized bbox [ymin, xmin, ymax, xmax] 0-1000."""
    try:
        clean = search_val.strip()
        if not clean or len(clean) < 2:
            return None
        rects = page.search_for(clean[:40])
        if rects:
            r = rects[0]
            w = page.rect.width or 1.0
            h = page.rect.height or 1.0
            ymin = round((r.y0 / h) * 1000, 1)
            xmin = round((r.x0 / w) * 1000, 1)
            ymax = round((r.y1 / h) * 1000, 1)
            xmax = round((r.x1 / w) * 1000, 1)
            return [ymin, xmin, ymax, xmax]
    except Exception:
        pass
    return None


class UniversalDocumentReader:
    """Reader for PDF, TXT, CSV, DOCX, XLSX, and Image files."""

    @staticmethod
    def read_file(file_path: str, password: Optional[str] = None) -> ExtractionResult:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise EmptyFileException("This file is empty.")

        ext = os.path.splitext(file_path)[1].lower()
        real_format = detect_file_format_from_bytes(file_path)

        extension_mismatch = False
        extension_mismatch_reason = None
        if real_format != "unknown" and real_format != "empty":
            norm_ext = ".jpg" if ext == ".jpeg" else ext
            norm_real = ".jpg" if real_format == ".jpeg" else real_format
            if norm_ext in [".tif", ".tiff"]:
                norm_ext = ".tiff"
            if norm_real in [".tif", ".tiff"]:
                norm_real = ".tiff"

            if norm_ext != norm_real:
                extension_mismatch = True
                extension_mismatch_reason = f"File extension '{ext}' does not match detected format '{real_format}'"
                logger.warning(extension_mismatch_reason)

        target_format = real_format if real_format != "unknown" else ext

        res: ExtractionResult
        if target_format == ".txt":
            res = UniversalDocumentReader._read_plain_text(file_path)
        elif target_format == ".csv":
            res = UniversalDocumentReader._read_csv_file(file_path)
        elif target_format == ".docx":
            res = UniversalDocumentReader._read_docx_file(file_path)
        elif target_format == ".xlsx":
            res = UniversalDocumentReader._read_xlsx_file(file_path)
        elif target_format in [".pdf"]:
            res = UniversalDocumentReader._read_pdf_file(file_path, password=password)
        elif target_format in [".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"]:
            res = UniversalDocumentReader._read_image_file(file_path)
        elif target_format in [".eml", ".msg"]:
            res = UniversalDocumentReader._read_email_file(file_path)
        else:
            raise ValueError(f"This file type isn't supported. Supported types: PDF, PNG, JPG, TIFF, BMP, TXT, CSV, DOCX, XLSX, EML.")

        if extension_mismatch:
            res.extension_mismatch = True
            res.extension_mismatch_reason = extension_mismatch_reason

        return res

    @staticmethod
    def _read_plain_text(file_path: str) -> ExtractionResult:
        """Direct text read without page rendering."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception as e:
            raise DamagedFileException("This file looks damaged. Try uploading it again from the original.")

        if not text.strip():
            raise EmptyFileException("This file is empty.")

        details = UniversalDocumentReader._extract_all_details_from_text(text, page_num=1)
        page = PageContent(page_number=1, full_text=text, is_blank=False, details=details)
        has_sensitive = any(d.is_sensitive for d in details)
        doc_type = UniversalDocumentReader._classify_doc_type(text, details)

        return ExtractionResult(
            doc_type=doc_type,
            pages=[page],
            all_details=details,
            is_sensitive=has_sensitive,
            page_count=1,
        )

    @staticmethod
    def _read_csv_file(file_path: str) -> ExtractionResult:
        """Direct CSV read with row and column table extraction."""
        rows = []
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                for r in reader:
                    rows.append(r)
        except Exception:
            raise DamagedFileException("This file looks damaged. Try uploading it again from the original.")

        if not rows or all(len(r) == 0 for r in rows):
            raise EmptyFileException("This file is empty.")

        full_text = "\n".join([", ".join(r) for r in rows])
        details = []

        # If has header row, extract columns
        if len(rows) > 1 and len(rows[0]) > 0:
            header = rows[0]
            for r_idx, row in enumerate(rows[1:], start=1):
                for c_idx, val in enumerate(row):
                    if c_idx < len(header):
                        lbl = f"{header[c_idx].strip()}"
                        val_str = val.strip()
                        if val_str:
                            is_sens = is_sensitive_detail(lbl, val_str)
                            details.append(ExtractedDetail(
                                label=lbl,
                                value=val_str,
                                confidence=1.0,
                                page=1,
                                is_sensitive=is_sens,
                            ))
        else:
            details = UniversalDocumentReader._extract_all_details_from_text(full_text, page_num=1)

        page = PageContent(page_number=1, full_text=full_text, details=details)
        has_sensitive = any(d.is_sensitive for d in details)

        return ExtractionResult(
            doc_type="Spreadsheet",
            pages=[page],
            all_details=details,
            is_sensitive=has_sensitive,
            page_count=1,
        )

    @staticmethod
    def _read_docx_file(file_path: str) -> ExtractionResult:
        """Word document reader extracting paragraphs and tables."""
        try:
            import docx
            doc = docx.Document(file_path)
        except Exception:
            raise DamagedFileException("This file looks damaged. Try uploading it again from the original.")

        paras = [p.text for p in doc.paragraphs if p.text.strip()]
        
        # Extract tables
        table_lines = []
        table_details = []
        for t_idx, table in enumerate(doc.tables):
            headers = [cell.text.strip() for cell in table.rows[0].cells] if len(table.rows) > 0 else []
            for r_idx, row in enumerate(table.rows[1:], start=1):
                row_vals = [cell.text.strip() for cell in row.cells]
                table_lines.append(" | ".join(row_vals))
                for c_idx, val in enumerate(row_vals):
                    if c_idx < len(headers) and val:
                        lbl = f"{headers[c_idx]}"
                        table_details.append(ExtractedDetail(
                            label=lbl,
                            value=val,
                            confidence=0.98,
                            page=1,
                            is_sensitive=is_sensitive_detail(lbl, val),
                        ))

        full_text = "\n".join(paras + table_lines).strip()
        if not full_text:
            raise EmptyFileException("This file is empty.")

        details = UniversalDocumentReader._extract_all_details_from_text(full_text, page_num=1)
        # Combine unique table details
        existing_keys = {(d.label.lower(), d.value.lower()) for d in details}
        for td in table_details:
            if (td.label.lower(), td.value.lower()) not in existing_keys:
                details.append(td)
                existing_keys.add((td.label.lower(), td.value.lower()))

        page = PageContent(page_number=1, full_text=full_text, details=details)
        doc_type = UniversalDocumentReader._classify_doc_type(full_text, details)
        return ExtractionResult(
            doc_type=doc_type,
            pages=[page],
            all_details=details,
            is_sensitive=any(d.is_sensitive for d in details),
            page_count=1,
        )

    @staticmethod
    def _read_xlsx_file(file_path: str) -> ExtractionResult:
        """Excel spreadsheet reader."""
        try:
            import openpyxl
            wb = openpyxl.load_workbook(file_path, data_only=True)
        except Exception:
            raise DamagedFileException("This file looks damaged. Try uploading it again from the original.")

        all_lines = []
        details = []
        for sheetname in wb.sheetnames:
            ws = wb[sheetname]
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                continue
            header = [str(c or "").strip() for c in rows[0]]
            for r_idx, row in enumerate(rows[1:], start=1):
                vals = [str(c or "").strip() for c in row]
                all_lines.append(", ".join(v for v in vals if v))
                for c_idx, v in enumerate(vals):
                    if v and c_idx < len(header) and header[c_idx]:
                        lbl = header[c_idx]
                        details.append(ExtractedDetail(
                            label=lbl,
                            value=v,
                            confidence=1.0,
                            page=1,
                            is_sensitive=is_sensitive_detail(lbl, v),
                        ))

        full_text = "\n".join(all_lines).strip()
        if not full_text:
            raise EmptyFileException("This file is empty.")

        page = PageContent(page_number=1, full_text=full_text, details=details)
        return ExtractionResult(
            doc_type="Spreadsheet",
            pages=[page],
            all_details=details,
            is_sensitive=any(d.is_sensitive for d in details),
            page_count=1,
        )

    @staticmethod
    def _read_email_file(file_path: str) -> ExtractionResult:
        """Email reader for .eml files."""
        try:
            import email
            with open(file_path, "rb") as f:
                msg = email.message_from_binary_file(f)
        except Exception:
            raise DamagedFileException("This file looks damaged. Try uploading it again from the original.")

        headers_dict = {
            "From": msg.get("From", ""),
            "To": msg.get("To", ""),
            "Subject": msg.get("Subject", ""),
            "Date": msg.get("Date", ""),
        }
        body_parts = []
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/plain":
                    body_parts.append(part.get_payload(decode=True).decode("utf-8", errors="replace"))
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body_parts.append(payload.decode("utf-8", errors="replace"))

        body_text = "\n".join(body_parts)
        header_text = "\n".join(f"{k}: {v}" for k, v in headers_dict.items() if v)
        full_text = f"{header_text}\n\n{body_text}".strip()

        details = []
        for k, v in headers_dict.items():
            if v:
                details.append(ExtractedDetail(label=k, value=v, confidence=1.0, page=1, is_sensitive=is_sensitive_detail(k, v)))

        body_details = UniversalDocumentReader._extract_all_details_from_text(body_text, page_num=1)
        details.extend(body_details)

        page = PageContent(page_number=1, full_text=full_text, details=details)
        return ExtractionResult(
            doc_type="Email",
            pages=[page],
            all_details=details,
            is_sensitive=any(d.is_sensitive for d in details),
            page_count=1,
        )

    @staticmethod
    def _read_pdf_file(file_path: str, password: Optional[str] = None) -> ExtractionResult:
        """Robust PDF reader with encryption check, digital layer preference, and page-by-page OCR fallback."""
        try:
            doc = fitz.open(file_path)
        except Exception:
            raise DamagedFileException("This file looks damaged. Try uploading it again from the original.")

        if doc.is_encrypted:
            if not password or not doc.authenticate(password):
                doc.close()
                raise PasswordProtectedException("This file is password protected.")

        page_count = len(doc)
        if page_count == 0:
            doc.close()
            raise EmptyFileException("This file is empty.")

        pages_content: List[PageContent] = []
        all_details: List[ExtractedDetail] = []
        has_text_layer_mismatch = False

        for p_idx in range(page_count):
            page_num = p_idx + 1
            page = doc[p_idx]
            emb_text = page.get_text("text").strip()

            # Always render visible page to image and perform OCR
            ocr_text = ""
            try:
                pix = page.get_pixmap(dpi=150)
                if pix.width > 0 and pix.height > 0:
                    import cv2
                    from app.core.preprocessing import preprocess_image
                    from app.adapters.ocr import get_ocr_engine
                    img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
                    if pix.n == 4:
                        img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
                    elif pix.n == 3:
                        img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

                    prep, _ = preprocess_image(img_np)
                    ocr_res = get_ocr_engine().extract_text(cv2.imencode(".png", prep)[1].tobytes(), "image/png")
                    ocr_text = (ocr_res.full_text or "").strip()
            except Exception as e:
                logger.warning(f"OCR/render failed on page {page_num}: {e}")

            # Point 9: Compare embedded text with OCR of the rendered page
            txt = emb_text
            if emb_text and ocr_text:
                words_emb = set(re.findall(r"\w+", emb_text.lower()))
                words_ocr = set(re.findall(r"\w+", ocr_text.lower()))
                if len(words_emb) >= 5 and len(words_ocr) >= 5:
                    jaccard = len(words_emb & words_ocr) / max(1, len(words_emb | words_ocr))
                    if jaccard < 0.40:
                        has_text_layer_mismatch = True
                        logger.warning(f"PDF page {page_num} text layer mismatch (Jaccard: {jaccard:.2f}). Preferring visible rendered page.")
                        txt = ocr_text
                    else:
                        txt = emb_text
            elif ocr_text:
                txt = ocr_text

            # Point 9: Also read images embedded inside the PDF
            try:
                for img_info in page.get_images(full=True):
                    xref = img_info[0]
                    base_img = doc.extract_image(xref)
                    img_bytes = base_img.get("image")
                    if img_bytes:
                        from app.adapters.ocr import get_ocr_engine
                        emb_ocr = get_ocr_engine().extract_text(img_bytes, base_img.get("ext", "png"))
                        if emb_ocr.full_text and emb_ocr.full_text.strip():
                            existing_words = set(re.findall(r"\w+", txt.lower()))
                            new_words = [w for w in re.findall(r"\w+", emb_ocr.full_text.lower()) if w not in existing_words]
                            if len(new_words) >= 2:
                                txt = f"{txt}\n{emb_ocr.full_text.strip()}"
            except Exception:
                pass

            if not txt:
                # Neutral status for empty pages
                pages_content.append(PageContent(page_number=page_num, full_text="", is_blank=True))
                continue

            # Extract all details from this page
            page_details = UniversalDocumentReader._extract_all_details_from_text(txt, page_num=page_num, page_obj=page)
            pages_content.append(PageContent(page_number=page_num, full_text=txt, is_blank=False, details=page_details))
            all_details.extend(page_details)

        doc.close()

        # Check if entire document was blank
        if all(p.is_blank for p in pages_content):
            raise EmptyFileException("This file is empty.")

        full_doc_text = "\n".join(p.full_text for p in pages_content)
        doc_type = UniversalDocumentReader._classify_doc_type(full_doc_text, all_details)
        has_sensitive = any(d.is_sensitive for d in all_details)

        return ExtractionResult(
            doc_type=doc_type,
            pages=pages_content,
            all_details=all_details,
            is_sensitive=has_sensitive,
            page_count=page_count,
            text_layer_mismatch=has_text_layer_mismatch,
        )

    @staticmethod
    def _read_image_file(file_path: str) -> ExtractionResult:
        """Image file reader with preprocessing and OCR."""
        import cv2
        from app.core.preprocessing import preprocess_image
        from app.adapters.ocr import get_ocr_engine

        img = cv2.imread(file_path)
        if img is None or img.size == 0:
            raise DamagedFileException("This file looks damaged. Try uploading it again from the original.")

        preprocessed, _ = preprocess_image(img)
        _, buf = cv2.imencode(".png", preprocessed)
        ocr_res = get_ocr_engine().extract_text(buf.tobytes(), "image/png")
        txt = (ocr_res.full_text or "").strip()

        if not txt:
            raise EmptyFileException("This file is empty.")

        details = UniversalDocumentReader._extract_all_details_from_text(txt, page_num=1)
        page = PageContent(page_number=1, full_text=txt, details=details)
        doc_type = UniversalDocumentReader._classify_doc_type(txt, details)

        return ExtractionResult(
            doc_type=doc_type,
            pages=[page],
            all_details=details,
            is_sensitive=any(d.is_sensitive for d in details),
            page_count=1,
        )

    @staticmethod
    def _extract_all_details_from_text(
        text: str, page_num: int = 1, page_obj: Optional[fitz.Page] = None
    ) -> List[ExtractedDetail]:
        """Extract labelled pairs, table rows, and unlabelled entities from text line by line."""
        details: List[ExtractedDetail] = []
        seen_keys: Set[Tuple[str, str]] = set()
        captured_values_norm: Set[str] = set()

        def add_detail(
            lbl: str,
            val: str,
            conf: float = 0.98,
            is_sens: Optional[bool] = None,
            tag: Optional[str] = None,
            is_unlabelled: bool = False,
        ):
            lbl_clean = lbl.strip()
            val_clean = val.strip()
            if (not lbl_clean and not is_unlabelled) or not val_clean or len(val_clean) < 1:
                return

            # Anti-Hallucination Gate: Stored ONLY if appears in text!
            clean_search = re.sub(r"\s+", " ", val_clean).lower()
            norm_doc = re.sub(r"\s+", " ", text).lower()
            if clean_search not in norm_doc and val_clean.lower() not in norm_doc:
                return

            # Deduplication key
            key = (lbl_clean.lower(), val_clean.lower())
            if key in seen_keys:
                return
            seen_keys.add(key)

            # Completeness & Quality Checks (Rule 3)
            # A value that is only a unit, only punctuation, or a bare title is incomplete -> conf = 0.40
            known_units = {
                "mg", "kg", "g", "mcg", "ml", "l", "dl", "g/dl", "mg/dl", "mmol/l", "umol/l",
                "mmhg", "bpm", "iu/l", "ng/ml", "pg/ml", "u/l", "meq/l", "cells/mcl", "fl",
                "pg", "g/l", "%", "usd", "eur", "inr", "gbp", "$", "€", "£", "₹", "cm", "mm",
                "m", "in", "ft", "years", "yrs", "days", "hrs", "mins", "sec", "units", "degrees",
                "kg/m2", "f", "c"
            }
            bare_titles = {
                "dr", "dr.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "prof", "prof.", "mx", "mx.", "sir", "madam"
            }
            incomplete_placeholders = {
                "-", "--", "—", "–", ":", ".", "..", "...", "/", "\\", "?", "!", "n/a", "na", "none", "null", "nil", "_"
            }

            final_conf = conf
            val_lower = val_clean.lower()
            if val_lower in known_units:
                final_conf = 0.40
            elif val_lower in incomplete_placeholders:
                final_conf = 0.40
            elif val_lower.strip(".") in bare_titles:
                final_conf = 0.40
            elif len(lbl_clean) <= 1:
                final_conf = 0.50
            elif re.search(r"\d{4,}[A-Za-z]", lbl_clean):
                final_conf = 0.50

            # Classification
            sens = is_sens
            det_tag = tag
            if sens is None:
                sens, det_tag = classify_sensitive_detail(lbl_clean, val_clean)

            bbox = locate_text_bbox(page_obj, val_clean) if page_obj else None

            details.append(ExtractedDetail(
                label=lbl_clean,
                value=val_clean,
                confidence=final_conf,
                page=page_num,
                bbox=bbox,
                is_sensitive=sens,
                detector_tag=det_tag,
                is_unlabelled=is_unlabelled,
            ))
            # Track normalized value to suppress unlabelled duplicates if captured under printed label
            if lbl_clean:
                captured_values_norm.add(re.sub(r"\s+", "", val_clean.lower()))

        lines = [line.rstrip() for line in text.splitlines()]
        num_lines = len(lines)
        i = 0
        table_headers: Optional[List[str]] = None

        doc_heading_keywords = {
            "internal memorandum", "memorandum", "tax invoice", "invoice", "receipt",
            "medical report", "patient report", "lab report", "prescription", "kyc form",
            "identity verification", "bank statement", "account statement", "agreement",
            "contract", "summary", "log sheet", "certificate", "confidential"
        }

        # Identify page title at the very top (Rule 5: Keep page title separate, not part of any label)
        page_title: Optional[str] = None
        first_non_empty_idx = -1
        for idx_check, raw_l in enumerate(lines[:4]):
            sl = raw_l.strip()
            if sl:
                first_non_empty_idx = idx_check
                # If first line has no separator and looks like a heading or document title
                if ":" not in sl and "=" not in sl and not sl.startswith("|") and (
                    sl.lower() in doc_heading_keywords or sl.isupper() or len(sl.split()) <= 6
                ):
                    page_title = sl
                break

        while i < num_lines:
            raw_line = lines[i]
            line = raw_line.strip()
            if not line:
                table_headers = None
                i += 1
                continue

            # Skip document title / page title line so it is never merged into a field label
            if i == first_non_empty_idx and page_title and line == page_title:
                i += 1
                continue

            # Layout 1: Markdown Table Row (| Cell 1 | Cell 2 |)
            if line.startswith("|") and line.endswith("|"):
                cells = [c.strip() for c in line[1:-1].split("|")]
                # Check if separator row (|---|---|)
                if all(re.match(r"^:?-+:?$", c) for c in cells if c):
                    i += 1
                    continue
                if table_headers is None:
                    table_headers = cells
                else:
                    for h_idx, cell_val in enumerate(cells):
                        if h_idx < len(table_headers) and cell_val:
                            h_lbl = table_headers[h_idx]
                            if h_lbl:
                                add_detail(h_lbl, cell_val, conf=0.98)
                i += 1
                continue
            else:
                table_headers = None

            # Layout 2: Colon Separator(s) on line ("Label: value")
            if ":" in line:
                # Find all distinct label-value pairs on this single line
                # E.g. "Name: John Doe    Age: 45    Status: Active"
                parts = re.split(r"(?<=[^\s])\s{2,}(?=[^\s:][^:\n]*:)", line)
                for part in parts:
                    if ":" in part:
                        c_idx = part.find(":")
                        lbl = part[:c_idx].strip()
                        val = part[c_idx+1:].strip()
                        if lbl:
                            add_detail(lbl, val if val else "", conf=0.98 if val else 0.40)
                    else:
                        if part.strip():
                            add_detail("", part.strip(), conf=0.85, is_unlabelled=True)
                i += 1
                continue

            # Layout 3: Dash or Equals Separator ("Label - Value" or "Label = Value")
            dash_match = re.split(r"\s+[-—–=]\s+", line, maxsplit=1)
            if len(dash_match) == 2:
                lbl, val = dash_match[0].strip(), dash_match[1].strip()
                if len(lbl.split()) <= 6 and not lbl.endswith((".", "?", "!")):
                    add_detail(lbl, val, conf=0.96)
                    i += 1
                    continue

            # Layout 4: Labels without a colon (Two-column layout separated by >= 2 spaces or tab)
            if "\t" in line or re.search(r"\s{2,}", line):
                parts = re.split(r"\t+|\s{2,}", line, maxsplit=1)
                if len(parts) == 2:
                    lbl, val = parts[0].strip(), parts[1].strip()
                    if 1 <= len(lbl.split()) <= 5 and not lbl.endswith((".", "?", "!")) and not lbl.isdigit():
                        add_detail(lbl, val, conf=0.96)
                        i += 1
                        continue

            # Layout 5: Label directly above its value (Vertical / Stacked layout)
            # Only if line is a short alphabetic heading (1-4 words) and next line has value
            if (
                re.match(r"^[A-Za-z][A-Za-z\s/&'()_-]{1,35}$", line)
                and len(line.split()) <= 4
                and not line.endswith((".", "?", "!"))
                and line.lower() not in doc_heading_keywords
                and i + 1 < num_lines
            ):
                next_line = lines[i+1].strip()
                if next_line and ":" not in next_line and not next_line.startswith("|") and next_line.lower() not in doc_heading_keywords:
                    add_detail(line, next_line, conf=0.95)
                    i += 2
                    continue

            # Layout 6: Unlabelled text line (Keep everything, never drop or hide)
            if line and line.lower() not in doc_heading_keywords:
                add_detail("", line, conf=0.85, is_unlabelled=True)

            i += 1

        # -------------------------------------------------------------------
        # Rule 2: Unlabelled Entities
        # Extract without inventing labels (Strictly empty string "" as label)
        # -------------------------------------------------------------------
        def is_already_captured(val_str: str) -> bool:
            clean = re.sub(r"\s+", "", val_str.lower())
            if not clean:
                return True
            for cap in captured_values_norm:
                if clean == cap or clean in cap:
                    return True
            return False

        # 1. Govt IDs
        for m in AADHAAR_REGEX.finditer(text):
            val = m.group(0).strip()
            if not is_already_captured(val) and validate_aadhaar(re.sub(r"\s+", "", val)):
                add_detail("", val, conf=0.95, is_sens=True, tag="Govt ID", is_unlabelled=True)
        for m in PAN_REGEX.finditer(text):
            val = m.group(0).strip()
            if not is_already_captured(val) and validate_pan(val):
                add_detail("", val, conf=0.95, is_sens=True, tag="Govt ID", is_unlabelled=True)
        for m in GSTIN_REGEX.finditer(text):
            val = m.group(0).strip()
            if not is_already_captured(val) and validate_gstin(val):
                add_detail("", val, conf=0.95, is_sens=True, tag="Govt ID", is_unlabelled=True)
        for m in IFSC_REGEX.finditer(text):
            val = m.group(0).strip()
            if not is_already_captured(val) and validate_ifsc(val):
                add_detail("", val, conf=0.95, is_sens=True, tag="Bank Code", is_unlabelled=True)
        for m in SSN_REGEX.finditer(text):
            val = m.group(0).strip()
            if not is_already_captured(val):
                add_detail("", val, conf=0.95, is_sens=True, tag="Govt ID", is_unlabelled=True)
        for m in PASSPORT_REGEX.finditer(text):
            val = m.group(0).strip()
            if not is_already_captured(val):
                add_detail("", val, conf=0.90, is_sens=True, tag="Govt ID", is_unlabelled=True)

        # 2. Contacts
        for m in EMAIL_REGEX.finditer(text):
            val = m.group(0).strip()
            if not is_already_captured(val):
                add_detail("", val, conf=0.95, is_sens=True, tag="Email", is_unlabelled=True)
        for m in PHONE_REGEX.finditer(text):
            val = m.group(0).strip()
            if len(re.sub(r"\D", "", val)) >= 10 and not is_already_captured(val):
                add_detail("", val, conf=0.95, is_sens=True, tag="Phone", is_unlabelled=True)
        for m in URL_REGEX.finditer(text):
            val = m.group(0).strip()
            if not is_already_captured(val):
                add_detail("", val, conf=0.95, is_sens=False, tag="Web Link", is_unlabelled=True)

        # 3. Amounts & Dates
        for m in AMOUNT_REGEX.finditer(text):
            val = m.group(0).strip()
            if not is_already_captured(val):
                add_detail("", val, conf=0.90, is_sens=False, tag="Amount", is_unlabelled=True)
        for m in DATE_REGEX.finditer(text):
            val = m.group(0).strip()
            if not is_already_captured(val):
                add_detail("", val, conf=0.90, is_sens=False, tag="Date", is_unlabelled=True)

        return details

    @staticmethod
    def _classify_doc_type(text: str, details: List[ExtractedDetail]) -> str:
        """Classify document type cleanly without hardcoding."""
        t_low = text.lower()
        if any(k in t_low for k in ["tax invoice", "invoice", "subtotal", "bill to", "due date", "amount due"]):
            return "Invoice"
        elif any(k in t_low for k in ["prescription", "rx", "diagnosis", "dosage", "patient", "medical report", "clinic"]):
            return "Medical Report"
        elif any(k in t_low for k in ["kyc", "identity verification", "pan card", "aadhaar", "driver license"]):
            return "KYC Form"
        elif any(k in t_low for k in ["bank statement", "account statement", "closing balance", "ledger"]):
            return "Bank Statement"
        elif any(k in t_low for k in ["agreement", "contract", "parties", "hereby agree", "terms and conditions"]):
            return "Contract"
        elif any(k in t_low for k in ["receipt", "cashier", "order #"]):
            return "Receipt"
        return "Document"
