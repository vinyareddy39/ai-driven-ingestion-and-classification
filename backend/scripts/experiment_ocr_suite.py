import os
import sys
import json
import time
from pathlib import Path
import cv2
import numpy as np
import fitz
import pytesseract

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.ocr import HybridOCREngine

local_tess = r"C:\ml\tools\tesseract_ub\tesseract.exe"
pytesseract.pytesseract.tesseract_cmd = local_tess
os.environ["TESSDATA_PREFIX"] = r"C:\ml\tools\tesseract_ub\tessdata"

def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

def preprocess_image(img_np: np.ndarray, config_name: str) -> np.ndarray:
    if config_name == "raw":
        return img_np

    # 1. Grayscale
    if len(img_np.shape) == 3:
        gray = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)
    else:
        gray = img_np.copy()

    if config_name == "grayscale":
        return gray

    # 2. Deskew
    deskewed = HybridOCREngine.deskew_image(gray)
    if config_name == "deskew":
        return deskewed

    # 3. Denoise
    denoised = cv2.medianBlur(deskewed, 3)
    if config_name == "denoise":
        return denoised

    # 4. Adaptive Threshold
    if config_name == "adaptive_threshold":
        # Block size 31, C=10
        thresh = cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10)
        return thresh

    # 5. Otsu Threshold
    if config_name == "otsu":
        _, thresh = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresh

    return denoised

def evaluate_ocr_config(val_files: list, config_name: str, psm: str = None) -> float:
    total_dist = 0
    total_chars = 0
    
    extra_config = f"--psm {psm}" if psm else ""
    
    t0 = time.time()
    for meta, pdf_path in val_files:
        doc = fitz.open(pdf_path)
        page = doc[0]
        pix = page.get_pixmap()
        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
        if pix.n == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
        doc.close()

        proc_img = preprocess_image(img_np, config_name)
        
        ocr_text = pytesseract.image_to_string(proc_img, config=extra_config)
        
        ref_clean = "".join(meta.get("text", "").split())
        hyp_clean = "".join(ocr_text.split())
        dist = levenshtein_distance(ref_clean, hyp_clean)
        total_dist += dist
        total_chars += len(ref_clean)
        
    duration = time.time() - t0
    cer = (total_dist / total_chars) * 100.0 if total_chars > 0 else 0.0
    print(f"Config: {config_name:<20} | PSM: {str(psm):<5} | CER: {cer:6.2f}% | Time: {duration:5.1f}s")
    return cer

def main():
    val_dir = Path("data/dataset/val")
    json_files = sorted(list(val_dir.glob("*.json")))[:40]
    val_files = []
    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            meta = json.load(f)
        val_files.append((meta, val_dir / meta["file_name"]))

    print("=" * 75)
    print("OCR ABLATION SUITE: CHARACTER ERROR RATE (CER) ON 40 VAL SCANS")
    print("=" * 75)
    
    results = {}
    
    # 1. 300 DPI Raw (no preprocessing, default PSM)
    results["300dpi_raw"] = evaluate_ocr_config(val_files, "raw", psm=None)
    
    # 2. 300 DPI + Grayscale
    results["300dpi_grayscale"] = evaluate_ocr_config(val_files, "grayscale", psm=None)
    
    # 3. 300 DPI + Deskew
    results["300dpi_deskew"] = evaluate_ocr_config(val_files, "deskew", psm=None)
    
    # 4. 300 DPI + Deskew + Denoise
    results["300dpi_denoise"] = evaluate_ocr_config(val_files, "denoise", psm=None)
    
    # 5. 300 DPI + Adaptive Threshold
    results["300dpi_adaptive"] = evaluate_ocr_config(val_files, "adaptive_threshold", psm=None)

    # 6. 300 DPI + Otsu Threshold
    results["300dpi_otsu"] = evaluate_ocr_config(val_files, "otsu", psm=None)

    # 7. Try --psm 4 on best preproc
    results["300dpi_denoise_psm4"] = evaluate_ocr_config(val_files, "denoise", psm="4")
    
    # 8. Try --psm 6 on best preproc
    results["300dpi_denoise_psm6"] = evaluate_ocr_config(val_files, "denoise", psm="6")

    # 9. Try --psm 6 on adaptive threshold
    results["300dpi_adaptive_psm6"] = evaluate_ocr_config(val_files, "adaptive_threshold", psm="6")
    
    # 10. Try --psm 4 on adaptive threshold
    results["300dpi_adaptive_psm4"] = evaluate_ocr_config(val_files, "adaptive_threshold", psm="4")

    print("=" * 75)
    print("Summary of Results:")
    for k, v in results.items():
        print(f"  {k:<25}: {v:.2f}%")
    print("=" * 75)

if __name__ == "__main__":
    main()
