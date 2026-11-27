"""Synthetic Document Generator for Pipeline Verification.

Generates 8 new synthetic test files covering all required scenarios:
1. Clean digital file (PDF with text layer)
2. Clean image (PNG)
3. Rotated or skewed noisy scan (PNG)
4. Image-only PDF (scanned PDF with 0 embedded text)
5. Multi-page file with two different documents (2-page PDF)
6. Table with many columns (PDF)
7. Resembles another type but states it is not (negative evidence PDF)
8. Value that looks sensitive but is not (unrelated label context PDF)
"""

import os
import cv2
import fitz  # PyMuPDF
import numpy as np


def create_synthetic_suite(output_dir: str):
    os.makedirs(output_dir, exist_ok=True)

    # -----------------------------------------------------------------------
    # 1. Clean digital file (Invoice with embedded text layer)
    # -----------------------------------------------------------------------
    p1 = os.path.join(output_dir, "syn_01_clean_digital.pdf")
    doc1 = fitz.open()
    page1 = doc1.new_page(width=612, height=792)
    page1.insert_text((72, 80), "ACME CLOUD ENTERPRISES", fontsize=18, fontname="helv")
    page1.insert_text((72, 110), "COMMERCIAL INVOICE", fontsize=14, fontname="helv")
    page1.insert_text((72, 140), "Invoice Number: INV-2026-9001", fontsize=11, fontname="helv")
    page1.insert_text((72, 160), "Invoice Date: 2026-11-20", fontsize=11, fontname="helv")
    page1.insert_text((72, 180), "Due Date: 2026-12-20", fontsize=11, fontname="helv")
    page1.insert_text((72, 200), "Bill To: Global Logistics Corp", fontsize=11, fontname="helv")

    page1.insert_text((72, 240), "Item Description           Qty    Unit Price    Total", fontsize=11, fontname="helv")
    page1.insert_text((72, 260), "Cloud Hosting Compute        2        150.00    300.00", fontsize=10, fontname="helv")
    page1.insert_text((72, 280), "Database Storage Clusters    1        100.00    100.00", fontsize=10, fontname="helv")

    page1.insert_text((72, 320), "Subtotal: $400.00", fontsize=11, fontname="helv")
    page1.insert_text((72, 340), "Tax Amount: $40.00", fontsize=11, fontname="helv")
    page1.insert_text((72, 360), "Total Amount: $440.00", fontsize=12, fontname="helv")
    doc1.save(p1)
    doc1.close()

    # -----------------------------------------------------------------------
    # 2. Clean image (Medical lab report rendered to PNG)
    # -----------------------------------------------------------------------
    p2 = os.path.join(output_dir, "syn_02_clean_image.png")
    doc2 = fitz.open()
    page2 = doc2.new_page(width=612, height=792)
    page2.insert_text((72, 80), "METROPOLITAN CLINICAL LABS", fontsize=18, fontname="helv")
    page2.insert_text((72, 110), "LABORATORY REPORT", fontsize=14, fontname="helv")
    page2.insert_text((72, 140), "Patient Name: John Doe", fontsize=11, fontname="helv")
    page2.insert_text((72, 160), "Specimen Type: Blood Serum", fontsize=11, fontname="helv")
    page2.insert_text((72, 180), "Collected On: 2026-10-15", fontsize=11, fontname="helv")
    page2.insert_text((72, 200), "Hemoglobin: 14.5 G/dL", fontsize=11, fontname="helv")
    page2.insert_text((72, 220), "Physician: Dr. Robert Smith MD", fontsize=11, fontname="helv")
    page2.insert_text((72, 240), "Remarks: All values within normal clinical range", fontsize=11, fontname="helv")
    pix2 = page2.get_pixmap(dpi=150)
    pix2.save(p2)
    doc2.close()

    # -----------------------------------------------------------------------
    # 3. Rotated, skewed, noisy scan (Receipt image rotated 90 deg + noise)
    # -----------------------------------------------------------------------
    p3 = os.path.join(output_dir, "syn_03_rotated_skewed_noisy.png")
    doc3 = fitz.open()
    page3 = doc3.new_page(width=500, height=600)
    page3.insert_text((50, 70), "CORNER CAFE & BAKERY", fontsize=16, fontname="helv")
    page3.insert_text((50, 100), "RECEIPT", fontsize=14, fontname="helv")
    page3.insert_text((50, 130), "Receipt Number: REC-8821", fontsize=11, fontname="helv")
    page3.insert_text((50, 150), "Date: 2026-11-22", fontsize=11, fontname="helv")
    page3.insert_text((50, 170), "Merchant Name: Corner Cafe LLC", fontsize=11, fontname="helv")
    page3.insert_text((50, 200), "Coffee Latte: $4.50", fontsize=11, fontname="helv")
    page3.insert_text((50, 220), "Croissant: $3.50", fontsize=11, fontname="helv")
    page3.insert_text((50, 250), "Total Paid: $8.00", fontsize=12, fontname="helv")
    page3.insert_text((50, 270), "Payment Method: Cash", fontsize=11, fontname="helv")
    pix3 = page3.get_pixmap(dpi=150)
    img_bgr = np.frombuffer(pix3.samples, dtype=np.uint8).reshape(pix3.height, pix3.width, pix3.n)
    if pix3.n == 4:
        img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_RGBA2BGR)
    elif pix3.n == 3:
        img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_RGB2BGR)

    # Rotate 90 degrees clockwise
    img_rot = cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)
    # Add slight skew (2 degrees)
    h_r, w_r = img_rot.shape[:2]
    m_skew = cv2.getRotationMatrix2D((w_r // 2, h_r // 2), 2.0, 1.0)
    img_skew = cv2.warpAffine(img_rot, m_skew, (w_r, h_r), borderMode=cv2.BORDER_REPLICATE)
    # Add light speckle noise
    noise = np.random.normal(0, 12, img_skew.shape).astype(np.float32)
    img_noisy = np.clip(img_skew.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    cv2.imwrite(p3, img_noisy)
    doc3.close()

    # -----------------------------------------------------------------------
    # 4. Image-only PDF (Contract rendered to raster image and placed in PDF with 0 text)
    # -----------------------------------------------------------------------
    p4 = os.path.join(output_dir, "syn_04_image_only.pdf")
    doc4_temp = fitz.open()
    page4_t = doc4_temp.new_page(width=612, height=792)
    page4_t.insert_text((72, 80), "CONSULTING SERVICES AGREEMENT", fontsize=16, fontname="helv")
    page4_t.insert_text((72, 110), "Contract ID: CSA-2026-004", fontsize=11, fontname="helv")
    page4_t.insert_text((72, 130), "Effective Date: 2026-11-01", fontsize=11, fontname="helv")
    page4_t.insert_text((72, 150), "First Party: Alpha Technology Partners", fontsize=11, fontname="helv")
    page4_t.insert_text((72, 170), "Second Party: Beta Solutions Group", fontsize=11, fontname="helv")
    page4_t.insert_text((72, 190), "Authorized Signatory: Alice Walker", fontsize=11, fontname="helv")
    page4_t.insert_text((72, 210), "Subject: Enterprise Architecture Consulting", fontsize=11, fontname="helv")
    pix4 = page4_t.get_pixmap(dpi=150)
    doc4_temp.close()

    # Create new PDF with ONLY the image, 0 text layer
    doc4 = fitz.open()
    page4 = doc4.new_page(width=612, height=792)
    page4.insert_image(page4.rect, stream=pix4.tobytes())
    doc4.save(p4)
    doc4.close()

    # -----------------------------------------------------------------------
    # 5. Multi-page file with two different documents (Page 1 = Invoice, Page 2 = Letter)
    # -----------------------------------------------------------------------
    p5 = os.path.join(output_dir, "syn_05_multipage_two_documents.pdf")
    doc5 = fitz.open()
    # Page 1: Invoice
    pg1 = doc5.new_page(width=612, height=792)
    pg1.insert_text((72, 80), "VERTEX SYSTEMS INC", fontsize=18, fontname="helv")
    pg1.insert_text((72, 110), "INVOICE", fontsize=14, fontname="helv")
    pg1.insert_text((72, 140), "Invoice Number: INV-7711", fontsize=11, fontname="helv")
    pg1.insert_text((72, 160), "Invoice Date: 2026-11-15", fontsize=11, fontname="helv")
    pg1.insert_text((72, 180), "Bill To: Wayne Enterprises", fontsize=11, fontname="helv")
    pg1.insert_text((72, 200), "Total Amount: $250.00", fontsize=12, fontname="helv")

    # Page 2: Letter / Correspondence
    pg2 = doc5.new_page(width=612, height=792)
    pg2.insert_text((72, 80), "WAYNE ENTERPRISES EXECUTIVE OFFICE", fontsize=16, fontname="helv")
    pg2.insert_text((72, 110), "MEMORANDUM", fontsize=14, fontname="helv")
    pg2.insert_text((72, 140), "Date: 2026-11-25", fontsize=11, fontname="helv")
    pg2.insert_text((72, 160), "To: Commissioner James Gordon", fontsize=11, fontname="helv")
    pg2.insert_text((72, 180), "From: Bruce Wayne", fontsize=11, fontname="helv")
    pg2.insert_text((72, 200), "Subject: Annual Infrastructure Security Review", fontsize=11, fontname="helv")
    pg2.insert_text((72, 240), "Dear Commissioner,", fontsize=11, fontname="helv")
    pg2.insert_text((72, 260), "Please find enclosed our executive summary regarding municipal security updates.", fontsize=11, fontname="helv")
    pg2.insert_text((72, 290), "Sincerely,", fontsize=11, fontname="helv")
    pg2.insert_text((72, 310), "Bruce Wayne", fontsize=11, fontname="helv")
    doc5.save(p5)
    doc5.close()

    # -----------------------------------------------------------------------
    # 6. Table with many columns (Purchase Order with 6 columns)
    # -----------------------------------------------------------------------
    p6 = os.path.join(output_dir, "syn_06_table_many_columns.pdf")
    doc6 = fitz.open()
    page6 = doc6.new_page(width=612, height=792)
    page6.insert_text((72, 70), "APEX INDUSTRIAL CORP", fontsize=18, fontname="helv")
    page6.insert_text((72, 95), "PURCHASE ORDER", fontsize=14, fontname="helv")
    page6.insert_text((72, 120), "PO Number: PO-99221", fontsize=11, fontname="helv")
    page6.insert_text((72, 140), "Order Date: 2026-11-18", fontsize=11, fontname="helv")
    page6.insert_text((72, 160), "Vendor: Apex Manufacturing Ltd", fontsize=11, fontname="helv")

    # 6-column aligned table
    page6.insert_text((72, 195), "Item Code    Description            Qty    Unit Price    Discount    Line Total", fontsize=10, fontname="helv")
    page6.insert_text((72, 215), "A-101        Steel Brackets         100         12.50        0.00       1250.00", fontsize=10, fontname="helv")
    page6.insert_text((72, 235), "B-204        Aluminum Fasteners     500          1.20       50.00        550.00", fontsize=10, fontname="helv")
    page6.insert_text((72, 255), "C-309        Copper Washers         250          0.80       10.00        190.00", fontsize=10, fontname="helv")
    page6.insert_text((72, 290), "Total Order Amount: $1990.00", fontsize=12, fontname="helv")
    doc6.save(p6)
    doc6.close()

    # -----------------------------------------------------------------------
    # 7. Document resembling invoice but explicitly stating it is NOT (Negative Evidence)
    # -----------------------------------------------------------------------
    p7 = os.path.join(output_dir, "syn_07_negative_evidence.pdf")
    doc7 = fitz.open()
    page7 = doc7.new_page(width=612, height=792)
    page7.insert_text((72, 80), "HORIZON MEDIA ENTERPRISES", fontsize=18, fontname="helv")
    page7.insert_text((72, 110), "FORMAL PRICE QUOTATION", fontsize=14, fontname="helv")
    page7.insert_text((72, 135), "THIS IS A QUOTATION ONLY. THIS IS NOT AN INVOICE. NO PAYMENT DUE.", fontsize=11, fontname="helv")
    page7.insert_text((72, 160), "Estimate Number: EST-4401", fontsize=11, fontname="helv")
    page7.insert_text((72, 180), "Estimate Date: 2026-11-21", fontsize=11, fontname="helv")
    page7.insert_text((72, 200), "Prepared For: Zenith Media Group", fontsize=11, fontname="helv")
    page7.insert_text((72, 230), "Estimated Total: $1200.00", fontsize=12, fontname="helv")
    doc7.save(p7)
    doc7.close()

    # -----------------------------------------------------------------------
    # 8. Value that looks sensitive but is under unrelated label
    # -----------------------------------------------------------------------
    p8 = os.path.join(output_dir, "syn_08_sensitive_lookalike_unrelated.pdf")
    doc8 = fitz.open()
    page8 = doc8.new_page(width=612, height=792)
    page8.insert_text((72, 80), "PRECISION ENGINEERING CO", fontsize=18, fontname="helv")
    page8.insert_text((72, 110), "PARTS INVENTORY SPECIFICATION", fontsize=14, fontname="helv")
    page8.insert_text((72, 140), "Catalogue Reference: CAT-2026", fontsize=11, fontname="helv")
    page8.insert_text((72, 160), "Part Number: 987-65-4321", fontsize=11, fontname="helv")  # Matches SSN regex, but label is 'Part Number'
    page8.insert_text((72, 180), "Warehouse Bin Location: BIN-04-NORTH", fontsize=11, fontname="helv")
    page8.insert_text((72, 200), "Item Description: Hydraulic Valve Coupling", fontsize=11, fontname="helv")
    doc8.save(p8)
    doc8.close()

    print(f"Generated 8 synthetic documents in {output_dir}")


if __name__ == "__main__":
    create_synthetic_suite("data/synthetic_tests")
