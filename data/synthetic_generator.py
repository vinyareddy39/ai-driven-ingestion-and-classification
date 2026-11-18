"""Upgraded Synthetic Document Generator for ECM Ingestion Pipeline.

Generates multi-layout realistic documents with:
- Zero embedded text layer (pure rasterized scans at 150 DPI)
- Skew, noise, low DPI, blur, fax binarization, and stamps
- 3 layouts per class with real-world label synonyms
- Hard negatives (quotes vs invoices, POs referencing invoices, letters mentioning billing, draft outlines)
- Format-based Tax IDs: Corporate EIN (XX-XXXXXXX) in invoices, SSN (XXX-XX-XXXX) in contracts
- Train (60%), Validation (20%), and Fresh Holdout (20%) partitions with seed 20261118
"""

import hashlib
import json
import os
from pathlib import Path
import random
from typing import Any, Dict, List, Optional, Tuple

import cv2
from faker import Faker
import fitz  # PyMuPDF
import numpy as np

# Seed for reproducible fresh holdout generation
SEED = 20261118
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

DOCS_PER_CLASS = 200

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "dataset"
TRAIN_DIR = OUTPUT_DIR / "train"
VAL_DIR = OUTPUT_DIR / "val"
HOLDOUT_DIR = OUTPUT_DIR / "holdout"
SPECIAL_DIR = OUTPUT_DIR / "special"

for d in [TRAIN_DIR, VAL_DIR, HOLDOUT_DIR, SPECIAL_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Template Generators with 3 Layouts per Class & Hard Negatives
# ---------------------------------------------------------------------------

def generate_invoice_content(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 3
    inv_num = f"INV-{20260000 + idx}"
    inv_date = fake.date_between(start_date="-1y", end_date="today").isoformat()
    amount = round(random.uniform(75.0, 18500.0), 2)
    vendor = fake.company()
    ein = f"{random.randint(10, 99)}-{random.randint(1000000, 9999999)}"
    phone = fake.phone_number()
    client = fake.name()

    if layout == 0:
        text = f"""============================================================
                    COMMERCIAL INVOICE
============================================================
Vendor Name: {vendor}
Vendor Tax ID (EIN): {ein}
Support Phone: {phone}

Invoice Number: {inv_num}
Invoice Date: {inv_date}
Payment Terms: Net 30 Days

BILL TO:
Client: {client}
Address: {fake.street_address()}, {fake.city()}, {fake.state()}

LINE ITEMS:
1. Enterprise Cloud Ingestion Subscription         $ {amount * 0.6:.2f}
2. Cognitive Processing & Automated Extraction     $ {amount * 0.4:.2f}

------------------------------------------------------------
TOTAL AMOUNT DUE: ${amount:.2f}
------------------------------------------------------------
Please remit payment to Account #{fake.bban()} within 30 days.
Thank you for your business!"""

    elif layout == 1:
        text = f"""############################################################
             BILL OF SALE & PROFESSIONAL SERVICES
############################################################
Billed By: {vendor}
Tax Identification (EIN): {ein}
Contact Phone: {phone}

Inv #: {inv_num}
Billing Date: {inv_date}
Payment Schedule: Immediate Due

CUSTOMER ACCOUNT:
Billed To: {client}
Location: {fake.street_address()}

SERVICES RENDERED:
- Digital Transformation Architecture Consulting   $ {amount * 0.7:.2f}
- Managed Microservices Infrastructure Provision   $ {amount * 0.3:.2f}

------------------------------------------------------------
Balance Due: ${amount:.2f}
------------------------------------------------------------
Electronic Bank Wire: Routing #{random.randint(100000000, 999999999)}."""

    else:
        text = f"""------------------------------------------------------------
                   TAX INVOICE STATEMENT
------------------------------------------------------------
Supplier: {vendor}
Corporate EIN: {ein}
Telephone: {phone}

Bill No.: {inv_num}
Date of Issue: {inv_date}
Due Date: Net 45 Days

RECIPIENT:
Purchaser: {client}

ITEMS DELIVERED:
* Automated Content Ingestion Software License     $ {amount * 0.8:.2f}
* Technical Implementation & Quality Assurance     $ {amount * 0.2:.2f}

============================================================
Grand Total: ${amount:.2f}
============================================================
Remittance terms: Bank transfer. All prices in USD."""

    fields = {
        "invoice_number": inv_num,
        "invoice_date": inv_date,
        "total_amount": amount,
        "vendor_name": vendor,
    }
    pii = [
        {"type": "US_EIN", "value": ein, "sensitivity": "medium"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "medium"},
    ]
    return text.strip(), fields, pii


def generate_contract_content(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 3
    cnt_id = f"CNT-{20260000 + idx}"
    eff_date = fake.date_between(start_date="-2y", end_date="today").isoformat()
    party_one = fake.company()
    party_two = fake.company()
    exec_name = fake.name()
    ssn = fake.ssn()

    if layout == 0:
        text = f"""============================================================
                 MASTER SERVICES AGREEMENT
============================================================
Contract ID: {cnt_id}
Effective Date: {eff_date}

This Master Services Agreement is entered into by and between:
Party One: {party_one}
Party Two: {party_two}

1. PURPOSE & ENGAGEMENT:
Party One hereby engages Party Two for enterprise architecture delivery.
All proprietary intellectual property rights remain protected.

2. CORPORATE AUTHORIZATION:
Authorized Signatory: {exec_name}
Corporate Officer SSN: {ssn}
IN WITNESS WHEREOF, the parties execute this Agreement."""

    elif layout == 1:
        text = f"""============================================================
           MUTUAL NON-DISCLOSURE & PROPRIETARY AGREEMENT
============================================================
Agreement Ref: {cnt_id}
Commencement Date: {eff_date}

BETWEEN:
First Party: {party_one}
Second Party: {party_two}

1. CONFIDENTIAL INFORMATION:
The parties agree to hold all technical and business disclosures confidential.
Term of confidentiality: 5 years from Commencement Date.

2. EXECUTION & REPRESENTATIONS:
Executive Officer: {exec_name}
Signatory Identity SSN: {ssn}
Governing Law: State of Delaware."""

    else:
        text = f"""------------------------------------------------------------
            ENTERPRISE VENDOR SUPPLY CONTRACT
------------------------------------------------------------
Contract No.: {cnt_id}
Execution Date: {eff_date}

PARTIES TO CONTRACT:
Disclosing Entity: {party_one}
Receiving Entity: {party_two}

1. STATEMENT OF WORK:
Delivery of cognitive workflow pipeline automation and QA benchmarking.

2. CORPORATE ATTESTATION:
Legal Representative: {exec_name}
Corporate Officer SSN: {ssn}
Executed on behalf of all entities."""

    fields = {
        "contract_id": cnt_id,
        "effective_date": eff_date,
        "party_one": party_one,
        "party_two": party_two,
    }
    pii = [
        {"type": "PERSON", "value": exec_name, "sensitivity": "medium"},
        {"type": "US_SSN", "value": ssn, "sensitivity": "high"},
    ]
    return text.strip(), fields, pii


def generate_kyc_content(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 3
    full_name = fake.name()
    id_num = f"ID-{random.randint(10000000, 99999999)}"
    passport = f"P{random.randint(10000000, 99999999)}"
    dob = fake.date_of_birth(minimum_age=21, maximum_age=70).isoformat()
    nationality = fake.country()
    ssn = fake.ssn()
    phone = fake.phone_number()

    if layout == 0:
        text = f"""============================================================
             KNOW YOUR CUSTOMER (KYC) FORM
============================================================
SECTION 1: CUSTOMER IDENTIFICATION
Full Name: {full_name}
ID Number: {id_num}
Passport No: {passport}
Social Security Number: {ssn}
Date of Birth: {dob}
Nationality: {nationality}
Mobile Phone: {phone}
Address: {fake.address()}

SECTION 2: VERIFICATION ATTESTATION
I declare the information provided is complete and accurate.
Customer Signature: {full_name}
Status: AML COMPLIANT."""

    elif layout == 1:
        text = f"""############################################################
       CUSTOMER IDENTIFICATION & AML VERIFICATION
############################################################
PRIMARY APPLICANT RECORD:
Legal Name: {full_name}
Document ID: {id_num}
Passport Code: {passport}
SSN: {ssn}
DOB: {dob}
Country of Citizenship: {nationality}
Primary Contact: {phone}

ATTESTATION & COMPLIANCE:
Documentary evidence verified in accordance with KYC standards.
Attested by: {full_name}."""

    else:
        text = f"""------------------------------------------------------------
          INDIVIDUAL CLIENT COMPLIANCE PROFILE
------------------------------------------------------------
PART A - PERSONAL IDENTITY:
Applicant Name: {full_name}
National Identity #: {id_num}
Travel Document: {passport}
Taxpayer ID (SSN): {ssn}
Birth Date: {dob}
Citizenship: {nationality}
Phone Number: {phone}

PART B - REGULATORY CLEARANCE:
Passed Office of Foreign Assets Control (OFAC) screening.
Customer Signature: {full_name}."""

    fields = {
        "full_name": full_name,
        "id_number": id_num,
        "date_of_birth": dob,
        "nationality": nationality,
    }
    pii = [
        {"type": "PERSON", "value": full_name, "sensitivity": "medium"},
        {"type": "PASSPORT", "value": passport, "sensitivity": "high"},
        {"type": "US_SSN", "value": ssn, "sensitivity": "high"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "medium"},
    ]
    return text.strip(), fields, pii


def generate_bank_statement_content(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 3
    acc_num = f"ACC-{random.randint(100000000, 999999999)}"
    opening = round(random.uniform(1500.0, 50000.0), 2)
    closing = round(opening + random.uniform(-1000.0, 4500.0), 2)
    period = "2026-01-01 to 2026-01-31"
    iban = fake.iban()
    holder = fake.name()

    if layout == 0:
        text = f"""============================================================
               OFFICIAL BANK STATEMENT
============================================================
Financial Institution: Apex Global Bank
Account Holder: {holder}
Account Number: {acc_num}
International IBAN: {iban}
Statement Period: {period}

SUMMARY OF ACCOUNTS:
Opening Balance: ${opening:.2f}
Total Deposits: $3,500.00
Total Withdrawals: $2,800.00
Closing Balance: ${closing:.2f}

DAILY TRANSACTION ACTIVITY:
Jan 05 Electronic Payroll Deposit +$3,500.00
Jan 12 Commercial Mortgage Debit -$2,100.00
Jan 20 Utility Service Provider -$700.00

FDIC Insured. Contact Customer Support at 1-800-555-0199."""

    elif layout == 1:
        text = f"""############################################################
           MONTHLY ACCOUNT ACTIVITY SUMMARY
############################################################
Institution: Horizon Federal Credit Union
Member Name: {holder}
Acct #: {acc_num}
IBAN Number: {iban}
Reporting Cycle: {period}

BALANCE SUMMARY:
Starting Balance: ${opening:.2f}
Total Inflow: $4,200.00
Total Outflow: $3,100.00
Ending Balance: ${closing:.2f}

CLEARED TRANSACTIONS:
Electronic Transfer: Corporate Client Remittance +$4,200.00
Authorized Merchant Payment -$3,100.00."""

    else:
        text = f"""------------------------------------------------------------
         FINANCIAL INSTITUTION ASSET STATEMENT
------------------------------------------------------------
Bank: Sovereign Trust Bank
Customer: {holder}
Account No.: {acc_num}
Wire IBAN: {iban}
Period: {period}

PORTFOLIO OVERVIEW:
Beginning Balance: ${opening:.2f}
Credits & Earnings: $5,100.00
Debits & Fees: $3,800.00
Final Balance: ${closing:.2f}

All deposits federally guaranteed. Sovereign Trust Services."""

    fields = {
        "account_number": acc_num,
        "statement_period": period,
        "opening_balance": opening,
        "closing_balance": closing,
    }
    pii = [
        {"type": "PERSON", "value": holder, "sensitivity": "medium"},
        {"type": "IBAN_CODE", "value": iban, "sensitivity": "medium"},
    ]
    return text.strip(), fields, pii


def generate_medical_report_content(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 3
    pid = f"PAT-{20260000 + idx}"
    doc_name = f"Dr. {fake.name()}"
    med_license = f"MD-{random.randint(100000, 999999)}"
    r_date = fake.date_between(start_date="-1y", end_date="today").isoformat()
    patient_name = fake.name()
    ssn = fake.ssn()
    diagnoses = [
        "Acute viral respiratory infection with mild bronchitis",
        "Essential hypertension stage 1 well managed",
        "Post-operative follow-up following lumbar microdiscectomy",
        "Type 2 diabetes mellitus under active glycemic control",
    ]
    diag = diagnoses[idx % len(diagnoses)]

    if layout == 0:
        text = f"""============================================================
              MEDICAL EXAMINATION REPORT
============================================================
Clinical Facility: St. Jude Metropolitan Medical Center
Attending Physician: {doc_name}
Medical License: {med_license}
Report Date: {r_date}

PATIENT INFORMATION:
Patient Name: {patient_name}
Patient ID: {pid}
Social Security Number: {ssn}

CLINICAL IMPRESSION:
Diagnosis: {diag}

TREATMENT PLAN:
Patient advised to continue prescribed medications.
Follow-up evaluation scheduled in six weeks.
Physician Signature: {doc_name}."""

    elif layout == 1:
        text = f"""############################################################
        CLINICAL HEALTH SUMMARY & CONSULTATION
############################################################
Provider: Metro Health Hospital
Consultant: {doc_name}
License No: {med_license}
Exam Date: {r_date}

SUBJECT PROFILE:
Patient Name: {patient_name}
Patient Ref: {pid}
Patient SSN: {ssn}

CLINICAL EVALUATION:
Primary Diagnosis: {diag}

RECOMMENDATION:
Diagnostic imaging confirmed stable progress.
Provider Attestation: {doc_name}."""

    else:
        text = f"""------------------------------------------------------------
            DIAGNOSTIC CONSULTATION NOTE
------------------------------------------------------------
Clinic: Summit Valley Healthcare
Physician: {doc_name}
Credentials: {med_license}
Date of Service: {r_date}

RECORDS:
Full Patient Name: {patient_name}
Medical Record No (MRN): {pid}
Confidential SSN: {ssn}

ASSESSMENT:
Impression/Diagnosis: {diag}

Therapy tolerated well. Standard clinical protocol observed."""

    fields = {
        "patient_id": pid,
        "diagnosis": diag,
        "doctor_name": doc_name,
        "report_date": r_date,
    }
    pii = [
        {"type": "PERSON", "value": patient_name, "sensitivity": "medium"},
        {"type": "MEDICAL_LICENSE", "value": med_license, "sensitivity": "high"},
        {"type": "US_SSN", "value": ssn, "sensitivity": "high"},
    ]
    return text.strip(), fields, pii


def generate_purchase_order_content(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 3
    po_num = f"PO-{20260000 + idx}"
    po_date = fake.date_between(start_date="-1y", end_date="today").isoformat()
    vendor = fake.company()
    total = round(random.uniform(100.0, 25000.0), 2)
    buyer = fake.name()
    phone = fake.phone_number()

    if layout == 0:
        text = f"""============================================================
                 OFFICIAL PURCHASE ORDER
============================================================
PO Number: {po_num}
PO Date: {po_date}
Procurement Officer: {buyer}

VENDOR INFORMATION:
Vendor Name: {vendor}
Contact Phone: {phone}

SHIP TO:
Acme Logistics Hub, Dock 4, Chicago, IL

ORDER SPECIFICATIONS:
1. High-Throughput Document Scanner Units - 2 Unit(s)
2. Storage Area Network Drive Arrays - 4 Unit(s)

Order Total: ${total:.2f}
Authorized Signature: {buyer}."""

    elif layout == 1:
        # Hard negative component: PO that explicitly references an invoice!
        text = f"""############################################################
              COMMERCIAL PROCUREMENT ORDER
############################################################
P.O. #: {po_num}
Order Date: {po_date}
Authorized Buyer: {buyer}

SUPPLIER:
Vendor: {vendor}
Phone: {phone}
Associated Billing Account & Reference Invoice: INV-998822

DELIVERY REQUIREMENTS:
Expedited ground logistics. Deliver to warehouse facility.
Standard warranty and maintenance obligations apply.

Total Cost: ${total:.2f}
Purchasing Department Clearance."""

    else:
        text = f"""------------------------------------------------------------
          PURCHASE REQUISITION & AUTHORIZATION
------------------------------------------------------------
Order Number: {po_num}
Date: {po_date}
Requisitioner: {buyer}

SUPPLY PARTNER:
Supplier Name: {vendor}
Contact: {phone}

ORDER ITEMS:
Enterprise server racks, patch cabling, and hardware accessories.

============================================================
Total Purchase Amount: ${total:.2f}
============================================================
Approved for corporate procurement."""

    fields = {
        "po_number": po_num,
        "po_date": po_date,
        "vendor_name": vendor,
        "order_total": total,
    }
    pii = [
        {"type": "PERSON", "value": buyer, "sensitivity": "medium"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "medium"},
    ]
    return text.strip(), fields, pii


def generate_letter_content(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 3
    sender = fake.company()
    recipient = fake.name()
    l_date = fake.date_between(start_date="-1y", end_date="today").isoformat()
    subjects = [
        "Notice of Upcoming Infrastructure Modernization",
        "Annual Corporate Account Relationship Review",
        "Policy Terms and Regulatory Directive Updates",
        "Inquiry Regarding Vendor Invoice Processing",  # Hard negative component!
    ]
    subj = subjects[idx % len(subjects)]

    if layout == 0:
        text = f"""From: {sender}
To: {recipient}
Date: {l_date}
Subject: {subj}

Dear {recipient},

We are writing to officially advise you regarding {subj.lower()}.
Our team has completed the preliminary review and confirmed that all
necessary standards remain satisfied.

Should you require further clarification, please contact our administrative office.

Sincerely,
Management Committee
{sender}"""

    elif layout == 1:
        text = f"""Sender: {sender}
Recipient: {recipient}
Date of Notice: {l_date}
RE: {subj}

Attention: {recipient}

Please be advised of our formal corporate communication regarding the subject referenced above.
Regarding your recent inquiry about invoice processing and account reconciliation,
all documentation has been forwarded to compliance.

Warm regards,
Operations Directorate
{sender}"""

    else:
        text = f"""============================================================
                  EXECUTIVE MEMORANDUM
============================================================
FROM: {sender}
TO: {recipient}
DATE: {l_date}
SUBJECT MATTER: {subj}

Dear {recipient},

This memorandum serves as official confirmation regarding {subj.lower()}.
Please file this letter in your records for audit and compliance inspection.

Authorized by:
Executive Governance Board
{sender}"""

    fields = {
        "sender": sender,
        "recipient": recipient,
        "letter_date": l_date,
        "subject": subj,
    }
    pii = [
        {"type": "PERSON", "value": recipient, "sensitivity": "medium"},
    ]
    return text.strip(), fields, pii


def generate_claim_form_content(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    layout = idx % 3
    claim_id = f"CLM-{20260000 + idx}"
    claimant = fake.name()
    inc_date = fake.date_between(start_date="-1y", end_date="today").isoformat()
    amt = round(random.uniform(250.0, 35000.0), 2)
    ssn = fake.ssn()
    phone = fake.phone_number()

    if layout == 0:
        text = f"""============================================================
                  INSURANCE CLAIM FORM
============================================================
Claim ID: {claim_id}
Incident Date: {inc_date}

POLICYHOLDER & CLAIMANT:
Claimant Name: {claimant}
Social Security Number: {ssn}
Contact Phone: {phone}

INCIDENT DETAILS:
Reported property damage and commercial operational interruption.

------------------------------------------------------------
Claim Amount: ${amt:.2f}
------------------------------------------------------------
I attest under penalty of perjury that this claim is authentic.
Signature: {claimant}."""

    elif layout == 1:
        text = f"""############################################################
           NOTICE OF LOSS & CLAIMS DECLARATION
############################################################
Claim Reference #: {claim_id}
Loss Date: {inc_date}

INSURED PARTY:
Insured Party: {claimant}
SSN: {ssn}
Phone Number: {phone}

INCIDENT STATEMENT:
Sudden equipment failure during standard manufacturing run.
Independent adjuster assessment submitted concurrently.

Claimed Loss Amount: ${amt:.2f}
Claimant Attestation: {claimant}."""

    else:
        text = f"""------------------------------------------------------------
             BENEFIT REIMBURSEMENT REQUEST
------------------------------------------------------------
Claim No.: {claim_id}
Date of Occurrence: {inc_date}

BENEFICIARY:
Applicant: {claimant}
Taxpayer SSN: {ssn}
Telephone: {phone}

REIMBURSEMENT PARTICULARS:
Emergency clinical and travel expense restitution request.

============================================================
Requested Amount: ${amt:.2f}
============================================================
Declared true by applicant."""

    fields = {
        "claim_id": claim_id,
        "claimant_name": claimant,
        "incident_date": inc_date,
        "claim_amount": amt,
    }
    pii = [
        {"type": "PERSON", "value": claimant, "sensitivity": "medium"},
        {"type": "US_SSN", "value": ssn, "sensitivity": "high"},
        {"type": "PHONE_NUMBER", "value": phone, "sensitivity": "medium"},
    ]
    return text.strip(), fields, pii


def generate_unknown_content(idx: int) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    # Includes hard negatives!
    category = idx % 4
    if category == 0:
        # Hard negative: Price Quotation / Estimate (Resembles invoice but is a Quote!)
        quote_num = f"QUO-{800000 + idx}"
        vendor = fake.company()
        amount = round(random.uniform(500.0, 8000.0), 2)
        text = f"""============================================================
       PRICE ESTIMATE & FORMAL QUOTATION (NOT AN INVOICE)
============================================================
Quote Reference: {quote_num}
Quotation Date: {fake.date_between(start_date="-6m", end_date="today").isoformat()}
Prepared By: {vendor}

PROSPECTIVE CLIENT:
Customer: {fake.name()}

PROPOSED SCOPE:
This document is an estimate and cost quotation only.
Does not constitute a demand for payment.
Estimated Project Budget: ${amount:.2f}
Proposal validity: 30 days from issuance."""

    elif category == 1:
        # Hard negative: KYC Draft Training Outline (Resembles KYC but is internal notes!)
        text = f"""############################################################
   PRELIMINARY ONBOARDING SYLLABUS & DRAFT TRAINING OUTLINE
############################################################
Document Code: SYLLABUS-KYC-DRAFT-{idx}
Instructor: {fake.name()}
Department: Corporate Staff Training

COURSE OUTLINE:
1. Introduction to Know Your Customer guidelines and compliance.
2. Standard verification procedures for passports and national IDs.
3. Review of anti-money laundering frameworks.
Note: This is an internal educational document and contains no customer data."""

    elif category == 2:
        # Technical Runbook / Log Dump
        text = f"""------------------------------------------------------------
           SYSTEM ARCHITECTURE RUNBOOK & KERNEL DUMP
------------------------------------------------------------
Trace Identifier: trace-{hashlib.sha256(str(idx).encode()).hexdigest()[:12]}
Timestamp: 2026-11-18T04:12:08Z
Node Cluster: us-east-worker-k8s-{idx}

[DEBUG] Worker process spawned with PID {1000 + idx}
[DEBUG] Redis streams consumer group initialized
[INFO] Heartbeat acknowledged on port 6379
[METRICS] Memory footprint: 142MB. CPU usage: 1.4%."""

    else:
        # Miscellaneous Poetry & Internal Notes
        text = f"""Project Notes: Cognitive Automation Exploration #{idx}
Author: {fake.name()}

The engine of cognition turns upon silent wheels of data.
In the digital archives where papers sleep in quiet rows,
patterns arise from pixels and algorithms seek the light of truth.

Status: Archived brainstorming draft. No business action required."""

    fields = {}
    pii = []
    return text.strip(), fields, pii


GENERATOR_MAP = {
    "invoice": generate_invoice_content,
    "contract": generate_contract_content,
    "kyc_form": generate_kyc_content,
    "bank_statement": generate_bank_statement_content,
    "medical_report": generate_medical_report_content,
    "purchase_order": generate_purchase_order_content,
    "letter": generate_letter_content,
    "claim_form": generate_claim_form_content,
    "unknown": generate_unknown_content,
}


# ---------------------------------------------------------------------------
# Visual Degradations & Pure Rasterized PDF Generation
# ---------------------------------------------------------------------------

def apply_image_degradations(img_np: np.ndarray, degradation_type: str) -> np.ndarray:
    """Apply visual distortions reflecting real-world scanned artifacts."""
    h, w = img_np.shape[:2]

    if degradation_type == "skew":
        angle = random.choice([-2.5, -1.8, 1.8, 2.5])
        m = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
        return cv2.warpAffine(img_np, m, (w, h), borderValue=(255, 255, 255))

    elif degradation_type == "noise":
        noise = np.random.normal(0, 12, img_np.shape).astype(np.int16)
        return np.clip(img_np.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    elif degradation_type == "blur":
        return cv2.GaussianBlur(img_np, (3, 3), 1.0)

    elif degradation_type == "fax_binarization":
        gray = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)
        _, binarized = cv2.threshold(gray, 185, 255, cv2.THRESH_BINARY)
        return cv2.cvtColor(binarized, cv2.COLOR_GRAY2BGR)

    elif degradation_type == "stamp":
        stamp_text = random.choice(["PAID", "CONFIDENTIAL", "VERIFIED", "ARCHIVED", "AUDITED"])
        cv2.putText(
            img_np, stamp_text, (w // 3, h // 2),
            cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 180), 3, cv2.LINE_AA
        )
        return img_np

    return img_np


def render_scanned_pdf(text: str, degradation_type: str = "none") -> bytes:
    """Render text to image, apply degradations, and insert ONLY the image into PDF with NO text layer."""
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

    # Apply visual degradation
    if degradation_type and degradation_type != "none":
        img_np = apply_image_degradations(img_np, degradation_type)

    _, img_encoded = cv2.imencode(".jpg", img_np, [int(cv2.IMWRITE_JPEG_QUALITY), 88])

    # Scanned PDF: Contains pure image ONLY, zero text layer!
    scanned_doc = fitz.open()
    scanned_page = scanned_doc.new_page(width=595, height=842)
    scanned_page.insert_image(scanned_page.rect, stream=img_encoded.tobytes())
    pdf_bytes = scanned_doc.tobytes()
    scanned_doc.close()
    return pdf_bytes


render_pdf_document = render_scanned_pdf


# ---------------------------------------------------------------------------
# Dataset Generation Runner
# ---------------------------------------------------------------------------

def generate_upgraded_dataset():
    print("=" * 75)
    print("GENERATING UPGRADED REALISTIC DATASET (PURE SCANS, ZERO TEXT LAYER)")
    print(f"Seed: {SEED} | Docs Per Class: {DOCS_PER_CLASS} across {len(CLASSES)} classes")
    print("=" * 75)

    degradations = ["none", "none", "skew", "noise", "blur", "fax_binarization", "stamp"]
    manifest = []

    for doc_type in CLASSES:
        generator = GENERATOR_MAP[doc_type]
        print(f"--> Generating {DOCS_PER_CLASS} realistic scans for class: {doc_type}...")

        for i in range(DOCS_PER_CLASS):
            idx = i + 1
            doc_id = f"{doc_type}_{idx:04d}"
            text, fields, pii_entities = generator(idx)
            deg = degradations[idx % len(degradations)]

            pdf_bytes = render_scanned_pdf(text, deg)
            sha = hashlib.sha256(pdf_bytes).hexdigest()

            # Partition: 60% Train (1-120), 20% Val (121-160), 20% Holdout (161-200)
            if idx <= 120:
                split = "train"
                target_dir = TRAIN_DIR
            elif idx <= 160:
                split = "val"
                target_dir = VAL_DIR
            else:
                split = "holdout"
                target_dir = HOLDOUT_DIR

            meta = {
                "doc_id": doc_id,
                "doc_type": doc_type,
                "sha256": sha,
                "split": split,
                "degradation": deg,
                "fields": fields,
                "pii_entities": pii_entities,
                "file_name": f"{doc_id}.pdf",
            }

            with open(target_dir / f"{doc_id}.pdf", "wb") as pf:
                pf.write(pdf_bytes)
            with open(target_dir / f"{doc_id}.json", "w", encoding="utf-8") as jf:
                json.dump(meta, jf, indent=2)

            manifest.append(meta)

    # Generate Special Test Files in special directory
    print("--> Generating special test files in dataset/special...")
    blank_doc = fitz.open()
    blank_doc.new_page(width=595, height=842)
    with open(SPECIAL_DIR / "special_blank_page.pdf", "wb") as f:
        f.write(blank_doc.tobytes())
    blank_doc.close()

    corrupt_bytes = b"%PDF-1.4\nCORRUPTED_FILE_DATA_NOT_A_VALID_DOCUMENT_EOF\x00\xff"
    with open(SPECIAL_DIR / "special_corrupt.pdf", "wb") as f:
        f.write(corrupt_bytes)

    pwd_doc = fitz.open()
    p = pwd_doc.new_page()
    p.insert_text(fitz.Point(50, 100), "Confidential Protected Document", fontsize=12)
    with open(SPECIAL_DIR / "special_password_protected.pdf", "wb") as f:
        f.write(pwd_doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="ecm_secret_123"))
    pwd_doc.close()

    # Special Conflict Document
    conflict_text = """From: Sovereign Human Resources
To: Jordan Miller
Date: 2026-11-18
Subject: Confidential Severance Agreement

Dear Jordan Miller,
Please review the terms of your departure.
Employee SSN: 111-22-3333
Support Contact: 1-800-555-0199"""
    c_bytes = render_scanned_pdf(conflict_text, "none")
    with open(SPECIAL_DIR / "special_conflict_document.pdf", "wb") as f:
        f.write(c_bytes)
    with open(SPECIAL_DIR / "special_conflict_document.json", "w", encoding="utf-8") as f:
        json.dump({
            "doc_id": "special_conflict_document",
            "doc_type": "letter",
            "sha256": hashlib.sha256(c_bytes).hexdigest(),
            "pii_entities": [{"type": "US_SSN", "value": "111-22-3333", "sensitivity": "high"}],
        }, f, indent=2)

    with open(OUTPUT_DIR / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Dataset generated successfully: {len(manifest)} total documents.")
    print(f"  Train:   {len(list(TRAIN_DIR.glob('*.json')))} documents")
    print(f"  Val:     {len(list(VAL_DIR.glob('*.json')))} documents")
    print(f"  Holdout: {len(list(HOLDOUT_DIR.glob('*.json')))} documents")
    print("=" * 75)


if __name__ == "__main__":
    generate_upgraded_dataset()
