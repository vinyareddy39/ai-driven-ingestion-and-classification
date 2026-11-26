"""Dataset Generator for Part 2 Extraction Accuracy Testing.

Generates 32 NEW synthetic documents with accompanied Ground Truth JSONs in:
- data/verification/accuracy_suite/docs/
- data/verification/accuracy_suite/ground_truth/

Covers:
- Clean digital files (Invoices, Receipts, Statements, Purchase Orders)
- Clean images (Medical Reports, KYC forms)
- Skewed and noisy scans
- Image-only PDFs
- Multi-page documents with distinct classes
- Multi-column tables (6+ columns)
- Negative evidence ("NOT AN INVOICE")
- Values resembling PII under unrelated labels
- Unknown/unclassified documents
"""

import os
import json
import random
import fitz
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DOCS = "data/verification/accuracy_suite/docs"
OUTPUT_GT = "data/verification/accuracy_suite/ground_truth"
os.makedirs(OUTPUT_DOCS, exist_ok=True)
os.makedirs(OUTPUT_GT, exist_ok=True)

def add_noise_and_skew(img_np, angle_deg=2.0, noise_prob=0.01):
    h, w = img_np.shape[:2]
    # Rotate
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    rotated = cv2.warpAffine(img_np, M, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    # Salt and pepper noise
    noisy = rotated.copy()
    num_noise = int(noise_prob * h * w)
    for _ in range(num_noise):
        y = random.randint(0, h - 1)
        x = random.randint(0, w - 1)
        val = random.choice([0, 240])
        noisy[y, x] = [val, val, val]
    return noisy

def create_dataset():
    random.seed(42)
    doc_index = 1

    # -------------------------------------------------------------------------
    # 1. Clean Digital Invoices (Docs 1 - 4)
    # -------------------------------------------------------------------------
    for i in range(1, 5):
        fname = f"doc_{doc_index:02d}_clean_digital_invoice.pdf"
        p = os.path.join(OUTPUT_DOCS, fname)
        gt_path = os.path.join(OUTPUT_GT, f"doc_{doc_index:02d}_clean_digital_invoice.json")
        
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        inv_num = f"INV-2026-80{i:02d}"
        inv_date = f"2026-11-1{i}"
        total_amt = f"${(500 + i * 50):.2f}"
        
        text_lines = [
            ("APEX HARDWARE & CLOUD CORP", 16, (72, 70)),
            ("COMMERCIAL INVOICE", 13, (72, 95)),
            (f"Invoice Number: {inv_num}", 10, (72, 125)),
            (f"Invoice Date: {inv_date}", 10, (72, 145)),
            ("Customer Name: Acme Global Logistics", 10, (72, 165)),
            ("Item Description         Qty   Unit Price   Total", 10, (72, 205)),
            (f"Cloud Server Cluster      2     200.00      400.00", 9, (72, 225)),
            (f"Database Managed Node     1     {100 + i * 50}.00      {100 + i * 50}.00", 9, (72, 245)),
            (f"Subtotal: ${(500 + i * 50 - 40):.2f}", 10, (72, 280)),
            ("Tax: $40.00", 10, (72, 300)),
            (f"Total Amount: {total_amt}", 11, (72, 320)),
        ]
        for t, sz, pos in text_lines:
            page.insert_text(pos, t, fontsize=sz, fontname="helv")
        doc.save(p)
        doc.close()

        gt = {
            "document_name": fname,
            "format": "digital_pdf",
            "expected_type": "invoice",
            "expected_routing": "FINANCE_ACCOUNTS_PAYABLE",
            "expected_needs_review": False,
            "expected_fields": {
                "Invoice Number": inv_num,
                "Invoice Date": inv_date,
                "Customer Name": "Acme Global Logistics",
                "Total Amount": total_amt
            },
            "expected_sensitive": [],
            "raw_text": " ".join([t[0] for t in text_lines])
        }
        with open(gt_path, "w", encoding="utf-8") as f:
            json.dump(gt, f, indent=2)
        doc_index += 1

    # -------------------------------------------------------------------------
    # 2. Clean Digital Receipts (Docs 5 - 8)
    # -------------------------------------------------------------------------
    for i in range(1, 5):
        fname = f"doc_{doc_index:02d}_clean_digital_receipt.pdf"
        p = os.path.join(OUTPUT_DOCS, fname)
        gt_path = os.path.join(OUTPUT_GT, f"doc_{doc_index:02d}_clean_digital_receipt.json")
        
        doc = fitz.open()
        page = doc.new_page(width=400, height=550)
        rec_num = f"REC-770{i}"
        rec_date = f"2026-10-2{i}"
        total_paid = f"${(25 + i * 4.5):.2f}"
        
        text_lines = [
            ("DOWNTOWN BISTRO & CAFE", 14, (50, 60)),
            ("SALES RECEIPT", 12, (50, 85)),
            (f"Receipt Number: {rec_num}", 10, (50, 115)),
            (f"Date: {rec_date}", 10, (50, 135)),
            ("Merchant Name: Downtown Bistro LLC", 10, (50, 155)),
            ("Payment Method: Cash", 10, (50, 175)),
            (f"Total Paid: {total_paid}", 11, (50, 205)),
        ]
        for t, sz, pos in text_lines:
            page.insert_text(pos, t, fontsize=sz, fontname="helv")
        doc.save(p)
        doc.close()

        gt = {
            "document_name": fname,
            "format": "digital_pdf",
            "expected_type": "receipt",
            "expected_routing": "FINANCE_EXPENSE_MANAGEMENT",
            "expected_needs_review": False,
            "expected_fields": {
                "Receipt Number": rec_num,
                "Date": rec_date,
                "Merchant Name": "Downtown Bistro LLC",
                "Total Paid": total_paid
            },
            "expected_sensitive": [],
            "raw_text": " ".join([t[0] for t in text_lines])
        }
        with open(gt_path, "w", encoding="utf-8") as f:
            json.dump(gt, f, indent=2)
        doc_index += 1

    # -------------------------------------------------------------------------
    # 3. Clean Images: Medical Lab Reports (Docs 9 - 12)
    # -------------------------------------------------------------------------
    for i in range(1, 5):
        fname = f"doc_{doc_index:02d}_clean_image_medical.png"
        p = os.path.join(OUTPUT_DOCS, fname)
        gt_path = os.path.join(OUTPUT_GT, f"doc_{doc_index:02d}_clean_image_medical.json")
        
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        pat_name = f"Patient Person_{i}"
        pat_id = f"MRN-8840{i}"
        dob = f"198{i}-05-14"
        
        text_lines = [
            ("ST. JUDE REGIONAL DIAGNOSTIC LAB", 16, (72, 70)),
            ("CLINICAL LABORATORY REPORT", 13, (72, 95)),
            (f"Patient Name: {pat_name}", 10, (72, 125)),
            (f"Patient ID: {pat_id}", 10, (72, 145)),
            (f"Date of Birth: {dob}", 10, (72, 165)),
            ("Physician: Dr. Sarah Jenkins MD", 10, (72, 185)),
            ("Specimen: Venous Blood Serum", 10, (72, 205)),
            ("Diagnosis: Routine Health Checkup", 10, (72, 225)),
            ("Remarks: Normal clinical parameters observed.", 10, (72, 250)),
        ]
        for t, sz, pos in text_lines:
            page.insert_text(pos, t, fontsize=sz, fontname="helv")
        pix = page.get_pixmap(dpi=150)
        pix.save(p)
        doc.close()

        gt = {
            "document_name": fname,
            "format": "image_png",
            "expected_type": "medical_report",
            "expected_routing": "RESTRICTED_HIPAA_SECURE_VAULT",
            "expected_needs_review": False,
            "expected_fields": {
                "Patient Name": pat_name,
                "Patient ID": pat_id,
                "Date of Birth": dob,
                "Specimen": "Venous Blood Serum"
            },
            "expected_sensitive": [
                {"type": "MEDICAL_ID", "value": pat_id}
            ],
            "raw_text": " ".join([t[0] for t in text_lines])
        }
        with open(gt_path, "w", encoding="utf-8") as f:
            json.dump(gt, f, indent=2)
        doc_index += 1

    # -------------------------------------------------------------------------
    # 4. Clean Bank Statements (Docs 13 - 16)
    # -------------------------------------------------------------------------
    for i in range(1, 5):
        fname = f"doc_{doc_index:02d}_clean_bank_statement.pdf"
        p = os.path.join(OUTPUT_DOCS, fname)
        gt_path = os.path.join(OUTPUT_GT, f"doc_{doc_index:02d}_clean_bank_statement.json")
        
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        holder = f"Corporate Holdings Group {i}"
        acct_num = f"ACCT-4491-00{i}"
        opening = f"${(10000 + i * 2000):.2f}"
        closing = f"${(14500 + i * 2000):.2f}"
        
        text_lines = [
            ("FIRST NATIONAL COMMERCIAL BANK", 16, (72, 70)),
            ("ACCOUNT STATEMENT", 13, (72, 95)),
            (f"Account Holder: {holder}", 10, (72, 125)),
            (f"Account Number: {acct_num}", 10, (72, 145)),
            ("Statement Period: 2026-10-01 to 2026-10-31", 10, (72, 165)),
            (f"Opening Balance: {opening}", 10, (72, 195)),
            (f"Closing Balance: {closing}", 10, (72, 215)),
            ("Total Deposits: $6,000.00", 10, (72, 235)),
            ("Total Withdrawals: $1,500.00", 10, (72, 255)),
        ]
        for t, sz, pos in text_lines:
            page.insert_text(pos, t, fontsize=sz, fontname="helv")
        doc.save(p)
        doc.close()

        gt = {
            "document_name": fname,
            "format": "digital_pdf",
            "expected_type": "bank_statement",
            "expected_routing": "FINANCE_TREASURY_OPERATIONS",
            "expected_needs_review": False,
            "expected_fields": {
                "Account Holder": holder,
                "Account Number": acct_num,
                "Opening Balance": opening,
                "Closing Balance": closing
            },
            "expected_sensitive": [],
            "raw_text": " ".join([t[0] for t in text_lines])
        }
        with open(gt_path, "w", encoding="utf-8") as f:
            json.dump(gt, f, indent=2)
        doc_index += 1

    # -------------------------------------------------------------------------
    # 5. Skewed & Noisy Scans (Docs 17 - 20)
    # -------------------------------------------------------------------------
    for i in range(1, 5):
        fname = f"doc_{doc_index:02d}_skewed_noisy_scan.png"
        p = os.path.join(OUTPUT_DOCS, fname)
        gt_path = os.path.join(OUTPUT_GT, f"doc_{doc_index:02d}_skewed_noisy_scan.json")
        
        doc = fitz.open()
        page = doc.new_page(width=500, height=600)
        rec_num = f"REC-NOISY-9{i}"
        text_lines = [
            ("EXPRESS HIGHWAY TOLL & FUEL", 14, (50, 60)),
            ("RECEIPT", 12, (50, 85)),
            (f"Receipt Number: {rec_num}", 10, (50, 115)),
            ("Date: 2026-11-18", 10, (50, 135)),
            ("Fuel Pump 3: $45.00", 10, (50, 160)),
            ("Total Amount: $45.00", 11, (50, 185)),
        ]
        for t, sz, pos in text_lines:
            page.insert_text(pos, t, fontsize=sz, fontname="helv")
        pix = page.get_pixmap(dpi=150)
        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
        else:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        
        # Apply 2.2 deg skew and noise
        degraded = add_noise_and_skew(img_np, angle_deg=2.2, noise_prob=0.015)
        cv2.imwrite(p, degraded)
        doc.close()

        gt = {
            "document_name": fname,
            "format": "scanned_image",
            "expected_type": "receipt",
            "expected_routing": "FINANCE_EXPENSE_MANAGEMENT",
            "expected_needs_review": False,
            "expected_fields": {
                "Receipt Number": rec_num,
                "Total Amount": "$45.00"
            },
            "expected_sensitive": [],
            "raw_text": " ".join([t[0] for t in text_lines])
        }
        with open(gt_path, "w", encoding="utf-8") as f:
            json.dump(gt, f, indent=2)
        doc_index += 1

    # -------------------------------------------------------------------------
    # 6. Image-Only PDFs (Docs 21 - 24)
    # -------------------------------------------------------------------------
    for i in range(1, 5):
        fname = f"doc_{doc_index:02d}_image_only_contract.pdf"
        p = os.path.join(OUTPUT_DOCS, fname)
        gt_path = os.path.join(OUTPUT_GT, f"doc_{doc_index:02d}_image_only_contract.json")
        
        # Create image first
        doc_tmp = fitz.open()
        page_tmp = doc_tmp.new_page(width=612, height=792)
        c_id = f"CTR-AGR-2026-00{i}"
        p1 = f"Alpha Solutions Corp {i}"
        p2 = f"Beta Enterprises LLC {i}"
        text_lines = [
            ("MUTUAL NON-DISCLOSURE AGREEMENT", 16, (72, 70)),
            ("COMMERCIAL CONTRACT", 13, (72, 95)),
            (f"Contract ID: {c_id}", 10, (72, 125)),
            ("Effective Date: 2026-11-01", 10, (72, 145)),
            (f"First Party: {p1}", 10, (72, 165)),
            (f"Second Party: {p2}", 10, (72, 185)),
            ("Whereas the parties desire to explore mutual business opportunities...", 10, (72, 215)),
            ("Governing Law: State of New York", 10, (72, 240)),
            ("IN WITNESS WHEREOF, the parties hereto have executed this Agreement.", 10, (72, 270)),
        ]
        for t, sz, pos in text_lines:
            page_tmp.insert_text(pos, t, fontsize=sz, fontname="helv")
        pix = page_tmp.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        doc_tmp.close()

        # Wrap purely as raster image in PDF with 0 digital text
        doc_raster = fitz.open()
        p_r = doc_raster.new_page(width=612, height=792)
        p_r.insert_image(fitz.Rect(0, 0, 612, 792), stream=img_bytes)
        doc_raster.save(p)
        doc_raster.close()

        gt = {
            "document_name": fname,
            "format": "image_only_pdf",
            "expected_type": "contract",
            "expected_routing": "LEGAL_CONTRACTS_REPOSITORY",
            "expected_needs_review": False,
            "expected_fields": {
                "Contract ID": c_id,
                "First Party": p1,
                "Second Party": p2,
                "Governing Law": "State of New York"
            },
            "expected_sensitive": [],
            "raw_text": " ".join([t[0] for t in text_lines])
        }
        with open(gt_path, "w", encoding="utf-8") as f:
            json.dump(gt, f, indent=2)
        doc_index += 1

    # -------------------------------------------------------------------------
    # 7. Multi-Page Files with Two Distinct Documents (Docs 25 - 26)
    # -------------------------------------------------------------------------
    for i in range(1, 3):
        fname = f"doc_{doc_index:02d}_multipage_two_documents.pdf"
        p = os.path.join(OUTPUT_DOCS, fname)
        gt_path = os.path.join(OUTPUT_GT, f"doc_{doc_index:02d}_multipage_two_documents.json")
        
        doc = fitz.open()
        # Page 1: Invoice
        p1 = doc.new_page(width=612, height=792)
        p1.insert_text((72, 80), "BILLING INVOICE", fontsize=15)
        p1.insert_text((72, 110), f"Invoice Number: INV-MULTI-{i}", fontsize=10)
        p1.insert_text((72, 130), "Total Amount: $850.00", fontsize=10)
        # Page 2: Letter
        p2 = doc.new_page(width=612, height=792)
        p2.insert_text((72, 80), "FORMAL CORRESPONDENCE", fontsize=15)
        p2.insert_text((72, 110), "Dear Valued Client,", fontsize=10)
        p2.insert_text((72, 130), "Please find attached our billing statement for services rendered.", fontsize=10)
        p2.insert_text((72, 160), "Sincerely, Customer Service Team", fontsize=10)
        doc.save(p)
        doc.close()

        gt = {
            "document_name": fname,
            "format": "multipage_pdf",
            "expected_type": "invoice",
            "expected_routing": "FINANCE_ACCOUNTS_PAYABLE",
            "expected_needs_review": False,
            "logical_documents": [
                {"page": 1, "type": "invoice"},
                {"page": 2, "type": "letter"}
            ],
            "expected_fields": {
                "Invoice Number": f"INV-MULTI-{i}",
                "Total Amount": "$850.00"
            },
            "expected_sensitive": [],
            "raw_text": "BILLING INVOICE Invoice Number Total Amount FORMAL CORRESPONDENCE Dear Valued Client"
        }
        with open(gt_path, "w", encoding="utf-8") as f:
            json.dump(gt, f, indent=2)
        doc_index += 1

    # -------------------------------------------------------------------------
    # 8. Tables with Many Columns (Docs 27 - 28)
    # -------------------------------------------------------------------------
    for i in range(1, 3):
        fname = f"doc_{doc_index:02d}_table_many_columns.pdf"
        p = os.path.join(OUTPUT_DOCS, fname)
        gt_path = os.path.join(OUTPUT_GT, f"doc_{doc_index:02d}_table_many_columns.json")
        
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        po_num = f"PO-9910{i}"
        page.insert_text((72, 70), "PURCHASE ORDER", fontsize=16)
        page.insert_text((72, 95), f"PO Number: {po_num}", fontsize=10)
        page.insert_text((72, 115), "Vendor Name: Precision Manufacturing Inc", fontsize=10)
        page.insert_text((72, 150), "Item Code  Description            Qty   Unit Price  Discount  Line Total", fontsize=9)
        page.insert_text((72, 170), "ITM-01     Machined Titanium Pin   10      25.00       0.00      250.00", fontsize=9)
        page.insert_text((72, 190), "ITM-02     Hydraulic Valve Seal    20      10.00       5.00      195.00", fontsize=9)
        page.insert_text((72, 210), "ITM-03     Precision Steel Ring    5       50.00       0.00      250.00", fontsize=9)
        page.insert_text((72, 250), "Total Amount: $695.00", fontsize=11)
        doc.save(p)
        doc.close()

        gt = {
            "document_name": fname,
            "format": "digital_pdf",
            "expected_type": "purchase_order",
            "expected_routing": "PROCUREMENT_OPERATIONS",
            "expected_needs_review": False,
            "expected_fields": {
                "PO Number": po_num,
                "Vendor Name": "Precision Manufacturing Inc",
                "Total Amount": "$695.00"
            },
            "expected_table": {
                "row_count": 3,
                "columns": ["Item Code", "Description", "Qty", "Unit Price", "Discount", "Line Total"]
            },
            "expected_sensitive": [],
            "raw_text": "PURCHASE ORDER PO Number Vendor Name Item Code Description Qty Unit Price Discount Line Total"
        }
        with open(gt_path, "w", encoding="utf-8") as f:
            json.dump(gt, f, indent=2)
        doc_index += 1

    # -------------------------------------------------------------------------
    # 9. Negative Evidence Documents (Docs 29 - 30)
    # -------------------------------------------------------------------------
    for i in range(1, 3):
        fname = f"doc_{doc_index:02d}_negative_evidence.pdf"
        p = os.path.join(OUTPUT_DOCS, fname)
        gt_path = os.path.join(OUTPUT_GT, f"doc_{doc_index:02d}_negative_evidence.json")
        
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 80), "PRELIMINARY PRICE ESTIMATE", fontsize=15)
        page.insert_text((72, 110), "THIS IS NOT AN INVOICE - NON-BINDING ESTIMATE ONLY", fontsize=12)
        page.insert_text((72, 140), "Estimate ID: EST-4420", fontsize=10)
        page.insert_text((72, 160), "Proposed Amount: $1,200.00", fontsize=10)
        doc.save(p)
        doc.close()

        gt = {
            "document_name": fname,
            "format": "digital_pdf",
            "expected_type": "unknown",  # Must NOT classify as invoice due to negative evidence
            "expected_routing": "MANUAL_TRIAGE_QUEUE",
            "expected_needs_review": True,
            "expected_fields": {
                "Estimate ID": "EST-4420"
            },
            "expected_sensitive": [],
            "raw_text": "PRELIMINARY PRICE ESTIMATE THIS IS NOT AN INVOICE - NON-BINDING ESTIMATE ONLY"
        }
        with open(gt_path, "w", encoding="utf-8") as f:
            json.dump(gt, f, indent=2)
        doc_index += 1

    # -------------------------------------------------------------------------
    # 10. Lookalike Sensitive Data Under Unrelated Label (Doc 31)
    # -------------------------------------------------------------------------
    fname = f"doc_{doc_index:02d}_lookalike_unrelated.pdf"
    p = os.path.join(OUTPUT_DOCS, fname)
    gt_path = os.path.join(OUTPUT_GT, f"doc_{doc_index:02d}_lookalike_unrelated.json")
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 80), "INVENTORY SPECIFICATION SHEET", fontsize=15)
    page.insert_text((72, 110), "Part Number: 123-45-6789", fontsize=10)
    page.insert_text((72, 130), "Serial Code: 4532015012345674", fontsize=10)
    page.insert_text((72, 150), "Description: Industrial Bearing Assembly", fontsize=10)
    doc.save(p)
    doc.close()

    gt = {
        "document_name": fname,
        "format": "digital_pdf",
        "expected_type": "unknown",
        "expected_routing": "MANUAL_TRIAGE_QUEUE",
        "expected_needs_review": True,
        "expected_fields": {
            "Part Number": "123-45-6789",
            "Serial Code": "4532015012345674"
        },
        "expected_sensitive": [],  # Should NOT trigger PII restriction due to contradiction penalty
        "raw_text": "INVENTORY SPECIFICATION SHEET Part Number Serial Code Description"
    }
    with open(gt_path, "w", encoding="utf-8") as f:
        json.dump(gt, f, indent=2)
    doc_index += 1

    # -------------------------------------------------------------------------
    # 11. Unknown / Informal General Note (Doc 32)
    # -------------------------------------------------------------------------
    fname = f"doc_{doc_index:02d}_unknown_memo.pdf"
    p = os.path.join(OUTPUT_DOCS, fname)
    gt_path = os.path.join(OUTPUT_GT, f"doc_{doc_index:02d}_unknown_memo.json")
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 80), "INTERNAL PROJECT THOUGHTS", fontsize=15)
    page.insert_text((72, 110), "Meeting Notes: Team brainstorm session regarding Q4 ideas.", fontsize=10)
    page.insert_text((72, 130), "Discussed general productivity and upcoming company picnic.", fontsize=10)
    doc.save(p)
    doc.close()

    gt = {
        "document_name": fname,
        "format": "digital_pdf",
        "expected_type": "unknown",
        "expected_routing": "MANUAL_TRIAGE_QUEUE",
        "expected_needs_review": True,
        "expected_fields": {},
        "expected_sensitive": [],
        "raw_text": "INTERNAL PROJECT THOUGHTS Meeting Notes Team brainstorm session Discussed general productivity"
    }
    with open(gt_path, "w", encoding="utf-8") as f:
        json.dump(gt, f, indent=2)
    doc_index += 1

    print(f"Successfully generated {doc_index - 1} documents and paired Ground Truth JSON files.")

if __name__ == "__main__":
    create_dataset()
