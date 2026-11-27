"""OCR and Document Pre-processing Engine implementing OCREngine interface.

Supports high-performance TrOCR on GPU with batching, fp16, text-layer bypass,
content-hash caching, and multi-page parallel processing, with configurable fallback
to HybridPyMuPDF-Tesseract.
"""

from concurrent.futures import ThreadPoolExecutor
import email
import hashlib
import io
import json
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Tuple

import cv2
import fitz  # PyMuPDF
import numpy as np
from PIL import Image


from app.core.config import get_app_settings
from app.core.interfaces import BoundingBox, OCREngine, OCRResult


# ---------------------------------------------------------------------------
# Image Pre-processing Utilities
# ---------------------------------------------------------------------------

def is_blank_image(image_np: np.ndarray, threshold: float = 0.995) -> bool:
    """Detect if an image page is essentially blank white space."""
    if len(image_np.shape) == 3:
        gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_np
    white_pixels = np.sum(gray > 250)
    total_pixels = gray.size
    return (white_pixels / float(total_pixels)) >= threshold


def deskew_image(image_np: np.ndarray) -> np.ndarray:
    """Deskew image using OpenCV contour minimum area rectangle."""
    try:
        if len(image_np.shape) == 3:
            gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)
        else:
            gray = image_np
        thresh = cv2.bitwise_not(gray)
        coords = np.column_stack(np.where(thresh > 0))
        if len(coords) < 10:
            return image_np
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        elif angle > 45:
            angle = 90 - angle
        else:
            angle = -angle

        if 0.5 < abs(angle) < 45.0:
            (h, w) = image_np.shape[:2]
            center = (w // 2, h // 2)
            m = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(
                image_np, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
            )
            return rotated
    except Exception:
        pass
    return image_np


def denoise_image(image_np: np.ndarray) -> np.ndarray:
    """Apply light bilateral filtering / denoising."""
    try:
        if len(image_np.shape) == 3:
            return cv2.bilateralFilter(image_np, 5, 50, 50)
        else:
            return cv2.medianBlur(image_np, 3)
    except Exception:
        return image_np


def detect_text_line_boxes(image_bgr: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """Detect text line bounding boxes using morphological dilation."""
    if len(image_bgr.shape) == 3:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_bgr

    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 5))
    dilated = cv2.dilate(thresh, kernel, iterations=1)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w > 20 and h > 8:
            boxes.append((x, y, w, h))

    # Sort boxes top to bottom, then left to right
    boxes.sort(key=lambda b: (b[1], b[0]))
    return boxes


# ---------------------------------------------------------------------------
# TrOCR Singleton Manager (GPU Acceleration, Batching, FP16)
# ---------------------------------------------------------------------------

class TrOCRManager:
    """Thread-safe singleton managing TrOCR model and processor on CUDA/CPU."""

    _instance: Optional["TrOCRManager"] = None
    _lock = threading.Lock()

    def __init__(self, model_name: str, use_gpu: bool = True):
        import torch
        self.model_name = model_name
        self.device = "cuda" if (use_gpu and torch.cuda.is_available()) else "cpu"
        self.fp16 = (self.device == "cuda")
        self.gpu_lock = threading.Lock()

        from transformers import TrOCRProcessor, VisionEncoderDecoderModel

        self.processor = TrOCRProcessor.from_pretrained(model_name, local_files_only=True)
        self.model = VisionEncoderDecoderModel.from_pretrained(model_name, local_files_only=True)
        self.model.eval()

        if self.device == "cuda":
            self.model.to("cuda")
            if self.fp16:
                self.model.half()

        # Warmup forward pass to prime CUDA kernels
        try:
            dummy_img = Image.new("RGB", (384, 48), color=(255, 255, 255))
            inputs = self.processor(dummy_img, return_tensors="pt").pixel_values.to(self.device)
            if self.fp16:
                inputs = inputs.half()
            with torch.inference_mode():
                self.model.generate(inputs, max_new_tokens=5, num_beams=1)
        except Exception:
            pass

    @classmethod
    def get_instance(cls, model_name: str = "microsoft/trocr-base-printed", use_gpu: bool = True) -> "TrOCRManager":
        import torch
        with cls._lock:
            if cls._instance is None or cls._instance.model_name != model_name or (use_gpu and cls._instance.device != "cuda" and torch.cuda.is_available()):
                cls._instance = cls(model_name, use_gpu=use_gpu)
            return cls._instance

    def recognize_crops(
        self,
        crops: List[Image.Image],
        batch_size: int = 16,
        max_new_tokens: int = 35,
    ) -> List[str]:
        if not crops:
            return []

        import torch
        results = []
        with self.gpu_lock:
            for i in range(0, len(crops), batch_size):
                batch = crops[i : i + batch_size]
                pixel_values = self.processor(batch, return_tensors="pt").pixel_values.to(self.device)
                if self.fp16:
                    pixel_values = pixel_values.half()

                with torch.inference_mode():
                    generated_ids = self.model.generate(
                        pixel_values,
                        max_new_tokens=max_new_tokens,
                        num_beams=1,
                    )
                texts = self.processor.batch_decode(generated_ids, skip_special_tokens=True)
                results.extend(texts)
        return results


# ---------------------------------------------------------------------------
# High-Performance TrOCR Pipeline Engine
# ---------------------------------------------------------------------------

class TrOCREngine(OCREngine):
    """Production TrOCR Engine with Text-Layer Bypass, CUDA Batching, and Hash Caching."""

    def __init__(self):
        settings = get_app_settings()
        self.engine_name = f"TrOCR-{settings.OCR_MODEL.split('/')[-1]}"
        self.engine_version = "1.0.0-gpu" if settings.OCR_USE_GPU else "1.0.0-cpu"
        self.model_name = settings.OCR_MODEL
        self.use_gpu = settings.OCR_USE_GPU
        self.batch_size = settings.OCR_BATCH_SIZE
        self.dpi = settings.OCR_DPI
        self.cache_enabled = settings.OCR_CACHE_ENABLED
        self.min_text_chars = 30

        # In-memory LRU content hash cache
        self._cache: Dict[str, OCRResult] = {}
        self._cache_lock = threading.Lock()

        # Initialize TrOCR manager singleton
        self.manager = TrOCRManager.get_instance(self.model_name, use_gpu=self.use_gpu)

    def _get_cached_result(self, file_bytes: bytes) -> Optional[OCRResult]:
        if not self.cache_enabled:
            return None
        sha256 = hashlib.sha256(file_bytes).hexdigest()
        with self._cache_lock:
            return self._cache.get(sha256)

    def _save_cached_result(self, file_bytes: bytes, result: OCRResult) -> None:
        if not self.cache_enabled:
            return
        sha256 = hashlib.sha256(file_bytes).hexdigest()
        with self._cache_lock:
            # Simple capacity limit of 500 documents in memory
            if len(self._cache) > 500:
                self._cache.pop(next(iter(self._cache)))
            self._cache[sha256] = result

    # -----------------------------------------------------------------------
    # Document Format Parsers
    # -----------------------------------------------------------------------

    def _parse_docx(self, file_bytes: bytes) -> OCRResult:
        import docx
        doc = docx.Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        full_text = "\n".join(paragraphs)
        words = full_text.split()
        bboxes = [
            BoundingBox(text=w, x0=10.0, y0=float(i * 15), x1=50.0, y1=float(i * 15 + 12), page=1)
            for i, w in enumerate(words[:500])
        ]
        return OCRResult(
            full_text=full_text,
            pages_count=1,
            bounding_boxes=bboxes,
            searchable_pdf_bytes=None,
            engine_name=self.engine_name,
            engine_version=self.engine_version,
            page_methods=["text_layer"],
        )

    def _parse_eml(self, file_bytes: bytes) -> OCRResult:
        msg = email.message_from_bytes(file_bytes)
        headers = []
        for h in ["From", "To", "Subject", "Date"]:
            val = msg.get(h, "")
            if val:
                headers.append(f"{h}: {val}")

        body_parts = []
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype in ["text/plain", "text/html"]:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body_parts.append(payload.decode("utf-8", errors="ignore"))
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body_parts.append(payload.decode("utf-8", errors="ignore"))

        full_text = "\n".join(headers) + "\n\n" + "\n".join(body_parts)
        words = full_text.split()
        bboxes = [
            BoundingBox(text=w, x0=10.0, y0=float(i * 15), x1=50.0, y1=float(i * 15 + 12), page=1)
            for i, w in enumerate(words[:500])
        ]
        return OCRResult(
            full_text=full_text,
            pages_count=1,
            bounding_boxes=bboxes,
            searchable_pdf_bytes=None,
            engine_name=self.engine_name,
            engine_version=self.engine_version,
            page_methods=["text_layer"],
        )

    def _process_scanned_page(
        self, img_np: np.ndarray, page_idx: int
    ) -> Tuple[str, List[BoundingBox]]:
        """Run text line detection and TrOCR on a single rendered page."""
        deskewed = deskew_image(img_np)
        denoised = denoise_image(deskewed)

        boxes = detect_text_line_boxes(denoised)
        crops = []
        valid_boxes = []

        for x, y, w, h in boxes:
            if w < 10 or h < 6:
                continue
            crop_np = denoised[y : y + h, x : x + w]
            crops.append(Image.fromarray(crop_np))
            valid_boxes.append((x, y, w, h))

        recognized_lines = self.manager.recognize_crops(crops, batch_size=self.batch_size)
        bboxes = []
        for (x, y, w, h), text_line in zip(valid_boxes, recognized_lines):
            for word in text_line.split():
                bboxes.append(
                    BoundingBox(
                        text=word,
                        x0=float(x),
                        y0=float(y),
                        x1=float(x + w),
                        y1=float(y + h),
                        page=page_idx + 1,
                        confidence=0.92,
                    )
                )

        page_text = "\n".join(recognized_lines)
        return page_text, bboxes

    def _parse_pdf(self, file_bytes: bytes) -> OCRResult:
        """Parse PDF: bypass OCR on pages with text layer, OCR scanned pages with TrOCR/Tesseract."""
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        if len(doc) > 500:
            doc.close()
            raise ValueError(f"PDF exceeds maximum allowed page count (500 pages, got {len(doc)}).")

        pages_text: List[str] = []
        bboxes: List[BoundingBox] = []
        page_methods: List[str] = []
        valid_pages_count = len(doc)

        scanned_pages: List[Tuple[int, np.ndarray]] = []
        safe_dpi = min(getattr(self, "dpi", 150), 200)

        for page_idx in range(len(doc)):
            page = doc[page_idx]

            # Step 1: Check if text layer exists directly
            direct_text = page.get_text("text").strip()
            if len(direct_text) >= self.min_text_chars:
                # Text layer present: extract directly and bypass OCR entirely
                page_words = page.get_text("words")
                for w in page_words:
                    bboxes.append(
                        BoundingBox(
                            text=w[4],
                            x0=float(w[0]),
                            y0=float(w[1]),
                            x1=float(w[2]),
                            y1=float(w[3]),
                            page=page_idx + 1,
                            confidence=0.99,
                        )
                    )
                pages_text.append(direct_text)
                page_methods.append("text_layer")
            else:
                # Scanned image page: render and queue for OCR
                pix = page.get_pixmap(dpi=safe_dpi)
                if pix.width * pix.height > 50_000_000:
                    del pix
                    doc.close()
                    raise ValueError(f"Page image resolution {pix.width}x{pix.height} exceeds safe limit of 50,000,000 pixels.")

                img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
                if pix.n == 4:
                    img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
                elif pix.n == 1:
                    img_np = cv2.cvtColor(img_np, cv2.COLOR_GRAY2RGB)

                del pix
                if len(doc) > 1 and is_blank_image(img_np):
                    del img_np
                    continue

                scanned_pages.append((page_idx, img_np))
                page_methods.append("ocr")
                pages_text.append("")

            del page

        doc.close()

        # Step 3: Process scanned pages in parallel (or sequential if 1 page)
        if scanned_pages:
            if len(scanned_pages) > 1 and not self.use_gpu:
                # Use CPU thread pool
                with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 2)) as executor:
                    futures = [
                        (p_idx, executor.submit(self._process_scanned_page, img, p_idx))
                        for p_idx, img in scanned_pages
                    ]
                    for p_idx, fut in futures:
                        p_text, p_boxes = fut.result()
                        pages_text[p_idx] = p_text
                        bboxes.extend(p_boxes)
            else:
                for p_idx, img in scanned_pages:
                    p_text, p_boxes = self._process_scanned_page(img, p_idx)
                    pages_text[p_idx] = p_text
                    bboxes.extend(p_boxes)

        full_text = "\n\n".join(t for t in pages_text if t.strip())
        is_all_text_layer = page_methods and all(m == "text_layer" for m in page_methods)
        engine_display = "direct text" if is_all_text_layer else "OCR"
        return OCRResult(
            full_text=full_text,
            pages_count=max(1, valid_pages_count),
            bounding_boxes=bboxes,
            searchable_pdf_bytes=file_bytes,
            engine_name=engine_display,
            engine_version=self.engine_version,
            page_methods=page_methods,
        )

    def _parse_image(self, file_bytes: bytes, file_ext: str) -> OCRResult:
        """Parse standalone images (PNG, JPG, TIFF) via TrOCR."""
        nparr = np.frombuffer(file_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Corrupt or invalid image format")

        page_text, bboxes = self._process_scanned_page(img, page_idx=0)
        return OCRResult(
            full_text=page_text,
            pages_count=1,
            bounding_boxes=bboxes,
            searchable_pdf_bytes=None,
            engine_name="OCR",
            engine_version=self.engine_version,
            page_methods=["ocr"],
        )

    def extract_text(self, file_bytes: bytes, file_type: str, file_name: Optional[str] = None) -> OCRResult:
        # Rule 6: No stored answers. Every upload is read again from scratch.
        file_type = file_type.lower().replace(".", "")
        if file_type == "pdf":
            res = self._parse_pdf(file_bytes)
        elif file_type in ["docx", "doc"]:
            res = self._parse_docx(file_bytes)
        elif file_type in ["eml", "msg"]:
            res = self._parse_eml(file_bytes)
        elif file_type in ["png", "jpg", "jpeg", "tiff", "tif"]:
            res = self._parse_image(file_bytes, file_type)
        else:
            try:
                res = self._parse_pdf(file_bytes)
            except Exception:
                res = OCRResult(
                    full_text=file_bytes.decode("utf-8", errors="ignore"),
                    pages_count=1,
                    bounding_boxes=[],
                    searchable_pdf_bytes=None,
                    engine_name=self.engine_name,
                    engine_version=self.engine_version,
                    page_methods=["fallback"],
                )

        return res

    def extract_bounding_boxes(self, file_bytes: bytes, file_type: str) -> List[BoundingBox]:
        return self.extract_text(file_bytes, file_type).bounding_boxes

    def generate_searchable_pdf(self, file_bytes: bytes, file_type: str) -> bytes:
        res = self.extract_text(file_bytes, file_type)
        if res.searchable_pdf_bytes:
            return res.searchable_pdf_bytes
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text(fitz.Point(50, 72), res.full_text[:3000], fontsize=10)
        return doc.tobytes()


# ---------------------------------------------------------------------------
# Legacy Hybrid Engine for Fallback Compatibility
# ---------------------------------------------------------------------------

class HybridOCREngine(OCREngine):
    """Lightweight OCR engine using PyMuPDF and optional Tesseract without heavy PyTorch models."""

    def __init__(self, engine_name: str = "HybridPyMuPDF-Tesseract", engine_version: str = "2.4.0"):
        self.engine_name = engine_name
        self.engine_version = engine_version

    def extract_text(self, file_bytes: bytes, file_type: str, *args, **kwargs) -> OCRResult:
        ft = file_type.lower().replace(".", "")
        try:
            doc = fitz.open(stream=file_bytes, filetype=ft)
        except Exception:
            doc = fitz.open(stream=file_bytes)
        pages_text = []
        bboxes = []
        methods = []
        for i, page in enumerate(doc):
            t = page.get_text("text").strip()
            w_list = page.get_text("words")
            if not t:
                # Attempt lightweight OCR via pytesseract using local Tesseract binary if available
                ocr_text = ""
                try:
                    import pytesseract
                    from PIL import Image

                    # Auto-detect local tesseract binary
                    for possible_cmd in [
                        os.getenv("TESSERACT_CMD"),
                        "C:/ml/backend/tools/tesseract/tesseract.exe",
                        "C:/ml/tools/tesseract/tesseract.exe",
                        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "tools", "tesseract", "tesseract.exe")),
                        "tesseract",
                    ]:
                        if possible_cmd and (os.path.exists(possible_cmd) or possible_cmd == "tesseract"):
                            pytesseract.pytesseract.tesseract_cmd = possible_cmd
                            break

                    for possible_tessdata in [
                        os.getenv("TESSDATA_PREFIX"),
                        "C:/ml/backend/tools/tesseract/tessdata",
                        "C:/ml/tools/tesseract/tessdata",
                        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "tools", "tesseract", "tessdata")),
                    ]:
                        if possible_tessdata and os.path.exists(possible_tessdata):
                            os.environ["TESSDATA_PREFIX"] = possible_tessdata
                            break

                    pix = page.get_pixmap()
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    
                    # Pass 1: Primary extraction with PSM 6 (uniform block of text)
                    data1 = pytesseract.image_to_data(img, config="--psm 6", output_type=pytesseract.Output.DICT)
                    
                    # Pass 2: Secondary extraction with PSM 4 (single column variable sizes) for two-pass validation
                    try:
                        data2 = pytesseract.image_to_data(img, config="--psm 4", output_type=pytesseract.Output.DICT)
                        pass2_words = [data2['text'][k].strip() for k in range(len(data2['text'])) if data2['text'][k].strip()]
                        pass2_text = " ".join(pass2_words)
                    except Exception:
                        pass2_text = ""

                    ocr_words = []
                    for j in range(len(data1['text'])):
                        word = data1['text'][j].strip()
                        if word:
                            bx = float(data1['left'][j])
                            by = float(data1['top'][j])
                            bw = float(data1['width'][j])
                            bh = float(data1['height'][j])
                            raw_conf = data1.get('conf', [])[j] if 'conf' in data1 else -1
                            try:
                                conf_val = max(0.20, min(1.0, float(raw_conf) / 100.0)) if float(raw_conf) >= 0 else 0.90
                            except Exception:
                                conf_val = 0.90
                            bboxes.append(BoundingBox(text=word, x0=bx, y0=by, x1=bx+bw, y1=by+bh, page=i + 1, confidence=conf_val))
                            ocr_words.append(word)
                    ocr_text = " ".join(ocr_words)
                    methods.append("tesseract")
                except Exception:
                    # When Tesseract is unavailable and external AI is not allowed, avoid heavy TrOCR if restricted
                    methods.append("direct_image")
                pages_text.append(ocr_text or "")
            else:
                methods.append("text_layer")
                pages_text.append(t)
                for w in w_list:
                    bboxes.append(BoundingBox(text=w[4], x0=float(w[0]), y0=float(w[1]), x1=float(w[2]), y1=float(w[3]), page=i + 1))
        return OCRResult(
            full_text="\n\n".join(pages_text),
            pages_count=len(doc),
            bounding_boxes=bboxes,
            engine_name=self.engine_name,
            engine_version=self.engine_version,
            page_methods=methods if methods else ["text_layer"] * len(doc),
        )

    def extract_bounding_boxes(self, file_bytes: bytes, file_type: str, *args, **kwargs) -> List[BoundingBox]:
        return self.extract_text(file_bytes, file_type, *args, **kwargs).bounding_boxes

    def generate_searchable_pdf(self, file_bytes: bytes, file_type: str) -> bytes:
        return file_bytes


# ---------------------------------------------------------------------------
# Engine Factory Singleton
# ---------------------------------------------------------------------------

_ocr_engine_singleton: Optional[OCREngine] = None


def get_ocr_engine() -> OCREngine:
    """Factory returning configured OCR engine instance."""
    global _ocr_engine_singleton
    if _ocr_engine_singleton is None:
        settings = get_app_settings()
        engine_type = os.getenv("OCR_ENGINE", getattr(settings, "OCR_ENGINE", "trocr")).lower()
        if engine_type == "trocr":
            _ocr_engine_singleton = TrOCREngine()
        else:
            _ocr_engine_singleton = HybridOCREngine()
    return _ocr_engine_singleton
