import json
import hashlib
import random
from pathlib import Path
import cv2
import fitz
import numpy as np
from faker import Faker

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.synthetic_generator import (
    SEED, CLASSES, GENERATOR_MAP, apply_image_degradations,
    TRAIN_DIR, VAL_DIR, SPECIAL_DIR
)

# Re-seed exactly as before
fake = Faker()
Faker.seed(SEED)
random.seed(SEED)
np.random.seed(SEED)

def render_scanned_pdf_300dpi(text: str, degradation_type: str = "none") -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    lines = text.split("\n")
    y = 50
    for line in lines[:45]:
        page.insert_text(fitz.Point(40, y), line, fontsize=10, fontname="helv")
        y += 16

    # 300 DPI rendering
    pix = page.get_pixmap(dpi=300)
    img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
    if pix.n == 4:
        img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
    else:
        img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
    doc.close()

    # Visual degradation
    if degradation_type and degradation_type != "none":
        img_np = apply_image_degradations(img_np, degradation_type)

    _, img_encoded = cv2.imencode(".png", img_np)

    scanned_doc = fitz.open()
    scanned_page = scanned_doc.new_page(width=595, height=842)
    scanned_page.insert_image(scanned_page.rect, stream=img_encoded.tobytes())
    pdf_bytes = scanned_doc.tobytes()
    scanned_doc.close()
    return pdf_bytes

def regenerate_train_and_val():
    print("Regenerating train (1080) and val (360) sets at 300 DPI with seed", SEED)
    degradations = ["none", "none", "skew", "noise", "blur", "fax_binarization", "stamp"]

    for doc_type in CLASSES:
        generator = GENERATOR_MAP[doc_type]
        print(f"  Rendering class: {doc_type} at 300 DPI...")
        for i in range(200):
            idx = i + 1
            doc_id = f"{doc_type}_{idx:04d}"
            text, fields, pii_entities = generator(idx)
            deg = degradations[idx % len(degradations)]

            if idx <= 120:
                split = "train"
                target_dir = TRAIN_DIR
            elif idx <= 160:
                split = "val"
                target_dir = VAL_DIR
            else:
                # Do NOT touch holdout (seed 20261118 holdout is burned, will generate fresh holdout 2 at end)
                continue

            pdf_bytes = render_scanned_pdf_300dpi(text, deg)
            sha = hashlib.sha256(pdf_bytes).hexdigest()

            meta = {
                "doc_id": doc_id,
                "doc_type": doc_type,
                "sha256": sha,
                "split": split,
                "degradation": deg,
                "fields": fields,
                "pii_entities": pii_entities,
                "file_name": f"{doc_id}.pdf",
                "text": text,
            }

            with open(target_dir / f"{doc_id}.pdf", "wb") as pf:
                pf.write(pdf_bytes)
            with open(target_dir / f"{doc_id}.json", "w", encoding="utf-8") as jf:
                json.dump(meta, jf, indent=2)

    print("Regeneration of train and val at 300 DPI complete.")

if __name__ == "__main__":
    regenerate_train_and_val()
