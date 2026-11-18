"""Generator V3: Independent Blind Template Generator for Final Holdout 4 Evaluation.

Specifications:
- Seed: 20261125
- 9 Classes x 40 docs = 360 total documents in data/dataset/holdout4/
- 5 completely distinct layouts per class with varied label phrasing and field ordering
- Pure 300 DPI rasterized scans (zero embedded text layer, 100% OCR through Tesseract)
- Visual degradations: skew, Gaussian noise, blur, fax binarization, stamps
- Format-based PII: EIN (XX-XXXXXXX), SSN (XXX-XX-XXXX), IBAN, Passport, MD License, National ID
- Hard Negatives: Price quotes vs invoices, internal requisitions vs POs, letters discussing invoices, corporate lookalikes
- Zero ghost PII: ground truth entities strictly reflect rendered document text
"""

import hashlib
import json
import os
from pathlib import Path
import random
from typing import Any, Dict, List, Tuple

import cv2
from faker import Faker
import fitz
import numpy as np

SEED = 20261125
fake = Faker()
Faker.seed(SEED)
random.seed(SEED)
np.random.seed(SEED)

CLASSES = [
    "invoice", "contract", "kyc_form", "bank_statement",
    "medical_report", "purchase_order", "letter", "claim_form", "unknown"
]

DOCS_PER_CLASS = 40

BASE_DIR = Path(__file__).resolve().parent
HOLDOUT4_DIR = BASE_DIR / "dataset" / "holdout4"
HOLDOUT4_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Visual Degradations & 300 DPI Scan Rendering
# ---------------------------------------------------------------------------

def apply_image_degradations(img_np: np.ndarray, degradation_type: str) -> np.ndarray:
    h, w = img_np.shape[:2]
    if degradation_type == "skew":
        angle = random.choice([-2.0, -1.2, 1.2, 2.0])
        m = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
        return cv2.warpAffine(img_np, m, (w, h), borderValue=(255, 255, 255))
    elif degradation_type == "noise":
        noise = np.random.normal(0, 8, img_np.shape).astype(np.int16)
        return np.clip(img_np.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    elif degradation_type == "blur":
        return cv2.GaussianBlur(img_np, (3, 3), 0.7)
    elif degradation_type == "fax_binarization":
        gray = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)
        _, binarized = cv2.threshold(gray, 190, 255, cv2.THRESH_BINARY)
        return cv2.cvtColor(binarized, cv2.COLOR_GRAY2BGR)
    elif degradation_type == "stamp":
        stamp_text = random.choice(["VERIFIED", "ARCHIVED", "ENTERED", "CONFIRMED"])
        cv2.putText(img_np, stamp_text, (w // 3, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 190), 3, cv2.LINE_AA)
        return img_np
    return img_np


def render_scanned_pdf(text: str, degradation_type: str = "none") -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    lines = text.split("\n")
    y = 50
    for line in lines[:48]:
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

    _, img_encoded = cv2.imencode(".jpg", img_np, [int(cv2.IMWRITE_JPEG_QUALITY), 90])

    scanned_doc = fitz.open()
    scanned_page = scanned_doc.new_page(width=595, height=842)
    scanned_page.insert_image(scanned_page.rect, stream=img_encoded.tobytes())
    pdf_bytes = scanned_doc.tobytes()
    scanned_doc.close()
    return pdf_bytes


# ---------------------------------------------------------------------------
# Template Generators (5 Layouts per Class)
# ---------------------------------------------------------------------------

def gen_invoice_v3(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 5
    inv_num = f"INV-2028{idx:04d}"
    inv_date = fake.date_between(start_date="-1y", end_date="today").isoformat()
    amount = round(random.uniform(250.0, 35000.0), 2)
    vendor = fake.company()
    ein = f"{random.randint(10, 99)}-{random.randint(1000000, 9999999)}"
    client = fake.name()
    phone = fake.phone_number()

    if layout == 0:
        text = (
            f"COMMERCIAL BILLING DISBURSEMENT NOTICE\n"
            f"============================================================\n"
            f"Bill Reference Code: {inv_num}\n"
            f"Date of Bill: {inv_date}\n"
            f"Issuing Entity: {vendor}\n"
            f"Federal Taxpayer ID: {ein}\n"
            f"Recipient: {client}\n"
            f"Direct Contact: {phone}\n"
            f"------------------------------------------------------------\n"
            f"Professional Technical Deliverables\n"
            f"Aggregate Net Payable: ${amount:.2f}\n"
            f"Remittance required within statutory period.\n"
        )
    elif layout == 1:
        text = (
            f"ENTERPRISE SERVICES INVOICE STATEMENT\n"
            f"Vendor Organization: {vendor}\n"
            f"Corporate EIN: {ein}\n"
            f"Invoice Tracking #: {inv_num}\n"
            f"Statement Issue Date: {inv_date}\n"
            f"Billed Account Party: {client}\n"
            f"Customer Care Hotline: {phone}\n"
            f"------------------------------------------------------------\n"
            f"Cloud Hosting and Architecture Services\n"
            f"Final Gross Total: ${amount:.2f}\n"
        )
    elif layout == 2:
        text = (
            f"STATEMENT OF ACCOUNT AND CHARGES\n"
            f"Doc ID: {inv_num} | Issued: {inv_date}\n"
            f"Supplier Name: {vendor}\n"
            f"Taxpayer EIN: {ein}\n"
            f"Client Name: {client}\n"
            f"Contact Number: {phone}\n"
            f"Itemized Professional Advisory\n"
            f"Total Amount Due: ${amount:.2f}\n"
            f"Please transfer funds via ACH transfer.\n"
        )
    elif layout == 3:
        text = (
            f"OFFICIAL TAX INVOICE\n"
            f"============================================================\n"
            f"Billed By: {vendor}\n"
            f"Supplier Tax ID: {ein}\n"
            f"Invoice Serial: {inv_num}\n"
            f"Creation Date: {inv_date}\n"
            f"Attention: {client}\n"
            f"Telephone: {phone}\n"
            f"Total Due: ${amount:.2f}\n"
            f"All payments are subject to corporate audit.\n"
        )
    else:
        text = (
            f"PAYMENT DEMAND AND INVOICE VOUCHER\n"
            f"Invoice Number: {inv_num}\n"
            f"Posting Date: {inv_date}\n"
            f"Creditor Entity: {vendor}\n"
            f"Business EIN: {ein}\n"
            f"Debtor Name: {client}\n"
            f"Debtor Phone: {phone}\n"
            f"Total Payable: ${amount:.2f}\n"
            f"Terms: Immediate settlement upon presentation.\n"
        )

    fields = {
        "invoice_number": inv_num,
        "invoice_date": inv_date,
        "total_amount": amount,
        "vendor_name": vendor,
    }
    pii = [
        {"type": "US_EIN", "value": ein, "sensitivity": "medium"},
        {"type": "PERSON", "value": client, "sensitivity": "medium"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
    ]
    return text, fields, pii


def gen_contract_v3(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 5
    cid = f"CNT-2028{idx:04d}"
    eff_date = fake.date_between(start_date="-2y", end_date="today").isoformat()
    p1 = fake.company()
    p2 = fake.company()
    exec_name = fake.name()
    ssn = f"{random.randint(100, 999)}-{random.randint(10, 99)}-{random.randint(1000, 9999)}"
    phone = fake.phone_number()

    if layout == 0:
        text = (
            f"BINDING COMMERCIAL ACCORD AND CONTRACT\n"
            f"============================================================\n"
            f"Contract Identifier: {cid}\n"
            f"Execution Date: {eff_date}\n"
            f"Contracting Party 1: {p1}\n"
            f"Contracting Party 2: {p2}\n"
            f"Signatory Officer: {exec_name}\n"
            f"Officer SSN: {ssn}\n"
            f"Direct Phone: {phone}\n"
            f"This contract establishes bilateral obligations under legal authority.\n"
        )
    elif layout == 1:
        text = (
            f"SERVICE LEVEL AND PARTNERSHIP COVENANT\n"
            f"Agreement Code: {cid} | Effective: {eff_date}\n"
            f"Primary Organization: {p1}\n"
            f"Secondary Organization: {p2}\n"
            f"Authorized Representative: {exec_name}\n"
            f"National SSN: {ssn}\n"
            f"Contact Number: {phone}\n"
            f"Both entities mutually assent to the terms stipulated herein.\n"
        )
    elif layout == 2:
        text = (
            f"MASTER ENGAGEMENT AGREEMENT\n"
            f"Contract Number: {cid}\n"
            f"Date of Signing: {eff_date}\n"
            f"Parties to Agreement: {p1} and {p2}\n"
            f"Corporate Representative: {exec_name}\n"
            f"Executive SSN: {ssn}\n"
            f"Phone: {phone}\n"
            f"The covenant herein shall remain binding upon all assigns.\n"
        )
    elif layout == 3:
        text = (
            f"STRATEGIC ALLIANCE CONTRACT\n"
            f"Contract ID: {cid}\n"
            f"Effective Date: {eff_date}\n"
            f"First Entity: {p1}\n"
            f"Second Entity: {p2}\n"
            f"Signatory Name: {exec_name}\n"
            f"Social Security Number: {ssn}\n"
            f"Direct Tel: {phone}\n"
            f"Executed in multiple counterparts with full legal force.\n"
        )
    else:
        text = (
            f"ENTERPRISE VENDOR MASTER COVENANT\n"
            f"Document Reference: {cid}\n"
            f"Commencement Date: {eff_date}\n"
            f"Party One: {p1}\n"
            f"Party Two: {p2}\n"
            f"Attesting Officer: {exec_name}\n"
            f"Officer Taxpayer SSN: {ssn}\n"
            f"Office Phone: {phone}\n"
            f"All covenants and stipulations are governed by state jurisprudence.\n"
        )

    fields = {
        "contract_id": cid,
        "effective_date": eff_date,
        "party_one": p1,
        "party_two": p2,
    }
    pii = [
        {"type": "US_SSN", "value": ssn, "sensitivity": "high"},
        {"type": "PERSON", "value": exec_name, "sensitivity": "medium"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
    ]
    return text, fields, pii


def gen_kyc_v3(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 5
    name = fake.name()
    dob = fake.date_of_birth(minimum_age=21, maximum_age=72).isoformat()
    passport_num = f"{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}{random.randint(10000000, 99999999)}"
    phone = fake.phone_number()
    email_addr = fake.safe_email()
    country = fake.country()

    if layout == 0:
        text = (
            f"CUSTOMER VERIFICATION AND IDENTITY REPORT\n"
            f"============================================================\n"
            f"Subject Legal Name: {name}\n"
            f"Date of Birth: {dob}\n"
            f"Passport Number: {passport_num}\n"
            f"Country of Citizenship: {country}\n"
            f"Registered Telephone: {phone}\n"
            f"Electronic Mail: {email_addr}\n"
            f"Anti-Money Laundering and KYC screening complete.\n"
        )
    elif layout == 1:
        text = (
            f"CLIENT IDENTIFICATION DOSSIER\n"
            f"Applicant Name: {name}\n"
            f"Birthdate (DOB): {dob}\n"
            f"Travel Document / Passport: {passport_num}\n"
            f"Nationality: {country}\n"
            f"Phone Contact: {phone}\n"
            f"Email Address: {email_addr}\n"
            f"Identity verified against authoritative international databases.\n"
        )
    elif layout == 2:
        text = (
            f"INDIVIDUAL DUE DILIGENCE ATTESTATION\n"
            f"Individual Name: {name}\n"
            f"Date of Birth (DOB): {dob}\n"
            f"Passport Reference: {passport_num}\n"
            f"Nationality: {country}\n"
            f"Telephone: {phone}\n"
            f"Email: {email_addr}\n"
            f"Attestation performed under Bank Secrecy Act requirements.\n"
        )
    elif layout == 3:
        text = (
            f"BENEFICIAL OWNER IDENTITY DECLARATION\n"
            f"============================================================\n"
            f"Full Name: {name}\n"
            f"Birth Date: {dob}\n"
            f"Passport ID: {passport_num}\n"
            f"Citizenship: {country}\n"
            f"Mobile Hotline: {phone}\n"
            f"Email Address: {email_addr}\n"
            f"KYC status confirmed by institutional compliance team.\n"
        )
    else:
        text = (
            f"PERSONAL BIODATA VERIFICATION VOUCHER\n"
            f"Customer Name: {name}\n"
            f"Date of Birth: {dob}\n"
            f"Passport Serial: {passport_num}\n"
            f"Country: {country}\n"
            f"Phone: {phone}\n"
            f"Email Address: {email_addr}\n"
            f"Customer passed regulatory onboarding checks.\n"
        )

    fields = {
        "customer_name": name,
        "date_of_birth": dob,
        "id_number": passport_num,
        "nationality": country,
    }
    pii = [
        {"type": "PERSON", "value": name, "sensitivity": "medium"},
        {"type": "PASSPORT", "value": passport_num, "sensitivity": "high"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
        {"type": "EMAIL_ADDRESS", "value": email_addr, "sensitivity": "low"},
    ]
    return text, fields, pii


def gen_bank_statement_v3(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 5
    acct = f"{random.randint(1000000000, 9999999999)}"
    holder = fake.name()
    iban = f"US20ABCD{random.randint(1000000000000000, 9999999999999999)}"
    p_start = fake.date_between(start_date="-180d", end_date="-30d").isoformat()
    p_end = fake.date_between(start_date="-30d", end_date="today").isoformat()
    period = f"{p_start} to {p_end}"
    open_bal = round(random.uniform(1000.0, 50000.0), 2)
    close_bal = round(open_bal + random.uniform(-4000.0, 15000.0), 2)
    phone = fake.phone_number()

    if layout == 0:
        text = (
            f"MONTHLY TREASURY FINANCIAL REPORT\n"
            f"============================================================\n"
            f"Account Holder: {holder}\n"
            f"Account Number: {acct}\n"
            f"Clearing IBAN: {iban}\n"
            f"Reporting Period: {period}\n"
            f"Customer Service Hotline: {phone}\n"
            f"Opening Ledger Balance: ${open_bal:.2f}\n"
            f"Closing Ledger Balance: ${close_bal:.2f}\n"
            f"All entries audited under federal banking regulations.\n"
        )
    elif layout == 1:
        text = (
            f"INSTITUTIONAL ACCOUNT STATEMENT\n"
            f"Primary Depositor: {holder}\n"
            f"Account Identifier: {acct}\n"
            f"Wire Transfer IBAN: {iban}\n"
            f"Statement Interval: {period}\n"
            f"Support Line: {phone}\n"
            f"Opening Balance: ${open_bal:.2f}\n"
            f"Ending Settlement Balance: ${close_bal:.2f}\n"
        )
    elif layout == 2:
        text = (
            f"COMMERCIAL BANKING ACTIVITY SUMMARY\n"
            f"Client Name: {holder}\n"
            f"Account ID: {acct}\n"
            f"International IBAN: {iban}\n"
            f"Cycle Period: {period}\n"
            f"Telephone: {phone}\n"
            f"Starting Balance: ${open_bal:.2f}\n"
            f"Final Balance: ${close_bal:.2f}\n"
        )
    elif layout == 3:
        text = (
            f"TREASURY LEDGER BALANCE SHEET\n"
            f"Account Owner: {holder}\n"
            f"Bank Account #: {acct}\n"
            f"Routing IBAN: {iban}\n"
            f"Audit Period: {period}\n"
            f"Direct Tel: {phone}\n"
            f"Initial Balance: ${open_bal:.2f}\n"
            f"Closing Balance: ${close_bal:.2f}\n"
        )
    else:
        text = (
            f"CONSOLIDATED DEPOSIT ACCOUNT STATEMENT\n"
            f"Beneficiary: {holder}\n"
            f"Account Number: {acct}\n"
            f"Wire IBAN: {iban}\n"
            f"Billing Period: {period}\n"
            f"Service Phone: {phone}\n"
            f"Starting Cycle Balance: ${open_bal:.2f}\n"
            f"Closing Statement Balance: ${close_bal:.2f}\n"
        )

    fields = {
        "account_number": acct,
        "statement_period": period,
        "opening_balance": open_bal,
        "closing_balance": close_bal,
    }
    pii = [
        {"type": "PERSON", "value": holder, "sensitivity": "medium"},
        {"type": "IBAN_CODE", "value": iban, "sensitivity": "high"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
    ]
    return text, fields, pii


def gen_medical_report_v3(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 5
    pid = f"PT-2028{idx:04d}"
    patient = fake.name()
    doc_name = f"Dr. {fake.first_name()} {fake.last_name()}"
    med_lic = f"MD-{random.randint(100000, 999999)}"
    r_date = fake.date_between(start_date="-1y", end_date="today").isoformat()
    phone = fake.phone_number()

    diagnoses = [
        "Acute viral rhinopharyngitis with secondary rhinitis",
        "Primary essential hypertension requiring ACE inhibitor monitoring",
        "Post-traumatic cervical strain with localized radiculopathy",
        "Type II diabetes mellitus with peripheral neuropathic indications",
        "Subacute bacterial bronchitis undergoing antibiotic course",
    ]
    diag = diagnoses[idx % len(diagnoses)]

    if layout == 0:
        text = (
            f"CLINICAL CONSULTATION AND DIAGNOSTIC RECORD\n"
            f"============================================================\n"
            f"Patient Legal Name: {patient}\n"
            f"Patient ID: {pid}\n"
            f"Attending Doctor: {doc_name}\n"
            f"Physician License: {med_lic}\n"
            f"Date of Examination: {r_date}\n"
            f"Clinic Telephone: {phone}\n"
            f"Diagnostic Assessment: {diag}\n"
            f"Patient instructed to adhere to conservative outpatient therapy.\n"
        )
    elif layout == 1:
        text = (
            f"HOSPITAL ENCOUNTER SUMMARY\n"
            f"Patient Name: {patient}\n"
            f"Medical Record Code: {pid}\n"
            f"Primary Clinician: {doc_name}\n"
            f"Medical License: {med_lic}\n"
            f"Consultation Date: {r_date}\n"
            f"Phone Hotline: {phone}\n"
            f"Clinical Diagnosis: {diag}\n"
        )
    elif layout == 2:
        text = (
            f"PHYSICIAN EVALUATION AND PROGRESS NOTES\n"
            f"Patient: {patient}\n"
            f"Patient Chart #: {pid}\n"
            f"Lead Doctor: {doc_name}\n"
            f"Medical Lic: {med_lic}\n"
            f"Report Date: {r_date}\n"
            f"Contact Number: {phone}\n"
            f"Medical Diagnosis: {diag}\n"
        )
    elif layout == 3:
        text = (
            f"MEDICAL OUTPATIENT ASSESSMENT MEMO\n"
            f"Patient Name: {patient}\n"
            f"Patient Identifier: {pid}\n"
            f"Consulting Physician: {doc_name}\n"
            f"State License: {med_lic}\n"
            f"Exam Date: {r_date}\n"
            f"Telephone: {phone}\n"
            f"Primary Assessment / Diagnosis: {diag}\n"
        )
    else:
        text = (
            f"DIAGNOSTIC CONSULTATION DISCHARGE VOUCHER\n"
            f"Individual Name: {patient}\n"
            f"Patient MRN: {pid}\n"
            f"Attending Doctor: {doc_name}\n"
            f"Doctor License #: {med_lic}\n"
            f"Record Date: {r_date}\n"
            f"Emergency Phone: {phone}\n"
            f"Findings / Clinical Diagnosis: {diag}\n"
        )

    fields = {
        "patient_id": pid,
        "diagnosis": diag,
        "doctor_name": doc_name,
        "report_date": r_date,
    }
    pii = [
        {"type": "PERSON", "value": patient, "sensitivity": "medium"},
        {"type": "MEDICAL_LICENSE", "value": med_lic, "sensitivity": "medium"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
    ]
    return text, fields, pii


def gen_purchase_order_v3(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 5
    ponum = f"PO-2028{idx:04d}"
    podate = fake.date_between(start_date="-1y", end_date="today").isoformat()
    vendor = fake.company()
    buyer = fake.name()
    amount = round(random.uniform(500.0, 48000.0), 2)
    phone = fake.phone_number()

    if layout == 0:
        text = (
            f"OFFICIAL PROCUREMENT PURCHASE ORDER\n"
            f"============================================================\n"
            f"Purchase Order Code: {ponum}\n"
            f"Issue Date: {podate}\n"
            f"Authorized Vendor: {vendor}\n"
            f"Procurement Officer: {buyer}\n"
            f"Buyer Telephone: {phone}\n"
            f"------------------------------------------------------------\n"
            f"Authorized Order Total: ${amount:.2f}\n"
            f"Goods must conform to technical specifications upon delivery.\n"
        )
    elif layout == 1:
        text = (
            f"AUTHORIZED PURCHASE AUTHORIZATION VOUCHER\n"
            f"PO Number: {ponum}\n"
            f"Order Issue Date: {podate}\n"
            f"Designated Supplier: {vendor}\n"
            f"Purchasing Agent: {buyer}\n"
            f"Contact Hotline: {phone}\n"
            f"Total Expenditure: ${amount:.2f}\n"
        )
    elif layout == 2:
        text = (
            f"EXTERNAL SUPPLY PURCHASE ORDER\n"
            f"Order Reference: {ponum} | Date: {podate}\n"
            f"Supplier Name: {vendor}\n"
            f"Approving Buyer: {buyer}\n"
            f"Phone: {phone}\n"
            f"Order Total: ${amount:.2f}\n"
        )
    elif layout == 3:
        text = (
            f"COMMERCIAL PROCUREMENT CONTRACT ORDER\n"
            f"PO Identifier: {ponum}\n"
            f"Order Date: {podate}\n"
            f"Vendor Organization: {vendor}\n"
            f"Purchasing Contact: {buyer}\n"
            f"Buyer Direct Tel: {phone}\n"
            f"Authorized Total: ${amount:.2f}\n"
        )
    else:
        text = (
            f"ENTERPRISE INVENTORY ACQUISITION PO\n"
            f"Purchase Order Tracking: {ponum}\n"
            f"Date of PO: {podate}\n"
            f"Vendor: {vendor}\n"
            f"Requisitioned By: {buyer}\n"
            f"Telephone: {phone}\n"
            f"Total Authorized Sum: ${amount:.2f}\n"
        )

    fields = {
        "po_number": ponum,
        "po_date": podate,
        "vendor_name": vendor,
        "order_total": amount,
    }
    pii = [
        {"type": "PERSON", "value": buyer, "sensitivity": "medium"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
    ]
    return text, fields, pii


def gen_letter_v3(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 5
    sender = fake.company()
    recipient = fake.name()
    ldate = fake.date_between(start_date="-1y", end_date="today").isoformat()
    phone = fake.phone_number()
    email_addr = fake.safe_email()

    subjects = [
        "Executive Notification Concerning Annual Corporate Restructuring",
        "Formal Clarification on Operational Policy Revisions",
        "Official Governance Advisory on Risk and Compliance",
        "Notice Regarding Institutional Stakeholder Proceedings",
        "Confirmation of Regulatory Audit and Oversight Findings",
    ]
    subj = subjects[idx % len(subjects)]

    if layout == 0:
        text = (
            f"FORMAL EXECUTIVE CORRESPONDENCE\n"
            f"============================================================\n"
            f"From: {sender}\n"
            f"To: {recipient}\n"
            f"Date: {ldate}\n"
            f"Subject: {subj}\n"
            f"Sender Telephone: {phone}\n"
            f"Sender Email: {email_addr}\n"
            f"\n"
            f"Dear {recipient},\n"
            f"We are writing to officially present you with this notification.\n"
            f"Please file this letter in your records.\n"
            f"Sincerely,\n"
            f"Executive Management Office\n"
            f"{sender}\n"
        )
    elif layout == 1:
        text = (
            f"INSTITUTIONAL MEMORANDUM OF CORRESPONDENCE\n"
            f"Originating Sender: {sender}\n"
            f"Addressee Recipient: {recipient}\n"
            f"Date of Letter: {ldate}\n"
            f"Regarding Topic: {subj}\n"
            f"Phone Hotline: {phone}\n"
            f"Email Address: {email_addr}\n"
            f"\n"
            f"Attention: {recipient}\n"
            f"Please be advised of our official enterprise memorandum.\n"
            f"Warm regards,\n"
            f"Corporate Secretarial Directorate\n"
        )
    elif layout == 2:
        text = (
            f"COMMUNICATION MEMO AND NOTICE\n"
            f"Sender Organization: {sender}\n"
            f"Recipient Party: {recipient}\n"
            f"Letter Date: {ldate}\n"
            f"Subject Matter: {subj}\n"
            f"Direct Telephone: {phone}\n"
            f"Email: {email_addr}\n"
            f"\n"
            f"Dear Stakeholder,\n"
            f"This letter provides formal documentation for audit purposes.\n"
            f"Sincerely,\n"
            f"Governance Directorate\n"
        )
    elif layout == 3:
        text = (
            f"OFFICIAL ADMINISTRATIVE NOTICE\n"
            f"Sender: {sender}\n"
            f"Recipient: {recipient}\n"
            f"Posting Date: {ldate}\n"
            f"Subject: {subj}\n"
            f"Telephone: {phone}\n"
            f"Email Address: {email_addr}\n"
            f"\n"
            f"Dear {recipient},\n"
            f"We write to provide administrative confirmation regarding your inquiry.\n"
            f"Best regards,\n"
            f"Administrative Office\n"
        )
    else:
        text = (
            f"FORMAL NOTICE OF EXECUTIVE PROCEEDINGS\n"
            f"Originator: {sender}\n"
            f"Addressed To: {recipient}\n"
            f"Date of Memo: {ldate}\n"
            f"Subject Reference: {subj}\n"
            f"Contact Phone: {phone}\n"
            f"Contact Email: {email_addr}\n"
            f"\n"
            f"Dear {recipient},\n"
            f"Please review the attached executive resolution at your earliest convenience.\n"
            f"Sincerely,\n"
            f"Executive Governance Committee\n"
        )

    fields = {
        "sender": sender,
        "recipient": recipient,
        "letter_date": ldate,
        "subject": subj,
    }
    pii = [
        {"type": "PERSON", "value": recipient, "sensitivity": "medium"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
        {"type": "EMAIL_ADDRESS", "value": email_addr, "sensitivity": "low"},
    ]
    return text, fields, pii


def gen_claim_form_v3(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 5
    cid = f"CLM-2028{idx:04d}"
    claimant = fake.name()
    idate = fake.date_between(start_date="-1y", end_date="today").isoformat()
    amount = round(random.uniform(350.0, 32000.0), 2)
    phone = fake.phone_number()
    email_addr = fake.safe_email()

    if layout == 0:
        text = (
            f"INSURANCE INDEMNITY CLAIM FORM\n"
            f"============================================================\n"
            f"Claim Reference Code: {cid}\n"
            f"Claimant Legal Name: {claimant}\n"
            f"Date of Loss: {idate}\n"
            f"Claimant Telephone: {phone}\n"
            f"Claimant Email: {email_addr}\n"
            f"------------------------------------------------------------\n"
            f"Total Claim Amount: ${amount:.2f}\n"
            f"Claimant certifies all losses reported are accurate.\n"
        )
    elif layout == 1:
        text = (
            f"CASUALTY AND LOSS CLAIM REPORT\n"
            f"Claim Tracking Number: {cid}\n"
            f"Policyholder / Claimant: {claimant}\n"
            f"Incident Date: {idate}\n"
            f"Contact Number: {phone}\n"
            f"Email Address: {email_addr}\n"
            f"Claimed Damages Sum: ${amount:.2f}\n"
        )
    elif layout == 2:
        text = (
            f"PROPERTY DAMAGE CLAIM ATTESTATION\n"
            f"Claim ID: {cid} | Date of Incident: {idate}\n"
            f"Claimant Name: {claimant}\n"
            f"Phone: {phone}\n"
            f"Email: {email_addr}\n"
            f"Claim Amount: ${amount:.2f}\n"
        )
    elif layout == 3:
        text = (
            f"POLICY DISBURSEMENT DEMAND AND CLAIM\n"
            f"Claim Identifier: {cid}\n"
            f"Claimant: {claimant}\n"
            f"Date of Occurrence: {idate}\n"
            f"Direct Tel: {phone}\n"
            f"Email Address: {email_addr}\n"
            f"Requested Amount: ${amount:.2f}\n"
        )
    else:
        text = (
            f"UNDERWRITING LOSS SETTLEMENT PETITION\n"
            f"Claim Reference: {cid}\n"
            f"Loss Incurred Date: {idate}\n"
            f"Claimant Full Name: {claimant}\n"
            f"Telephone: {phone}\n"
            f"Email: {email_addr}\n"
            f"Loss Claim Amount: ${amount:.2f}\n"
        )

    fields = {
        "claim_id": cid,
        "claimant_name": claimant,
        "incident_date": idate,
        "claim_amount": amount,
    }
    pii = [
        {"type": "PERSON", "value": claimant, "sensitivity": "medium"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
        {"type": "EMAIL_ADDRESS", "value": email_addr, "sensitivity": "low"},
    ]
    return text, fields, pii


def gen_unknown_hard_negatives_v3(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    sub_type = idx % 4
    phone = fake.phone_number()
    client = fake.name()
    company = fake.company()
    dt = fake.date_between(start_date="-1y", end_date="today").isoformat()

    if sub_type == 0:
        # Hard Negative: Formal Price Quotation (looks like invoice)
        q_num = f"QUO-2028{idx:04d}"
        q_amt = round(random.uniform(500.0, 15000.0), 2)
        text = (
            f"FORMAL COMMERCIAL PRICE ESTIMATE AND QUOTATION\n"
            f"============================================================\n"
            f"Quotation Reference: {q_num}\n"
            f"Date of Quotation: {dt}\n"
            f"Vendor Organization: {company}\n"
            f"Prospective Client: {client}\n"
            f"Telephone: {phone}\n"
            f"------------------------------------------------------------\n"
            f"THIS IS NOT AN INVOICE. NO MONIES ARE PRESENTLY DUE.\n"
            f"Estimated Advisory Scope: ${q_amt:.2f}\n"
            f"Prices valid for 30 calendar days from quotation date.\n"
        )
    elif sub_type == 1:
        # Hard Negative: Internal Purchase Requisition (looks like PO)
        req_num = f"REQ-2028{idx:04d}"
        req_amt = round(random.uniform(1000.0, 20000.0), 2)
        text = (
            f"INTERNAL PROCUREMENT PURCHASE REQUISITION\n"
            f"============================================================\n"
            f"Internal Requisition #: {req_num}\n"
            f"Requisition Date: {dt}\n"
            f"Proposed Vendor: {company}\n"
            f"Requesting Employee: {client}\n"
            f"Contact Tel: {phone}\n"
            f"------------------------------------------------------------\n"
            f"INTERNAL REQUISITION REQUEST ONLY - DO NOT SHIP GOODS.\n"
            f"THIS IS NOT A VALIDATED PURCHASE ORDER.\n"
            f"Estimated Budget Authorization: ${req_amt:.2f}\n"
        )
    elif sub_type == 2:
        # Hard Negative: Letter Discussing Invoice (letter mentioning invoice terms)
        ref_inv = f"INV-2027{random.randint(1000, 9999)}"
        text = (
            f"CORRESPONDENCE INQUIRY REGARDING BILLING AUDIT\n"
            f"============================================================\n"
            f"Originating Entity: {company}\n"
            f"Addressed To: {client}\n"
            f"Correspondence Date: {dt}\n"
            f"Subject: Inquiring about past invoice {ref_inv}\n"
            f"Direct Phone: {phone}\n"
            f"\n"
            f"Dear {client},\n"
            f"We are writing this letter to follow up on the status of our billing audit.\n"
            f"Although invoice number {ref_inv} was discussed during our meeting,\n"
            f"this communication is an informal letter inquiry, NOT an invoice.\n"
            f"Do not remit payment against this correspondence.\n"
            f"Sincerely,\n"
            f"Billing Inquiries Team\n"
        )
    else:
        # Hard Negative: Corporate Meeting Minutes / Lookalike
        text = (
            f"QUARTERLY COMPLIANCE REVIEW AND GOVERNANCE MINUTES\n"
            f"============================================================\n"
            f"Convening Enterprise: {company}\n"
            f"Presiding Chair: {client}\n"
            f"Session Date: {dt}\n"
            f"Contact Secretary Tel: {phone}\n"
            f"------------------------------------------------------------\n"
            f"The governance committee met to review annual regulatory disclosures.\n"
            f"All operational teams certified full adherence to corporate bylaws.\n"
            f"Meeting adjourned with no dissenting motions recorded.\n"
        )

    fields = {}
    pii = [
        {"type": "PERSON", "value": client, "sensitivity": "medium"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
    ]
    return text, fields, pii


GENERATORS = {
    "invoice": gen_invoice_v3,
    "contract": gen_contract_v3,
    "kyc_form": gen_kyc_v3,
    "bank_statement": gen_bank_statement_v3,
    "medical_report": gen_medical_report_v3,
    "purchase_order": gen_purchase_order_v3,
    "letter": gen_letter_v3,
    "claim_form": gen_claim_form_v3,
    "unknown": gen_unknown_hard_negatives_v3,
}

DEGRADATIONS = ["skew", "noise", "blur", "fax_binarization", "stamp", "none"]


def generate_holdout4_dataset():
    print("=" * 80, flush=True)
    print("GENERATING BLIND HOLDOUT 4 DATASET (Seed 20261125)", flush=True)
    print("=" * 80, flush=True)
    print(f"Target Directory: {HOLDOUT4_DIR}")
    print(f"9 Classes x {DOCS_PER_CLASS} docs = {len(CLASSES) * DOCS_PER_CLASS} total documents")
    print("Rendering mode: Pure 300 DPI rasterized scans with no embedded text layer\n", flush=True)

    manifest = []
    total_docs = len(CLASSES) * DOCS_PER_CLASS
    doc_counter = 0

    for cls in CLASSES:
        gen_fn = GENERATORS[cls]
        for i in range(1, DOCS_PER_CLASS + 1):
            doc_counter += 1
            did = f"h4_{cls}_{i:04d}"
            deg = DEGRADATIONS[(doc_counter + i) % len(DEGRADATIONS)]

            text, fields, pii_entities = gen_fn(i)
            pdf_bytes = render_scanned_pdf(text, deg)
            sha256 = hashlib.sha256(pdf_bytes).hexdigest()

            pdf_file = HOLDOUT4_DIR / f"{did}.pdf"
            with open(pdf_file, "wb") as pf:
                pf.write(pdf_bytes)

            meta = {
                "doc_id": did,
                "doc_type": cls,
                "sha256": sha256,
                "split": "holdout4",
                "degradation": deg,
                "fields": fields,
                "pii_entities": pii_entities,
                "file_name": f"{did}.pdf",
                "full_text": text,
            }

            json_file = HOLDOUT4_DIR / f"{did}.json"
            with open(json_file, "w", encoding="utf-8") as jf:
                json.dump(meta, jf, indent=2)

            manifest.append(meta)

            if doc_counter % 45 == 0 or doc_counter == total_docs:
                print(f"  Generated {doc_counter:3d}/{total_docs} Holdout 4 assets (Class: {cls:<16})...", flush=True)

    manifest_file = HOLDOUT4_DIR / "manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as mf:
        json.dump(manifest, mf, indent=2)

    print(f"\nHoldout 4 generation complete: {len(manifest)} documents generated successfully at {HOLDOUT4_DIR}.\n", flush=True)


if __name__ == "__main__":
    generate_holdout4_dataset()
