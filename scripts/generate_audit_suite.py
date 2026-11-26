"""Generate 30 synthetic audit documents across diverse document kinds and formats.
Includes digital PDFs, clean images, noisy/skewed scans, image-only PDFs, multi-page mixed docs,
and 3 documents with no schema.
"""

import os
import json
import random
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

OUT_DIR = "audit_inputs"
os.makedirs(OUT_DIR, exist_ok=True)

def add_scan_effects(img: Image.Image, skew_angle: float = 1.2, noise_sigma: float = 8.0) -> Image.Image:
    """Simulate a scanned document with slight rotation, speckle noise, and paper texture."""
    np_img = np.array(img.convert("RGB"))
    # Rotation
    h, w = np_img.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, skew_angle, 1.0)
    rotated = cv2.warpAffine(np_img, M, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=(248, 248, 245))
    # Gaussian noise
    noise = np.random.normal(0, noise_sigma, rotated.shape).astype(np.float32)
    noisy = np.clip(rotated.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(noisy)

def save_expected(base_name: str, doc_kind: str, key_values: dict, notes: str = ""):
    exp_path = os.path.join(OUT_DIR, f"{base_name}.expected.json")
    with open(exp_path, "w", encoding="utf-8") as f:
        json.dump({
            "document_kind": doc_kind,
            "key_values": key_values,
            "notes": notes,
        }, f, indent=2)

print("Synthesizing 30 diverse audit documents in audit_inputs/...")

# -----------------------------------------------------------------------------
# 1. doc01_invoice.pdf (Digital PDF)
# -----------------------------------------------------------------------------
def gen_doc01():
    pdf_path = os.path.join(OUT_DIR, "doc01_invoice.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>APEX CLOUD SYSTEMS INC.</b>", styles['Title']),
        Paragraph("INVOICE", styles['Heading2']),
        Spacer(1, 10),
        Paragraph("<b>Invoice Number:</b> INV-84920", styles['Normal']),
        Paragraph("<b>Invoice Date:</b> 2026-10-14", styles['Normal']),
        Paragraph("<b>Due Date:</b> 2026-11-14", styles['Normal']),
        Paragraph("<b>Customer Name:</b> Horizon Analytics LLC", styles['Normal']),
        Paragraph("<b>Billing Address:</b> 450 Silicon Parkway, Austin, TX 78701", styles['Normal']),
        Spacer(1, 15),
    ]
    data = [
        ["Description", "Qty", "Unit Price", "Total"],
        ["Cloud Enterprise Hosting Q4", "1", "$4,200.00", "$4,200.00"],
        ["Dedicated VPC Firewall Support", "1", "$850.00", "$850.00"],
        ["Subtotal", "", "", "$5,050.00"],
        ["Tax Amount (8.25%)", "", "", "$416.63"],
        ["Total Amount", "", "", "$5,466.63"],
    ]
    t = Table(data, colWidths=[240, 60, 100, 100])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1e293b")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('GRID', (0,0), (-1,-1), 1, colors.HexColor("#cbd5e1")),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
    ]))
    story.append(t)
    doc.build(story)
    save_expected("doc01_invoice", "invoice", {
        "invoice_number": "INV-84920",
        "invoice_date": "2026-10-14",
        "due_date": "2026-11-14",
        "customer_name": "Horizon Analytics LLC",
        "total_amount": "$5,466.63",
        "tax_amount": "$416.63",
        "subtotal": "$5,050.00",
    })

# -----------------------------------------------------------------------------
# 2. doc02_receipt.png (Clean Image)
# -----------------------------------------------------------------------------
def gen_doc02():
    img = Image.new("RGB", (600, 800), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    lines = [
        ("BLUE HARBOR BISTRO", 18, True),
        ("77 Ocean Avenue, Seattle, WA", 12, False),
        ("----------------------------------------", 12, False),
        ("Receipt #: R-90214", 14, True),
        ("Date: 2026-11-02 12:45 PM", 12, False),
        ("Server: Marcus T.", 12, False),
        ("Payment Method: Visa Ending 4012", 12, False),
        ("----------------------------------------", 12, False),
        ("2x Artisanal Espresso     $9.00", 13, False),
        ("1x Smoked Salmon Bagel    $14.50", 13, False),
        ("1x Mixed Berry Parfait    $8.00", 13, False),
        ("----------------------------------------", 12, False),
        ("Subtotal: $31.50", 13, False),
        ("Sales Tax: $3.15", 13, False),
        ("Tip: $6.00", 13, False),
        ("Total Amount: $40.65", 15, True),
        ("----------------------------------------", 12, False),
        ("Thank you for dining with us!", 12, False),
    ]
    y = 30
    for text, size, is_bold in lines:
        draw.text((40, y), text, fill=(20, 20, 20))
        y += 35
    img.save(os.path.join(OUT_DIR, "doc02_receipt.png"))
    save_expected("doc02_receipt", "receipt", {
        "receipt_number": "R-90214",
        "date": "2026-11-02",
        "vendor_name": "BLUE HARBOR BISTRO",
        "subtotal": "$31.50",
        "total_amount": "$40.65",
        "payment_method": "Visa Ending 4012",
    })

# -----------------------------------------------------------------------------
# 3. doc03_purchase_order.pdf (Digital PDF)
# -----------------------------------------------------------------------------
def gen_doc03():
    pdf_path = os.path.join(OUT_DIR, "doc03_purchase_order.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>PURCHASE ORDER</b>", styles['Title']),
        Spacer(1, 10),
        Paragraph("<b>PO Number:</b> PO-2026-7731", styles['Normal']),
        Paragraph("<b>Order Date:</b> 2026-09-18", styles['Normal']),
        Paragraph("<b>Vendor Name:</b> Global Tech Hardware Distributors", styles['Normal']),
        Paragraph("<b>Delivery Date:</b> 2026-10-05", styles['Normal']),
        Paragraph("<b>Shipping Terms:</b> FOB Destination", styles['Normal']),
        Spacer(1, 15),
    ]
    data = [
        ["Line", "Item SKU", "Description", "Qty", "Unit Price", "Total"],
        ["1", "SVR-1002", "Rackmount Server Node 64GB", "4", "$1,800.00", "$7,200.00"],
        ["2", "SW-48P", "48-Port Managed PoE Switch", "2", "$950.00", "$1,900.00"],
        ["", "", "", "", "Total PO Value", "$9,100.00"],
    ]
    t = Table(data, colWidths=[40, 90, 180, 50, 80, 90])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#334155")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('GRID', (0,0), (-1,-1), 1, colors.grey),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
    ]))
    story.append(t)
    doc.build(story)
    save_expected("doc03_purchase_order", "purchase_order", {
        "po_number": "PO-2026-7731",
        "order_date": "2026-09-18",
        "vendor_name": "Global Tech Hardware Distributors",
        "delivery_date": "2026-10-05",
        "total_amount": "$9,100.00",
    })

# -----------------------------------------------------------------------------
# 4. doc04_bank_statement.pdf (Digital PDF)
# -----------------------------------------------------------------------------
def gen_doc04():
    pdf_path = os.path.join(OUT_DIR, "doc04_bank_statement.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>PACIFIC CREST FEDERAL BANK</b>", styles['Title']),
        Paragraph("Commercial Checking Statement", styles['Heading3']),
        Spacer(1, 10),
        Paragraph("<b>Account Number:</b> 9834-0192-4411", styles['Normal']),
        Paragraph("<b>Statement Period:</b> October 1, 2026 - October 31, 2026", styles['Normal']),
        Paragraph("<b>Account Holder:</b> Cascade Engineering Partners", styles['Normal']),
        Paragraph("<b>Opening Balance:</b> $45,210.80", styles['Normal']),
        Paragraph("<b>Total Deposits:</b> $18,400.00", styles['Normal']),
        Paragraph("<b>Total Withdrawals:</b> $12,750.30", styles['Normal']),
        Paragraph("<b>Closing Balance:</b> $50,860.50", styles['Normal']),
        Spacer(1, 15),
    ]
    data = [
        ["Date", "Transaction Details", "Amount", "Balance"],
        ["10/05/2026", "Direct Deposit Client Retainer", "+$10,000.00", "$55,210.80"],
        ["10/12/2026", "Wire Transfer Office Rent", "-$4,500.00", "$50,710.80"],
        ["10/24/2026", "Payroll Distribution Batch", "-$8,250.30", "$42,460.50"],
        ["10/29/2026", "Deposit Invoice #8410", "+$8,400.00", "$50,860.50"],
    ]
    t = Table(data, colWidths=[80, 220, 100, 100])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0f172a")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('GRID', (0,0), (-1,-1), 1, colors.grey),
    ]))
    story.append(t)
    doc.build(story)
    save_expected("doc04_bank_statement", "bank_statement", {
        "account_number": "9834-0192-4411",
        "account_holder": "Cascade Engineering Partners",
        "opening_balance": "$45,210.80",
        "closing_balance": "$50,860.50",
        "statement_period": "October 1, 2026 - October 31, 2026",
    })

# -----------------------------------------------------------------------------
# 5. doc05_tax_w2.png (Clean Image)
# -----------------------------------------------------------------------------
def gen_doc05():
    img = Image.new("RGB", (800, 500), color=(250, 250, 250))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(20, 20), (780, 480)], outline=(100, 100, 100), width=2)
    draw.text((40, 35), "Form W-2 Wage and Tax Statement 2026", fill=(0, 0, 0))
    fields = [
        ("Employee Social Security Number: 111-22-3333", 40, 80),
        ("Employer Identification Number (EIN): 84-9921045", 40, 120),
        ("Employer Name: Orion Logistics Corporation", 40, 160),
        ("Employee Name: Jennifer M. Walsh", 40, 200),
        ("Box 1 Wages, tips, other compensation: $94,500.00", 40, 250),
        ("Box 2 Federal income tax withheld: $16,840.00", 40, 290),
        ("Box 3 Social security wages: $94,500.00", 40, 330),
        ("Box 4 Social security tax withheld: $5,859.00", 40, 370),
        ("Box 5 Medicare wages and tips: $94,500.00", 40, 410),
        ("Box 6 Medicare tax withheld: $1,370.25", 40, 450),
    ]
    for text, x, y in fields:
        draw.text((x, y), text, fill=(20, 20, 20))
    img.save(os.path.join(OUT_DIR, "doc05_tax_w2.png"))
    save_expected("doc05_tax_w2", "tax_form", {
        "ssn": "111-22-3333",
        "ein": "84-9921045",
        "employee_name": "Jennifer M. Walsh",
        "employer_name": "Orion Logistics Corporation",
        "wages": "$94,500.00",
        "federal_tax_withheld": "$16,840.00",
    })

# -----------------------------------------------------------------------------
# 6. doc06_nda_contract.pdf (Digital PDF)
# -----------------------------------------------------------------------------
def gen_doc06():
    pdf_path = os.path.join(OUT_DIR, "doc06_nda_contract.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>MUTUAL NON-DISCLOSURE AGREEMENT</b>", styles['Title']),
        Spacer(1, 10),
        Paragraph("<b>Contract ID:</b> NDA-2026-559", styles['Normal']),
        Paragraph("<b>Effective Date:</b> 2026-08-01", styles['Normal']),
        Paragraph("<b>Disclosing Party:</b> Quantum Dynamics Inc.", styles['Normal']),
        Paragraph("<b>Receiving Party:</b> NorthStar Robotics Corp.", styles['Normal']),
        Paragraph("<b>Jurisdiction:</b> State of Delaware", styles['Normal']),
        Spacer(1, 10),
        Paragraph("1. Purpose: The parties intend to engage in technical discussions concerning autonomous sensor fusion algorithms.", styles['Normal']),
        Spacer(1, 5),
        Paragraph("2. Term of Confidentiality: 3 years from the Effective Date.", styles['Normal']),
        Spacer(1, 15),
        Paragraph("<b>Authorized Signatory (Party A):</b> Dr. Alan Turing, CTO", styles['Normal']),
        Paragraph("<b>Authorized Signatory (Party B):</b> Sarah Connor, VP Engineering", styles['Normal']),
    ]
    doc.build(story)
    save_expected("doc06_nda_contract", "contract", {
        "contract_id": "NDA-2026-559",
        "effective_date": "2026-08-01",
        "disclosing_party": "Quantum Dynamics Inc.",
        "receiving_party": "NorthStar Robotics Corp.",
        "jurisdiction": "State of Delaware",
    })

# -----------------------------------------------------------------------------
# 7. doc07_employment_agreement.pdf (Digital PDF, Multi-page)
# -----------------------------------------------------------------------------
def gen_doc07():
    from reportlab.platypus import PageBreak
    pdf_path = os.path.join(OUT_DIR, "doc07_employment_agreement.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>EXECUTIVE EMPLOYMENT AGREEMENT</b>", styles['Title']),
        Spacer(1, 10),
        Paragraph("<b>Document Reference:</b> EMP-2026-891", styles['Normal']),
        Paragraph("<b>Employer:</b> Vanguard Biotech Laboratories", styles['Normal']),
        Paragraph("<b>Employee Name:</b> Marcus Aurelius Vance", styles['Normal']),
        Paragraph("<b>Job Title:</b> Principal Bioinformatician", styles['Normal']),
        Paragraph("<b>Commencement Date:</b> 2026-12-01", styles['Normal']),
        Paragraph("<b>Base Salary:</b> $185,000.00 per annum", styles['Normal']),
        Spacer(1, 200),
        Paragraph("<i>Continued on Page 2...</i>", styles['Italic']),
        PageBreak(),
        Paragraph("<b>EXECUTIVE EMPLOYMENT AGREEMENT (Page 2)</b>", styles['Heading2']),
        Spacer(1, 10),
        Paragraph("<b>Annual Target Bonus:</b> 25% of Base Salary ($46,250.00)", styles['Normal']),
        Paragraph("<b>Equity Grant:</b> 15,000 Restricted Stock Units (RSUs) vesting over 4 years", styles['Normal']),
        Paragraph("<b>Governing Law:</b> Commonwealth of Massachusetts", styles['Normal']),
        Paragraph("<b>Signatures:</b>", styles['Heading3']),
        Paragraph("Employer: Vanguard Biotech Laboratories (by CEO Eleanor Vance)", styles['Normal']),
        Paragraph("Employee: Marcus Aurelius Vance", styles['Normal']),
    ]
    doc.build(story)
    save_expected("doc07_employment_agreement", "contract", {
        "contract_id": "EMP-2026-891",
        "employer": "Vanguard Biotech Laboratories",
        "employee_name": "Marcus Aurelius Vance",
        "job_title": "Principal Bioinformatician",
        "start_date": "2026-12-01",
        "base_salary": "$185,000.00",
    })

# -----------------------------------------------------------------------------
# 8. doc08_lease_agreement.pdf (Image-only PDF, scanned)
# -----------------------------------------------------------------------------
def gen_doc08():
    img = Image.new("RGB", (800, 1050), color=(252, 252, 250))
    draw = ImageDraw.Draw(img)
    lines = [
        "COMMERCIAL PROPERTY LEASE AGREEMENT",
        "Lease Agreement ID: LSE-2026-904",
        "Date of Execution: 2026-07-15",
        "Landlord: Beacon Hill Realty Trust",
        "Tenant: Apex Digital Solutions LLC",
        "Premises Address: 1200 Beacon Street, Suite 400, Boston, MA",
        "Lease Term: 36 Months",
        "Commencement Date: 2026-09-01",
        "Monthly Base Rent: $6,500.00",
        "Security Deposit: $13,000.00",
        "Permitted Use: Commercial General Office",
    ]
    y = 50
    for line in lines:
        draw.text((60, y), line, fill=(30, 30, 30))
        y += 45
    scanned_img = add_scan_effects(img, skew_angle=-0.8, noise_sigma=6.0)
    pdf_path = os.path.join(OUT_DIR, "doc08_lease_agreement.pdf")
    scanned_img.save(pdf_path, "PDF", resolution=100.0)
    save_expected("doc08_lease_agreement", "contract", {
        "lease_id": "LSE-2026-904",
        "landlord": "Beacon Hill Realty Trust",
        "tenant": "Apex Digital Solutions LLC",
        "monthly_rent": "$6,500.00",
        "security_deposit": "$13,000.00",
        "commencement_date": "2026-09-01",
    })

# -----------------------------------------------------------------------------
# 9. doc09_service_agreement.jpg (Skewed scan)
# -----------------------------------------------------------------------------
def gen_doc09():
    img = Image.new("RGB", (800, 1000), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    lines = [
        "MASTER SERVICES AGREEMENT",
        "Agreement Number: MSA-8812",
        "Client: Redwood Financial Group",
        "Service Provider: CyberShield Managed Defense",
        "Effective Date: 2026-05-10",
        "Monthly Service Retainer: $3,750.00",
        "Service Scope: 24/7 Endpoint Detection and Response",
        "Payment Terms: Net 30 Days",
    ]
    y = 60
    for l in lines:
        draw.text((60, y), l, fill=(15, 15, 15))
        y += 45
    skewed = add_scan_effects(img, skew_angle=2.1, noise_sigma=10.0)
    skewed.save(os.path.join(OUT_DIR, "doc09_service_agreement.jpg"))
    save_expected("doc09_service_agreement", "contract", {
        "agreement_number": "MSA-8812",
        "client": "Redwood Financial Group",
        "service_provider": "CyberShield Managed Defense",
        "effective_date": "2026-05-10",
        "monthly_retainer": "$3,750.00",
    })

# -----------------------------------------------------------------------------
# 10. doc10_job_offer.pdf (Digital PDF)
# -----------------------------------------------------------------------------
def gen_doc10():
    pdf_path = os.path.join(OUT_DIR, "doc10_job_offer.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>NEXUS ARTIFICIAL INTELLIGENCE CORP.</b>", styles['Title']),
        Paragraph("Formal Offer of Employment", styles['Heading3']),
        Spacer(1, 10),
        Paragraph("<b>Candidate Name:</b> Alexander Wright", styles['Normal']),
        Paragraph("<b>Offer Date:</b> 2026-11-05", styles['Normal']),
        Paragraph("<b>Position:</b> Senior Machine Learning Scientist", styles['Normal']),
        Paragraph("<b>Department:</b> Applied Perception Research", styles['Normal']),
        Paragraph("<b>Starting Base Salary:</b> $190,000.00", styles['Normal']),
        Paragraph("<b>Signing Bonus:</b> $25,000.00", styles['Normal']),
        Paragraph("<b>Target Start Date:</b> 2027-01-15", styles['Normal']),
        Paragraph("<b>Offer Expiration Date:</b> 2026-11-20", styles['Normal']),
        Spacer(1, 15),
        Paragraph("We are thrilled to offer you this role on our core vision model team.", styles['Normal']),
    ]
    doc.build(story)
    save_expected("doc10_job_offer", "offer_letter", {
        "candidate_name": "Alexander Wright",
        "position": "Senior Machine Learning Scientist",
        "base_salary": "$190,000.00",
        "signing_bonus": "$25,000.00",
        "start_date": "2027-01-15",
        "expiration_date": "2026-11-20",
    })

# -----------------------------------------------------------------------------
# 11. doc11_resignation_letter.png (Clean Image)
# -----------------------------------------------------------------------------
def gen_doc11():
    img = Image.new("RGB", (700, 700), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    lines = [
        "FORMAL RESIGNATION NOTICE",
        "Date: 2026-10-30",
        "To: Director of Operations, Cascade Logistics",
        "From: Daniel K. Martinez",
        "Employee ID: EMP-4019",
        "Position: Senior Route Dispatcher",
        "Subject: Notice of Resignation",
        "",
        "Please accept this letter as formal notification of my resignation.",
        "My final working day with the company will be: 2026-11-14.",
        "I want to thank the entire team for the opportunity to work together.",
        "",
        "Sincerely,",
        "Daniel K. Martinez",
    ]
    y = 40
    for l in lines:
        draw.text((50, y), l, fill=(20, 20, 20))
        y += 35
    img.save(os.path.join(OUT_DIR, "doc11_resignation_letter.png"))
    save_expected("doc11_resignation_letter", "correspondence", {
        "from": "Daniel K. Martinez",
        "employee_id": "EMP-4019",
        "position": "Senior Route Dispatcher",
        "date": "2026-10-30",
        "last_day": "2026-11-14",
    })

# -----------------------------------------------------------------------------
# 12. doc12_performance_review.pdf (Digital PDF)
# -----------------------------------------------------------------------------
def gen_doc12():
    pdf_path = os.path.join(OUT_DIR, "doc12_performance_review.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>ANNUAL PERFORMANCE APPRAISAL</b>", styles['Title']),
        Spacer(1, 10),
        Paragraph("<b>Employee Name:</b> Samantha Sterling", styles['Normal']),
        Paragraph("<b>Employee ID:</b> HR-8819", styles['Normal']),
        Paragraph("<b>Job Role:</b> Lead Product Designer", styles['Normal']),
        Paragraph("<b>Reviewing Manager:</b> Victoria Hayes", styles['Normal']),
        Paragraph("<b>Appraisal Period:</b> FY 2026", styles['Normal']),
        Paragraph("<b>Overall Rating:</b> Exceeds Expectations (4.8 / 5.0)", styles['Normal']),
        Paragraph("<b>Recommended Merit Increase:</b> 6.5%", styles['Normal']),
        Spacer(1, 10),
        Paragraph("Key Achievements: Led the redesign of the user onboarding flow resulting in a 24% uplift in retention.", styles['Normal']),
    ]
    doc.build(story)
    save_expected("doc12_performance_review", "performance_review", {
        "employee_name": "Samantha Sterling",
        "employee_id": "HR-8819",
        "role": "Lead Product Designer",
        "rating": "4.8 / 5.0",
        "merit_increase": "6.5%",
    })

# -----------------------------------------------------------------------------
# 13. doc13_employee_onboarding.pdf (Digital PDF)
# -----------------------------------------------------------------------------
def gen_doc13():
    pdf_path = os.path.join(OUT_DIR, "doc13_employee_onboarding.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>NEW EMPLOYEE ONBOARDING FORM</b>", styles['Title']),
        Spacer(1, 10),
        Paragraph("<b>Full Name:</b> Robert Liam Gallagher", styles['Normal']),
        Paragraph("<b>Social Security Number:</b> 333-44-5555", styles['Normal']),
        Paragraph("<b>Date of Birth:</b> 1991-06-22", styles['Normal']),
        Paragraph("<b>Contact Phone:</b> (555) 392-8104", styles['Normal']),
        Paragraph("<b>Emergency Contact:</b> Fiona Gallagher (Spouse)", styles['Normal']),
        Paragraph("<b>Emergency Phone:</b> (555) 392-8109", styles['Normal']),
        Paragraph("<b>Direct Deposit Bank:</b> First Federal Credit Union", styles['Normal']),
        Paragraph("<b>Routing Number:</b> 011000015", styles['Normal']),
        Paragraph("<b>Account Number:</b> 881029384", styles['Normal']),
    ]
    doc.build(story)
    save_expected("doc13_employee_onboarding", "form", {
        "full_name": "Robert Liam Gallagher",
        "ssn": "333-44-5555",
        "phone": "(555) 392-8104",
        "emergency_contact": "Fiona Gallagher",
        "bank_routing": "011000015",
        "bank_account": "881029384",
    })

# -----------------------------------------------------------------------------
# 14. doc14_bill_of_lading.pdf (Image-only PDF)
# -----------------------------------------------------------------------------
def gen_doc14():
    img = Image.new("RGB", (800, 1000), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    lines = [
        "OCEAN BILL OF LADING",
        "B/L Number: MEDU-9921840",
        "Vessel: MV Pacific Voyager Voyage 204E",
        "Port of Loading: Port of Long Beach, USA",
        "Port of Discharge: Port of Rotterdam, Netherlands",
        "Shipper: Western Grain Exporters LLC",
        "Consignee: EuroAgri Foodstuffs BV",
        "Container Number: TGHU-849102-1",
        "Gross Cargo Weight: 24,500 KG",
        "Number of Packages: 500 Sacks Hard Red Wheat",
    ]
    y = 50
    for l in lines:
        draw.text((60, y), l, fill=(20, 20, 20))
        y += 45
    pdf_path = os.path.join(OUT_DIR, "doc14_bill_of_lading.pdf")
    img.save(pdf_path, "PDF")
    save_expected("doc14_bill_of_lading", "logistics", {
        "bl_number": "MEDU-9921840",
        "shipper": "Western Grain Exporters LLC",
        "consignee": "EuroAgri Foodstuffs BV",
        "gross_weight": "24,500 KG",
        "container_number": "TGHU-849102-1",
    })

# -----------------------------------------------------------------------------
# 15. doc15_shipping_waybill.png (Clean Image)
# -----------------------------------------------------------------------------
def gen_doc15():
    img = Image.new("RGB", (700, 750), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    lines = [
        "AIR EXPRESS SHIPPING WAYBILL",
        "Tracking Number: 1Z9999999999999999",
        "Ship Date: 2026-11-04",
        "Service: Priority Overnight Air",
        "Origin: Chicago Logistics Hub, IL",
        "Destination: Atlanta Fulfillment Center, GA",
        "Sender: Apex Hardware Distribution",
        "Recipient: Southern Industrial Supplies",
        "Package Weight: 14.8 LBS",
        "Declared Value: $1,250.00",
    ]
    y = 40
    for l in lines:
        draw.text((50, y), l, fill=(15, 15, 15))
        y += 40
    img.save(os.path.join(OUT_DIR, "doc15_shipping_waybill.png"))
    save_expected("doc15_shipping_waybill", "logistics", {
        "tracking_number": "1Z9999999999999999",
        "ship_date": "2026-11-04",
        "sender": "Apex Hardware Distribution",
        "recipient": "Southern Industrial Supplies",
        "package_weight": "14.8 LBS",
    })

# -----------------------------------------------------------------------------
# 16. doc16_packing_slip.jpg (Noisy scan)
# -----------------------------------------------------------------------------
def gen_doc16():
    img = Image.new("RGB", (750, 850), color=(252, 252, 250))
    draw = ImageDraw.Draw(img)
    lines = [
        "WAREHOUSE PACKING SLIP",
        "Packing Slip #: PS-50192",
        "Order Reference: ORD-99201",
        "Pack Date: 2026-10-28",
        "Customer: Blue Horizon Laboratories",
        "Packed By: Inspector #42",
        "Item 1: Centrifuge Tubes 50mL (Pack of 500) - Qty: 2",
        "Item 2: Pipette Tips 200uL (Pack of 1000) - Qty: 5",
        "Item 3: Glass Beaker Set (5 pieces) - Qty: 1",
        "Total Cartons: 3 Boxes",
    ]
    y = 50
    for l in lines:
        draw.text((50, y), l, fill=(25, 25, 25))
        y += 45
    noisy = add_scan_effects(img, skew_angle=1.5, noise_sigma=12.0)
    noisy.save(os.path.join(OUT_DIR, "doc16_packing_slip.jpg"))
    save_expected("doc16_packing_slip", "logistics", {
        "packing_slip_number": "PS-50192",
        "order_reference": "ORD-99201",
        "customer": "Blue Horizon Laboratories",
        "pack_date": "2026-10-28",
        "total_cartons": "3 Boxes",
    })

# -----------------------------------------------------------------------------
# 17. doc17_customs_declaration.pdf (Digital PDF)
# -----------------------------------------------------------------------------
def gen_doc17():
    pdf_path = os.path.join(OUT_DIR, "doc17_customs_declaration.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>INTERNATIONAL COMMERCIAL CUSTOMS INVOICE</b>", styles['Title']),
        Spacer(1, 10),
        Paragraph("<b>Customs Declaration ID:</b> CUST-2026-1184", styles['Normal']),
        Paragraph("<b>Exporting Country:</b> United States", styles['Normal']),
        Paragraph("<b>Importing Country:</b> United Kingdom", styles['Normal']),
        Paragraph("<b>Harmonized Code (HS Code):</b> 8471.50.0150", styles['Normal']),
        Paragraph("<b>Exporter:</b> Silicon Valley Chips Ltd", styles['Normal']),
        Paragraph("<b>Importer:</b> Thames Computing Technologies Plc", styles['Normal']),
        Paragraph("<b>Declared Customs Value:</b> $12,400.00 USD", styles['Normal']),
        Paragraph("<b>Duty Payable:</b> $496.00 USD", styles['Normal']),
    ]
    doc.build(story)
    save_expected("doc17_customs_declaration", "logistics", {
        "customs_declaration_id": "CUST-2026-1184",
        "hs_code": "8471.50.0150",
        "exporter": "Silicon Valley Chips Ltd",
        "importer": "Thames Computing Technologies Plc",
        "customs_value": "$12,400.00 USD",
    })

# -----------------------------------------------------------------------------
# 18. doc18_formal_business_letter.pdf (Digital PDF)
# -----------------------------------------------------------------------------
def gen_doc18():
    pdf_path = os.path.join(OUT_DIR, "doc18_formal_business_letter.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>STRATOSPHERE CAPITAL MANAGEMENT</b>", styles['Title']),
        Paragraph("November 8, 2026", styles['Normal']),
        Spacer(1, 10),
        Paragraph("To: Board of Directors, Horizon Tech Partners", styles['Normal']),
        Paragraph("From: Arthur Pendelton, Managing Director", styles['Normal']),
        Paragraph("<b>Subject:</b> Proposed Strategic Co-Investment Partnership", styles['Normal']),
        Spacer(1, 10),
        Paragraph("Dear Members of the Board,", styles['Normal']),
        Spacer(1, 5),
        Paragraph("Following our preliminary discussions in New York last month, Stratosphere Capital is pleased to formally submit this letter of intent to commit up to $15,000,000.00 in growth equity capital towards your Series C financing round.", styles['Normal']),
    ]
    doc.build(story)
    save_expected("doc18_formal_business_letter", "correspondence", {
        "date": "November 8, 2026",
        "from": "Arthur Pendelton, Managing Director",
        "to": "Board of Directors, Horizon Tech Partners",
        "subject": "Proposed Strategic Co-Investment Partnership",
        "investment_amount": "$15,000,000.00",
    })

# -----------------------------------------------------------------------------
# 19. doc19_vendor_price_notice.png (Clean Image)
# -----------------------------------------------------------------------------
def gen_doc19():
    img = Image.new("RGB", (700, 650), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    lines = [
        "VULCAN STEEL PRODUCTS LLC",
        "Official Notice: Annual Price Adjustment",
        "Notice Reference: PN-2026-44",
        "Date of Notice: 2026-10-15",
        "Effective Date: 2027-01-01",
        "Addressed to: Valued Commercial Distribution Clients",
        "Price Change Summary: Structural Steel tubing prices will increase by 4.2%",
        "Reason for Adjustment: Raw alloy raw material and regional transport cost increases.",
        "Contact Person: Gregory Stone, VP of Commercial Sales",
    ]
    y = 40
    for l in lines:
        draw.text((45, y), l, fill=(10, 10, 10))
        y += 40
    img.save(os.path.join(OUT_DIR, "doc19_vendor_price_notice.png"))
    save_expected("doc19_vendor_price_notice", "correspondence", {
        "notice_reference": "PN-2026-44",
        "date": "2026-10-15",
        "effective_date": "2027-01-01",
        "price_increase": "4.2%",
        "vendor": "VULCAN STEEL PRODUCTS LLC",
    })

# -----------------------------------------------------------------------------
# 20. doc20_customer_inquiry.pdf (Digital PDF)
# -----------------------------------------------------------------------------
def gen_doc20():
    pdf_path = os.path.join(OUT_DIR, "doc20_customer_inquiry.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>CUSTOMER SERVICE TICKET CORRESPONDENCE</b>", styles['Title']),
        Spacer(1, 10),
        Paragraph("<b>Ticket Number:</b> TCK-77192", styles['Normal']),
        Paragraph("<b>Customer Name:</b> Beatrice Vance", styles['Normal']),
        Paragraph("<b>Customer Email:</b> bvance@omega-tech.example", styles['Normal']),
        Paragraph("<b>Product Model:</b> LaserScanner 4000-X", styles['Normal']),
        Paragraph("<b>Inquiry Date:</b> 2026-11-01", styles['Normal']),
        Paragraph("<b>Priority Level:</b> High", styles['Normal']),
        Paragraph("<b>Issue Description:</b> Scanner lens calibration fails with Error Code ERR-409 after firmware upgrade 3.4.1.", styles['Normal']),
    ]
    doc.build(story)
    save_expected("doc20_customer_inquiry", "correspondence", {
        "ticket_number": "TCK-77192",
        "customer_name": "Beatrice Vance",
        "product_model": "LaserScanner 4000-X",
        "error_code": "ERR-409",
        "date": "2026-11-01",
    })

# -----------------------------------------------------------------------------
# 21. doc21_patient_intake_form.jpg (Skewed scan)
# -----------------------------------------------------------------------------
def gen_doc21():
    img = Image.new("RGB", (750, 950), color=(250, 250, 248))
    draw = ImageDraw.Draw(img)
    lines = [
        "METROPOLITAN HEALTH CLINIC",
        "New Patient Medical Intake Form",
        "Patient ID: PT-90214",
        "Patient Name: Jonathan David Reynolds",
        "Date of Birth: 1984-03-12",
        "Phone Number: (555) 721-9940",
        "Insurance Provider: BlueCross BlueShield",
        "Policy Group Number: GRP-881924",
        "Primary Care Physician: Dr. Laura Croft, MD",
        "Known Allergies: Penicillin, Sulfa drugs",
    ]
    y = 50
    for l in lines:
        draw.text((50, y), l, fill=(20, 20, 20))
        y += 45
    skewed = add_scan_effects(img, skew_angle=-1.8, noise_sigma=9.0)
    skewed.save(os.path.join(OUT_DIR, "doc21_patient_intake_form.jpg"))
    save_expected("doc21_patient_intake_form", "medical_report", {
        "patient_id": "PT-90214",
        "patient_name": "Jonathan David Reynolds",
        "dob": "1984-03-12",
        "insurance_group": "GRP-881924",
        "allergies": "Penicillin, Sulfa drugs",
    })

# -----------------------------------------------------------------------------
# 22. doc22_insurance_claim.pdf (Digital PDF)
# -----------------------------------------------------------------------------
def gen_doc22():
    pdf_path = os.path.join(OUT_DIR, "doc22_insurance_claim.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>LIBERTY CASUALTY INSURANCE GROUP</b>", styles['Title']),
        Paragraph("Automobile Loss & Damage Claim Form", styles['Heading3']),
        Spacer(1, 10),
        Paragraph("<b>Claim Number:</b> CLM-2026-8841", styles['Normal']),
        Paragraph("<b>Policyholder:</b> Timothy Sterling", styles['Normal']),
        Paragraph("<b>Policy Number:</b> POL-99210-A", styles['Normal']),
        Paragraph("<b>Incident Date:</b> 2026-10-22", styles['Normal']),
        Paragraph("<b>Location of Incident:</b> Route 9, Framingham, MA", styles['Normal']),
        Paragraph("<b>Vehicle Make & Model:</b> 2024 Honda Accord Touring", styles['Normal']),
        Paragraph("<b>Estimated Repair Cost:</b> $4,850.00", styles['Normal']),
        Paragraph("<b>Deductible:</b> $500.00", styles['Normal']),
    ]
    doc.build(story)
    save_expected("doc22_insurance_claim", "form", {
        "claim_number": "CLM-2026-8841",
        "policyholder": "Timothy Sterling",
        "policy_number": "POL-99210-A",
        "incident_date": "2026-10-22",
        "estimated_repair_cost": "$4,850.00",
    })

# -----------------------------------------------------------------------------
# 23. doc23_expense_reimbursement.pdf (Digital PDF)
# -----------------------------------------------------------------------------
def gen_doc23():
    pdf_path = os.path.join(OUT_DIR, "doc23_expense_reimbursement.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>EMPLOYEE BUSINESS TRAVEL EXPENSE REPORT</b>", styles['Title']),
        Spacer(1, 10),
        Paragraph("<b>Report ID:</b> EXP-2026-049", styles['Normal']),
        Paragraph("<b>Employee Name:</b> Claire Dunphy", styles['Normal']),
        Paragraph("<b>Department:</b> Enterprise Sales", styles['Normal']),
        Paragraph("<b>Trip Destination:</b> Chicago Tech Summit 2026", styles['Normal']),
        Paragraph("<b>Airfare Expense:</b> $640.00", styles['Normal']),
        Paragraph("<b>Hotel Accommodations:</b> $920.00", styles['Normal']),
        Paragraph("<b>Client Dinner Meals:</b> $310.50", styles['Normal']),
        Paragraph("<b>Total Claim Amount:</b> $1,870.50", styles['Normal']),
        Paragraph("<b>Supervisor Approval:</b> Approved by Michael Scott, VP Sales", styles['Normal']),
    ]
    doc.build(story)
    save_expected("doc23_expense_reimbursement", "form", {
        "report_id": "EXP-2026-049",
        "employee_name": "Claire Dunphy",
        "destination": "Chicago Tech Summit 2026",
        "total_amount": "$1,870.50",
    })

# -----------------------------------------------------------------------------
# 24. doc24_clinical_lab_report.pdf (Digital PDF)
# -----------------------------------------------------------------------------
def gen_doc24():
    pdf_path = os.path.join(OUT_DIR, "doc24_clinical_lab_report.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>DIAGNOSTIC PATHOLOGY LABORATORIES</b>", styles['Title']),
        Paragraph("COMPREHENSIVE METABOLIC PANEL REPORT", styles['Heading3']),
        Spacer(1, 10),
        Paragraph("<b>Patient Name:</b> Eleanor Rigby", styles['Normal']),
        Paragraph("<b>Patient DOB:</b> 1978-11-19", styles['Normal']),
        Paragraph("<b>Specimen ID:</b> SPEC-88419", styles['Normal']),
        Paragraph("<b>Collection Date:</b> 2026-11-03", styles['Normal']),
        Paragraph("<b>Ordering Physician:</b> Dr. Robert Chase, MD", styles['Normal']),
        Spacer(1, 10),
    ]
    data = [
        ["Test Name", "Result", "Reference Range", "Flag"],
        ["Fasting Glucose", "92 mg/dL", "70 - 99 mg/dL", "Normal"],
        ["Blood Urea Nitrogen (BUN)", "16 mg/dL", "7 - 20 mg/dL", "Normal"],
        ["Serum Creatinine", "0.9 mg/dL", "0.6 - 1.2 mg/dL", "Normal"],
        ["Serum Sodium", "139 mmol/L", "135 - 145 mmol/L", "Normal"],
        ["Serum Potassium", "4.2 mmol/L", "3.5 - 5.1 mmol/L", "Normal"],
    ]
    t = Table(data, colWidths=[160, 100, 140, 80])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#065f46")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('GRID', (0,0), (-1,-1), 1, colors.grey),
    ]))
    story.append(t)
    doc.build(story)
    save_expected("doc24_clinical_lab_report", "medical_report", {
        "patient_name": "Eleanor Rigby",
        "specimen_id": "SPEC-88419",
        "collection_date": "2026-11-03",
        "glucose": "92 mg/dL",
        "creatinine": "0.9 mg/dL",
    })

# -----------------------------------------------------------------------------
# 25. doc25_financial_audit_report.pdf (Digital PDF, Multi-page)
# -----------------------------------------------------------------------------
def gen_doc25():
    from reportlab.platypus import PageBreak
    pdf_path = os.path.join(OUT_DIR, "doc25_financial_audit_report.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>INDEPENDENT AUDITOR'S REPORT</b>", styles['Title']),
        Paragraph("Fiscal Year Ended September 30, 2026", styles['Heading3']),
        Spacer(1, 10),
        Paragraph("<b>Entity Audited:</b> Apex Global Infrastructure Trust", styles['Normal']),
        Paragraph("<b>Auditor Firm:</b> Sterling & Cooper LLP", styles['Normal']),
        Paragraph("<b>Audit Opinion:</b> Unqualified Clean Opinion", styles['Normal']),
        Paragraph("<b>Total Consolidated Revenue:</b> $482,000,000.00", styles['Normal']),
        Paragraph("<b>Operating Income:</b> $84,500,000.00", styles['Normal']),
        Spacer(1, 200),
        PageBreak(),
        Paragraph("<b>FINANCIAL STATEMENT METRICS (Page 2)</b>", styles['Heading2']),
        Spacer(1, 10),
        Paragraph("<b>Net Earnings Before Tax:</b> $72,100,000.00", styles['Normal']),
        Paragraph("<b>Consolidated Total Assets:</b> $1,240,000,000.00", styles['Normal']),
        Paragraph("<b>Total Long-Term Liabilities:</b> $390,000,000.00", styles['Normal']),
        Paragraph("<b>Report Date:</b> 2026-10-31", styles['Normal']),
    ]
    doc.build(story)
    save_expected("doc25_financial_audit_report", "report", {
        "audited_entity": "Apex Global Infrastructure Trust",
        "auditor": "Sterling & Cooper LLP",
        "audit_opinion": "Unqualified Clean Opinion",
        "total_revenue": "$482,000,000.00",
        "report_date": "2026-10-31",
    })

# -----------------------------------------------------------------------------
# 26. doc26_maintenance_inspection.png (Clean Image)
# -----------------------------------------------------------------------------
def gen_doc26():
    img = Image.new("RGB", (750, 750), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    lines = [
        "INDUSTRIAL EQUIPMENT INSPECTION RECORD",
        "Inspection ID: CHK-2026-881",
        "Facility Location: Building 4, North Campus",
        "Equipment Name: Rooftop Chiller Unit #3",
        "Manufacturer: Carrier Commercial HVAC",
        "Inspection Date: 2026-10-25",
        "Inspected By: Lead Technician Carl Jenkins",
        "Refrigerant Pressure: 118 PSI (Within Normal Limits)",
        "Compressor Vibration: 0.12 mm/s (Passed)",
        "Overall Status: Operational / Pass",
        "Next Scheduled Service: 2027-04-25",
    ]
    y = 40
    for l in lines:
        draw.text((50, y), l, fill=(15, 15, 15))
        y += 40
    img.save(os.path.join(OUT_DIR, "doc26_maintenance_inspection.png"))
    save_expected("doc26_maintenance_inspection", "report", {
        "inspection_id": "CHK-2026-881",
        "equipment": "Rooftop Chiller Unit #3",
        "date": "2026-10-25",
        "status": "Operational / Pass",
        "next_service": "2027-04-25",
    })

# -----------------------------------------------------------------------------
# 27. doc27_meeting_minutes_note.pdf (Digital PDF)
# -----------------------------------------------------------------------------
def gen_doc27():
    pdf_path = os.path.join(OUT_DIR, "doc27_meeting_minutes_note.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>EXECUTIVE BOARD MEETING MINUTES</b>", styles['Title']),
        Spacer(1, 10),
        Paragraph("<b>Meeting Date:</b> 2026-11-06", styles['Normal']),
        Paragraph("<b>Time:</b> 10:00 AM - 12:30 PM EST", styles['Normal']),
        Paragraph("<b>Meeting Location:</b> Executive Boardroom A & Virtual Zoom", styles['Normal']),
        Paragraph("<b>Meeting Chair:</b> Douglas Davenport, Chairman", styles['Normal']),
        Paragraph("<b>Attendees Present:</b> Douglas Davenport, Brenda Miller, Carlos Santana, Dr. Julia Chen", styles['Normal']),
        Spacer(1, 10),
        Paragraph("<b>Resolution Passed:</b> Motion to approve Q1 capital expenditure budget of $3,200,000.00 passed unanimously (4-0).", styles['Normal']),
        Paragraph("<b>Next Meeting Date:</b> 2026-12-15", styles['Normal']),
    ]
    doc.build(story)
    save_expected("doc27_meeting_minutes_note", "notes", {
        "meeting_date": "2026-11-06",
        "chair": "Douglas Davenport, Chairman",
        "resolution": "Approve Q1 capital expenditure budget of $3,200,000.00",
        "next_meeting": "2026-12-15",
    })

# -----------------------------------------------------------------------------
# 28. doc28_unknown_astronomy_paper.pdf (Digital PDF - No Schema)
# -----------------------------------------------------------------------------
def gen_doc28():
    pdf_path = os.path.join(OUT_DIR, "doc28_unknown_astronomy_paper.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>SPECTRAL EMISSION MAPPING OF PROTO-STELLAR NEBULA NGC-4819</b>", styles['Title']),
        Spacer(1, 10),
        Paragraph("<b>Preprint Identifier:</b> arXiv:2026.09841v2 [astro-ph.GA]", styles['Normal']),
        Paragraph("<b>Lead Researcher:</b> Dr. Helena Drake, Institute for Astrophysics", styles['Normal']),
        Paragraph("<b>Co-Authors:</b> Liam O'Connor, Kenji Sato", styles['Normal']),
        Paragraph("<b>Telescope Facility:</b> Atacama Large Millimeter Array (ALMA)", styles['Normal']),
        Paragraph("<b>Observation Band:</b> Band 7 Submillimeter (345 GHz)", styles['Normal']),
        Spacer(1, 10),
        Paragraph("<b>Abstract:</b> We report high-resolution interferometric observations of rotational transitions in carbon monoxide isotope CO-13 towards the central core of NGC-4819. Measured gas kinetic temperature is 34.2 Kelvin with column density 4.8e22 cm^-2.", styles['Normal']),
    ]
    doc.build(story)
    save_expected("doc28_unknown_astronomy_paper", "unknown", {
        "paper_title": "Spectral Emission Mapping of Proto-Stellar Nebula NGC-4819",
        "preprint_id": "arXiv:2026.09841v2",
        "lead_researcher": "Dr. Helena Drake",
        "telescope": "Atacama Large Millimeter Array (ALMA)",
        "temperature": "34.2 Kelvin",
    }, notes="Explicitly unknown schema (Astrophysics Preprint)")

# -----------------------------------------------------------------------------
# 29. doc29_unknown_architectural_spec.png (Clean Image - No Schema)
# -----------------------------------------------------------------------------
def gen_doc29():
    img = Image.new("RGB", (800, 750), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    lines = [
        "ARCHITECTURAL STRUCTURAL BLUEPRINT SPECIFICATION",
        "Project Code: BLDG-NORTH-770",
        "Sheet Number: A-104 (Foundation Detail)",
        "Lead Architect: Marcus Sterling, AIA",
        "Structural Engineer Firm: Simpson & Associates PE",
        "Design Load: 120 PSF Floor Live Load",
        "Concrete Compressive Strength: 5,000 PSI at 28 days",
        "Reinforcing Steel: ASTM A615 Grade 60 Rebar",
        "Seismic Design Category: Category D",
        "Date of Release: 2026-10-10",
    ]
    y = 40
    for l in lines:
        draw.text((50, y), l, fill=(15, 15, 15))
        y += 40
    img.save(os.path.join(OUT_DIR, "doc29_unknown_architectural_spec.png"))
    save_expected("doc29_unknown_architectural_spec", "unknown", {
        "project_code": "BLDG-NORTH-770",
        "sheet_number": "A-104",
        "architect": "Marcus Sterling, AIA",
        "concrete_strength": "5,000 PSI",
        "release_date": "2026-10-10",
    }, notes="Explicitly unknown schema (Architectural Blueprint Spec)")

# -----------------------------------------------------------------------------
# 30. doc30_multipage_mixed.pdf (Multi-page PDF with mixed documents: Page 1 Invoice, Page 2 Waybill)
# -----------------------------------------------------------------------------
def gen_doc30():
    from reportlab.platypus import PageBreak
    pdf_path = os.path.join(OUT_DIR, "doc30_multipage_mixed.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>NORTHWEST PARTS WHOLESALE</b>", styles['Title']),
        Paragraph("INVOICE", styles['Heading2']),
        Spacer(1, 10),
        Paragraph("<b>Invoice Number:</b> NWP-99120", styles['Normal']),
        Paragraph("<b>Invoice Date:</b> 2026-11-01", styles['Normal']),
        Paragraph("<b>Customer Name:</b> Cascade Machinery LLC", styles['Normal']),
        Paragraph("<b>Total Amount:</b> $3,450.00", styles['Normal']),
        Spacer(1, 200),
        PageBreak(),
        Paragraph("<b>CASCADE LOGISTICS FREIGHT WAYBILL</b>", styles['Title']),
        Paragraph("DELIVERY RECEIPT & WAYBILL", styles['Heading2']),
        Spacer(1, 10),
        Paragraph("<b>Waybill Tracking:</b> CL-WAYBILL-44019", styles['Normal']),
        Paragraph("<b>Delivery Date:</b> 2026-11-03", styles['Normal']),
        Paragraph("<b>Carrier Name:</b> Cascade Freight Lines", styles['Normal']),
        Paragraph("<b>Receiver Signature:</b> J. Miller", styles['Normal']),
        Paragraph("<b>Package Count:</b> 4 Wooden Crates", styles['Normal']),
    ]
    doc.build(story)
    save_expected("doc30_multipage_mixed", "multi_document", {
        "page1_invoice_number": "NWP-99120",
        "page1_total_amount": "$3,450.00",
        "page2_waybill_tracking": "CL-WAYBILL-44019",
        "page2_delivery_date": "2026-11-03",
    }, notes="Multi-page file containing Invoice on Page 1 and Delivery Waybill on Page 2")

# Run all 30 generators
gen_doc01()
gen_doc02()
gen_doc03()
gen_doc04()
gen_doc05()
gen_doc06()
gen_doc07()
gen_doc08()
gen_doc09()
gen_doc10()
gen_doc11()
gen_doc12()
gen_doc13()
gen_doc14()
gen_doc15()
gen_doc16()
gen_doc17()
gen_doc18()
gen_doc19()
gen_doc20()
gen_doc21()
gen_doc22()
gen_doc23()
gen_doc24()
gen_doc25()
gen_doc26()
gen_doc27()
gen_doc28()
gen_doc29()
gen_doc30()

print("Generated 30 documents and 30 paired expected.json files successfully.")
