import json
import time
from pathlib import Path
import cv2
import numpy as np
import fitz
import pytesseract
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.adapters.ocr import HybridOCREngine

pytesseract.pytesseract.tesseract_cmd = r"C:\ml\tools\tesseract_ub\tesseract.exe"
import os
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

val_dir = Path("data/dataset/val")
json_files = sorted(list(val_dir.glob("*.json")))[:40]

for psm in [None, "4", "6"]:
    total_dist = 0
    total_chars = 0
    cfg = f"--psm {psm}" if psm else ""
    t0 = time.time()
    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            meta = json.load(f)
        doc = fitz.open(val_dir / meta["file_name"])
        page = doc[0]
        pix = page.get_pixmap()
        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
        if pix.n == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
        doc.close()
        
        # Grayscale + Deskew only
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        deskewed = HybridOCREngine.deskew_image(gray)
        
        text = pytesseract.image_to_string(deskewed, config=cfg)
        ref_clean = "".join(meta.get("text", "").split())
        hyp_clean = "".join(text.split())
        dist = levenshtein_distance(ref_clean, hyp_clean)
        total_dist += dist
        total_chars += len(ref_clean)
    cer = (total_dist / total_chars) * 100.0
    print(f"Deskew Only | PSM {str(psm):<5} | CER: {cer:.2f}% | Time: {time.time()-t0:.1f}s")
