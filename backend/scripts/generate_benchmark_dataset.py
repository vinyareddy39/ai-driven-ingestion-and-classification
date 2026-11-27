"""Generate 60 unique, non-duplicate documents for Step 1 baseline benchmark.

Covers 7 document classes:
- 15 Invoices
- 10 KYC Forms
- 10 Contracts
- 10 Medical Reports
- 5 Bank Statements
- 5 Memorandums
- 5 Receipts / Tickets

Each document has a distinct SHA-256 and known ground truth for accuracy measurement.
"""

import json
import os
import random
import uuid
import fitz  # PyMuPDF

OUT_DIR = os.path.abspath("data/benchmark_60")
os.makedirs(OUT_DIR, exist_ok=True)

ground_truth = {}

VENDORS = ["Apex Logistics", "Globex Global", "Acme Industrial", "Soylent Corp", "Initech Software", "Wayne Enterprises", "Stark Logistics", "Umbrella Bio", "Cyberdyne Systems", "Hooli Cloud"]
NAMES = ["Eleanor Vance", "Marcus Brody", "Sarah Connor", "Arthur Dent", "Dana Scully", "Fox Mulder", "James Holden", "Naomi Nagata", "Amos Burton", "Chrisjen Avasarala"]
CITIES = ["New York, NY", "Austin, TX", "Seattle, WA", "Chicago, IL", "London, UK", "Toronto, ON", "Sydney, AU", "Berlin, DE"]

def create_pdf(filename: str, lines: list, meta: dict):
    filepath = os.path.join(OUT_DIR, filename)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842) # A4
    y = 50
    for line in lines:
        page.insert_text((50, y), line, fontsize=11)
        y += 24
    doc.save(filepath)
    doc.close()
    ground_truth[filename] = meta

print("Generating 60 benchmark documents...")

doc_idx = 1

# 1. 15 Invoices
for i in range(15):
    fname = f"bench_{doc_idx:02d}_invoice.pdf"
    vendor = VENDORS[i % len(VENDORS)]
    inv_num = f"INV-2026-{1000 + i}"
    date = f"2026-11-{10 + (i % 15):02d}"
    amount = f"${(150 + i * 47.5):.2f}"
    lines = [
        f"INVOICE",
        f"Vendor: {vendor}",
        f"Invoice Number: {inv_num}",
        f"Date: {date}",
        f"Customer: Acme Client {i+1}",
        f"Service: Technical Consultation Batch {i+1}",
        f"Total: {amount}",
        f"Payment Terms: Net 30 Days",
        f"Unique Token: {uuid.uuid4()}",
    ]
    meta = {
        "class": "invoice",
        "expected_fields": {
            "Vendor": vendor,
            "Invoice Number": inv_num,
            "Date": date,
            "Total": amount,
        }
    }
    create_pdf(fname, lines, meta)
    doc_idx += 1

# 2. 10 KYC Forms
for i in range(10):
    fname = f"bench_{doc_idx:02d}_kyc.pdf"
    name = NAMES[i % len(NAMES)]
    dob = f"198{i}-05-{12 + (i % 15):02d}"
    nat_id = f"ID-987-{4000 + i}"
    addr = f"{100 + i * 12} Market St, {CITIES[i % len(CITIES)]}"
    lines = [
        "KYC IDENTIFICATION FORM",
        f"Full Name: {name}",
        f"Date of Birth: {dob}",
        f"National ID: {nat_id}",
        f"Residential Address: {addr}",
        f"Country: United States",
        f"Status: Verified",
        f"Verification Ref: {uuid.uuid4()}",
    ]
    meta = {
        "class": "kyc_form",
        "expected_fields": {
            "Full Name": name,
            "Date of Birth": dob,
            "National ID": nat_id,
        }
    }
    create_pdf(fname, lines, meta)
    doc_idx += 1

# 3. 10 Contracts
for i in range(10):
    fname = f"bench_{doc_idx:02d}_contract.pdf"
    p1 = VENDORS[i % len(VENDORS)]
    p2 = f"Partner Firm {i+1} LLC"
    eff_date = f"2026-01-{15 + i:02d}"
    jurisdiction = "Delaware, United States"
    lines = [
        "COMMERCIAL SERVICES AGREEMENT",
        f"Party One: {p1}",
        f"Party Two: {p2}",
        f"Effective Date: {eff_date}",
        f"Governing Law: {jurisdiction}",
        "Term: Two (2) Years from Effective Date",
        "Confidentiality: Strict non-disclosure obligations apply",
        f"Contract UUID: {uuid.uuid4()}",
    ]
    meta = {
        "class": "contract",
        "expected_fields": {
            "Party One": p1,
            "Party Two": p2,
            "Effective Date": eff_date,
            "Governing Law": jurisdiction,
        }
    }
    create_pdf(fname, lines, meta)
    doc_idx += 1

# 4. 10 Medical Reports
for i in range(10):
    fname = f"bench_{doc_idx:02d}_medical.pdf"
    patient = NAMES[(i + 3) % len(NAMES)]
    physician = f"Dr. Julian Bashir MD"
    diagnosis = "Mild seasonal hypertension, recommended diet adjustment"
    lab_id = f"LAB-{202600 + i}"
    lines = [
        "MEDICAL CLINICAL SUMMARY",
        f"Patient Name: {patient}",
        f"Attending Physician: {physician}",
        f"Lab Test ID: {lab_id}",
        f"Diagnosis: {diagnosis}",
        f"Blood Pressure: {120 + i}/80 mmHg",
        "Result: Normal variation",
        f"Electronic Medical Record: {uuid.uuid4()}",
    ]
    meta = {
        "class": "medical_report",
        "expected_fields": {
            "Patient Name": patient,
            "Attending Physician": physician,
            "Lab Test ID": lab_id,
        }
    }
    create_pdf(fname, lines, meta)
    doc_idx += 1

# 5. 5 Bank Statements
for i in range(5):
    fname = f"bench_{doc_idx:02d}_bank.pdf"
    acc = f"ACCT-4490-218{i}"
    balance = f"${(12450.50 + i * 830.25):.2f}"
    period = f"November 2026 Statement"
    lines = [
        "MONTHLY BANK STATEMENT",
        f"Account Holder: {NAMES[i]}",
        f"Account Number: {acc}",
        f"Statement Period: {period}",
        f"Closing Balance: {balance}",
        f"Branch: Downtown Financial Center",
        f"Transaction Audit: {uuid.uuid4()}",
    ]
    meta = {
        "class": "bank_statement",
        "expected_fields": {
            "Account Number": acc,
            "Closing Balance": balance,
            "Account Holder": NAMES[i],
        }
    }
    create_pdf(fname, lines, meta)
    doc_idx += 1

# 6. 5 Memorandums
for i in range(5):
    fname = f"bench_{doc_idx:02d}_memo.pdf"
    to_person = NAMES[i]
    from_person = NAMES[(i + 5) % len(NAMES)]
    subj = f"Q4 Infrastructure Optimization Milestone {i+1}"
    lines = [
        "INTERNAL MEMORANDUM",
        f"To: {to_person}",
        f"From: {from_person}",
        f"Date: 2026-11-{20 + i:02d}",
        f"Subject: {subj}",
        "Priority: High",
        "Message: Please review the updated scaling metrics before Friday.",
        f"Trace ID: {uuid.uuid4()}",
    ]
    meta = {
        "class": "memorandum",
        "expected_fields": {
            "To": to_person,
            "From": from_person,
            "Subject": subj,
        }
    }
    create_pdf(fname, lines, meta)
    doc_idx += 1

# 7. 5 Receipts / Tickets
for i in range(5):
    fname = f"bench_{doc_idx:02d}_receipt.pdf"
    store = f"QuickStop Mart Store #{501 + i}"
    rcpt_id = f"REC-994{i}"
    total = f"${(34.75 + i * 11.20):.2f}"
    lines = [
        "SALES RECEIPT",
        f"Merchant: {store}",
        f"Receipt ID: {rcpt_id}",
        f"Date: 2026-11-24",
        f"Payment Method: Visa Ending in {1000 + i}",
        f"Total: {total}",
        f"Barcode Verification: {uuid.uuid4()}",
    ]
    meta = {
        "class": "receipt",
        "expected_fields": {
            "Merchant": store,
            "Receipt ID": rcpt_id,
            "Total": total,
        }
    }
    create_pdf(fname, lines, meta)
    doc_idx += 1

gt_path = os.path.join(OUT_DIR, "ground_truth.json")
with open(gt_path, "w", encoding="utf-8") as f:
    json.dump(ground_truth, f, indent=2)

print(f"Successfully generated {doc_idx - 1} documents and ground truth in {OUT_DIR}")
