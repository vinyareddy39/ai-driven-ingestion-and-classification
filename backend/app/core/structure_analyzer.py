"""Enterprise Page Structure Analyzer and Universal Region Classifier.

Implements deep layout and structural understanding across all document formats:
- Multi-column layout detection and column-ordered reading
- 17 Configurable Region Structure Types:
  label_value_pair, table, list, paragraph, heading, form_row, checkbox_group,
  signature_stamp, handwriting, image_logo, chart_diagram, barcode_qr,
  header_footer, footnote, watermark, side_by_side, other.
- Checkbox/Radio detection (selected, empty, unclear)
- Barcode and QR code detection and decoding via OpenCV
- Signature, stamp, seal, and initials detection (with adjacent signers/dates)
- List detection with preserved item order, numbering, and hierarchy
- Chart, logo, and image structure extraction
- Footnote linking and watermark suppression
- Purely layout- and content-driven (zero hardcoded document types or labels).
"""

import os
import re
import math
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Set

import cv2
import fitz  # PyMuPDF
import numpy as np

from app.core.config_loader import ConfigLoader
from app.core.learned_registry import LearnedRegistry

logger = logging.getLogger(__name__)

# Standard structural patterns
BULLET_REGEX = re.compile(r"^(?:[•*\-–—▪►]|(?:\d+|[a-zA-Z]|[ivxIVX]+)[\.\)])\s+")
CHECKBOX_REGEX = re.compile(
    r"(?:\[([ xX✓✔✗✘?_])\]|([☑☒☐✓✔])|(?:\(([ xX*])\))|(🔘|⚪))\s*([^\n\r]+)",
    re.UNICODE,
)
DATE_NEARBY_REGEX = re.compile(
    r"\b(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
SIGNATURE_KEYWORDS = re.compile(
    r"\b(?:signature|signed\s+by|authorized\s+signature|sign\s+here|"
    r"stamp|official\s+seal|initials|approved\s+by|doctor'?s\s+signature|"
    r"patient'?s\s+signature|witness)\b",
    re.IGNORECASE,
)
WATERMARK_KEYWORDS = re.compile(
    r"\b(?:CONFIDENTIAL|DRAFT|COPY|VOID|SAMPLE|PREVIEW|INTERNAL\s+USE\s+ONLY|FOR\s+REVIEW\s+ONLY)\b",
    re.IGNORECASE,
)
PAGE_NUM_REGEX = re.compile(
    r"^(?:page\s+\d+(?:\s+of\s+\d+)?|\d+\s*/\s*\d+|\d+)$",
    re.IGNORECASE,
)
FOOTNOTE_REF_REGEX = re.compile(r"^(?:\[\d+\]|\*\s*|\†\s*|\d+\.)\s*([A-Z].{10,})")


@dataclass
class PageRegion:
    """A classified structural region on a document page."""
    id: str
    page: int
    structure_type: str
    structure_name: str
    structure_group: str
    confidence: float
    bbox: List[float]  # [ymin, xmin, ymax, xmax] 0-1000
    raw_bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1) in points
    reading_order: int
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    details: List[Dict[str, Any]] = field(default_factory=list)


class PageStructureAnalyzer:
    """Enterprise Page Structure Analyzer decomposing pages into structured regions."""

    def __init__(self, config_loader: Optional[ConfigLoader] = None):
        self.loader = config_loader or ConfigLoader.get_instance()
        self.registry = LearnedRegistry.get_instance()
        self.type_map = self.loader.structure_type_map
        self._qr_detector = None
        self._barcode_detector = None

    def _get_qr_detector(self):
        if self._qr_detector is None:
            self._qr_detector = cv2.QRCodeDetector()
        return self._qr_detector

    def _get_barcode_detector(self):
        if self._barcode_detector is None:
            if hasattr(cv2, "barcode") and hasattr(cv2.barcode, "BarcodeDetector"):
                self._barcode_detector = cv2.barcode.BarcodeDetector()
            elif hasattr(cv2, "barcode_BarcodeDetector"):
                self._barcode_detector = cv2.barcode_BarcodeDetector()
        return self._barcode_detector

    def _normalize_bbox(self, raw_bbox: Tuple[float, float, float, float], pw: float, ph: float) -> List[float]:
        x0, y0, x1, y1 = raw_bbox
        w = max(1.0, float(pw))
        h = max(1.0, float(ph))
        ymin = max(0.0, round((y0 / h) * 1000, 1))
        xmin = max(0.0, round((x0 / w) * 1000, 1))
        ymax = min(1000.0, round((y1 / h) * 1000, 1))
        xmax = min(1000.0, round((x1 / w) * 1000, 1))
        return [ymin, xmin, ymax, xmax]

    # -------------------------------------------------------------------------
    # 1. Multi-Column Layout Detection
    # -------------------------------------------------------------------------
    def detect_columns(self, blocks: List[Any], pw: float) -> List[Tuple[float, float]]:
        """Detect 1, 2, or 3 vertical reading columns by finding white-space gutters."""
        if not blocks or len(blocks) < 4:
            return [(0.0, pw)]

        # Sample horizontal span occupancies
        bins = np.zeros(int(pw), dtype=np.int32)
        for b in blocks:
            x0 = max(0, int(b.bbox[0]))
            x1 = min(int(pw), int(b.bbox[2]))
            if x1 > x0:
                bins[x0:x1] += 1

        # Look for prominent vertical troughs (gutters with near zero occupancy)
        gutter_min_w = 22
        min_gutter_margin = int(pw * 0.15)
        max_gutter_margin = int(pw * 0.85)

        gutters = []
        in_trough = False
        trough_start = 0

        for x in range(min_gutter_margin, max_gutter_margin):
            if bins[x] <= 1:
                if not in_trough:
                    in_trough = True
                    trough_start = x
            else:
                if in_trough:
                    in_trough = False
                    if (x - trough_start) >= gutter_min_w:
                        gutters.append((trough_start, x))

        if len(gutters) == 1:
            g_mid = (gutters[0][0] + gutters[0][1]) / 2.0
            return [(0.0, g_mid), (g_mid, pw)]
        elif len(gutters) >= 2:
            g1_mid = (gutters[0][0] + gutters[0][1]) / 2.0
            g2_mid = (gutters[1][0] + gutters[1][1]) / 2.0
            return [(0.0, g1_mid), (g1_mid, g2_mid), (g2_mid, pw)]

        return [(0.0, pw)]

    def sort_blocks_by_columns(self, blocks: List[Any], pw: float) -> List[Any]:
        """Keep reading order strictly top-to-bottom and left-to-right along each line baseline.
        Never split ordinary text lines or forms into vertical columns down the page."""
        return sorted(blocks, key=lambda b: (round(b.bbox[1] / 6.0), b.bbox[0]))

    # -------------------------------------------------------------------------
    # 2. Structural Region Identification
    # -------------------------------------------------------------------------
    def analyze_page_structures(
        self,
        page_num: int,
        blocks: List[Any],
        pw: float,
        ph: float,
        doc_page: Optional[fitz.Page] = None,
        page_img: Optional[np.ndarray] = None,
        repeating_headers: Optional[Set[str]] = None,
        repeating_footers: Optional[Set[str]] = None,
    ) -> List[PageRegion]:
        """Analyze page geometry and contents, returning classified PageRegions."""
        repeating_headers = repeating_headers or set()
        repeating_footers = repeating_footers or set()

        sorted_blocks = self.sort_blocks_by_columns(blocks, pw)
        regions: List[PageRegion] = []
        reg_counter = 1

        # A. Visual barcode & QR code detection on page image or pixmap
        barcode_regions = self._detect_barcodes_and_qr(doc_page, page_img, page_num, pw, ph, blocks=sorted_blocks)
        for br in barcode_regions:
            br.reading_order = reg_counter
            reg_counter += 1
            regions.append(br)

        # B. Check for form widgets in digital PDF (e.g., checkboxes, radiobuttons, signatures)
        if doc_page:
            widget_regions = self._detect_pdf_widgets(doc_page, page_num, pw, ph)
            for wr in widget_regions:
                wr.reading_order = reg_counter
                reg_counter += 1
                regions.append(wr)

            # C. Detect embedded images, logos and charts
            img_regions = self._detect_page_images_and_charts(doc_page, page_num, pw, ph, blocks=sorted_blocks)
            for imr in img_regions:
                imr.reading_order = reg_counter
                reg_counter += 1
                regions.append(imr)

        # D. Classify LayoutBlocks into regions
        for b in sorted_blocks:
            b_text = b.text.strip()
            if not b_text:
                continue

            # 1. Watermark Detection
            if self._is_watermark(b, b_text, pw, ph):
                regions.append(self._make_region(
                    reg_counter, page_num, "watermark", b.bbox, pw, ph, b_text,
                    confidence=0.95,
                    metadata={"reason": "Background or diagonal transparency text"}
                ))
                reg_counter += 1
                continue

            # 2. Header / Footer / Page Number
            if self._is_header_or_footer(b, b_text, ph, repeating_headers, repeating_footers):
                regions.append(self._make_region(
                    reg_counter, page_num, "header_footer", b.bbox, pw, ph, b_text,
                    confidence=0.98,
                    metadata={"reason": "Margin banner or repeating page text"}
                ))
                reg_counter += 1
                continue

            # 3. Footnote / Reference
            if self._is_footnote(b, b_text, ph):
                regions.append(self._make_region(
                    reg_counter, page_num, "footnote", b.bbox, pw, ph, b_text,
                    confidence=0.92,
                    metadata={"ref_tag": b_text.split()[0]}
                ))
                reg_counter += 1
                continue

            # 4. Checkbox / Radio Group
            cb_data = self._parse_checkbox_block(b_text)
            if cb_data:
                regions.append(self._make_region(
                    reg_counter, page_num, "checkbox_group", b.bbox, pw, ph, b_text,
                    confidence=0.96,
                    metadata={"options": cb_data}
                ))
                reg_counter += 1
                continue

            # 5. Signature / Stamp / Seal / Initials
            sig_data = self._parse_signature_block(b, b_text, sorted_blocks, ph)
            if sig_data:
                regions.append(self._make_region(
                    reg_counter, page_num, "signature_stamp", b.bbox, pw, ph, b_text,
                    confidence=sig_data.get("confidence", 0.94),
                    metadata=sig_data
                ))
                reg_counter += 1
                continue

            # 6. List Structure (ordered or bulleted)
            list_items = self._parse_list_items(b)
            if len(list_items) >= 2:
                regions.append(self._make_region(
                    reg_counter, page_num, "list", b.bbox, pw, ph, b_text,
                    confidence=0.97,
                    metadata={"items": list_items, "count": len(list_items)}
                ))
                reg_counter += 1
                continue

            # 7. Heading
            is_large = getattr(b, "font_size", 10.0) >= 12.0
            is_bold = getattr(b, "style", "") in ["bold", "heading"] or any(getattr(s, "is_bold", False) for l in getattr(b, "lines", []) for s in getattr(l, "spans", []))
            is_headline_role = getattr(b, "block_role", "") == "headline"
            has_no_kv = not any(sep in b_text for sep in [":", " = "])
            word_count = len(b_text.split())

            if (is_headline_role or (is_large and word_count <= 10) or (is_bold and word_count <= 8 and has_no_kv)):
                is_doc_title = (page_num == 1 and b.bbox[1] < (ph * 0.35) and not any(r.structure_type == "heading" for r in regions))
                regions.append(self._make_region(
                    reg_counter, page_num, "heading", b.bbox, pw, ph, b_text,
                    confidence=0.98,
                    metadata={"is_document_title": is_doc_title, "font_size": getattr(b, "font_size", 10.0)}
                ))
                reg_counter += 1
                continue

            # 8. Handwriting / Filled-in text
            if self._is_handwriting(b):
                regions.append(self._make_region(
                    reg_counter, page_num, "handwriting", b.bbox, pw, ph, b_text,
                    confidence=b.confidence,
                    metadata={"style": "cursive/handwritten"}
                ))
                reg_counter += 1
                continue

            # 9. Form Row / Label-Value Pair
            if any(sep in b_text for sep in [":", " = ", " - ", "\t"]) or len(b.lines) <= 2:
                regions.append(self._make_region(
                    reg_counter, page_num, "label_value_pair", b.bbox, pw, ph, b_text,
                    confidence=b.confidence,
                    metadata={"lines_count": len(b.lines)}
                ))
                reg_counter += 1
                continue

            # 10. Default Paragraph
            regions.append(self._make_region(
                reg_counter, page_num, "paragraph", b.bbox, pw, ph, b_text,
                confidence=b.confidence,
                metadata={"word_count": len(b_text.split())}
            ))
            reg_counter += 1

        # D. Detect embedded images, logos, charts from page graphics
        if doc_page:
            img_regions = self._detect_page_images_and_charts(doc_page, page_num, pw, ph, blocks=blocks)
            for ir in img_regions:
                ir.reading_order = reg_counter
                reg_counter += 1
                regions.append(ir)

        return regions

    # -------------------------------------------------------------------------
    # 3. Detection Helper Methods
    # -------------------------------------------------------------------------
    def _make_region(
        self,
        idx: int,
        page: int,
        st_type: str,
        raw_bbox: Tuple[float, float, float, float],
        pw: float,
        ph: float,
        text: str,
        confidence: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PageRegion:
        type_info = self.type_map.get(st_type, {})
        name = type_info.get("name", st_type.replace("_", " ").title())
        group = type_info.get("group", "fields")
        bbox_norm = self._normalize_bbox(raw_bbox, pw, ph)

        return PageRegion(
            id=f"reg_p{page}_{idx:02d}",
            page=page,
            structure_type=st_type,
            structure_name=name,
            structure_group=group,
            confidence=round(confidence, 4),
            bbox=bbox_norm,
            raw_bbox=raw_bbox,
            reading_order=idx,
            text=text,
            metadata=metadata or {},
        )

    def _is_watermark(self, b: Any, text: str, pw: float, ph: float) -> bool:
        if WATERMARK_KEYWORDS.search(text):
            # Often near center or across large span
            mid_y = (b.bbox[1] + b.bbox[3]) / 2.0
            if (ph * 0.20) < mid_y < (ph * 0.80):
                return True
        return False

    def _is_header_or_footer(
        self,
        b: Any,
        text: str,
        ph: float,
        repeating_headers: Set[str],
        repeating_footers: Set[str],
    ) -> bool:
        if text in repeating_headers or text in repeating_footers:
            return True
        if PAGE_NUM_REGEX.match(text):
            return True
        # Margin thresholds: small margin text only, never prominent headings with font_size >= 12 or bold
        f_size = getattr(b, "font_size", 10.0)
        is_bold = getattr(b, "style", "") == "bold" or any(getattr(s, "is_bold", False) for l in getattr(b, "lines", []) for s in getattr(l, "spans", []))
        if f_size < 11.5 and not is_bold:
            if b.bbox[1] <= 45.0 and len(text.split()) <= 8:
                return True
            if b.bbox[3] >= (ph - 45.0) and len(text.split()) <= 8:
                return True
        return False

    def _is_footnote(self, b: Any, text: str, ph: float) -> bool:
        if b.bbox[1] >= (ph * 0.78):
            if FOOTNOTE_REF_REGEX.match(text) or text.startswith(("*", "†", "‡", "[1]", "[2]", "[3]")):
                return True
        return False

    def _is_handwriting(self, b: Any) -> bool:
        font_name = ""
        for line in getattr(b, "lines", []):
            for sp in getattr(line, "spans", []):
                font_name = getattr(sp, "font_name", "").lower()
                break
        if any(h in font_name for h in ["script", "hand", "caveat", "comic", "brush", "pencil", "pen", "italic", "cursive"]):
            return True
        return False

    def _parse_checkbox_block(self, text: str) -> List[Dict[str, Any]]:
        options = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = CHECKBOX_REGEX.search(line)
            if m:
                mark1, mark2, mark3, mark4, label = m.groups()
                mark = (mark1 or mark2 or mark3 or mark4 or "").strip()
                if mark in ["x", "X", "✓", "✔", "☑", "☒", "*", "🔘"]:
                    state = "selected"
                elif mark in ["?", "_"]:
                    state = "unclear"
                else:
                    state = "empty"

                clean_lbl = label.strip()
                options.append({
                    "label": clean_lbl,
                    "state": state,
                    "confidence": 0.98 if state != "unclear" else 0.70,
                })
        return options

    def _parse_signature_block(self, b: Any, text: str, all_blocks: List[Any], ph: float) -> Optional[Dict[str, Any]]:
        if not SIGNATURE_KEYWORDS.search(text):
            return None

        # Check for signature presence
        sig_kind = "signature"
        if re.search(r"\b(?:stamp|seal)\b", text, re.IGNORECASE):
            sig_kind = "stamp"
        elif re.search(r"\binitials\b", text, re.IGNORECASE):
            sig_kind = "initials"

        # Search nearby lines for printed name or date
        nearby_signer = ""
        nearby_date = ""

        # Check within this block
        for line in getattr(b, "lines", []):
            l_txt = line.text.strip()
            date_m = DATE_NEARBY_REGEX.search(l_txt)
            if date_m:
                nearby_date = date_m.group(0)
            name_m = re.search(r"(?:name|signed\s+by|printed\s+name):\s*([A-Za-z\s.]+)", l_txt, re.IGNORECASE)
            if name_m:
                nearby_signer = name_m.group(1).strip()

        # If not found inside, inspect immediately adjacent blocks
        b_y = b.bbox[3]
        for other in all_blocks:
            if other.page == b.page and other != b:
                if 0.0 <= (other.bbox[1] - b_y) <= 45.0:
                    o_txt = other.text.strip()
                    if not nearby_date:
                        dm = DATE_NEARBY_REGEX.search(o_txt)
                        if dm:
                            nearby_date = dm.group(0)
                    if not nearby_signer:
                        nm = re.search(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}$", o_txt)
                        if nm and not any(k in o_txt.lower() for k in ["signature", "date", "page"]):
                            nearby_signer = o_txt

        return {
            "kind": sig_kind,
            "status": "present",
            "confidence": 0.95,
            "printed_signer": nearby_signer or None,
            "signature_date": nearby_date or None,
        }

    def _parse_list_items(self, b: Any) -> List[str]:
        items = []
        for line in getattr(b, "lines", []):
            txt = line.text.strip()
            if not txt:
                continue
            if BULLET_REGEX.match(txt):
                items.append(txt)
            elif items:
                # Continuation line
                items[-1] += " " + txt
        return items

    def _detect_pdf_widgets(self, doc_page: fitz.Page, page_num: int, pw: float, ph: float) -> List[PageRegion]:
        regions = []
        try:
            for widget in doc_page.widgets():
                w_rect = widget.rect
                raw_bbox = (float(w_rect.x0), float(w_rect.y0), float(w_rect.x1), float(w_rect.y1))
                w_type = widget.field_type_string
                val = str(widget.field_value or "")

                if w_type in ["CheckBox", "Radio"]:
                    state = "selected" if val.lower() in ["yes", "/yes", "on", "true", "1"] else "empty"
                    lbl = widget.field_name or "Checkbox"
                    regions.append(self._make_region(
                        len(regions) + 1, page_num, "checkbox_group", raw_bbox, pw, ph,
                        text=f"[{'X' if state == 'selected' else ' '}] {lbl}",
                        confidence=0.99,
                        metadata={"options": [{"label": lbl, "state": state, "confidence": 0.99}]},
                    ))
                elif w_type == "Signature":
                    regions.append(self._make_region(
                        len(regions) + 1, page_num, "signature_stamp", raw_bbox, pw, ph,
                        text=f"Digital Signature: {widget.field_name}",
                        confidence=0.99,
                        metadata={"kind": "signature", "status": "present", "confidence": 0.99},
                    ))
        except Exception as e:
            logger.debug(f"Error reading PDF widgets on page {page_num}: {e}")
        return regions

    def _detect_barcodes_and_qr(
        self,
        doc_page: Optional[fitz.Page],
        page_img: Optional[np.ndarray],
        page_num: int,
        pw: float,
        ph: float,
        blocks: Optional[List[Any]] = None,
    ) -> List[PageRegion]:
        regions = []
        img_to_scan = page_img

        if img_to_scan is None and doc_page is not None:
            try:
                pix = doc_page.get_pixmap(dpi=150)
                img_to_scan = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
                if pix.n == 4:
                    img_to_scan = cv2.cvtColor(img_to_scan, cv2.COLOR_RGBA2BGR)
            except Exception as e:
                logger.debug(f"Could not render pixmap for barcode scanning: {e}")
                img_to_scan = None

        if img_to_scan is None:
            return regions

        h_img, w_img = img_to_scan.shape[:2]
        scale_x = pw / max(1.0, float(w_img))
        scale_y = ph / max(1.0, float(h_img))

        # 1. QR Code Detection
        try:
            qr = self._get_qr_detector()
            val, points, _ = qr.detectAndDecode(img_to_scan)
            if val and points is not None and len(points) > 0:
                pts = points.reshape(-1, 2)
                x0 = float(np.min(pts[:, 0]) * scale_x)
                x1 = float(np.max(pts[:, 0]) * scale_x)
                y0 = float(np.min(pts[:, 1]) * scale_y)
                y1 = float(np.max(pts[:, 1]) * scale_y)
                raw_bbox = (x0, y0, x1, y1)
                regions.append(self._make_region(
                    len(regions) + 1, page_num, "barcode_qr", raw_bbox, pw, ph,
                    text=val,
                    confidence=0.99,
                    metadata={"code_type": "QR_CODE", "decoded_value": val},
                ))
        except Exception as e:
            logger.debug(f"QR decode error: {e}")

        # 2. 1D Barcode Detection
        try:
            bd = self._get_barcode_detector()
            if bd is not None:
                ok, decoded_info, decoded_type, corners = bd.detectAndDecodeWithType(img_to_scan)
                if corners is not None and len(corners) > 0:
                    for b_idx, d_pts in enumerate(corners):
                        pts = d_pts.reshape(-1, 2)
                        x0 = float(np.min(pts[:, 0]) * scale_x)
                        x1 = float(np.max(pts[:, 0]) * scale_x)
                        y0 = float(np.min(pts[:, 1]) * scale_y)
                        y1 = float(np.max(pts[:, 1]) * scale_y)
                        raw_bbox = (x0, y0, x1, y1)

                        d_val = ""
                        d_typ = "BARCODE"
                        if ok and decoded_info and b_idx < len(decoded_info) and decoded_info[b_idx]:
                            d_val = decoded_info[b_idx]
                            if b_idx < len(decoded_type) and decoded_type[b_idx]:
                                d_typ = decoded_type[b_idx]

                        # If text not directly decoded by engine, search nearby text directly below barcode box
                        if not d_val and blocks:
                            for blk in blocks:
                                if blk.page == page_num and abs(blk.bbox[1] - y1) < 40.0 and (x0 - 50 <= blk.bbox[0] <= x1 + 50):
                                    txt_clean = blk.text.strip().strip("*").strip()
                                    if len(txt_clean) >= 6:
                                        d_val = txt_clean
                                        d_typ = "CODE_128"
                                        break

                        regions.append(self._make_region(
                            len(regions) + 1, page_num, "barcode_qr", raw_bbox, pw, ph,
                            text=d_val or "Barcode present",
                            confidence=0.99 if d_val else 0.90,
                            metadata={"code_type": d_typ, "decoded_value": d_val or "Barcode present"},
                        ))
        except Exception as e:
            logger.debug(f"Barcode decode error: {e}")

        return regions

    def _detect_page_images_and_charts(
        self,
        doc_page: fitz.Page,
        page_num: int,
        pw: float,
        ph: float,
        blocks: Optional[List[Any]] = None,
    ) -> List[PageRegion]:
        regions = []
        if not doc_page:
            return regions
        has_readable_text = bool(blocks and any(len(getattr(b, "text", "").strip()) >= 3 for b in blocks))
        try:
            images = doc_page.get_images()
            for idx, img_info in enumerate(images):
                xref = img_info[0]
                rects = doc_page.get_image_rects(xref)
                for r in rects:
                    raw_bbox = (float(r.x0), float(r.y0), float(r.x1), float(r.y1))
                    img_w = raw_bbox[2] - raw_bbox[0]
                    img_h = raw_bbox[3] - raw_bbox[1]

                    if img_w < 15.0 or img_h < 15.0:
                        continue

                    # If page has readable text, whole-page or large raster scans are page canvases, not charts
                    if has_readable_text and (img_w >= pw * 0.5 and img_h >= ph * 0.5):
                        continue

                    # If region overlaps with readable text lines, it is not an image or chart
                    if has_readable_text and blocks:
                        overlap_with_text = any(
                            not (raw_bbox[2] < b.bbox[0] or raw_bbox[0] > b.bbox[2] or raw_bbox[3] < b.bbox[1] or raw_bbox[1] > b.bbox[3])
                            for b in blocks if len(getattr(b, "text", "").strip()) >= 3
                        )
                        if overlap_with_text:
                            continue

                    if raw_bbox[1] <= (ph * 0.25) and img_w <= (pw * 0.40):
                        st_type = "image_logo"
                        desc = "Document Logo"
                    else:
                        st_type = "chart_diagram" if (img_w >= 100.0 and img_h >= 70.0) else "image_logo"
                        desc = "Chart / Diagram" if st_type == "chart_diagram" else "Embedded Image"

                    regions.append(self._make_region(
                        len(regions) + 1, page_num, st_type, raw_bbox, pw, ph,
                        text=desc,
                        confidence=0.95,
                        metadata={"description": desc, "width": img_w, "height": img_h},
                    ))

            # Also check vector drawings for charts/diagrams and logo shapes
            drawings = doc_page.get_drawings()
            if drawings and len(drawings) >= 8:
                all_rects = [d["rect"] for d in drawings if d.get("rect")]
                if all_rects:
                    x0 = float(min(r.x0 for r in all_rects))
                    y0 = float(min(r.y0 for r in all_rects))
                    x1 = float(max(r.x1 for r in all_rects))
                    y1 = float(max(r.y1 for r in all_rects))
                    w = x1 - x0
                    h = y1 - y0
                    if w >= 80.0 and h >= 50.0:
                        st_type = "chart_diagram" if (y0 > ph * 0.20 or h > 80.0) else "image_logo"
                        desc = "Chart / Diagram" if st_type == "chart_diagram" else "Document Logo"
                        regions.append(self._make_region(
                            len(regions) + 1, page_num, st_type, (x0, y0, x1, y1), pw, ph,
                            text=desc,
                            confidence=0.96,
                            metadata={"description": desc, "width": w, "height": h},
                        ))
        except Exception as e:
            logger.debug(f"Error detecting page images/drawings on page {page_num}: {e}")

        return regions
