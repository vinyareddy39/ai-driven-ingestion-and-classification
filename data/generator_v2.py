"""Generator V2: Independent Template Generator for Holdout 3 Evaluation.

Designed with completely distinct layout structures, field orderings, and vocabulary
synonyms to eliminate circularity between the original synthetic generator and extractor.
Evaluates model generalization and hard negative robustness.

Specifications:
- Seed: 20261120
- 9 Classes x 40 docs = 360 total documents
- Pure 300 DPI rasterized scans (zero embedded text layer)
- Realistic degradations: skew, noise, blur, fax binarization, rubber stamps
- Format-based PII: EIN (XX-XXXXXXX), SSN (XXX-XX-XXXX), IBAN, Passport, MD License
- Proven Hard Negatives (10 Quotes, 10 PO Requisitions, 10 Letters mentioning invoices, 10 Lookalikes)
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

SEED = 20261120
fake = Faker()
Faker.seed(SEED)
random.seed(SEED)
np.random.seed(SEED)

CLASSES = [
    "invoice",
    "contract",
    "kyc_form",
    "bank_statement",
    "medical_report",
    "purchase_order",
    "letter",
    "claim_form",
    "unknown",
]

DOCS_PER_CLASS = 40

BASE_DIR = Path(__file__).resolve().parent
HOLDOUT3_DIR = BASE_DIR / "dataset" / "holdout3"
HOLDOUT3_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Visual Degradations & 300 DPI Scan Rendering
# ---------------------------------------------------------------------------

def apply_image_degradations(img_np: np.ndarray, degradation_type: str) -> np.ndarray:
    h, w = img_np.shape[:2]
    if degradation_type == "skew":
        angle = random.choice([-2.0, -1.5, 1.5, 2.0])
        m = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
        return cv2.warpAffine(img_np, m, (w, h), borderValue=(255, 255, 255))
    elif degradation_type == "noise":
        noise = np.random.normal(0, 10, img_np.shape).astype(np.int16)
        return np.clip(img_np.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    elif degradation_type == "blur":
        return cv2.GaussianBlur(img_np, (3, 3), 0.8)
    elif degradation_type == "fax_binarization":
        gray = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)
        _, binarized = cv2.threshold(gray, 185, 255, cv2.THRESH_BINARY)
        return cv2.cvtColor(binarized, cv2.COLOR_GRAY2BGR)
    elif degradation_type == "stamp":
        stamp_text = random.choice(["OFFICIAL COPY", "PROCESSED", "AUDITED", "ENTERED"])
        cv2.putText(img_np, stamp_text, (w // 3, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (0, 0, 180), 3, cv2.LINE_AA)
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

    _, img_encoded = cv2.imencode(".jpg", img_np, [int(cv2.IMWRITE_JPEG_QUALITY), 88])

    scanned_doc = fitz.open()
    scanned_page = scanned_doc.new_page(width=595, height=842)
    scanned_page.insert_image(scanned_page.rect, stream=img_encoded.tobytes())
    pdf_bytes = scanned_doc.tobytes()
    scanned_doc.close()
    return pdf_bytes


# ---------------------------------------------------------------------------
# Template Generators (Independent Layouts, Vocabularies, Synonyms)
# ---------------------------------------------------------------------------

def gen_invoice_v2(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 3
    inv_num = f"INV-2027{idx:04d}"
    inv_date = fake.date_between(start_date="-1y", end_date="today").isoformat()
    amount = round(random.uniform(150.0, 22000.0), 2)
    vendor = fake.company()
    ein = f"{random.randint(10, 99)}-{random.randint(1000000, 9999999)}"
    client = fake.name()
    phone = fake.phone_number()

    if layout == 0:
        text = (
            f"TAX INVOICE & BILLING SUMMARY\n"
            f"============================================================\n"
            f"Billing Timestamp: {inv_date}\n"
            f"Billing Identifier: {inv_num}\n"
            f"Vendor Organization: {vendor}\n"
            f"Taxpayer EIN: {ein}\n"
            f"Recipient Customer: {client}\n"
            f"Customer Phone: {phone}\n"
            f"------------------------------------------------------------\n"
            f"Consulting and Engineering Services Retainer\n"
            f"Remittance Total: ${amount:.2f}\n"
            f"Payment due within 30 days of receipt.\n"
        )
    elif layout == 1:
        text = (
            f"STATEMENT OF CHARGES AND COMMERCIAL BILL\n"
            f"------------------------------------------------------------\n"
            f"Payee / Supplier: {vendor}\n"
            f"Federal Tax ID: {ein}\n"
            f"Reference Folio: {inv_num}\n"
            f"Date of Invoicing: {inv_date}\n"
            f"Billed Entity: {client}\n\n"
            f"Itemized Professional Technology Deliverables\n"
            f"Net Due: ${amount:.2f}\n"
            f"Remit to corporate escrow account.\n"
        )
    else:
        text = (
            f"COMMERCIAL BILL OF LIABILITIES\n"
            f"Remit To: {vendor}\n"
            f"Employer Identification No: {ein}\n"
            f"Document No.: {inv_num}\n"
            f"Issued Date: {inv_date}\n"
            f"Purchaser: {client}\n"
            f"Contact Tel: {phone}\n"
            f"Line Item: Enterprise Software Infrastructure\n"
            f"Amount Payable: ${amount:.2f}\n"
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
    return text.strip(), fields, pii


def gen_contract_v2(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 3
    contract_id = f"CNT-2027{idx:04d}"
    eff_date = fake.date_between(start_date="-2y", end_date="today").isoformat()
    p1 = fake.company()
    p2 = fake.company()
    exec_name = fake.name()
    ssn = fake.ssn()
    phone = fake.phone_number()

    if layout == 0:
        text = (
            f"COMMERCIAL COVENANT & SERVICES INDENTURE\n"
            f"Covenant Reference #: {contract_id}\n"
            f"Effective Covenant Date: {eff_date}\n"
            f"Principal Signatories: {p1} and {p2}\n"
            f"Governing Authority: Commercial Code\n"
            f"Authorized Representative: {exec_name}\n"
            f"Signatory SSN: {ssn}\n"
            f"Signatory Direct Line: {phone}\n"
            f"The counterparties hereby agree to execute the covenants described herein.\n"
        )
    elif layout == 1:
        text = (
            f"MASTER UNDERTAKING AND ENGAGEMENT AGREEMENT\n"
            f"============================================================\n"
            f"Contract Tracking Code: {contract_id}\n"
            f"Commencement Date: {eff_date}\n"
            f"Counterparties: {p1} and {p2}\n"
            f"Designated Executive: {exec_name}\n"
            f"Executive SSN: {ssn}\n"
            f"Telephone: {phone}\n"
            f"This instrument formalizes the legal liabilities between the parties.\n"
        )
    else:
        text = (
            f"BINDING SETTLEMENT AND LICENSING PROTOCOL\n"
            f"Instrument Number: {contract_id}\n"
            f"Execution Date: {eff_date}\n"
            f"Engaged Parties: {p1} and {p2}\n"
            f"Attesting Officer: {exec_name}\n"
            f"Officer Taxpayer SSN: {ssn}\n"
            f"All covenants shall remain in effect for a tenure of thirty-six months.\n"
        )

    fields = {
        "contract_id": contract_id,
        "effective_date": eff_date,
        "parties": f"{p1} and {p2}",
    }
    pii = [
        {"type": "US_SSN", "value": ssn, "sensitivity": "high"},
        {"type": "PERSON", "value": exec_name, "sensitivity": "medium"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
    ]
    return text.strip(), fields, pii


def gen_kyc_v2(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 3
    name = fake.name()
    dob = fake.date_of_birth(minimum_age=21, maximum_age=72).isoformat()
    passport = f"{fake.random_letter().upper()}{random.randint(10000000, 99999999)}"
    phone = fake.phone_number()
    email = fake.ascii_email()

    if layout == 0:
        text = (
            f"CLIENT DUE DILIGENCE DOSSIER\n"
            f"============================================================\n"
            f"Subject Full Legal Name: {name}\n"
            f"Birthdate: {dob}\n"
            f"Legal Passport Serial: {passport}\n"
            f"Contact Phone Number: {phone}\n"
            f"Electronic Mail: {email}\n"
            f"Nationality Attestation: Verified by Compliance Officer.\n"
        )
    elif layout == 1:
        text = (
            f"INDIVIDUAL IDENTITY ATTESTATION FORM\n"
            f"Applicant Complete Name: {name}\n"
            f"Date of Birth (DOB): {dob}\n"
            f"National Passport No.: {passport}\n"
            f"Telephone: {phone}\n"
            f"Email Address: {email}\n"
            f"Customer risk profile assessed under KYC guidelines.\n"
        )
    else:
        text = (
            f"REGULATORY CUSTOMER VERIFICATION QUESTIONNAIRE\n"
            f"Full Identity Name: {name}\n"
            f"Birth Registration Date: {dob}\n"
            f"Identification Travel Passport #: {passport}\n"
            f"Cell Phone: {phone}\n"
            f"Direct Email: {email}\n"
            f"Anti-Money Laundering verification status: COMPLIANT.\n"
        )

    fields = {
        "customer_name": name,
        "date_of_birth": dob,
        "id_number": passport,
    }
    pii = [
        {"type": "PERSON", "value": name, "sensitivity": "medium"},
        {"type": "PASSPORT", "value": passport, "sensitivity": "high"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
        {"type": "EMAIL_ADDRESS", "value": email, "sensitivity": "low"},
    ]
    return text.strip(), fields, pii


def gen_bank_statement_v2(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 3
    acc_num = f"{random.randint(1000000000, 9999999999)}"
    d_start = fake.date_between(start_date="-6m", end_date="-1m")
    d_end = fake.date_between(start_date=d_start, end_date="today")
    period = f"{d_start.isoformat()} to {d_end.isoformat()}"
    balance = round(random.uniform(500.0, 75000.0), 2)
    holder = fake.name()
    iban = f"US{random.randint(10, 99)}ABCD{random.randint(1000000000000000, 9999999999999999)}"
    phone = fake.phone_number()

    if layout == 0:
        text = (
            f"DEPOSITORY ACCOUNT LEDGER & SUMMARY\n"
            f"============================================================\n"
            f"Depository Account #: {acc_num}\n"
            f"Primary Beneficiary: {holder}\n"
            f"International IBAN: {iban}\n"
            f"Audit Timeframe: {period}\n"
            f"Customer Inquiries: {phone}\n"
            f"------------------------------------------------------------\n"
            f"Aggregate Deposits: $12,450.00\n"
            f"Aggregate Withdrawals: $8,120.00\n"
            f"Net Final Balance: ${balance:.2f}\n"
        )
    elif layout == 1:
        text = (
            f"MONTHLY TREASURY CASH FLOW REPORT\n"
            f"Account Holder: {holder}\n"
            f"Account Reference Code: {acc_num}\n"
            f"Routing IBAN: {iban}\n"
            f"Reporting Interval: {period}\n"
            f"Support Hotline: {phone}\n"
            f"Total Cleared Debits: $4,500.00\n"
            f"Closing Settlement Balance: ${balance:.2f}\n"
        )
    else:
        text = (
            f"FINANCIAL INSTITUTION BALANCE SHEET STATEMENT\n"
            f"Account Name: {holder}\n"
            f"Account Number: {acc_num}\n"
            f"IBAN Code: {iban}\n"
            f"Statement Period: {period}\n"
            f"Telephone Support: {phone}\n"
            f"Total Credits: $9,200.00\n"
            f"Ending Balance: ${balance:.2f}\n"
        )

    fields = {
        "account_number": acc_num,
        "statement_period": period,
        "closing_balance": balance,
    }
    pii = [
        {"type": "PERSON", "value": holder, "sensitivity": "medium"},
        {"type": "IBAN_CODE", "value": iban, "sensitivity": "high"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
    ]
    return text.strip(), fields, pii


def gen_medical_report_v2(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 3
    patient_id = f"PT-2027{idx:04d}"
    patient_name = fake.name()
    doc_name = f"Dr. {fake.first_name()} {fake.last_name()}"
    license_no = f"MD-{random.randint(100000, 999999)}"
    phone = fake.phone_number()
    diagnoses = [
        "Acute viral respiratory infection with secondary rhinitis",
        "Essential stage 1 hypertension requiring metabolic monitoring",
        "Type 2 diabetes mellitus under therapeutic dietary control",
        "Lumbar radiculopathy with mild peripheral neuropathy",
    ]
    diag = diagnoses[idx % len(diagnoses)]

    if layout == 0:
        text = (
            f"CLINICAL ASSESSMENT & ENCOUNTER RECORD\n"
            f"============================================================\n"
            f"Patient Clinical Identifier: {patient_id}\n"
            f"Subject Patient: {patient_name}\n"
            f"Attending Clinician: {doc_name}\n"
            f"Medical Practitioner License: {license_no}\n"
            f"Clinic Emergency Contact: {phone}\n"
            f"Clinical Evaluation History: Patient presented with chronic symptoms.\n"
            f"Primary Clinical Findings: {diag}\n"
            f"RECOMMENDATION: Routine follow-up scheduled in 6 weeks.\n"
        )
    elif layout == 1:
        text = (
            f"DIAGNOSTIC CONSULTATION SUMMARY\n"
            f"Patient Name: {patient_name}\n"
            f"Medical Record #: {patient_id}\n"
            f"Lead Physician: {doc_name}\n"
            f"Clinician State License: {license_no}\n"
            f"Telephone: {phone}\n"
            f"Clinician Evaluation / Diagnosis: {diag}\n"
            f"Patient prescribed conservative pharmacological regimen.\n"
        )
    else:
        text = (
            f"HOSPITAL INPATIENT DISCHARGE & EVALUATION\n"
            f"Patient Medical ID: {patient_id}\n"
            f"Patient Identity: {patient_name}\n"
            f"Practitioner: {doc_name}\n"
            f"License ID: {license_no}\n"
            f"Contact Number: {phone}\n"
            f"Assessment / Impression: {diag}\n"
            f"Discharge status favorable; prognosis stable.\n"
        )

    fields = {
        "patient_id": patient_id,
        "diagnosis": diag,
        "doctor_name": doc_name,
    }
    pii = [
        {"type": "PERSON", "value": patient_name, "sensitivity": "medium"},
        {"type": "MEDICAL_LICENSE", "value": license_no, "sensitivity": "medium"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
    ]
    return text.strip(), fields, pii


def gen_po_v2(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 3
    po_num = f"PO-2027{idx:04d}"
    order_date = fake.date_between(start_date="-1y", end_date="today").isoformat()
    amount = round(random.uniform(500.0, 45000.0), 2)
    vendor = fake.company()
    ein = f"{random.randint(10, 99)}-{random.randint(1000000, 9999999)}"
    officer = fake.name()
    phone = fake.phone_number()

    if layout == 0:
        text = (
            f"OFFICIAL PROCUREMENT REQUISITION\n"
            f"============================================================\n"
            f"Procurement Tracking #: {po_num}\n"
            f"Requisition Date: {order_date}\n"
            f"Authorized Vendor: {vendor}\n"
            f"Vendor EIN: {ein}\n"
            f"Purchasing Officer: {officer}\n"
            f"Direct Phone: {phone}\n"
            f"Commodity: Industrial hardware components\n"
            f"Authorized Requisition Sum: ${amount:.2f}\n"
            f"Delivery required within 14 business days.\n"
        )
    elif layout == 1:
        text = (
            f"COMMERCIAL PURCHASE ORDER SHEET\n"
            f"Supplier Entity: {vendor}\n"
            f"Supplier Tax Code: {ein}\n"
            f"Order Slip Code: {po_num}\n"
            f"Purchase Date: {order_date}\n"
            f"Procurement Agent: {officer}\n"
            f"Phone: {phone}\n"
            f"Total Purchase Value: ${amount:.2f}\n"
            f"Authorized against corporate procurement budget.\n"
        )
    else:
        text = (
            f"EXTERNAL REQUISITION MEMORANDUM\n"
            f"Vendor Name: {vendor}\n"
            f"Federal Taxpayer EIN: {ein}\n"
            f"PO Reference No.: {po_num}\n"
            f"Issuance Date: {order_date}\n"
            f"Buyer Representative: {officer}\n"
            f"Telephone: {phone}\n"
            f"Aggregate Commitment: ${amount:.2f}\n"
        )

    fields = {
        "po_number": po_num,
        "order_date": order_date,
        "total_amount": amount,
        "vendor_name": vendor,
    }
    pii = [
        {"type": "US_EIN", "value": ein, "sensitivity": "medium"},
        {"type": "PERSON", "value": officer, "sensitivity": "medium"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
    ]
    return text.strip(), fields, pii


def gen_letter_v2(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 3
    date_str = fake.date_between(start_date="-1y", end_date="today").isoformat()
    sender = fake.name()
    recipient = fake.name()
    email = fake.ascii_email()
    phone = fake.phone_number()
    subjects = [
        "Executive Advisory Regarding Organizational Restructuring",
        "Formal Notification of Annual Corporate Audit Schedule",
        "Memorandum on New Information Security Governance Standards",
        "Quarterly Strategic Review Meeting Coordination",
    ]
    subject = subjects[idx % len(subjects)]

    if layout == 0:
        text = (
            f"FORMAL CORPORATE DISPATCH\n"
            f"============================================================\n"
            f"Dispatch Date: {date_str}\n"
            f"Transmitted By: {sender}\n"
            f"Deliver To: {recipient}\n"
            f"Subject Header: {subject}\n"
            f"Sender Email: {email}\n"
            f"Sender Telephone: {phone}\n\n"
            f"Dear {recipient},\n"
            f"This correspondence serves as formal confirmation of the executive directives discussed.\n"
            f"Please ensure all departmental stakeholders are briefed before the upcoming operational review.\n"
            f"Sincerely,\n{sender}\n"
        )
    elif layout == 1:
        text = (
            f"EXECUTIVE OFFICE CORRESPONDENCE\n"
            f"Correspondence Date: {date_str}\n"
            f"Originator / From: {sender}\n"
            f"Recipient / To: {recipient}\n"
            f"RE / In Reference To: {subject}\n"
            f"Direct Contact: {phone} | {email}\n\n"
            f"Attention: {recipient}\n"
            f"We are writing to provide advance guidance on corporate operational changes scheduled for this quarter.\n"
            f"Regards,\n{sender}\n"
        )
    else:
        text = (
            f"OFFICIAL BUSINESS NOTIFICATION\n"
            f"Date: {date_str}\n"
            f"From: {sender}\n"
            f"To: {recipient}\n"
            f"Subject: {subject}\n"
            f"Email: {email}\n\n"
            f"Dear Colleague,\n"
            f"Please take note of the matters referenced above and initiate necessary preparations.\n"
            f"Respectfully,\n{sender}\n"
        )

    fields = {
        "sender": sender,
        "recipient": recipient,
        "date": date_str,
        "subject": subject,
    }
    pii = [
        {"type": "PERSON", "value": sender, "sensitivity": "medium"},
        {"type": "PERSON", "value": recipient, "sensitivity": "medium"},
        {"type": "EMAIL_ADDRESS", "value": email, "sensitivity": "low"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
    ]
    return text.strip(), fields, pii


def gen_claim_form_v2(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 3
    claim_id = f"CLM-2027{idx:04d}"
    inc_date = fake.date_between(start_date="-1y", end_date="today").isoformat()
    amount = round(random.uniform(250.0, 32000.0), 2)
    claimant = fake.name()
    phone = fake.phone_number()
    email = fake.ascii_email()

    if layout == 0:
        text = (
            f"INDEMNITY SETTLEMENT APPLICATION\n"
            f"============================================================\n"
            f"Policy Claim Docket: {claim_id}\n"
            f"Loss Occurrence Date: {inc_date}\n"
            f"Claimant Full Name: {claimant}\n"
            f"Settlement Demand: ${amount:.2f}\n"
            f"Claimant Telephone: {phone}\n"
            f"Contact Email: {email}\n"
            f"Description: Physical asset damage incurred during transshipment transit.\n"
            f"Application submitted for loss adjustment appraisal.\n"
        )
    elif layout == 1:
        text = (
            f"ACCIDENT & LOSS BENEFIT PETITION\n"
            f"Claim Record ID: {claim_id}\n"
            f"Incident Date: {inc_date}\n"
            f"Claimant Name: {claimant}\n"
            f"Claimed Compensation: ${amount:.2f}\n"
            f"Phone: {phone}\n"
            f"Email: {email}\n"
            f"The undersigned affirms the validity of all representations made herein.\n"
        )
    else:
        text = (
            f"INSURANCE RECOVERY FORM\n"
            f"Claim Reference #: {claim_id}\n"
            f"Date of Loss: {inc_date}\n"
            f"Policyholder / Claimant: {claimant}\n"
            f"Total Claimed Amount: ${amount:.2f}\n"
            f"Telephone: {phone}\n"
            f"Claim verification under review by underwriting syndicate.\n"
        )

    fields = {
        "claim_id": claim_id,
        "incident_date": inc_date,
        "claimant_name": claimant,
        "claim_amount": amount,
    }
    pii = [
        {"type": "PERSON", "value": claimant, "sensitivity": "medium"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
        {"type": "EMAIL_ADDRESS", "value": email, "sensitivity": "low"},
    ]
    return text.strip(), fields, pii


def gen_unknown_hard_negatives(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """Hard Negatives: 10 Quotes, 10 Purchase Requisitions, 10 Letters about Invoices, 10 Lookalikes."""
    category = idx % 4
    amount = round(random.uniform(500.0, 15000.0), 2)
    date_str = fake.date_between(start_date="-1y", end_date="today").isoformat()
    company = fake.company()
    person = fake.name()
    phone = fake.phone_number()

    if category == 0:
        # Category A: Non-binding Price Quotation / Estimate (Resembles invoice)
        q_num = f"EST-QUOTE-{9000 + idx}"
        text = (
            f"COMMERCIAL PRICE ESTIMATION & QUOTATION\n"
            f"============================================================\n"
            f"Notice: THIS DOCUMENT IS AN ESTIMATE, NOT A BILL OR INVOICE\n"
            f"Quotation Reference #: {q_num}\n"
            f"Date Issued: {date_str}\n"
            f"Prepared For: {person}\n"
            f"Estimated By: {company}\n"
            f"Contact Phone: {phone}\n"
            f"Proposed Scope: Architectural Consulting Feasibility Study\n"
            f"Estimated Valuation: ${amount:.2f}\n"
            f"Quotation valid for 30 calendar days from issuance.\n"
        )
    elif category == 1:
        # Category B: Internal Purchase Requisition Draft (Resembles PO / Invoice)
        req_num = f"INT-REQ-{8000 + idx}"
        text = (
            f"INTERNAL PROCUREMENT REQUISITION DRAFT\n"
            f"Requisition Slip: {req_num}\n"
            f"Target Supplier: {company}\n"
            f"Requisition Date: {date_str}\n"
            f"Originating Staff: {person}\n"
            f"Staff Extension: {phone}\n"
            f"Departmental Estimate: ${amount:.2f}\n"
            f"Status: PENDING DEPARTMENT HEAD BUDGET APPROVAL\n"
            f"Do not issue purchase order until formal budgetary sign-off.\n"
        )
    elif category == 2:
        # Category C: Letter Mentioning Invoices & Billing (Resembles Letter / Invoice dispute)
        text = (
            f"OFFICE OF LEGAL COUNSEL - DISPATCH\n"
            f"Date: {date_str}\n"
            f"From: {person}, General Counsel\n"
            f"To: Financial Operations Directorate\n"
            f"RE: In-Depth Review of Disputed Billing Statement INV-449102\n"
            f"Inquiry Hotline: {phone}\n\n"
            f"Dear Directors,\n"
            f"Our audit team has concluded the formal review of disputed invoice INV-449102 submitted by {company}.\n"
            f"We advise immediate suspension of payment pending delivery verification of the licensed software assets.\n"
            f"Sincerely,\n{person}\n"
        )
    else:
        # Category D: Lookalike Unknown Documents (Syllabi, Environmental Safety Advisories)
        text = (
            f"DEPARTMENT OF ENVIRONMENTAL HEALTH & SAFETY\n"
            f"BIOSAFETY PROTOCOL DIRECTIVE # EHS-2027-{idx}\n"
            f"Effective Date: {date_str}\n"
            f"Safety Administrator: {person}\n"
            f"Hotline: {phone}\n\n"
            f"Laboratory Inspection Protocols:\n"
            f"1. All biosafety cabinet certifications must be maintained annually.\n"
            f"2. Chemical inventory tracking logs must be submitted by quarterly deadlines.\n"
            f"3. Strict secondary containment required for all solvent reagents.\n"
            f"Compliance is mandatory under institutional regulatory governance.\n"
        )

    fields = {}
    pii = [
        {"type": "PERSON", "value": person, "sensitivity": "medium"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "low"},
    ]
    return text.strip(), fields, pii


GENERATORS_V2 = {
    "invoice": gen_invoice_v2,
    "contract": gen_contract_v2,
    "kyc_form": gen_kyc_v2,
    "bank_statement": gen_bank_statement_v2,
    "medical_report": gen_medical_report_v2,
    "purchase_order": gen_po_v2,
    "letter": gen_letter_v2,
    "claim_form": gen_claim_form_v2,
    "unknown": gen_unknown_hard_negatives,
}


def generate_holdout3():
    print("=" * 80)
    print("GENERATING HOLDOUT 3 (INDEPENDENT TEMPLATES, HARD NEGATIVES, SEED 20261120)")
    print(f"Target: {len(CLASSES)} classes x {DOCS_PER_CLASS} = {len(CLASSES) * DOCS_PER_CLASS} total scans")
    print("=" * 80)

    degradations = ["none", "none", "skew", "noise", "blur", "fax_binarization", "stamp"]
    manifest = []

    for doc_type in CLASSES:
        gen = GENERATORS_V2[doc_type]
        print(f"--> Generating {DOCS_PER_CLASS} documents for class: {doc_type}...")
        for i in range(DOCS_PER_CLASS):
            idx = i + 1
            doc_id = f"h3_{doc_type}_{idx:04d}"
            text, fields, pii = gen(idx)
            deg = degradations[idx % len(degradations)]

            pdf_bytes = render_scanned_pdf(text, deg)
            sha = hashlib.sha256(pdf_bytes).hexdigest()

            meta = {
                "doc_id": doc_id,
                "doc_type": doc_type,
                "sha256": sha,
                "split": "holdout3",
                "degradation": deg,
                "fields": fields,
                "pii_entities": pii,
                "file_name": f"{doc_id}.pdf",
                "full_text": text,
            }

            with open(HOLDOUT3_DIR / f"{doc_id}.pdf", "wb") as pf:
                pf.write(pdf_bytes)
            with open(HOLDOUT3_DIR / f"{doc_id}.json", "w", encoding="utf-8") as jf:
                json.dump(meta, jf, indent=2)

            manifest.append(meta)

    with open(HOLDOUT3_DIR / "manifest.json", "w", encoding="utf-8") as mf:
        json.dump(manifest, mf, indent=2)

    print(f"Holdout 3 generation complete: {len(manifest)} documents generated at {HOLDOUT3_DIR}")


if __name__ == "__main__":
    generate_holdout3()
