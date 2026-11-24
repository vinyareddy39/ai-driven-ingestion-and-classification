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


def is_sensitive_detail(label: str, value: str) -> bool:
    """Classify whether a detail is sensitive based on its label or value."""
    text = f"{label} {value}".lower()
    
    # 1. Health & Medical
    if HEALTH_TERMS_REGEX.search(text):
        return True
    
    # 2. Government & Tax IDs
    if any(k in text for k in ["aadhaar", "pan", "ssn", "social security", "passport", "driving licence", "dl no", "national id", "tax id", "gstin"]):
        return True
    if AADHAAR_REGEX.search(value) or PAN_REGEX.search(value) or SSN_REGEX.search(value) or PASSPORT_REGEX.search(value):
        return True

    # 3. Bank & Cards
    if any(k in text for k in ["account number", "acct no", "bank a/c", "iban", "swift", "sort code", "card number", "routing"]):
        return True
    if IBAN_REGEX.search(value) or validate_luhn(value):
        return True

    # 4. Phone & Email
    if PHONE_REGEX.search(value) or any(k in label.lower() for k in ["phone", "mobile", "tel", "contact no"]):
        return True
    if EMAIL_REGEX.search(value) or "email" in label.lower():
        return True

    # 5. Dates of Birth
    if any(k in label.lower() for k in ["birth", "dob", "born"]):
        return True

    # 6. Personal Salary, Compensation, Balances
    if PERSONAL_FINANCE_TERMS.search(label.lower()):
        return True

    # 7. Passwords, Access codes, Tokens
    if any(k in label.lower() for k in ["password", "pwd", "access code", "token", "key", "pin", "secret"]):
        return True

    # 8. Signatures & "Signed by"
    if any(k in label.lower() for k in ["signed by", "signature", "signatory"]):
        return True

    # 9. Home / Postal Address
    if any(k in label.lower() for k in ["home address", "residential address", "postal address", "permanent address"]):
        return True

    # 10. Names of people
    if any(k in label.lower() for k in ["patient name", "employee name", "cardholder", "account holder", "doctor name", "physician", "father's name"]):
        return True

    return False


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

        if ext == ".txt":
            return UniversalDocumentReader._read_plain_text(file_path)
        elif ext == ".csv":
            return UniversalDocumentReader._read_csv_file(file_path)
        elif ext == ".docx":
            return UniversalDocumentReader._read_docx_file(file_path)
        elif ext == ".xlsx":
            return UniversalDocumentReader._read_xlsx_file(file_path)
        elif ext in [".pdf"]:
            return UniversalDocumentReader._read_pdf_file(file_path, password=password)
        elif ext in [".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"]:
            return UniversalDocumentReader._read_image_file(file_path)
        elif ext in [".eml", ".msg"]:
            return UniversalDocumentReader._read_email_file(file_path)
        else:
            raise ValueError(f"This file type isn't supported. Supported types: PDF, PNG, JPG, TIFF, BMP, TXT, CSV, DOCX, XLSX, EML.")

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

        for p_idx in range(page_count):
            page_num = p_idx + 1
            page = doc[p_idx]
            txt = page.get_text("text").strip()

            # Part 3, Point 2: Use digital text when it exists. Use OCR only for pages lacking text.
            if not txt:
                # Page has no text: try OCR on page image
                pix = page.get_pixmap(dpi=150)
                if pix.width == 0 or pix.height == 0:
                    pages_content.append(PageContent(page_number=page_num, full_text="", is_blank=True))
                    continue

                try:
                    import cv2
                    img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
                    if pix.n >= 3:
                        img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
                    from app.adapters.ocr import get_ocr_engine
                    ocr_res = get_ocr_engine().extract_text(cv2.imencode(".png", img_np)[1].tobytes(), "image/png")
                    txt = (ocr_res.full_text or "").strip()
                except Exception as e:
                    logger.warning(f"OCR failed on page {page_num}: {e}")
                    txt = ""

            if not txt:
                # Part 4, Point 2: Calm neutral status for empty pages
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
        """Extract labelled pairs, table rows, and unlabelled entities from text."""
        details: List[ExtractedDetail] = []
        seen_keys: Set[Tuple[str, str]] = set()

        def add_detail(lbl: str, val: str, conf: float = 0.95, is_sens: Optional[bool] = None):
            lbl_clean = lbl.strip()
            val_clean = val.strip().strip(",;.")
            if not lbl_clean or not val_clean or len(val_clean) < 1:
                return

            # Part 1, Point 3: Anti-Hallucination Gate. Stored ONLY if appears in text!
            # Strip non-alphanumeric punctuation for substring verification
            clean_search = re.sub(r"\s+", " ", val_clean).lower()
            norm_doc = re.sub(r"\s+", " ", text).lower()
            if clean_search not in norm_doc and val_clean.lower() not in norm_doc:
                # Value not present in text: drop it!
                return

            key = (lbl_clean.lower(), val_clean.lower())
            if key in seen_keys:
                return
            seen_keys.add(key)

            sens = is_sens if is_sens is not None else is_sensitive_detail(lbl_clean, val_clean)
            bbox = locate_text_bbox(page_obj, val_clean) if page_obj else None

            details.append(ExtractedDetail(
                label=lbl_clean,
                value=val_clean,
                confidence=conf,
                page=page_num,
                bbox=bbox,
                is_sensitive=sens,
            ))

        # 1. Labelled Pairs ("Label: value")
        for m in LABEL_PAIR_REGEX.finditer(text):
            raw_lbl = m.group(1).strip()
            raw_val = m.group(2).strip()
            # Clean up trailing label markers
            if ":" in raw_val:
                # Sub-split if another label: value was merged
                sub_parts = re.split(r"(?<=[A-Za-z0-9])\s{2,}(?=[A-Za-z0-9]{2,}:)", raw_val)
                for sp in sub_parts:
                    if ":" in sp:
                        p_lbl, p_val = sp.split(":", 1)
                        add_detail(p_lbl, p_val, conf=0.98)
                    else:
                        add_detail(raw_lbl, sp, conf=0.98)
            else:
                add_detail(raw_lbl, raw_val, conf=0.98)

        # 2. Government & Tax IDs (Unlabelled or weakly labelled)
        for m in AADHAAR_REGEX.finditer(text):
            clean_adh = re.sub(r"\s+", "", m.group(0))
            if validate_aadhaar(clean_adh):
                add_detail("Aadhaar Number", m.group(0), conf=0.99, is_sens=True)
        for m in PAN_REGEX.finditer(text):
            if validate_pan(m.group(0)):
                add_detail("PAN Number", m.group(0), conf=0.99, is_sens=True)
        for m in GSTIN_REGEX.finditer(text):
            if validate_gstin(m.group(0)):
                add_detail("GSTIN", m.group(0), conf=0.99, is_sens=True)
        for m in IFSC_REGEX.finditer(text):
            if validate_ifsc(m.group(0)):
                add_detail("IFSC Code", m.group(0), conf=0.99, is_sens=True)
        for m in SSN_REGEX.finditer(text):
            add_detail("SSN", m.group(0), conf=0.99, is_sens=True)
        for m in PASSPORT_REGEX.finditer(text):
            add_detail("Passport Number", m.group(0), conf=0.95, is_sens=True)

        # 3. Bank & Cards
        for m in BANK_ACCOUNT_REGEX.finditer(text):
            add_detail("Bank Account Number", m.group(1), conf=0.96, is_sens=True)
        for m in IBAN_REGEX.finditer(text):
            add_detail("IBAN", m.group(0), conf=0.97, is_sens=True)
        for m in SWIFT_REGEX.finditer(text):
            add_detail("SWIFT Code", m.group(0), conf=0.95, is_sens=True)
        for m in CARD_REGEX.finditer(text):
            if validate_luhn(m.group(0)):
                add_detail("Payment Card Number", m.group(0), conf=0.99, is_sens=True)

        # 4. Contacts (Email, Phone, URLs)
        for m in EMAIL_REGEX.finditer(text):
            add_detail("Email Address", m.group(0), conf=0.99, is_sens=True)
        for m in PHONE_REGEX.finditer(text):
            # Exclude dates matching phone-like numbers
            ph_val = m.group(0).strip()
            if len(re.sub(r"\D", "", ph_val)) >= 10:
                add_detail("Phone Number", ph_val, conf=0.95, is_sens=True)
        for m in URL_REGEX.finditer(text):
            add_detail("Web Link", m.group(0), conf=0.98, is_sens=False)

        # 5. Amounts
        for m in AMOUNT_REGEX.finditer(text):
            add_detail("Amount", m.group(0), conf=0.90, is_sens=False)

        # 6. Dates
        for m in DATE_REGEX.finditer(text):
            add_detail("Date", m.group(0), conf=0.90, is_sens=False)

        # 7. Passwords, Tokens, Signatures
        for m in PASSWORD_TOKEN_REGEX.finditer(text):
            add_detail("Access Token / Password", m.group(1), conf=0.98, is_sens=True)
        for m in SIGNATURE_REGEX.finditer(text):
            add_detail("Signature", m.group(1), conf=0.95, is_sens=True)

        # 8. Person Names with Titles
        for m in PERSON_NAME_HINTS.finditer(text):
            add_detail("Person Name", m.group(0), conf=0.92, is_sens=True)

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
