"""Generate 100+ Independent Synthetic Test Documents and Answer Keys.

Rules:
- Synthetic data only, no real PII.
- No reuse of existing test generator code.
- Fully paired with pre-written answer keys containing exact fields, types, canonical routings, sensitive data, and raw text.
- Covers digital PDFs, images, noisy scans, multi-page documents, negative evidence, and Set B / Set C files.
"""

import os
import json
import random
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
import fitz
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import yaml

DOCS_DIR = os.path.abspath("data/verification/independent_suite/docs")
GT_DIR = os.path.abspath("data/verification/independent_suite/ground_truth")

os.makedirs(DOCS_DIR, exist_ok=True)
os.makedirs(GT_DIR, exist_ok=True)

# Load canonical routing destinations
with open("config/routing.yaml", "r", encoding="utf-8") as f:
    ROUTING_CONFIG = yaml.safe_load(f).get("routing_destinations", {})

def get_routing(doc_type: str, is_restricted: bool = False) -> str:
    cfg = ROUTING_CONFIG.get(doc_type, ROUTING_CONFIG.get("unknown", {}))
    return cfg.get("restricted_destination" if is_restricted else "destination", "MANUAL_TRIAGE_QUEUE")


def add_scan_effects(img_np: np.ndarray, angle: float = 2.0, noise_level: int = 15) -> np.ndarray:
    """Apply realistic scan artifacts: rotation, noise, slight blur."""
    h, w = img_np.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    rotated = cv2.warpAffine(img_np, M, (w, h), borderValue=(255, 255, 255))
    if noise_level > 0:
        noise = np.random.normal(0, noise_level, (h, w, 3)).astype(np.int16)
        noisy = np.clip(rotated.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        return noisy
    return rotated


def create_digital_pdf(path: str, lines: list, draw_table: bool = False, table_rows: list = None):
    c = canvas.Canvas(path, pagesize=letter)
    width, height = letter
    y = height - 50
    for line in lines:
        if isinstance(line, tuple):
            text, size, is_bold = line
        else:
            text, size, is_bold = line, 10, False
        c.setFont("Helvetica-Bold" if is_bold else "Helvetica", size)
        c.drawString(50, y, str(text))
        y -= (size + 6)
        if y < 50:
            c.showPage()
            y = height - 50

    if draw_table and table_rows:
        y -= 10
        c.setFont("Helvetica-Bold", 10)
        c.drawString(50, y, "Item Description                  Qty    Unit Price    Total")
        y -= 14
        c.setFont("Helvetica", 9)
        for row in table_rows:
            c.drawString(50, y, row)
            y -= 13
            if y < 50:
                c.showPage()
                y = height - 50

    c.save()


def create_image_doc(path: str, lines: list, scan_effect: bool = False, angle: float = 0.0, noise: int = 0):
    img = Image.new("RGB", (800, 1050), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    y = 50
    for line in lines:
        text = line[0] if isinstance(line, tuple) else str(line)
        draw.text((60, y), text, fill=(20, 20, 20))
        y += 24

    img_np = np.array(img)
    if scan_effect:
        img_np = add_scan_effects(img_np, angle=angle, noise_level=noise)
    cv2.imwrite(path, cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR))


def create_image_only_pdf(path: str, lines: list, angle: float = 0.0, noise: int = 0):
    tmp_png = path.replace(".pdf", "_tmp.png")
    create_image_doc(tmp_png, lines, scan_effect=True, angle=angle, noise=noise)
    doc = fitz.open()
    img_doc = fitz.open(tmp_png)
    rect = img_doc[0].rect
    pdf_bytes = img_doc.convert_to_pdf()
    img_doc.close()
    img_pdf = fitz.open("pdf", pdf_bytes)
    page = doc.new_page(width=rect.width, height=rect.height)
    page.show_pdf_page(rect, img_pdf, 0)
    doc.save(path)
    doc.close()
    img_pdf.close()
    if os.path.exists(tmp_png):
        os.remove(tmp_png)


print("Building independent dataset...")
count = 0

# -----------------------------------------------------------------------------
# 1. INVOICES (16 documents)
# -----------------------------------------------------------------------------
for i in range(1, 17):
    doc_id = f"indep_inv_{i:02d}"
    inv_num = f"INV-2026-{9000 + i}"
    po_ref = f"PO-REF-{1000 + i}"
    total = f"${1200 + i * 85}.50"
    tax = f"${(1200 + i * 85) * 0.08:.2f}"
    subtotal = f"${(1200 + i * 85) * 0.92:.2f}"
    date = f"2026-10-{10 + (i % 18):02d}"
    due_date = f"2026-11-{10 + (i % 18):02d}"
    vendor = f"Apex Solutions Group {i}"
    customer = f"Global Tech Enterprises {i}"

    lines = [
        (vendor, 16, True),
        (f"100 Corporate Parkway, Suite {100 + i}, New York, NY 10001", 9, False),
        ("INVOICE", 14, True),
        (f"Invoice Number: {inv_num}", 10, False),
        (f"Invoice Date: {date}", 10, False),
        (f"Due Date: {due_date}", 10, False),
        (f"Customer PO Reference: {po_ref}", 10, False),  # Cross-type reference!
        (f"Bill To: {customer}", 10, False),
        ("Payment Terms: Net 30", 9, False),
        (f"Subtotal: {subtotal}", 10, False),
        (f"Tax Amount: {tax}", 10, False),
        (f"Total Amount Due: {total}", 11, True),
    ]
    table = [
        f"Professional IT Consulting Services {i}    10    $100.00    $1000.00",
        f"Server Maintenance & Backup Support        1    ${200 + i*85}.50    ${200 + i*85}.50"
    ]
    raw_text = "\n".join([l[0] for l in lines] + table)

    fmt = "digital_pdf" if i <= 10 else ("image_png" if i <= 13 else "image_only_pdf")
    ext = ".png" if fmt == "image_png" else ".pdf"
    doc_file = os.path.join(DOCS_DIR, f"{doc_id}{ext}")

    if fmt == "digital_pdf":
        create_digital_pdf(doc_file, lines, draw_table=True, table_rows=table)
    elif fmt == "image_png":
        create_image_doc(doc_file, lines + [("Table:", 10, True)] + [(r, 9, False) for r in table], scan_effect=(i%2==0), angle=1.2, noise=12)
    else:
        create_image_only_pdf(doc_file, lines + [("Table:", 10, True)] + [(r, 9, False) for r in table], angle=-1.5, noise=15)

    gt_data = {
        "file": f"{doc_id}{ext}",
        "expected_type": "invoice",
        "expected_routing": get_routing("invoice"),
        "expected_fields": {
            "Invoice Number": inv_num,
            "Invoice Date": date,
            "Due Date": due_date,
            "Vendor Name": vendor,
            "Total Amount Due": total,
            "Subtotal": subtotal,
            "Tax Amount": tax,
        },
        "expected_sensitive": [],
        "format": fmt,
        "raw_text": raw_text,
        "needs_review": False,
        "notes": "Invoice with cross-type PO reference number."
    }
    with open(os.path.join(GT_DIR, f"{doc_id}{ext}.json"), "w", encoding="utf-8") as f:
        json.dump(gt_data, f, indent=2)
    count += 1

# -----------------------------------------------------------------------------
# 2. RECEIPTS (16 documents, including many-line-items receipt)
# -----------------------------------------------------------------------------
for i in range(1, 17):
    doc_id = f"indep_rcpt_{i:02d}"
    rcpt_num = f"RCPT-887{i:03d}"
    merchant = f"Metro Bistro & Cafe {i}"
    date = f"2026-11-{1 + (i % 25):02d}"
    card_last4 = f"************{4000 + i}"
    total = f"${45.00 + i * 6.50:.2f}"

    lines = [
        (merchant, 14, True),
        ("OFFICIAL RECEIPT", 12, True),
        (f"Receipt #: {rcpt_num}", 10, False),
        (f"Date: {date}", 10, False),
        ("Payment Method: Credit Card", 10, False),
        (f"Card Number: {card_last4}", 10, False),
    ]

    # If i == 5, create receipt with 12 line items!
    table = []
    if i == 5:
        for item_idx in range(1, 13):
            table.append(f"Gourmet Item {item_idx}                   1    $4.50    $4.50")
        lines.append(("--- 12 ITEM TRANSACTION ---", 9, False))
    else:
        table = [
            f"Breakfast Combo #{i}                     1    $12.50    $12.50",
            f"Espresso Roast Beverage                  2     $4.50     $9.00",
            f"Bakery Pastry Assortment                 1     $5.00     $5.00"
        ]

    lines.append((f"Subtotal: ${35.00 + i * 6.50:.2f}", 10, False))
    lines.append((f"Tax: $2.50", 10, False))
    lines.append((f"Total Paid: {total}", 11, True))
    lines.append(("Thank you for your business!", 9, False))

    raw_text = "\n".join([l[0] for l in lines] + table)
    fmt = "digital_pdf" if i <= 10 else ("image_png" if i <= 14 else "image_only_pdf")
    ext = ".png" if fmt == "image_png" else ".pdf"
    doc_file = os.path.join(DOCS_DIR, f"{doc_id}{ext}")

    if fmt == "digital_pdf":
        create_digital_pdf(doc_file, lines, draw_table=True, table_rows=table)
    elif fmt == "image_png":
        create_image_doc(doc_file, lines + [(r, 9, False) for r in table], scan_effect=(i%2==0), angle=2.0, noise=15)
    else:
        create_image_only_pdf(doc_file, lines + [(r, 9, False) for r in table], angle=-1.2, noise=10)

    gt_data = {
        "file": f"{doc_id}{ext}",
        "expected_type": "receipt",
        "expected_routing": get_routing("receipt"),
        "expected_fields": {
            "Receipt Number": rcpt_num,
            "Date": date,
            "Merchant Name": merchant,
            "Total Paid": total,
        },
        "expected_sensitive": [{"type": "CREDIT_CARD", "value": card_last4}] if card_last4 else [],
        "format": fmt,
        "raw_text": raw_text,
        "needs_review": False,
        "notes": "Receipt with many line items" if i == 5 else "Standard retail receipt"
    }
    with open(os.path.join(GT_DIR, f"{doc_id}{ext}.json"), "w", encoding="utf-8") as f:
        json.dump(gt_data, f, indent=2)
    count += 1

# -----------------------------------------------------------------------------
# 3. PURCHASE ORDERS (14 documents, including invoice-like totals)
# -----------------------------------------------------------------------------
for i in range(1, 15):
    doc_id = f"indep_po_{i:02d}"
    po_num = f"PO-IND-2026-{500 + i}"
    vendor = f"National Equipment Corp {i}"
    order_date = f"2026-10-{5 + (i % 20):02d}"
    delivery_date = f"2026-11-{15 + (i % 10):02d}"
    total = f"${5400 + i * 320}.00"

    lines = [
        (vendor, 14, True),
        ("PURCHASE ORDER", 14, True),
        (f"PO Number: {po_num}", 10, False),
        (f"Order Date: {order_date}", 10, False),
        (f"Delivery Terms: FOB Destination", 9, False),
        (f"Expected Delivery Date: {delivery_date}", 9, False),
        (f"Vendor Name: {vendor}", 10, False),
        (f"Ship To: Global Logistics Hub, Dock #{i}, Chicago IL", 9, False),
        (f"Requisition Approved By: Director of Procurement", 9, False),
        # Invoice-like totals structure!
        (f"Subtotal: ${5000 + i * 320}.00", 10, False),
        (f"Freight & Handling: $400.00", 10, False),
        (f"Total Order Amount: {total}", 11, True),
    ]
    table = [
        f"Heavy Duty Server Rack Units               4    $1000.00    $4000.00",
        f"Industrial Cooling Apparatus               2     ${500 + i*160}.00    ${1000 + i*320}.00"
    ]
    raw_text = "\n".join([l[0] for l in lines] + table)

    fmt = "digital_pdf" if i <= 9 else ("image_png" if i <= 12 else "image_only_pdf")
    ext = ".png" if fmt == "image_png" else ".pdf"
    doc_file = os.path.join(DOCS_DIR, f"{doc_id}{ext}")

    if fmt == "digital_pdf":
        create_digital_pdf(doc_file, lines, draw_table=True, table_rows=table)
    elif fmt == "image_png":
        create_image_doc(doc_file, lines + [(r, 9, False) for r in table], scan_effect=True, angle=-1.0, noise=14)
    else:
        create_image_only_pdf(doc_file, lines + [(r, 9, False) for r in table], angle=1.0, noise=10)

    gt_data = {
        "file": f"{doc_id}{ext}",
        "expected_type": "purchase_order",
        "expected_routing": get_routing("purchase_order"),
        "expected_fields": {
            "PO Number": po_num,
            "Order Date": order_date,
            "Vendor Name": vendor,
            "Total Amount": total,
        },
        "expected_sensitive": [],
        "format": fmt,
        "raw_text": raw_text,
        "needs_review": False,
        "notes": "Purchase order with invoice-like totals"
    }
    with open(os.path.join(GT_DIR, f"{doc_id}{ext}.json"), "w", encoding="utf-8") as f:
        json.dump(gt_data, f, indent=2)
    count += 1

# -----------------------------------------------------------------------------
# 4. BANK STATEMENTS (12 documents)
# -----------------------------------------------------------------------------
for i in range(1, 13):
    doc_id = f"indep_bank_{i:02d}"
    bank_name = f"Horizon Commercial Bank {i}"
    holder = f"Acme Holding Ventures LLC {i}"
    acct_num = f"****{1122 + i}"
    open_bal = f"${10000 + i * 250:.2f}"
    close_bal = f"${18500 + i * 310:.2f}"
    period = f"2026-10-01 to 2026-10-31"

    lines = [
        (bank_name, 14, True),
        ("MONTHLY ACCOUNT STATEMENT", 12, True),
        (f"Account Holder: {holder}", 10, False),
        (f"Account Number: {acct_num}", 10, False),
        (f"Statement Period: {period}", 10, False),
        (f"Opening Balance: {open_bal}", 10, False),
        (f"Closing Balance: {close_bal}", 11, True),
        ("Transaction History:", 10, True),
    ]
    table = [
        "2026-10-05    Direct Deposit Payroll Credit         +$12,500.00",
        "2026-10-12    Vendor Wire Transfer Outflow           -$3,200.00",
        "2026-10-25    Corporate Office Lease Payment         -$4,800.00"
    ]
    raw_text = "\n".join([l[0] for l in lines] + table)

    fmt = "digital_pdf" if i <= 8 else ("image_png" if i <= 10 else "image_only_pdf")
    ext = ".png" if fmt == "image_png" else ".pdf"
    doc_file = os.path.join(DOCS_DIR, f"{doc_id}{ext}")

    if fmt == "digital_pdf":
        create_digital_pdf(doc_file, lines, draw_table=True, table_rows=table)
    elif fmt == "image_png":
        create_image_doc(doc_file, lines + [(r, 9, False) for r in table], scan_effect=True, angle=1.1, noise=12)
    else:
        create_image_only_pdf(doc_file, lines + [(r, 9, False) for r in table], angle=-1.1, noise=12)

    gt_data = {
        "file": f"{doc_id}{ext}",
        "expected_type": "bank_statement",
        "expected_routing": get_routing("bank_statement", is_restricted=True),
        "expected_fields": {
            "Account Holder": holder,
            "Account Number": acct_num,
            "Opening Balance": open_bal,
            "Closing Balance": close_bal,
        },
        "expected_sensitive": [{"type": "BANK_ACCOUNT", "value": acct_num}],
        "format": fmt,
        "raw_text": raw_text,
        "needs_review": False,
        "notes": "Bank statement with transaction ledger"
    }
    with open(os.path.join(GT_DIR, f"{doc_id}{ext}.json"), "w", encoding="utf-8") as f:
        json.dump(gt_data, f, indent=2)
    count += 1

# -----------------------------------------------------------------------------
# 5. MEDICAL REPORTS (12 documents - sensitive HIPAA)
# -----------------------------------------------------------------------------
for i in range(1, 13):
    doc_id = f"indep_med_{i:02d}"
    clinic = f"St. Jude Regional Diagnostic Center {i}"
    patient = f"Patient {chr(65 + i)} Anderson"
    mrn = f"MRN-{880000 + i}"
    dob = f"198{i % 9}-04-12"
    ssn = f"219-45-{6000 + i}"
    test_date = f"2026-10-{12 + (i % 15):02d}"
    diagnosis = f"Acute Bilateral Respiratory Syndrome Grade {i % 3 + 1}"

    lines = [
        (clinic, 14, True),
        ("CONFIDENTIAL CLINICAL LABORATORY REPORT", 12, True),
        (f"Patient Name: {patient}", 10, False),
        (f"Medical Record Number: {mrn}", 10, False),
        (f"Date of Birth: {dob}", 10, False),
        (f"Social Security Number: {ssn}", 10, False),  # HIPAA sensitive canary
        (f"Test Date: {test_date}", 10, False),
        (f"Attending Physician: Dr. Marcus Vance MD", 10, False),
        (f"Primary Clinical Diagnosis: {diagnosis}", 11, True),
        ("Specimen Evaluation: Complete blood chemistry panel within acceptable margins.", 9, False),
    ]
    raw_text = "\n".join([l[0] for l in lines])

    fmt = "digital_pdf" if i <= 7 else ("image_png" if i <= 10 else "image_only_pdf")
    ext = ".png" if fmt == "image_png" else ".pdf"
    doc_file = os.path.join(DOCS_DIR, f"{doc_id}{ext}")

    if fmt == "digital_pdf":
        create_digital_pdf(doc_file, lines)
    elif fmt == "image_png":
        create_image_doc(doc_file, lines, scan_effect=True, angle=1.0, noise=10)
    else:
        create_image_only_pdf(doc_file, lines, angle=-1.0, noise=12)

    gt_data = {
        "file": f"{doc_id}{ext}",
        "expected_type": "medical_report",
        "expected_routing": get_routing("medical_report", is_restricted=True),
        "expected_fields": {
            "Patient Name": patient,
            "Date of Birth": dob,
            "Medical Record Number": mrn,
            "Primary Clinical Diagnosis": diagnosis,
        },
        "expected_sensitive": [
            {"type": "US_SSN", "value": ssn},
            {"type": "HEALTH_IDENTIFIER", "value": mrn}
        ],
        "format": fmt,
        "raw_text": raw_text,
        "needs_review": False,
        "notes": "Medical report containing HIPAA restricted identifiers"
    }
    with open(os.path.join(GT_DIR, f"{doc_id}{ext}.json"), "w", encoding="utf-8") as f:
        json.dump(gt_data, f, indent=2)
    count += 1

# -----------------------------------------------------------------------------
# 6. CONTRACTS (12 documents - multi-page)
# -----------------------------------------------------------------------------
for i in range(1, 13):
    doc_id = f"indep_contract_{i:02d}"
    contract_id = f"CTR-AGMT-2026-{100 + i}"
    eff_date = f"2026-09-01"
    party_a = f"Enterprise Cloud Systems Inc {i}"
    party_b = f"Strategic Data Analytics LLC {i}"
    law = "State of Delaware"

    lines_p1 = [
        ("MASTER SERVICE AGREEMENT", 16, True),
        (f"Agreement ID: {contract_id}", 10, False),
        (f"Effective Date: {eff_date}", 10, False),
        (f"First Party: {party_a}", 10, False),
        (f"Second Party: {party_b}", 10, False),
        ("Section 1: Scope of Work", 12, True),
        ("The parties hereby enter into this binding commercial agreement for enterprise software services.", 9, False),
        ("Each party agrees to maintain strict confidentiality of all proprietary operational materials.", 9, False),
    ]
    lines_p2 = [
        ("Section 2: Term and Termination", 12, True),
        ("This agreement shall remain effective for a period of thirty-six (36) months from the Effective Date.", 9, False),
        (f"Governing Law: This agreement shall be governed by the laws of the {law}.", 10, False),
        ("IN WITNESS WHEREOF, the parties hereto have executed this Agreement as of the date first above written.", 9, False),
        (f"Signed by: Authorized Representative for {party_a}", 9, False),
        (f"Signed by: Authorized Representative for {party_b}", 9, False),
    ]

    c = canvas.Canvas(os.path.join(DOCS_DIR, f"{doc_id}.pdf"), pagesize=letter)
    for p_lines in [lines_p1, lines_p2]:
        y = 750
        for l in p_lines:
            c.setFont("Helvetica-Bold" if l[2] else "Helvetica", l[1])
            c.drawString(60, y, l[0])
            y -= (l[1] + 6)
        c.showPage()
    c.save()

    raw_text = "\n".join([l[0] for l in lines_p1 + lines_p2])
    gt_data = {
        "file": f"{doc_id}.pdf",
        "expected_type": "contract",
        "expected_routing": get_routing("contract"),
        "expected_fields": {
            "Agreement ID": contract_id,
            "Effective Date": eff_date,
            "First Party": party_a,
            "Second Party": party_b,
        },
        "expected_sensitive": [],
        "format": "multi_page_pdf",
        "raw_text": raw_text,
        "needs_review": False,
        "notes": "Two-page legal contract"
    }
    with open(os.path.join(GT_DIR, f"{doc_id}.pdf.json"), "w", encoding="utf-8") as f:
        json.dump(gt_data, f, indent=2)
    count += 1

# -----------------------------------------------------------------------------
# 7. FORMAL LETTERS & CORRESPONDENCE (10 documents)
# -----------------------------------------------------------------------------
for i in range(1, 11):
    doc_id = f"indep_letter_{i:02d}"
    sender = f"Office of Executive Operations, Dept {i}"
    date = f"2026-11-{5 + i:02d}"
    subject = f"Notice of Regulatory Update #{i}"

    lines = [
        (sender, 12, True),
        (f"Date: {date}", 10, False),
        ("To: All Department Heads and Operational Supervisors", 10, False),
        (f"Subject: {subject}", 11, True),
        ("Dear Team,", 10, False),
        ("Please be advised that the updated annual compliance procedures will take effect next quarter.", 9, False),
        ("Review the attached guidelines carefully and confirm receipt with your department coordinator.", 9, False),
        ("Sincerely,", 9, False),
        ("Executive Leadership Committee", 9, False),
    ]
    raw_text = "\n".join([l[0] for l in lines])
    create_digital_pdf(os.path.join(DOCS_DIR, f"{doc_id}.pdf"), lines)

    gt_data = {
        "file": f"{doc_id}.pdf",
        "expected_type": "letter",
        "expected_routing": get_routing("letter"),
        "expected_fields": {
            "Date": date,
            "Subject": subject,
        },
        "expected_sensitive": [],
        "format": "digital_pdf",
        "raw_text": raw_text,
        "needs_review": False,
        "notes": "Formal corporate correspondence letter"
    }
    with open(os.path.join(GT_DIR, f"{doc_id}.pdf.json"), "w", encoding="utf-8") as f:
        json.dump(gt_data, f, indent=2)
    count += 1

# -----------------------------------------------------------------------------
# 8. NEGATIVE EVIDENCE & AMBIGUITY EDGE CASES (8 documents)
# -----------------------------------------------------------------------------
for i in range(1, 9):
    doc_id = f"indep_edge_{i:02d}"
    if i <= 4:
        # Negative evidence: looks like invoice but is quotation
        lines = [
            ("PRE-SALE ESTIMATE & QUOTATION", 14, True),
            ("THIS IS A QUOTATION ONLY, NOT AN INVOICE", 12, True),  # Negative keyword!
            (f"Quotation ID: QUOTE-2026-{100 + i}", 10, False),
            (f"Date: 2026-11-15", 10, False),
            ("Bill To / Inquire By: Prospective Client Corp", 10, False),
            ("Estimated Total Amount: $4,500.00", 11, True),
            ("Payment Terms: Not applicable until formal invoice issued.", 9, False),
        ]
        expected_type = "unknown"
        expected_routing = get_routing("unknown")
        needs_review = True
        notes = "Negative evidence: explicit 'not an invoice' quotation"
    else:
        # Close candidates: receipt with full invoice-style summary
        lines = [
            ("TRANSACTION SUMMARY DOCUMENT", 14, True),
            ("Invoice and Receipt Combined Record", 12, True),
            (f"Reference Code: TX-REC-{900 + i}", 10, False),
            ("Date: 2026-11-20", 10, False),
            ("Total Amount / Paid: $350.00", 10, True),
            ("Payment Received by Cashier", 9, False),
        ]
        expected_type = "receipt"
        expected_routing = get_routing("receipt")
        needs_review = True
        notes = "Close score between invoice and receipt - triggers top-2 margin rule"

    raw_text = "\n".join([l[0] for l in lines])
    create_digital_pdf(os.path.join(DOCS_DIR, f"{doc_id}.pdf"), lines)

    gt_data = {
        "file": f"{doc_id}.pdf",
        "expected_type": expected_type,
        "expected_routing": expected_routing,
        "expected_fields": {},
        "expected_sensitive": [],
        "format": "digital_pdf",
        "raw_text": raw_text,
        "needs_review": needs_review,
        "notes": notes
    }
    with open(os.path.join(GT_DIR, f"{doc_id}.pdf.json"), "w", encoding="utf-8") as f:
        json.dump(gt_data, f, indent=2)
    count += 1

# -----------------------------------------------------------------------------
# 9. UNKNOWN / UNSTRUCTURED DOCUMENTS (8 documents)
# -----------------------------------------------------------------------------
for i in range(1, 9):
    doc_id = f"indep_unknown_{i:02d}"
    lines = [
        ("INTERNAL DISCUSSION MEMORANDUM", 14, True),
        (f"Topic: Exploration of Novel Quantum Computing Architecture Part {i}", 11, True),
        ("We reviewed recent advancements in quantum error correction and topological qubits.", 10, False),
        ("The primary objective is to evaluate decoherence rates across differing cryogenic setups.", 10, False),
        ("Next meeting scheduled for Thursday morning at the laboratory annex.", 10, False),
        ("Attendees: Dr. Smith, Dr. Taylor, Research Fellows.", 9, False),
    ]
    raw_text = "\n".join([l[0] for l in lines])
    create_digital_pdf(os.path.join(DOCS_DIR, f"{doc_id}.pdf"), lines)

    gt_data = {
        "file": f"{doc_id}.pdf",
        "expected_type": "unknown",
        "expected_routing": get_routing("unknown"),
        "expected_fields": {},
        "expected_sensitive": [],
        "format": "digital_pdf",
        "raw_text": raw_text,
        "needs_review": True,
        "notes": "Unstructured technical article with no matching schema"
    }
    with open(os.path.join(GT_DIR, f"{doc_id}.pdf.json"), "w", encoding="utf-8") as f:
        json.dump(gt_data, f, indent=2)
    count += 1

# -----------------------------------------------------------------------------
# 10. SET B AND SET C FILES (6 documents)
# -----------------------------------------------------------------------------
set_files = [
    ("b_01.pdf", "invoice", "AP_INVOICE_PROCESSING", [("Apex Solutions", 14, True), ("INVOICE", 12, True), ("Invoice Number: INV-B01", 10, False), ("Total Amount Due: $1,250.00", 10, True)]),
    ("b_02.pdf", "receipt", "EXPENSE_REIMBURSEMENT_SYSTEM", [("City Cafe", 14, True), ("RECEIPT", 12, True), ("Receipt #: RCPT-B02", 10, False), ("Total Paid: $32.50", 10, True)]),
    ("b_03.png", "purchase_order", "PO_MATCHING_SYSTEM", [("Logistics Supply Co", 14, True), ("PURCHASE ORDER", 12, True), ("PO Number: PO-B03", 10, False), ("Total Order Amount: $8,400.00", 10, True)]),
    ("c_01.pdf", "bank_statement", "TREASURY_RECONCILIATION", [("Metro Bank", 14, True), ("BANK STATEMENT", 12, True), ("Account Holder: Set C Corp", 10, False), ("Closing Balance: $45,000.00", 10, True)]),
    ("c_02.pdf", "medical_report", "RESTRICTED_HIPAA_SECURE_VAULT", [("Memorial Clinic", 14, True), ("LAB REPORT", 12, True), ("Patient Name: John Doe", 10, False), ("Diagnosis: Hypertension", 10, True)]),
    ("c_03.pdf", "contract", "LEGAL_CONTRACT_REPOSITORY", [("AGREEMENT", 14, True), ("Effective Date: 2026-11-01", 10, False), ("First Party: Alpha Corp", 10, False), ("Second Party: Beta LLC", 10, False)]),
]

for fname, dtype, droute, flines in set_files:
    fpath = os.path.join(DOCS_DIR, fname)
    if fname.endswith(".png"):
        create_image_doc(fpath, flines, scan_effect=False)
    else:
        create_digital_pdf(fpath, flines)
    raw_text = "\n".join([l[0] for l in flines])
    gt_data = {
        "file": fname,
        "expected_type": dtype,
        "expected_routing": droute,
        "expected_fields": {},
        "expected_sensitive": [],
        "format": "image_png" if fname.endswith(".png") else "digital_pdf",
        "raw_text": raw_text,
        "needs_review": False,
        "notes": f"Standard {dtype} verification document"
    }
    with open(os.path.join(GT_DIR, f"{fname}.json"), "w", encoding="utf-8") as f:
        json.dump(gt_data, f, indent=2)
    count += 1

print(f"SUCCESS: Generated {count} independent documents and answer keys!")
