"""Multi-Format Document Ingestion, Pre-processing, and Auto-Orientation Engine.

Features:
- Uniform ingestion across:
  * PDF documents (digital layer & scanned page rendering via PyMuPDF)
  * Standard images (PNG, JPG, BMP)
  * Multi-page TIFF (via PIL ImageSequence)
  * Email attachments (.eml / .msg via email library)
- Image Pre-processing:
  * Skew measurement & correction (Canny edges + Hough lines)
  * Auto-orientation detection (0, 90, 180, 270 degrees) to fix upside-down / sideways scans
  * Contrast optimization and long-side downscaling to ~1000px
- All local OCR and vision pipelines run on PREPROCESSED images, never raw pages.
"""

import email
import io
import logging
import os
from typing import Any, Dict, Generator, List, Optional, Tuple

import cv2
import fitz  # PyMuPDF
import numpy as np
from PIL import Image, ImageSequence

logger = logging.getLogger("core.preprocessing")


# ---------------------------------------------------------------------------
# 1. Orientation Detection (0, 90, 180, 270 degrees)
# ---------------------------------------------------------------------------
def detect_orientation_angle(img_bgr: np.ndarray) -> int:
    """Detect image orientation angle (0, 90, 180, 270) by running fast reading at each angle.
    
    Chooses the orientation with the best reading score (readable word count & confidence).
    """
    try:
        import pytesseract

        # Ensure tesseract executable and tessdata are discovered
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

        scores: Dict[int, float] = {}
        for ang in [0, 90, 180, 270]:
            if ang == 0:
                t_img = img_bgr
            elif ang == 90:
                t_img = cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)
            elif ang == 180:
                t_img = cv2.rotate(img_bgr, cv2.ROTATE_180)
            elif ang == 270:
                t_img = cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)

            g = cv2.cvtColor(t_img, cv2.COLOR_BGR2GRAY) if len(t_img.shape) == 3 else t_img
            h, w = g.shape[:2]
            scale = min(1.0, 700.0 / max(h, w))
            if scale < 1.0:
                sg = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            else:
                sg = g

            # Fast reading pass with PSM 6
            d = pytesseract.image_to_data(sg, config="--psm 6", output_type=pytesseract.Output.DICT)
            words = []
            confs = []
            for i in range(len(d["text"])):
                txt = d["text"][i].strip()
                c_val = int(d["conf"][i]) if i < len(d["conf"]) else -1
                if c_val >= 20 and len(txt) >= 2 and any(ch.isalnum() for ch in txt):
                    words.append(txt)
                    confs.append(c_val)

            cnt = len(words)
            avg_c = (sum(confs) / cnt) if cnt > 0 else 0.0
            # Higher score for more readable words with higher confidence
            scores[ang] = float(cnt) * (avg_c / 100.0)

            # Optimization: If angle 0 has very strong reading (>= 25 clear words, avg_conf >= 85), page is upright
            if ang == 0 and cnt >= 25 and avg_c >= 85.0:
                return 0

        best_ang = max(scores, key=lambda k: scores[k])
        if scores[best_ang] > 0.0:
            return best_ang
    except Exception as e:
        logger.debug(f"Orientation scoring failed: {e}")

    return 0


def auto_rotate_image(img_bgr: np.ndarray, angle: int) -> np.ndarray:
    """Rotate image by 90, 180, or 270 degrees clockwise to make it upright."""
    if angle == 90:
        return cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)
    elif angle == 180:
        return cv2.rotate(img_bgr, cv2.ROTATE_180)
    elif angle == 270:
        return cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img_bgr


# ---------------------------------------------------------------------------
# 2. Skew Angle Detection & Deskewing
# ---------------------------------------------------------------------------
def detect_skew_angle(img_bgr: np.ndarray) -> float:
    """Detect skew angle in degrees using Hough lines and contour minAreaRect."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if len(img_bgr.shape) == 3 else img_bgr
    
    # 1. Hough lines method
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 80, minLineLength=50, maxLineGap=10)
    
    angles = []
    if lines is not None:
        for line in lines:
            pts = line.flatten()
            if len(pts) == 4:
                x1, y1, x2, y2 = pts
                if abs(x2 - x1) > 20:
                    ang = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
                    if abs(ang) < 45.0:
                        angles.append(ang)
                        
    if angles:
        return float(np.median(angles))

    # 2. Fallback to minAreaRect on dilated text lines
    try:
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        coords = np.column_stack(np.where(thresh > 0))
        if len(coords) > 50:
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                angle = -(90 + angle)
            elif angle > 45:
                angle = 90 - angle
            else:
                angle = -angle
            if 0.5 <= abs(angle) <= 45.0:
                return float(angle)
    except Exception:
        pass

    return 0.0


def deskew_and_rescale(img_bgr: np.ndarray, skew_angle: float, max_dim: int = 1400) -> np.ndarray:
    """Deskew image if angle >= 0.5 degrees with bounding box expansion, and downscale longest edge to max_dim."""
    h, w = img_bgr.shape[:2]
    result = img_bgr

    if 0.5 <= abs(skew_angle) <= 45.0:
        center = (w // 2, h // 2)
        m = cv2.getRotationMatrix2D(center, skew_angle, 1.0)
        # Full bounding expansion so corners and text are NEVER clipped
        cos_val = np.abs(m[0, 0])
        sin_val = np.abs(m[0, 1])
        new_w = int((h * sin_val) + (w * cos_val))
        new_h = int((h * cos_val) + (w * sin_val))
        m[0, 2] += (new_w / 2.0) - center[0]
        m[1, 2] += (new_h / 2.0) - center[1]
        result = cv2.warpAffine(result, m, (new_w, new_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))

    cur_max = max(result.shape[:2])
    if cur_max > max_dim:
        scale = float(max_dim) / cur_max
        new_w = int(result.shape[1] * scale)
        new_h = int(result.shape[0] * scale)
        result = cv2.resize(result, (new_w, new_h), interpolation=cv2.INTER_AREA)

    return result


# ---------------------------------------------------------------------------
# 3. Comprehensive Quality Assessment and Pre-processing
# ---------------------------------------------------------------------------
def assess_page_quality(img_bgr: np.ndarray) -> Dict[str, Any]:
    """Measure orientation, then upright skew, blur, noise, and contrast to evaluate page quality."""
    # 1. Orientation first across 0°, 90°, 180°, 270°
    orientation = detect_orientation_angle(img_bgr)
    upright = auto_rotate_image(img_bgr, orientation)

    gray = cv2.cvtColor(upright, cv2.COLOR_BGR2GRAY) if len(upright.shape) == 3 else upright
    
    # 2. Blur score via Laplacian variance
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    is_blurred = blur_score < 70.0

    # 3. Speckle noise count in mid-tones
    hist = np.histogram(gray, bins=10)[0]
    mid_noise = int(sum(hist[1:5]))
    is_noisy = mid_noise > 22000

    # 4. Contrast check
    contrast_std = float(np.std(gray))
    is_low_contrast = contrast_std < 40.0

    # 5. Skew detection on the upright page
    skew = detect_skew_angle(upright)
    is_skewed = abs(skew) >= 1.0

    # Determine condition text label
    conditions = []
    penalty = 0.0

    if orientation != 0:
        conditions.append(f"rotated {orientation}°")
    if is_skewed:
        conditions.append(f"skewed ({skew:.1f}°)")
        penalty += min(0.08, abs(skew) * 0.01)
    if is_noisy:
        conditions.append("noisy/speckled")
        penalty += 0.06
    if is_blurred:
        conditions.append("blurred")
        penalty += 0.07
    if is_low_contrast:
        conditions.append("low contrast")
        penalty += 0.04

    condition_str = ", ".join(conditions) if conditions else "clean"

    return {
        "condition": condition_str,
        "orientation_degrees": orientation,
        "skew_angle": round(skew, 2),
        "blur_score": round(blur_score, 2),
        "noise_level": mid_noise,
        "contrast_std": round(contrast_std, 2),
        "is_noisy": is_noisy,
        "is_blurred": is_blurred,
        "is_low_contrast": is_low_contrast,
        "confidence_penalty": min(0.20, penalty),
    }


def preprocess_image(img_bgr: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Complete pre-processing pipeline: auto-orient, deskew, denoise, normalize, and rescale."""
    quality = assess_page_quality(img_bgr)
    
    # 1. Orientation correction (including upside-down 180)
    rot_angle = quality["orientation_degrees"]
    oriented = auto_rotate_image(img_bgr, rot_angle)

    # 2. Skew correction
    skew_angle = quality["skew_angle"]
    deskewed = deskew_and_rescale(oriented, skew_angle)

    result = deskewed
    was_denoised = False
    was_normalized = False

    # 3. Small image / text height scaling (ensure text is at least ~30px tall)
    try:
        gray_tmp = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY) if len(result.shape) == 3 else result
        _, thresh_tmp = cv2.threshold(gray_tmp, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(thresh_tmp, connectivity=8)
        char_heights = [
            stats[i, cv2.CC_STAT_HEIGHT]
            for i in range(1, num_labels)
            if 4 <= stats[i, cv2.CC_STAT_HEIGHT] <= 250 and 3 <= stats[i, cv2.CC_STAT_WIDTH] <= 300
        ]
        if char_heights:
            med_char_h = float(np.median(char_heights))
            if med_char_h < 28.0:
                scale_up = min(3.5, 30.0 / max(6.0, med_char_h))
                if scale_up > 1.1:
                    new_w = int(result.shape[1] * scale_up)
                    new_h = int(result.shape[0] * scale_up)
                    result = cv2.resize(result, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    except Exception:
        pass

    # 4. Denoising: gentle bilateral filter to reduce speckle noise without destroying thin character strokes
    was_denoised = False
    if quality["is_noisy"]:
        if len(result.shape) == 3:
            result = cv2.bilateralFilter(result, 5, 35, 35)
        else:
            result = cv2.bilateralFilter(result, 5, 35, 35)
        was_denoised = True

    # 5. Contrast normalization if low contrast
    was_normalized = False
    if quality["is_low_contrast"]:
        if len(result.shape) == 3:
            lab = cv2.cvtColor(result, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            cl = clahe.apply(l)
            merged = cv2.merge((cl, a, b))
            result = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
        else:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            result = clahe.apply(result)
        was_normalized = True

    pad = 0
    # Do not inject artificial borders that degrade OCR page segmentation

    metadata = {
        "condition": quality["condition"],
        "orientation_degrees": rot_angle,
        "skew_angle": skew_angle,
        "blur_score": quality["blur_score"],
        "noise_level": quality["noise_level"],
        "denoised": was_denoised,
        "contrast_normalized": was_normalized,
        "confidence_penalty": quality["confidence_penalty"],
        "dimensions": (result.shape[1], result.shape[0]),
        "pad": pad,
    }
    return result, metadata


# ---------------------------------------------------------------------------
# 3. Multi-Format File Ingestion
# ---------------------------------------------------------------------------
def load_document_pages(file_path: str) -> List[np.ndarray]:
    """Ingest document from PDF, multi-page TIFF, PNG/JPG, or EML and return list of preprocessed BGR pages."""
    ext = os.path.splitext(file_path)[1].lower()
    pages_bgr: List[np.ndarray] = []

    # 1. PDF
    if ext == ".pdf":
        doc = fitz.open(file_path)
        for page in doc:
            pix = page.get_pixmap(dpi=150)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            if pix.n == 4:
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            elif pix.n == 3:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            prep, _ = preprocess_image(img)
            pages_bgr.append(prep)
        doc.close()

    # 2. Multi-page TIFF
    elif ext in (".tif", ".tiff"):
        with Image.open(file_path) as tiff_img:
            for frame in ImageSequence.Iterator(tiff_img):
                rgb = frame.convert("RGB")
                np_frame = np.array(rgb)
                bgr = cv2.cvtColor(np_frame, cv2.COLOR_RGB2BGR)
                prep, _ = preprocess_image(bgr)
                pages_bgr.append(prep)

    # 3. Email files (.eml / .msg)
    elif ext in (".eml", ".msg"):
        with open(file_path, "rb") as f:
            msg = email.message_from_binary_file(f)
            # Look for image attachments
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type.startswith("image/"):
                    payload = part.get_payload(decode=True)
                    if payload:
                        nparr = np.frombuffer(payload, np.uint8)
                        bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        if bgr is not None:
                            prep, _ = preprocess_image(bgr)
                            pages_bgr.append(prep)

    # 4. Standard Images (PNG, JPG, BMP)
    else:
        bgr = cv2.imread(file_path)
        if bgr is not None:
            prep, _ = preprocess_image(bgr)
            pages_bgr.append(prep)

    return pages_bgr
