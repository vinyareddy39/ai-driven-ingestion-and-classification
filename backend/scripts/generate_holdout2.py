import json
import hashlib
import random
from pathlib import Path
from collections import Counter
import cv2
import fitz
import numpy as np
from faker import Faker

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.synthetic_generator import (
    CLASSES, GENERATOR_MAP, apply_image_degradations
)

SEED_HOLDOUT_2 = 20261119
fake = Faker()
Faker.seed(SEED_HOLDOUT_2)
random.seed(SEED_HOLDOUT_2)
np.random.seed(SEED_HOLDOUT_2)

HOLDOUT2_DIR = Path("data/dataset/holdout2")
HOLDOUT2_DIR.mkdir(parents=True, exist_ok=True)

def render_scanned_pdf_300dpi(text: str, degradation_type: str = "none") -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    lines = text.split("\n")
    y = 50
    for line in lines[:45]:
        page.insert_text(fitz.Point(40, y), line, fontsize=10, fontname="helv")
        y += 16

    pix = page.get_pixmap(dpi=300)
    img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
    if pix.n == 4:
        img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
    else:
        img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
    doc.close()

    if degradation_type and degradation_type != "none":
        img_np = apply_image_degradations(img_np, degradation_type)

    _, img_encoded = cv2.imencode(".png", img_np)

    scanned_doc = fitz.open()
    scanned_page = scanned_doc.new_page(width=595, height=842)
    scanned_page.insert_image(scanned_page.rect, stream=img_encoded.tobytes())
    pdf_bytes = scanned_doc.tobytes()
    scanned_doc.close()
    return pdf_bytes

def generate_holdout2():
    print(f"Generating Fresh Holdout 2 (Seed={SEED_HOLDOUT_2}) at 300 DPI pure scans...", flush=True)
    degradations = ["none", "none", "skew", "noise", "blur", "fax_binarization", "stamp"]
    
    # 40 docs per class across 9 classes = 360 documents
    manifest = []
    for doc_type in CLASSES:
        generator = GENERATOR_MAP[doc_type]
        print(f"  Generating 40 scans for class: {doc_type}...", flush=True)
        for i in range(40):
            idx = 500 + i + 1  # Unique index space (501..540) to guarantee zero ID collision
            doc_id = f"{doc_type}_h2_{idx:04d}"
            text, fields, pii_entities = generator(idx)
            deg = degradations[idx % len(degradations)]
            
            pdf_bytes = render_scanned_pdf_300dpi(text, deg)
            sha = hashlib.sha256(pdf_bytes).hexdigest()
            
            meta = {
                "doc_id": doc_id,
                "doc_type": doc_type,
                "sha256": sha,
                "split": "holdout2",
                "degradation": deg,
                "fields": fields,
                "pii_entities": pii_entities,
                "file_name": f"{doc_id}.pdf",
                "text": text,
            }
            
            with open(HOLDOUT2_DIR / f"{doc_id}.pdf", "wb") as pf:
                pf.write(pdf_bytes)
            with open(HOLDOUT2_DIR / f"{doc_id}.json", "w", encoding="utf-8") as jf:
                json.dump(meta, jf, indent=2)
            manifest.append(meta)
            
    print(f"Fresh Holdout 2 generated: {len(manifest)} documents in {HOLDOUT2_DIR}", flush=True)

if __name__ == "__main__":
    generate_holdout2()
