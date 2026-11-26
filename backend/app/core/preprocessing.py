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
    """Detect image orientation angle (0, 90, 180, 270) to correct upside-down or sideways scans.
    
    Uses horizontal vs vertical projection variance and morphological text line analysis.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if len(img_bgr.shape) == 3 else img_bgr
    
    try:
        import pytesseract
        osd = pytesseract.image_to_osd(gray, output_type=pytesseract.Output.DICT)
        rot = int(osd.get("rotate", 0))
        if rot in (90, 180, 270):
            return rot
    except Exception:
        pass

    # Variance-based aspect and text line orientation check
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    proj_h = np.sum(thresh, axis=1)
    proj_v = np.sum(thresh, axis=0)
    var_h = float(np.var(proj_h))
    var_v = float(np.var(proj_v))

    # If vertical variance is significantly higher than horizontal variance, text is likely rotated 90 or 270
    if var_v > var_h * 1.4:
        # Check ink density in left vs right half to distinguish 90 vs 270
        w = thresh.shape[1]
        left_ink = np.sum(thresh[:, : w // 3])
        right_ink = np.sum(thresh[:, 2 * w // 3 :])
        if right_ink > left_ink * 1.5:
            return 270
        return 90

    # Upside-down check (180 degrees)
    # 1. Document title/header ink concentration is typically in the top 25% of upright documents
    h, w = thresh.shape
    top_quarter = np.sum(thresh[: h // 4, :])
    bot_quarter = np.sum(thresh[3 * h // 4 :, :])
    
    if bot_quarter > top_quarter * 2.8 and top_quarter > 0:
        return 180

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
    """Deskew image if angle >= 0.5 degrees and downscale longest edge to max_dim."""
    h, w = img_bgr.shape[:2]
    result = img_bgr

    if 0.5 <= abs(skew_angle) <= 45.0:
        center = (w // 2, h // 2)
        m = cv2.getRotationMatrix2D(center, skew_angle, 1.0)
        result = cv2.warpAffine(result, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

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
    """Measure blur, noise, contrast, orientation, and skew to evaluate page quality."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if len(img_bgr.shape) == 3 else img_bgr
    
    # 1. Blur score via Laplacian variance
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    is_blurred = blur_score < 70.0

    # 2. Speckle noise count in mid-tones
    hist = np.histogram(gray, bins=10)[0]
    mid_noise = int(sum(hist[1:5]))
    is_noisy = mid_noise > 22000

    # 3. Contrast check
    contrast_std = float(np.std(gray))
    is_low_contrast = contrast_std < 40.0

    # 4. Orientation & Skew
    orientation = detect_orientation_angle(img_bgr)
    skew = detect_skew_angle(img_bgr)
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

    # 3. Denoising if noisy
    if quality["is_noisy"]:
        if len(result.shape) == 3:
            result = cv2.bilateralFilter(result, 5, 40, 40)
        else:
            result = cv2.medianBlur(result, 3)
        was_denoised = True

    # 4. Contrast normalization if low contrast
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
