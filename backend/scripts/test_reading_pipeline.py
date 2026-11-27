"""Test script for reading pipeline on two real files."""

import os
import sys
from app.workers.vision_pipeline import (
    render_first_page_image,
    detect_page_condition,
    deskew_and_clean,
    call_anthropic_vision,
    cross_check_confidence,
)

test_files = ["test_files/trap_02_lab_report.pdf", "test_files/trap_03_mixed_case.pdf"]

for fpath in test_files:
    print(f"\n=======================================================")
    print(f"Reading file: {fpath}")
    print(f"=======================================================")
    
    # 1. Render page image
    img, page_count = render_first_page_image(fpath, dpi=150)
    print(f"Rendered page 1: image shape {img.shape}, total pages: {page_count}")
    
    # 2. Detect page condition
    cond, angle = detect_page_condition(img)
    print(f"Page condition detected: '{cond}' (skew angle: {angle:.2f} deg)")
    
    # 3. Deskew and clean
    cleaned = deskew_and_clean(img, angle)
    print(f"Cleaned image shape: {cleaned.shape}")
    
    # 4. Attempt vision extraction
    try:
        res = call_anthropic_vision(cleaned)
        print("Vision Extraction Success:")
        print(f"  Document Type: {res.get('doc_type')}")
        print(f"  Title: {res.get('title')}")
        print("  Extracted Fields:")
        for field in res.get("fields", []):
            print(f"    - {field.get('label')}: {field.get('value')} (conf: {field.get('confidence')})")
    except Exception as e:
        print(f"Vision Extraction Result (Honest Error): {type(e).__name__}: {e}")
