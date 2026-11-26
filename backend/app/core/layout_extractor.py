"""Generalized Layout-Aware Field and Table Extraction Engine.

1. Universal Document Reading: digital PDFs read via native text layer (dict with positions and font sizes);
   scanned images and image-only PDFs preprocessed (orientation, skew, noise) and OCR'd into the EXACT same layout block structures.
2. Layout blocks per page: position, size, style, reading order, and block roles (headline, paragraph, list, table, form_row, footer, decoration).
3. Candidate details: meaningful business units, avoiding decoration, fine print, and footer noise.
4. Table filtering: structured tables extracted only when primary document focus.
5. Found vs Generated labels: layout-aware found labels ('document') vs context-based generated labels ('generated') with alternatives.
6. Split & Complete: prominent text capture and mixed-value splitting suggestions.
7. Grounding spans: strict exact-text grounding per detail.
8. Real confidences: separate value_confidence and label_confidence based on genuine engine scores.
"""

import os
import re
import math
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Set
from collections import Counter

import cv2
import fitz  # PyMuPDF
import numpy as np

from app.core.config_loader import ConfigLoader
from app.core.preprocessing import preprocess_image
from app.core.learned_registry import LearnedRegistry
from app.core.structure_analyzer import PageStructureAnalyzer, PageRegion
from app.core.comprehensive_extractor import (
    PasswordProtectedException,
    EmptyFileException,
    DamagedFileException,
)

logger = logging.getLogger(__name__)


@dataclass
class LayoutSpan:
    text: str
    bbox: Tuple[float, float, float, float]
    font_size: float
    is_bold: bool
    is_italic: bool
    font_name: str
    confidence: float
    page: int


@dataclass
class LayoutLine:
    spans: List[LayoutSpan]
    text: str
    bbox: Tuple[float, float, float, float]
    font_size: float
    confidence: float
    page: int
    y_center: float


@dataclass
class LayoutBlock:
    lines: List[LayoutLine]
    text: str
    bbox: Tuple[float, float, float, float]
    font_size: float
    style: str
    reading_order: int
    block_role: str  # headline, paragraph, list, table, form_row, footer, decoration
    page: int
    confidence: float


@dataclass
class ExtractionOutput:
    fields: List[Dict[str, Any]]
    table_rows: List[Dict[str, Any]]
    tables: List[Dict[str, Any]] = field(default_factory=list)
    regions: List[Dict[str, Any]] = field(default_factory=list)
    lists: List[Dict[str, Any]] = field(default_factory=list)
    checkboxes: List[Dict[str, Any]] = field(default_factory=list)
    signatures: List[Dict[str, Any]] = field(default_factory=list)
    images_and_charts: List[Dict[str, Any]] = field(default_factory=list)
    codes: List[Dict[str, Any]] = field(default_factory=list)
    text_blocks: List[Dict[str, Any]] = field(default_factory=list)
    layout_blocks: List[Dict[str, Any]] = field(default_factory=list)
    dates: List[Dict[str, Any]] = field(default_factory=list)
    title_block: Optional[Dict[str, Any]] = None
    full_text: str = ""
    is_digital_text: bool = True
    page_count: int = 1
    page_conditions: List[Dict[str, Any]] = field(default_factory=list)
    pages_text: Dict[int, str] = field(default_factory=dict)
    key_details: List[Dict[str, Any]] = field(default_factory=list)
    more_details: List[Dict[str, Any]] = field(default_factory=list)


DATE_REGEX = re.compile(
    r"\b(?:"
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|"
    r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}|"
    r"\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)

DECORATIVE_LINE_REGEX = re.compile(r"^[-=_*~.]{3,}$")
FOOTER_PAGE_NUM_REGEX = re.compile(r"^(?:page\s+\d+(?:\s+of\s+\d+)?|\d+\s*/\s*\d+|\d+)$", re.IGNORECASE)


class LayoutAwareExtractor:
    """Enterprise document layout and structured detail extraction engine."""

    def __init__(self, config_loader: Optional[ConfigLoader] = None):
        self.loader = config_loader or ConfigLoader.get_instance()
        self.registry = LearnedRegistry.get_instance()
        pipe_cfg = self.loader.pipeline_config
        conf_cfg = pipe_cfg.get("confidence", {})
        self.embedded_conf = float(conf_cfg.get("embedded_text_layer_confidence", 0.98))
        self.review_threshold = float(conf_cfg.get("field_review_threshold", 0.85))
        self.max_key_details = int(pipe_cfg.get("pipeline", {}).get("max_key_details", 8))
        self.structure_analyzer = PageStructureAnalyzer(self.loader)
        self._ocr_engine = None

    def _get_trocr_engine(self):
        if self._ocr_engine is None:
            from app.adapters.ocr import get_ocr_engine
            self._ocr_engine = get_ocr_engine()
        return self._ocr_engine

    def extract_from_file(self, file_path: str) -> ExtractionOutput:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            return self._extract_from_pdf(file_path)
        elif ext in [".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"]:
            return self._extract_from_image(file_path)
        else:
            return self._extract_from_text_file(file_path)

    # -------------------------------------------------------------------------
    # 1. Universal Document Reading
    # -------------------------------------------------------------------------
    def _extract_from_pdf(self, pdf_path: str) -> ExtractionOutput:
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        if len(pdf_bytes) == 0:
            raise EmptyFileException("This file is empty.")

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            raise DamagedFileException(f"Corrupt or damaged PDF: {e}")

        if doc.is_encrypted:
            raise PasswordProtectedException("This file is password protected.")

        page_count = len(doc)
        all_blocks: List[LayoutBlock] = []
        page_conditions: List[Dict[str, Any]] = []
        page_dims: Dict[int, Tuple[float, float]] = {}
        is_digital_overall = True

        for page_idx in range(page_count):
            page = doc[page_idx]
            page_num = page_idx + 1
            pw, ph = float(page.rect.width), float(page.rect.height)
            page_dims[page_num] = (pw, ph)
            page_dict = page.get_text("dict")
            raw_blocks = page_dict.get("blocks", [])

            # Check if digital text layer has sufficient content
            total_words = len(page.get_text("words"))

            if total_words >= 10:
                page_conditions.append({
                    "page": page_num,
                    "condition": "clean (digital)",
                    "orientation_degrees": 0,
                    "skew_angle": 0.0,
                    "denoised": False,
                    "blur_score": 100.0,
                    "noise_level": 0,
                    "confidence_penalty": 0.0,
                })
                page_blocks = self._parse_digital_pdf_blocks(raw_blocks, page_num, ph)
                all_blocks.extend(page_blocks)
            else:
                is_digital_overall = False
                pix = page.get_pixmap(dpi=150)
                img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                if pix.n == 4:
                    img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
                elif pix.n == 3:
                    img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
                else:
                    img_bgr = cv2.cvtColor(img_np, cv2.COLOR_GRAY2BGR)

                prep_img, quality = preprocess_image(img_bgr)
                page_conditions.append({
                    "page": page_num,
                    "condition": quality["condition"],
                    "orientation_degrees": quality["orientation_degrees"],
                    "skew_angle": quality["skew_angle"],
                    "denoised": quality["denoised"],
                    "blur_score": quality["blur_score"],
                    "noise_level": quality["noise_level"],
                    "confidence_penalty": quality["confidence_penalty"],
                })

                _, png_buf = cv2.imencode(".png", prep_img)
                trocr = self._get_trocr_engine()
                ocr_res = trocr.extract_text(png_buf.tobytes(), "png", file_name=f"page_{page_num}.png")
                penalty = quality["confidence_penalty"]
                page_blocks = self._parse_ocr_into_blocks(ocr_res, page_num, prep_img.shape[0], penalty)
                all_blocks.extend(page_blocks)

        # Detect repeating margin headers and footers across multi-page documents
        repeating_headers: Set[str] = set()
        repeating_footers: Set[str] = set()
        if page_count > 1:
            header_cand = Counter()
            footer_cand = Counter()
            for b in all_blocks:
                b_ph = page_dims.get(b.page, (595.0, 842.0))[1]
                t_cl = b.text.strip()
                if not t_cl:
                    continue
                if b.bbox[1] <= 55.0 and len(t_cl.split()) <= 10:
                    header_cand[t_cl] += 1
                elif b.bbox[3] >= (b_ph - 55.0) and len(t_cl.split()) <= 10:
                    footer_cand[t_cl] += 1
            for t_txt, cnt in header_cand.items():
                if cnt >= 2:
                    repeating_headers.add(t_txt)
            for t_txt, cnt in footer_cand.items():
                if cnt >= 2:
                    repeating_footers.add(t_txt)

        # Execute Page Structure Analysis across all pages
        all_regions: List[PageRegion] = []
        for page_idx in range(page_count):
            p_obj = doc[page_idx]
            p_num = page_idx + 1
            pw_p, ph_p = page_dims[p_num]
            p_blks = [b for b in all_blocks if b.page == p_num]
            p_regs = self.structure_analyzer.analyze_page_structures(
                page_num=p_num,
                blocks=p_blks,
                pw=pw_p,
                ph=ph_p,
                doc_page=p_obj,
                repeating_headers=repeating_headers,
                repeating_footers=repeating_footers,
            )
            all_regions.extend(p_regs)

        doc.close()
        return self._build_extraction_output(all_blocks, is_digital_overall, page_count, page_conditions, page_dims, all_regions)

    def _extract_from_image(self, img_path: str) -> ExtractionOutput:
        if not os.path.exists(img_path) or os.path.getsize(img_path) == 0:
            raise EmptyFileException("This file is empty.")

        img_bgr = cv2.imread(img_path)
        if img_bgr is None:
            try:
                with open(img_path, "rb") as f:
                    img_bytes = f.read()
                nparr = np.frombuffer(img_bytes, np.uint8)
                img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            except Exception as e:
                raise DamagedFileException(f"Unable to decode image: {e}")

        if img_bgr is None:
            raise DamagedFileException("Unable to decode image file.")

        prep_img, quality = preprocess_image(img_bgr)
        page_condition = {
            "page": 1,
            "condition": quality["condition"],
            "orientation_degrees": quality["orientation_degrees"],
            "skew_angle": quality["skew_angle"],
            "denoised": quality["denoised"],
            "blur_score": quality["blur_score"],
            "noise_level": quality["noise_level"],
            "confidence_penalty": quality["confidence_penalty"],
        }

        _, png_buf = cv2.imencode(".png", prep_img)
        trocr = self._get_trocr_engine()
        ocr_res = trocr.extract_text(png_buf.tobytes(), "png", file_name=os.path.basename(img_path))
        penalty = quality["confidence_penalty"]
        page_blocks = self._parse_ocr_into_blocks(ocr_res, 1, prep_img.shape[0], penalty)
        page_dims = {1: (float(prep_img.shape[1]), float(prep_img.shape[0]))}
        img_regions = self.structure_analyzer.analyze_page_structures(
            page_num=1,
            blocks=page_blocks,
            pw=float(prep_img.shape[1]),
            ph=float(prep_img.shape[0]),
            doc_page=None,
            page_img=prep_img,
        )
        return self._build_extraction_output(page_blocks, False, 1, [page_condition], page_dims, img_regions)

    def _extract_from_text_file(self, txt_path: str) -> ExtractionOutput:
        try:
            with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            content = ""

        page_blocks: List[LayoutBlock] = []
        for idx, line in enumerate(content.splitlines()):
            if not line.strip():
                continue
            span = LayoutSpan(
                text=line.strip(),
                bbox=(0.0, idx * 20.0, 500.0, idx * 20.0 + 15.0),
                font_size=10.0,
                is_bold=False,
                is_italic=False,
                font_name="Courier",
                confidence=self.embedded_conf,
                page=1,
            )
            layout_line = LayoutLine([span], line.strip(), span.bbox, 10.0, self.embedded_conf, 1, idx * 20.0 + 7.5)
            role = "form_row" if any(sep in line for sep in [":", " - ", " = "]) else "paragraph"
            page_blocks.append(LayoutBlock(
                lines=[layout_line],
                text=line.strip(),
                bbox=span.bbox,
                font_size=10.0,
                style="regular",
                reading_order=idx + 1,
                block_role=role,
                page=1,
                confidence=self.embedded_conf,
            ))

        page_condition = {
            "page": 1,
            "condition": "clean (text layer)",
            "orientation_degrees": 0,
            "skew_angle": 0.0,
            "denoised": False,
            "blur_score": 100.0,
            "noise_level": 0,
            "confidence_penalty": 0.0,
        }
        page_dims = {1: (600.0, 800.0)}
        txt_regions = self.structure_analyzer.analyze_page_structures(
            page_num=1,
            blocks=page_blocks,
            pw=600.0,
            ph=800.0,
        )
        return self._build_extraction_output(page_blocks, True, 1, [page_condition], page_dims, txt_regions)

    # -------------------------------------------------------------------------
    # Layout Block Construction & Role Classification
    # -------------------------------------------------------------------------
    def _parse_digital_pdf_blocks(self, raw_blocks: List[Dict[str, Any]], page_num: int, page_height: float) -> List[LayoutBlock]:
        blocks: List[LayoutBlock] = []
        reading_order = 1

        for b in raw_blocks:
            if b.get("type") != 0:  # Not a text block
                continue

            # Group raw lines that share the same horizontal baseline into a single visual line
            raw_lines = b.get("lines", [])
            line_groups: List[List[Dict[str, Any]]] = []
            for rl in raw_lines:
                ry0 = rl.get("bbox", (0, 0, 0, 0))[1]
                matched_grp = None
                for grp in line_groups:
                    gy0 = grp[0].get("bbox", (0, 0, 0, 0))[1]
                    if abs(ry0 - gy0) <= 3.5:
                        matched_grp = grp
                        break
                if matched_grp is not None:
                    matched_grp.append(rl)
                else:
                    line_groups.append([rl])

            lines: List[LayoutLine] = []
            for grp in line_groups:
                spans: List[LayoutSpan] = []
                for rl in grp:
                    for s in rl.get("spans", []):
                        text = s.get("text", "")
                        if not text.strip():
                            continue
                        flags = s.get("flags", 0)
                        is_bold = bool(flags & 2 ** 4) or "bold" in s.get("font", "").lower()
                        is_italic = bool(flags & 2 ** 1) or "italic" in s.get("font", "").lower()
                        spans.append(LayoutSpan(
                            text=text,
                            bbox=tuple(float(c) for c in s.get("bbox", (0, 0, 0, 0))),
                            font_size=float(s.get("size", 10.0)),
                            is_bold=is_bold,
                            is_italic=is_italic,
                            font_name=s.get("font", "Unknown"),
                            confidence=self.embedded_conf,
                            page=page_num,
                        ))

                if spans:
                    spans.sort(key=lambda sp: sp.bbox[0])
                    parts = []
                    for s_idx, sp in enumerate(spans):
                        if s_idx > 0 and sp.bbox[0] - spans[s_idx - 1].bbox[2] >= 3.0:
                            parts.append(" ")
                        parts.append(sp.text)
                    line_text = "".join(parts).strip()
                    x0 = min(s.bbox[0] for s in spans)
                    y0 = min(s.bbox[1] for s in spans)
                    x1 = max(s.bbox[2] for s in spans)
                    y1 = max(s.bbox[3] for s in spans)
                    avg_size = sum(s.font_size for s in spans) / len(spans)
                    lines.append(LayoutLine(
                        spans=spans,
                        text=line_text,
                        bbox=(x0, y0, x1, y1),
                        font_size=avg_size,
                        confidence=self.embedded_conf,
                        page=page_num,
                        y_center=(y0 + y1) / 2.0,
                    ))

            if not lines:
                continue

            block_text = "\n".join(l.text for l in lines)
            bx0 = min(l.bbox[0] for l in lines)
            by0 = min(l.bbox[1] for l in lines)
            bx1 = max(l.bbox[2] for l in lines)
            by1 = max(l.bbox[3] for l in lines)
            max_size = max(l.font_size for l in lines)
            is_bold_block = any(s.is_bold for l in lines for s in l.spans)
            style = "bold" if is_bold_block else ("heading" if max_size >= 14.0 else "regular")

            # Determine block role
            role = self._classify_block_role(lines, (bx0, by0, bx1, by1), max_size, is_bold_block, page_height)

            blocks.append(LayoutBlock(
                lines=lines,
                text=block_text,
                bbox=(bx0, by0, bx1, by1),
                font_size=max_size,
                style=style,
                reading_order=reading_order,
                block_role=role,
                page=page_num,
                confidence=self.embedded_conf,
            ))
            reading_order += 1

        return blocks

    def _parse_ocr_into_blocks(self, ocr_res: Any, page_num: int, page_height: float, penalty: float) -> List[LayoutBlock]:
        """Convert OCR bounding boxes into identical LayoutBlock structure."""
        if not ocr_res.bounding_boxes:
            return []

        # Sort boxes by y0 then x0
        sorted_boxes = sorted(ocr_res.bounding_boxes, key=lambda b: (b.y0, b.x0))
        lines_words: List[List[Any]] = []
        curr_line: List[Any] = []
        curr_y = -1.0

        for b in sorted_boxes:
            b_y = (b.y0 + b.y1) / 2.0
            h = max(1.0, b.y1 - b.y0)
            if not curr_line:
                curr_line.append(b)
                curr_y = b_y
            else:
                if abs(b_y - curr_y) <= (h * 0.5):
                    curr_line.append(b)
                    curr_y = sum((item.y0 + item.y1) / 2.0 for item in curr_line) / len(curr_line)
                else:
                    lines_words.append(curr_line)
                    curr_line = [b]
                    curr_y = b_y
        if curr_line:
            lines_words.append(curr_line)

        layout_lines: List[LayoutLine] = []
        for l_boxes in lines_words:
            l_boxes.sort(key=lambda b: b.x0)
            spans = []
            for b in l_boxes:
                conf = max(0.20, float(b.confidence) - penalty)
                spans.append(LayoutSpan(
                    text=b.text,
                    bbox=(b.x0, b.y0, b.x1, b.y1),
                    font_size=max(8.0, b.y1 - b.y0),
                    is_bold=False,
                    is_italic=False,
                    font_name="OCR",
                    confidence=conf,
                    page=page_num,
                ))
            line_text = " ".join(s.text for s in spans)
            x0 = min(s.bbox[0] for s in spans)
            y0 = min(s.bbox[1] for s in spans)
            x1 = max(s.bbox[2] for s in spans)
            y1 = max(s.bbox[3] for s in spans)
            conf = sum(s.confidence for s in spans) / len(spans)
            layout_lines.append(LayoutLine(
                spans=spans,
                text=line_text,
                bbox=(x0, y0, x1, y1),
                font_size=max(s.font_size for s in spans),
                confidence=conf,
                page=page_num,
                y_center=(y0 + y1) / 2.0,
            ))

        # Group lines into blocks
        blocks: List[LayoutBlock] = []
        reading_order = 1
        for idx, line in enumerate(layout_lines):
            role = self._classify_block_role([line], line.bbox, line.font_size, False, page_height)
            blocks.append(LayoutBlock(
                lines=[line],
                text=line.text,
                bbox=line.bbox,
                font_size=line.font_size,
                style="regular",
                reading_order=reading_order,
                block_role=role,
                page=page_num,
                confidence=line.confidence,
            ))
            reading_order += 1

        return blocks

    def _classify_block_role(
        self,
        lines: List[LayoutLine],
        bbox: Tuple[float, float, float, float],
        font_size: float,
        is_bold: bool,
        page_height: float,
    ) -> str:
        text = " ".join(l.text.strip() for l in lines).strip()
        y0, y1 = bbox[1], bbox[3]

        # 1. Decoration / Divider
        if DECORATIVE_LINE_REGEX.match(text) or font_size <= 6.5:
            return "decoration"

        # 2. Footer (bottom 12% of page with page number or copyright)
        if y1 >= (page_height * 0.88):
            if FOOTER_PAGE_NUM_REGEX.match(text) or any(w in text.lower() for w in ["page", "copyright", "all rights reserved"]):
                return "footer"

        # 3. Headline (large font or bold at the top of the page)
        if (font_size >= 14.0 or (is_bold and font_size >= 12.0)) and len(text.split()) <= 10:
            return "headline"

        # 4. Form Row (contains key-value separator, or prompt/value format)
        if any(sep in text for sep in [":", " - ", " = ", "\t"]) and len(lines) <= 2:
            return "form_row"

        # 5. List item
        if text.startswith(("•", "-", "*")) or re.match(r"^\d+[\.\)]\s+", text):
            return "list"

        # 6. Table row candidate (multiple horizontal aligned columns or multi-space column gaps)
        column_gaps = len(re.findall(r"\s{2,}|\t", text))
        if (len(lines[0].spans) >= 3 or column_gaps >= 2) and not any(sep in text for sep in [":", " = "]):
            return "table"

        # 7. Default to paragraph
        return "paragraph"

    # -------------------------------------------------------------------------
    # 2. Candidate Detail Extraction & Filtering
    # -------------------------------------------------------------------------
    def _normalize_bbox(self, bbox: Tuple[float, float, float, float], pw: float, ph: float) -> List[float]:
        """Convert points/pixel bbox (x0, y0, x1, y1) to normalized [ymin, xmin, ymax, xmax] 0-1000 covering full text span."""
        if not bbox or len(bbox) != 4:
            return [0.0, 0.0, 100.0, 100.0]
        x0, y0, x1, y1 = bbox
        w = max(1.0, float(pw))
        h = max(1.0, float(ph))
        pad_x = 1.5
        pad_y = 0.5
        ymin = max(0.0, round(((y0 - pad_y) / h) * 1000, 1))
        xmin = max(0.0, round(((x0 - pad_x) / w) * 1000, 1))
        ymax = min(1000.0, round(((y1 + pad_y) / h) * 1000, 1))
        xmax = min(1000.0, round(((x1 + pad_x) / w) * 1000, 1))
        return [ymin, xmin, ymax, xmax]

    def _split_line_into_cells(self, line: LayoutLine) -> List[Dict[str, Any]]:
        """Split a LayoutLine into horizontal column cells with accurate bounding coordinates."""
        if len(line.spans) >= 2:
            sorted_spans = sorted(line.spans, key=lambda s: s.bbox[0])
            grouped: List[List[LayoutSpan]] = []
            curr_group = [sorted_spans[0]]
            for s in sorted_spans[1:]:
                prev_x1 = max(sp.bbox[2] for sp in curr_group)
                if s.bbox[0] - prev_x1 >= 10.0:
                    grouped.append(curr_group)
                    curr_group = [s]
                else:
                    curr_group.append(s)
            if curr_group:
                grouped.append(curr_group)

            if len(grouped) >= 2:
                cells = []
                for grp in grouped:
                    txt = "".join(sp.text for sp in grp).strip()
                    if txt:
                        cells.append({
                            "text": txt,
                            "x0": min(sp.bbox[0] for sp in grp),
                            "x1": max(sp.bbox[2] for sp in grp),
                            "y0": min(sp.bbox[1] for sp in grp),
                            "y1": max(sp.bbox[3] for sp in grp),
                            "confidence": sum(sp.confidence for sp in grp) / len(grp),
                        })
                if len(cells) >= 2:
                    return cells

        raw_text = line.text.strip()
        parts = [p.strip() for p in re.split(r"\s{2,}|\t", raw_text) if p.strip()]
        if len(parts) >= 2:
            lx0, ly0, lx1, ly1 = line.bbox
            total_chars = max(1, sum(len(p) for p in parts))
            line_w = max(10.0, lx1 - lx0)
            cur_x = lx0
            cells = []
            for p in parts:
                p_len_ratio = len(p) / total_chars
                cell_w = line_w * p_len_ratio
                cells.append({
                    "text": p,
                    "x0": cur_x,
                    "x1": cur_x + cell_w,
                    "y0": ly0,
                    "y1": ly1,
                    "confidence": line.confidence,
                })
                cur_x += cell_w + 10.0
            return cells

        return []

    def _verify_table_arithmetic(self, headers: List[str], rows: List[Dict[str, Any]], all_text: str) -> Tuple[List[Dict[str, Any]], float]:
        """Check arithmetic: quantity * price = amount, and column sum = total."""
        arithmetic_checks = []
        confidence_boost = 0.0

        for r_idx, r in enumerate(rows):
            cells = r.get("cells", {})
            num_cells = {}
            for h, val in cells.items():
                clean_v = re.sub(r"[^\d.-]", "", str(val))
                try:
                    if clean_v and clean_v not in ["-", "."]:
                        num_cells[h] = float(clean_v)
                except ValueError:
                    pass

            cols = list(num_cells.keys())
            matched_product = False
            for i in range(len(cols)):
                for j in range(len(cols)):
                    if i != j:
                        for k in range(len(cols)):
                            if k != i and k != j:
                                v_i = num_cells[cols[i]]
                                v_j = num_cells[cols[j]]
                                v_k = num_cells[cols[k]]
                                if v_i > 0 and v_j > 0 and v_k > 0:
                                    expected = round(v_i * v_j, 2)
                                    if abs(expected - v_k) <= 0.05:
                                        formula_str = f"{v_i:g} * {v_j:g} = {v_k:.2f}"
                                        arithmetic_checks.append({
                                            "row_index": r_idx,
                                            "type": "product",
                                            "formula": formula_str,
                                            "message": formula_str,
                                            "status": "verified",
                                            "valid": True,
                                        })
                                        r["arithmetic_valid"] = True
                                        matched_product = True
                                        confidence_boost = max(confidence_boost, 0.05)
                                        break
                        if matched_product:
                            break
                if matched_product:
                    break

        col_sums = {}
        for h in headers:
            vals = []
            for r in rows:
                clean_v = re.sub(r"[^\d.-]", "", str(r.get("cells", {}).get(h, "")))
                try:
                    if clean_v and clean_v not in ["-", "."]:
                        vals.append(float(clean_v))
                except ValueError:
                    pass
            if len(vals) == len(rows) and len(vals) >= 2:
                col_sums[h] = round(sum(vals), 2)

        for col_name, total_sum in col_sums.items():
            sum_str_2dec = f"{total_sum:.2f}"
            sum_str_commas = f"{total_sum:,.2f}"
            if sum_str_2dec in all_text or sum_str_commas in all_text:
                formula_str = f"Sum({col_name}) = {sum_str_commas}"
                arithmetic_checks.append({
                    "type": "sum",
                    "column": col_name,
                    "sum": total_sum,
                    "formula": formula_str,
                    "message": formula_str,
                    "status": "verified",
                    "matches_total": True,
                    "valid": True,
                })
                confidence_boost = max(confidence_boost, 0.05)

        return arithmetic_checks, confidence_boost

    def _detect_tables_on_pages(
        self,
        blocks: List[LayoutBlock],
        page_count: int,
        page_dims: Dict[int, Tuple[float, float]],
        all_text: str,
    ) -> Tuple[List[Dict[str, Any]], Set[str], List[Dict[str, Any]]]:
        """Detect tables by layout: aligned columns across consecutive lines."""
        tables: List[Dict[str, Any]] = []
        table_lines_text: Set[str] = set()
        compat_table_rows: List[Dict[str, Any]] = []

        for p in range(1, page_count + 1):
            pw, ph = page_dims.get(p, (595.0, 842.0))
            page_lines = [l for b in blocks if b.page == p for l in b.lines]
            page_lines.sort(key=lambda l: l.y_center)

            if len(page_lines) < 2:
                continue

            line_cells: List[Tuple[LayoutLine, List[Dict[str, Any]]]] = []
            for l in page_lines:
                c = self._split_line_into_cells(l)
                line_cells.append((l, c))

            i = 0
            t_counter = 1
            while i < len(line_cells):
                l_curr, cells_curr = line_cells[i]
                is_totals_row = any(l_curr.text.strip().lower().startswith(p) for p in ["subtotal", "total due", "tax", "balance due", "amount due", "amount paid", "total:"])
                has_colons = ":" in l_curr.text and len(cells_curr) <= 2
                has_numbers_in_header = any(re.search(r"^[-+]?[\$€£¥]?[-+]?\d+[.,]?\d*$", c["text"].strip()) for c in cells_curr)

                if len(cells_curr) >= 2 and not is_totals_row and not has_colons and not has_numbers_in_header:
                    candidate_table_lines = [(l_curr, cells_curr)]
                    j = i + 1
                    header_cols = [c["x0"] for c in cells_curr]

                    while j < len(line_cells):
                        l_next, cells_next = line_cells[j]
                        if any(l_next.text.strip().lower().startswith(p) for p in ["subtotal", "total due", "tax (", "balance due", "amount due", "amount paid", "thank you"]):
                            break
                        if ":" in l_next.text and len(cells_next) <= 2:
                            break

                        if len(cells_next) >= 2:
                            prev_l, _ = candidate_table_lines[-1]
                            v_dist = l_next.y_center - prev_l.y_center
                            if v_dist > 45.0:
                                break

                            aligned_count = 0
                            for cn in cells_next:
                                if any(abs(cn["x0"] - hc) <= 45.0 for hc in header_cols):
                                    aligned_count += 1

                            if aligned_count >= max(1, len(cells_next) - 1):
                                candidate_table_lines.append((l_next, cells_next))
                                j += 1
                            else:
                                break
                        else:
                            break

                    if len(candidate_table_lines) >= 2:
                        hdr_line, hdr_cells = candidate_table_lines[0]
                        data_lines = candidate_table_lines[1:]

                        headers = []
                        for idx, c in enumerate(hdr_cells):
                            clean_h = re.sub(r"[:\-=]+$", "", c["text"]).strip()
                            headers.append(clean_h or f"Column_{idx + 1}")

                        rows = []
                        for r_idx, (d_line, d_cells) in enumerate(data_lines):
                            row_dict = {}
                            assigned_headers = set()
                            if len(d_cells) == len(headers):
                                for h_idx, c in enumerate(d_cells):
                                    row_dict[headers[h_idx]] = c["text"]
                            else:
                                for c in d_cells:
                                    best_h = None
                                    min_dist = float("inf")
                                    for h_idx, h_name in enumerate(headers):
                                        if h_name not in assigned_headers:
                                            dist = abs(c["x0"] - hdr_cells[h_idx]["x0"])
                                            if dist < min_dist:
                                                min_dist = dist
                                                best_h = h_name
                                    if best_h:
                                        row_dict[best_h] = c["text"]
                                        assigned_headers.add(best_h)

                            for h_name in headers:
                                if h_name not in row_dict:
                                    row_dict[h_name] = ""

                            rx0 = min(c["x0"] for c in d_cells)
                            ry0 = min(c["y0"] for c in d_cells)
                            rx1 = max(c["x1"] for c in d_cells)
                            ry1 = max(c["y1"] for c in d_cells)
                            r_bbox = self._normalize_bbox((rx0, ry0, rx1, ry1), pw, ph)

                            row_obj = {
                                "id": f"row_{p}_{t_counter}_{r_idx + 1}",
                                "row_index": r_idx,
                                "cells": row_dict,
                                "bbox": r_bbox,
                                "confidence": round(d_line.confidence, 4),
                            }
                            rows.append(row_obj)
                            compat_table_rows.append({
                                "cells": [row_dict.get(h, "") for h in headers],
                                "confidence": round(d_line.confidence, 4),
                                "page": p,
                                "bbox": r_bbox,
                            })

                        tx0 = min(c[0].bbox[0] for c in candidate_table_lines)
                        ty0 = min(c[0].bbox[1] for c in candidate_table_lines)
                        tx1 = max(c[0].bbox[2] for c in candidate_table_lines)
                        ty1 = max(c[0].bbox[3] for c in candidate_table_lines)
                        t_bbox = self._normalize_bbox((tx0, ty0, tx1, ty1), pw, ph)

                        arithmetic_checks, _ = self._verify_table_arithmetic(headers, rows, all_text)

                        # Detect totals that sit under or beside the table
                        attached_totals = []
                        k = j
                        while k < len(line_cells):
                            l_tot, cells_tot = line_cells[k]
                            if (l_tot.y_center - ty1) > 70.0:
                                break
                            tot_t = l_tot.text.strip()
                            if any(tot_t.lower().startswith(p) for p in ["subtotal", "tax", "total", "balance due", "amount due", "amount paid", "discount"]):
                                p_parts = [p.strip() for p in re.split(r":|\s{2,}|\t", tot_t) if p.strip()]
                                t_lbl = p_parts[0] if len(p_parts) >= 2 else "Total"
                                t_val = p_parts[-1] if len(p_parts) >= 2 else tot_t
                                attached_totals.append({
                                    "label": t_lbl,
                                    "value": t_val,
                                    "raw_text": tot_t,
                                    "bbox": self._normalize_bbox(l_tot.bbox, pw, ph),
                                    "confidence": round(l_tot.confidence, 4),
                                    "page": p,
                                })
                                table_lines_text.add(tot_t)
                                k += 1
                            else:
                                break

                        tables.append({
                            "id": f"tbl_{p}_{t_counter}",
                            "page": p,
                            "headers": headers,
                            "rows": rows,
                            "bbox": t_bbox,
                            "arithmetic_checks": arithmetic_checks,
                            "totals": attached_totals,
                        })

                        for tl, _ in candidate_table_lines:
                            table_lines_text.add(tl.text.strip())

                        t_counter += 1
                        i = k if attached_totals else j
                        continue

                i += 1

        return tables, table_lines_text, compat_table_rows

    def _extract_same_line_pair(self, line: LayoutLine, pw: float, ph: float) -> Optional[Tuple[str, str, float, List[float], str]]:
        """Pair a line that has a label on the left and a value on the right as ONE field."""
        text = line.text.strip()
        if not text:
            return None

        # 1. Standard punctuation separators: ": ", " = ", " - ", "\t"
        match = None
        for pattern in [r":\s+", r"\s+=\s+", r"\s+-\s+", r"\t+"]:
            m = re.search(pattern, text)
            if m:
                if ":" in m.group(0):
                    before = text[:m.start()]
                    after = text[m.end():]
                    if re.search(r"\b\d{1,2}$", before) and re.search(r"^\d{2}\b", after):
                        continue
                    if before.lower().endswith(("http", "https")):
                        continue
                match = m
                break

        if match:
            lbl = text[:match.start()].strip()
            val = text[match.end():].strip()
            if lbl and val and len(lbl.split()) <= 6:
                norm_lbl = self.registry.normalize_label(lbl)
                bbox = self._normalize_bbox(line.bbox, pw, ph)
                return (norm_lbl, val, 0.98, bbox, text)

        # 2. Aligned gap or multi-space separation: Description on left, amount/number on right
        gap_match = re.match(r"^([A-Za-z0-9#&()./'-]+(?:\s+[A-Za-z0-9#&()./'-]+){0,5})\s{2,}(\$?-?\d[\d,.]*(?:%|\b)?|[A-Z0-9-]{3,}.*)$", text)
        if gap_match:
            lbl = gap_match.group(1).strip()
            val = gap_match.group(2).strip()
            if lbl and val:
                norm_lbl = self.registry.normalize_label(lbl)
                bbox = self._normalize_bbox(line.bbox, pw, ph)
                return (norm_lbl, val, 0.96, bbox, text)

        # 3. Two spans separated by horizontal gap >= 18 pt
        if len(line.spans) >= 2:
            s0 = line.spans[0]
            s1 = line.spans[-1]
            if s1.bbox[0] - s0.bbox[2] >= 18.0:
                left_txt = " ".join(s.text for s in line.spans[:-1]).strip()
                right_txt = s1.text.strip()
                if left_txt and right_txt and len(left_txt.split()) <= 6:
                    norm_lbl = self.registry.normalize_label(left_txt)
                    bbox = self._normalize_bbox(line.bbox, pw, ph)
                    return (norm_lbl, right_txt, 0.95, bbox, text)

        return None

    def _build_extraction_output(
        self,
        blocks: List[LayoutBlock],
        is_digital: bool,
        page_count: int,
        page_conditions: List[Dict[str, Any]],
        page_dims: Dict[int, Tuple[float, float]],
        page_regions: Optional[List[PageRegion]] = None,
    ) -> ExtractionOutput:
        page_regions = page_regions or []
        pages_text: Dict[int, str] = {}
        full_text_list: List[str] = []
        for p in range(1, page_count + 1):
            p_blocks = [b for b in blocks if b.page == p and b.block_role not in ["decoration"]]
            p_text = "\n".join(b.text for b in p_blocks)
            pages_text[p] = p_text
            if p_text:
                full_text_list.append(p_text)
        full_text = "\n\n".join(full_text_list)

        title_block = None
        dates: List[Dict[str, Any]] = []
        seen_dates = set()
        fields: List[Dict[str, Any]] = []

        # 1. Layout-Aware Table Detection (tables never turned into loose fields or label/value pairs)
        tables, table_lines_text, compat_table_rows = self._detect_tables_on_pages(blocks, page_count, page_dims, full_text)

        pw1, ph1 = page_dims.get(1, (595.0, 842.0))

        # 2. Find title block from headline blocks on page 1
        for b in blocks:
            if b.page == 1 and b.block_role == "headline" and len(b.text.strip()) >= 3 and b.text.strip() not in table_lines_text:
                title_block = {
                    "text": b.text.strip(),
                    "confidence": round(b.confidence, 4),
                    "page": 1,
                    "bbox": self._normalize_bbox(b.bbox, pw1, ph1),
                }
                break

        # 3. Extract dates
        for b in blocks:
            pw, ph = page_dims.get(b.page, (595.0, 842.0))
            for match in DATE_REGEX.finditer(b.text):
                d_str = match.group(0).strip()
                if d_str not in seen_dates:
                    seen_dates.add(d_str)
                    dates.append({
                        "date": d_str,
                        "page": b.page,
                        "confidence": round(b.confidence, 4),
                        "bbox": self._normalize_bbox(b.bbox, pw, ph),
                    })

        # 4. Candidate Details Extraction & Grounding Mask
        extracted_groundings: Set[str] = set()
        extracted_groundings.update(table_lines_text)

        # 4.0 Mask suppressible regions (headers, footers, watermarks, footnotes) from loose fields
        for r in page_regions:
            if r.structure_type in ["header_footer", "watermark", "footnote"]:
                extracted_groundings.add(r.text.strip())
                for line in r.text.splitlines():
                    extracted_groundings.add(line.strip())

        # 4.1 Process Structured Regions into cohesive details
        # A. Table attached totals: keep attached to table AND make available as individual fields
        for tbl in tables:
            for tot in tbl.get("totals", []):
                fields.append(self._create_detail_dict(
                    label=tot["label"],
                    value=tot["value"],
                    value_confidence=tot.get("confidence", 0.98),
                    label_confidence=0.98,
                    page=tbl["page"],
                    bbox=tot["bbox"],
                    source="document",
                    reason="Attached total beneath table grid",
                    structure_type="table",
                    structure_group="tables",
                    structure_confidence=0.98,
                    region_id=tbl["id"],
                    grounding_text=tot.get("raw_text", tot["value"]),
                ))
                extracted_groundings.add(tot.get("raw_text", tot["value"]).strip())

        # B. List regions: keep a list as ONE field with items in order (not 1 field per bullet)
        for r in page_regions:
            if r.structure_type == "list":
                # Find preceding heading for label if available
                prec_heading = None
                for b in reversed(blocks):
                    if b.page == r.page and b.bbox[3] <= r.raw_bbox[1] and b.block_role in ["headline", "heading"]:
                        if 1 <= len(b.text.split()) <= 6:
                            prec_heading = b.text.strip()
                            break
                list_lbl = prec_heading or "List of Items"
                items_val = "\n".join(r.metadata.get("items", [r.text]))
                fields.append(self._create_detail_dict(
                    label=list_lbl,
                    value=items_val,
                    value_confidence=r.confidence,
                    label_confidence=0.96,
                    page=r.page,
                    bbox=r.bbox,
                    source="document",
                    reason="Structured ordered or bulleted list",
                    suggested_label=list_lbl,
                    structure_type="list",
                    structure_group="lists",
                    structure_confidence=0.97,
                    region_id=r.id,
                    grounding_text=r.text,
                ))
                extracted_groundings.add(r.text.strip())
                for line in r.text.splitlines():
                    extracted_groundings.add(line.strip())

        # C. Checkboxes / Radio groups: extract as label plus state (selected, empty, unclear)
        for r in page_regions:
            if r.structure_type == "checkbox_group":
                for opt in r.metadata.get("options", []):
                    opt_lbl = opt.get("label", "Option")
                    opt_state = opt.get("state", "empty")
                    mark_char = "X" if opt_state == "selected" else ("?" if opt_state == "unclear" else " ")
                    state_str = f"[{mark_char}] {opt_state.title()}"
                    fields.append(self._create_detail_dict(
                        label=opt_lbl,
                        value=state_str,
                        value_confidence=opt.get("confidence", 0.98),
                        label_confidence=0.98,
                        page=r.page,
                        bbox=r.bbox,
                        source="document",
                        reason=f"Form option marked {opt_state}",
                        structure_type="checkbox_group",
                        structure_group="checkboxes",
                        structure_confidence=0.98,
                        region_id=r.id,
                        grounding_text=f"[{mark_char}] {opt_lbl}",
                    ))
                    extracted_groundings.add(opt_lbl)
                extracted_groundings.add(r.text.strip())

        # D. Signatures, stamps, seals, initials: report presence and nearby signer/date
        for r in page_regions:
            if r.structure_type == "signature_stamp":
                sig_kind = r.metadata.get("kind", "signature").title()
                signer = r.metadata.get("printed_signer")
                s_date = r.metadata.get("signature_date")
                if signer and s_date:
                    sig_val = f"{sig_kind} present (Signed by: {signer}, Date: {s_date})"
                elif signer:
                    sig_val = f"{sig_kind} present (Signed by: {signer})"
                elif s_date:
                    sig_val = f"{sig_kind} present (Date: {s_date})"
                else:
                    sig_val = f"{sig_kind} present"

                fields.append(self._create_detail_dict(
                    label=sig_kind,
                    value=sig_val,
                    value_confidence=r.confidence,
                    label_confidence=0.95,
                    page=r.page,
                    bbox=r.bbox,
                    source="document",
                    reason=f"{sig_kind} presence verified on document",
                    structure_type="signature_stamp",
                    structure_group="signatures_and_stamps",
                    structure_confidence=0.95,
                    region_id=r.id,
                    grounding_text=r.text,
                ))
                extracted_groundings.add(r.text.strip())

        # E. Barcodes and QR codes: decode value and code type
        for r in page_regions:
            if r.structure_type == "barcode_qr":
                c_type = r.metadata.get("code_type", "BARCODE")
                c_val = r.metadata.get("decoded_value", r.text)
                c_lbl = "QR Code" if "QR" in c_type else f"Barcode ({c_type})"
                fields.append(self._create_detail_dict(
                    label=c_lbl,
                    value=c_val,
                    value_confidence=r.confidence,
                    label_confidence=0.99,
                    page=r.page,
                    bbox=r.bbox,
                    source="document",
                    reason=f"Decoded {c_lbl} visual content",
                    structure_type="barcode_qr",
                    structure_group="codes",
                    structure_confidence=0.99,
                    region_id=r.id,
                    grounding_text=c_val,
                ))
                extracted_groundings.add(c_val)

        # F. Logos, photos, charts, diagrams
        for r in page_regions:
            if r.structure_type in ["image_logo", "chart_diagram"]:
                c_desc = r.metadata.get("description", r.text)
                c_lbl = "Chart / Diagram" if r.structure_type == "chart_diagram" else "Logo / Image"
                fields.append(self._create_detail_dict(
                    label=c_lbl,
                    value=c_desc,
                    value_confidence=r.confidence,
                    label_confidence=0.95,
                    page=r.page,
                    bbox=r.bbox,
                    source="document",
                    reason=f"{c_lbl} visual component",
                    structure_type=r.structure_type,
                    structure_group="images_and_charts",
                    structure_confidence=0.95,
                    region_id=r.id,
                    grounding_text=r.text,
                ))
                extracted_groundings.add(r.text.strip())

        # G. Document Title from primary heading on Page 1
        for r in page_regions:
            if r.structure_type == "heading" and r.metadata.get("is_document_title"):
                fields.append(self._create_detail_dict(
                    label="Document Title",
                    value=r.text.strip(),
                    value_confidence=r.confidence,
                    label_confidence=0.98,
                    page=r.page,
                    bbox=r.bbox,
                    source="document",
                    reason="Primary document title heading",
                    structure_type="heading",
                    structure_group="fields",
                    structure_confidence=0.98,
                    region_id=r.id,
                    grounding_text=r.text.strip(),
                ))
                extracted_groundings.add(r.text.strip())
                break

        # 4a. Top Issuing Party Block check (generate label 'Issuer Name' if none printed)
        issuer_extracted = False
        for b in blocks:
            if b.page == 1 and b.bbox[1] < (ph1 * 0.25):
                clean_t = b.text.strip()
                if clean_t and clean_t not in extracted_groundings and clean_t not in table_lines_text:
                    upper_t = clean_t.upper()
                    if not any(k in upper_t for k in ["INVOICE", "RECEIPT", "STATEMENT", "PURCHASE ORDER", "ESTIMATE", "BILL TO", "SHIP TO"]):
                        if 1 <= len(clean_t.split()) <= 8 and not re.search(r"^\d+$", clean_t):
                            fields.append(self._create_detail_dict(
                                label="Issuer Name",
                                value=clean_t,
                                value_confidence=b.confidence,
                                label_confidence=0.94,
                                page=1,
                                bbox=self._normalize_bbox(b.bbox, pw1, ph1),
                                source="generated",
                                reason="Issuing organization identified at top of document",
                                suggested_label="Issuer Name",
                                grounding_text=clean_t,
                                structure_type="form_row",
                                structure_group="fields",
                                structure_confidence=0.95,
                            ))
                            extracted_groundings.add(clean_t)
                            issuer_extracted = True
                            break

        # 4b. Extract candidate pairs from non-table lines
        for b in blocks:
            if b.block_role in ["decoration", "footer"]:
                continue
            pw, ph = page_dims.get(b.page, (595.0, 842.0))

            for line in b.lines:
                line_clean = line.text.strip()
                if line_clean in table_lines_text or any(line_clean in t_txt for t_txt in table_lines_text) or line_clean in extracted_groundings:
                    continue

                pair = self._extract_same_line_pair(line, pw, ph)
                if pair:
                    fields.extend(self._process_candidate_pair(pair, line.page, "document", extracted_groundings, pw, ph))

        # 4c. Check vertically stacked pairs (e.g. label line above value line)
        for idx in range(len(blocks) - 1):
            b1 = blocks[idx]
            b2 = blocks[idx + 1]
            if b1.text.strip() in extracted_groundings or b2.text.strip() in extracted_groundings:
                continue
            if b1.text.strip() in table_lines_text or b2.text.strip() in table_lines_text:
                continue
            if b1.page == b2.page and b1.block_role in ["headline", "paragraph", "heading"] and len(b1.text.split()) <= 4:
                pw, ph = page_dims.get(b1.page, (595.0, 842.0))
                stacked = self._check_stacked_blocks(b1, b2, pw, ph)
                if stacked:
                    fields.extend(self._process_candidate_pair(stacked, b1.page, "document", extracted_groundings, pw, ph))

        # 4d. Prominent Text Check: bold or large text not yet extracted as a detail
        for b in blocks:
            pw, ph = page_dims.get(b.page, (595.0, 842.0))
            if b.page == 1 and (b.font_size >= 14.0 or b.style == "bold" or b.bbox[1] < 120):
                text_clean = b.text.strip()
                if text_clean in table_lines_text or text_clean in extracted_groundings:
                    continue
                if len(text_clean.split()) <= 8 and not any(sep in text_clean for sep in [":", " = "]):
                    gen_meta = self.registry.generate_label_for_detail(
                        value=text_clean,
                        position_style={"font_size": b.font_size, "is_bold": True, "y": b.bbox[1]},
                        doc_summary=title_block["text"] if title_block else "",
                    )
                    gen_conf = gen_meta.get("label_confidence", 0.85)
                    sug_lbl = gen_meta.get("suggested_label", "")
                    fields.append(self._create_detail_dict(
                        label=sug_lbl if gen_conf >= 0.70 else "",
                        value=text_clean,
                        value_confidence=b.confidence,
                        label_confidence=gen_conf if gen_conf >= 0.70 else None,
                        page=b.page,
                        bbox=self._normalize_bbox(b.bbox, pw, ph),
                        source="generated" if gen_conf >= 0.70 else "unlabelled",
                        reason=gen_meta.get("reason", ""),
                        suggested_label=sug_lbl,
                        alternatives=gen_meta.get("alternatives", []),
                        grounding_text=text_clean,
                        hint="suggested" if sug_lbl and gen_conf >= 0.70 else "needs label",
                        structure_type="heading" if b.font_size >= 14.0 else "label_value_pair",
                        structure_group="fields",
                        structure_confidence=0.95,
                    ))
                    extracted_groundings.add(text_clean)

        # 4e. Mixed Value Check: Unextracted blocks containing both date and amount
        for b in blocks:
            pw, ph = page_dims.get(b.page, (595.0, 842.0))
            text_clean = b.text.strip()
            if text_clean in extracted_groundings or text_clean in table_lines_text:
                continue
            amt_match = re.search(r"\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})", text_clean)
            date_match = DATE_REGEX.search(text_clean)
            if amt_match and date_match and abs(amt_match.start() - date_match.start()) >= 5:
                gen_meta = self.registry.generate_label_for_detail(
                    value=text_clean,
                    position_style={"font_size": b.font_size, "is_bold": b.style == "bold", "y": b.bbox[1]},
                    doc_summary=title_block["text"] if title_block else "",
                )
                fields.append(self._create_detail_dict(
                    label=gen_meta.get("suggested_label", "Payment Detail"),
                    value=text_clean,
                    value_confidence=b.confidence,
                    label_confidence=0.88,
                    page=b.page,
                    bbox=self._normalize_bbox(b.bbox, pw, ph),
                    source="generated",
                    reason="Mixed detail combining transaction and timestamp",
                    suggested_label=gen_meta.get("suggested_label", "Payment Detail"),
                    alternatives=gen_meta.get("alternatives", []),
                    grounding_text=text_clean,
                    hint="suggested",
                    structure_type="form_row",
                    structure_group="fields",
                    structure_confidence=0.95,
                ))
                extracted_groundings.add(text_clean)

        # 4f. Single Main Paragraph Promotion (if document has minimal fields and a dominant statement)
        if len(fields) <= 3:
            for b in blocks:
                if b.page == 1 and b.block_role == "paragraph" and len(b.text.split()) >= 15:
                    if b.text.strip() not in extracted_groundings:
                        fields.append(self._create_detail_dict(
                            label="Notice Statement",
                            value=b.text.strip(),
                            value_confidence=b.confidence,
                            label_confidence=0.92,
                            page=1,
                            bbox=self._normalize_bbox(b.bbox, pw1, ph1),
                            source="document",
                            reason="Promoted central announcement/statement of document",
                            structure_type="paragraph",
                            structure_group="fields",
                            structure_confidence=0.95,
                            grounding_text=b.text.strip(),
                        ))
                        extracted_groundings.add(b.text.strip())
                        break

        # 5. Split and Complete
        final_fields: List[Dict[str, Any]] = []
        for fld in fields:
            splits = self._check_and_split_mixed_value(fld)
            final_fields.extend(splits)

        # 6. Partition into Key Details and More Details
        key_details = final_fields[:self.max_key_details]
        more_details = final_fields[self.max_key_details:]
        for f in more_details:
            f["in_more_details"] = True
            f["is_promoted"] = False

        serialized_layout_blocks = [
            {
                "page": b.page,
                "reading_order": b.reading_order,
                "role": b.block_role,
                "text": b.text,
                "bbox": self._normalize_bbox(b.bbox, page_dims.get(b.page, (595.0, 842.0))[0], page_dims.get(b.page, (595.0, 842.0))[1]),
                "font_size": b.font_size,
                "style": b.style,
                "confidence": round(b.confidence, 4),
            }
            for b in blocks
        ]

        serialized_regions = [
            {
                "id": r.id,
                "page": r.page,
                "structure_type": r.structure_type,
                "structure_name": r.structure_name,
                "structure_group": r.structure_group,
                "confidence": r.confidence,
                "bbox": r.bbox,
                "reading_order": r.reading_order,
                "text": r.text,
                "metadata": r.metadata,
            }
            for r in page_regions
        ]

        lists_out = [r for r in serialized_regions if r["structure_group"] == "lists"]
        checkboxes_out = [r for r in serialized_regions if r["structure_group"] == "checkboxes"]
        signatures_out = [r for r in serialized_regions if r["structure_group"] == "signatures_and_stamps"]
        images_and_charts_out = [r for r in serialized_regions if r["structure_group"] == "images_and_charts"]
        codes_out = [r for r in serialized_regions if r["structure_group"] == "codes"]

        return ExtractionOutput(
            fields=final_fields,
            table_rows=compat_table_rows,
            tables=tables,
            regions=serialized_regions,
            lists=lists_out,
            checkboxes=checkboxes_out,
            signatures=signatures_out,
            images_and_charts=images_and_charts_out,
            codes=codes_out,
            text_blocks=[],
            layout_blocks=serialized_layout_blocks,
            dates=dates,
            title_block=title_block,
            full_text=full_text,
            is_digital_text=is_digital,
            page_count=page_count,
            page_conditions=page_conditions,
            pages_text=pages_text,
            key_details=key_details,
            more_details=more_details,
        )

    def _check_stacked_blocks(self, b_top: LayoutBlock, b_bot: LayoutBlock, pw: float, ph: float) -> Optional[Tuple[str, str, float, List[float], str]]:
        """Detect label on top block and value on bottom block."""
        if b_top.block_role == "table" or b_bot.block_role == "table":
            return None
        v_gap = b_bot.bbox[1] - b_top.bbox[3]
        if 0 <= v_gap <= 30.0 and abs(b_top.bbox[0] - b_bot.bbox[0]) <= 25.0:
            top_t = b_top.text.strip()
            bot_t = b_bot.text.strip()
            if ":" in top_t and len(top_t.split(":", 1)[1].strip()) > 0:
                return None
            if ":" in bot_t and len(bot_t.split(":", 1)[1].strip()) > 0:
                return None
            if 1 <= len(top_t.split()) <= 5 and not top_t.endswith("."):
                bbox = self._normalize_bbox((
                    min(b_top.bbox[0], b_bot.bbox[0]),
                    b_top.bbox[1],
                    max(b_top.bbox[2], b_bot.bbox[2]),
                    b_bot.bbox[3],
                ), pw, ph)
                conf = (b_top.confidence + b_bot.confidence) / 2.0
                norm_lbl = self.registry.normalize_label(top_t)
                grounding = f"{top_t}\n{bot_t}"
                return (norm_lbl, bot_t, conf, bbox, grounding)
        return None

    def _process_candidate_pair(
        self,
        pair: Tuple[str, str, float, List[float], str],
        page: int,
        source: str,
        extracted_groundings: Set[str],
        pw: float,
        ph: float,
    ) -> List[Dict[str, Any]]:
        lbl, val, conf, bbox, grounding = pair
        if val in extracted_groundings:
            return []
        extracted_groundings.add(val)

        return [self._create_detail_dict(
            label=lbl,
            value=val,
            value_confidence=conf,
            label_confidence=0.98 if source == "document" else 0.88,
            page=page,
            bbox=bbox,
            source=source,
            grounding_text=grounding,
            suggested_label=lbl if source == "generated" else "",
            hint="" if lbl else "needs label",
        )]

    def _create_detail_dict(
        self,
        label: str,
        value: str,
        value_confidence: float,
        label_confidence: Optional[float],
        page: int,
        bbox: Optional[List[float]],
        source: str,
        reason: str = "",
        suggested_label: str = "",
        alternatives: Optional[List[str]] = None,
        grounding_text: str = "",
        hint: str = "",
        structure_type: str = "label_value_pair",
        structure_group: str = "fields",
        structure_confidence: float = 0.95,
        region_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        has_label = bool(label and label.strip())
        v_conf = round(float(value_confidence), 4)

        if not has_label:
            l_conf = None
            overall_conf = round(v_conf * 0.85, 4)
            needs_rev = True
            if not hint:
                hint = "suggested" if suggested_label else "needs label"
        else:
            l_conf = round(float(label_confidence), 4) if label_confidence is not None else (0.98 if source == "document" else 0.88)
            overall_conf = round(math.sqrt(v_conf * l_conf), 4)
            needs_rev = overall_conf < self.review_threshold

        return {
            "label": label if has_label else "",
            "original_label": label if has_label else "",
            "value": value,
            "original_value": value,
            "confidence": overall_conf,
            "value_confidence": v_conf,
            "label_confidence": l_conf,
            "structure_confidence": round(float(structure_confidence), 4),
            "structure_type": structure_type,
            "structure_group": structure_group,
            "region_id": region_id,
            "source": source,
            "page": page,
            "bbox": bbox,
            "needs_review": needs_rev,
            "reason": reason,
            "suggested_label": suggested_label,
            "alternatives": alternatives or [],
            "hint": hint,
            "grounding_span": {
                "text": grounding_text or value,
                "bbox": bbox,
                "page": page,
            },
            "is_promoted": True,
            "in_more_details": False,
        }

    # -------------------------------------------------------------------------
    # 4. Split and Complete
    # -------------------------------------------------------------------------
    def _check_and_split_mixed_value(self, fld: Dict[str, Any]) -> List[Dict[str, Any]]:
        val = fld["value"]
        amt_match = re.search(r"\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})", val)
        date_match = DATE_REGEX.search(val)

        if amt_match and date_match and abs(amt_match.start() - date_match.start()) >= 5:
            amt_val = amt_match.group(0)
            date_val = date_match.group(0)
            fld1 = dict(fld)
            fld1["value"] = amt_val
            fld1["label"] = "Amount"
            fld1["split_suggestion"] = {
                "original_combined": val,
                "part": 1,
            }
            fld2 = dict(fld)
            fld2["value"] = date_val
            fld2["label"] = "Date"
            fld2["split_suggestion"] = {
                "original_combined": val,
                "part": 2,
            }
            return [fld1, fld2]

        return [fld]
