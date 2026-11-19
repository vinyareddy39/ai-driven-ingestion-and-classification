"""Generate synthetic benchmark files for OCR benchmarking.

Generates:
- 1page_sample.pdf (1 page)
- 3page_sample.pdf (3 pages)
- 10page_sample.pdf (10 pages)
- 100page_sample.pdf (100 pages)
- scan_sample.png (1 page rendered as flat image scan)
"""

import os
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont


SAMPLE_TEXT_PAGE = """INVOICE
Invoice Number: INV-2026-8891
Invoice Date: 2026-11-12
Due Date: 2026-12-12
Vendor: Apex Healthcare Systems
Vendor Address: 100 Medical Center Blvd, Suite 400
Customer: Jane Doe
Email: jane.doe@example.com
Phone: (555) 234-5678
Address: 742 Evergreen Terrace, Springfield, IL 62704
SSN: 000-12-3456

Description                       Qty    Unit Price    Total
-----------------------------------------------------------------
Comprehensive Consultation          1       $250.00    $250.00
Blood Chemistry Screening           1       $180.00    $180.00
Diagnostic Imaging Service          1       $520.00    $520.00
Medication Delivery Support         2        $25.00     $50.00
-----------------------------------------------------------------
Subtotal:                                            $1000.00
Tax (8%):                                              $80.00
Total Amount:                                        $1080.00

Payment Terms: Net 30 Days.
Thank you for your business."""


def generate_benchmark_files(output_dir: str = "data/test"):
    os.makedirs(output_dir, exist_ok=True)

    # 1. Generate 1-page PDF
    doc1 = fitz.open()
    page1 = doc1.new_page(width=595, height=842)  # A4
    page1.insert_text(fitz.Point(50, 72), SAMPLE_TEXT_PAGE, fontsize=11)
    p1_path = os.path.join(output_dir, "1page_sample.pdf")
    doc1.save(p1_path)
    doc1.close()
    print(f"Created {p1_path}")

    # 2. Generate 3-page PDF
    doc3 = fitz.open()
    for i in range(3):
        p = doc3.new_page(width=595, height=842)
        p_text = f"PAGE {i+1} of 3\n\n" + SAMPLE_TEXT_PAGE.replace("INV-2026-8891", f"INV-2026-889{i+1}")
        p.insert_text(fitz.Point(50, 72), p_text, fontsize=11)
    p3_path = os.path.join(output_dir, "3page_sample.pdf")
    doc3.save(p3_path)
    doc3.close()
    print(f"Created {p3_path}")

    # 3. Generate 10-page PDF
    doc10 = fitz.open()
    for i in range(10):
        p = doc10.new_page(width=595, height=842)
        p_text = f"DOCUMENT SECTION {i+1} OF 10\n\n" + SAMPLE_TEXT_PAGE.replace("INV-2026-8891", f"INV-2026-89{i:02d}")
        p.insert_text(fitz.Point(50, 72), p_text, fontsize=11)
    p10_path = os.path.join(output_dir, "10page_sample.pdf")
    doc10.save(p10_path)
    doc10.close()
    print(f"Created {p10_path}")

    # 4. Generate 100-page PDF
    doc100 = fitz.open()
    for i in range(100):
        p = doc100.new_page(width=595, height=842)
        p_text = f"ARCHIVAL RECORD PAGE {i+1} OF 100\n\n" + SAMPLE_TEXT_PAGE.replace("INV-2026-8891", f"INV-2026-{i+1000:04d}")
        p.insert_text(fitz.Point(50, 72), p_text, fontsize=10)
    p100_path = os.path.join(output_dir, "100page_sample.pdf")
    doc100.save(p100_path)
    doc100.close()
    print(f"Created {p100_path}")

    # 5. Generate image scan (rendered from page 1 as PNG image)
    doc_img = fitz.open(p1_path)
    pix = doc_img[0].get_pixmap(dpi=300)
    scan_path = os.path.join(output_dir, "scan_sample.png")
    pix.save(scan_path)
    doc_img.close()
    print(f"Created {scan_path}")


if __name__ == "__main__":
    generate_benchmark_files()
