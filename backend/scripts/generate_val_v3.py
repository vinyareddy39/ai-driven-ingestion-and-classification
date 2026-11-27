"""Generate fresh development evaluation set val-v3.
Specifications:
- Seed: 20261128 (New independent seed)
- 9 Classes x 40 docs = 360 documents in data/dataset/val_v3/
- Pure 300 DPI rasterized scans with Gaussian noise, skew, blur, stamps
- Includes NATIONAL_ID entities in KYC and Claim forms so NATIONAL_ID can be measured
"""

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple
import cv2
from faker import Faker
import fitz
import numpy as np

SEED = 20261128
fake = Faker()
Faker.seed(SEED)
random.seed(SEED)
np.random.seed(SEED)

CLASSES = [
    "invoice", "contract", "kyc_form", "bank_statement",
    "medical_report", "purchase_order", "letter", "claim_form", "unknown"
]

DOCS_PER_CLASS = 40
OUT_DIR = Path("data/dataset/val_v3")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def apply_degradations(img_np: np.ndarray, deg: str) -> np.ndarray:
    h, w = img_np.shape[:2]
    if deg == "skew":
        angle = random.choice([-1.5, -0.8, 0.8, 1.5])
        m = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
        return cv2.warpAffine(img_np, m, (w, h), borderValue=(255, 255, 255))
    elif deg == "noise":
        noise = np.random.normal(0, 10, img_np.shape).astype(np.int16)
        return np.clip(img_np.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    elif deg == "blur":
        return cv2.GaussianBlur(img_np, (3, 3), 0.8)
    return img_np

def render_scan_pdf(text: str, deg: str = "noise") -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    lines = text.split("\n")
    y = 50
    for line in lines[:45]:
        page.insert_text(fitz.Point(40, y), line, fontsize=10, fontname="helv")
        y += 16

    pix = page.get_pixmap(dpi=300)
    img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
    img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR)
    doc.close()

    if deg and deg != "none":
        img_np = apply_degradations(img_np, deg)

    _, enc = cv2.imencode(".jpg", img_np, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    s_doc = fitz.open()
    sp = s_doc.new_page(width=595, height=842)
    sp.insert_image(sp.rect, stream=enc.tobytes())
    pdf_bytes = s_doc.tobytes()
    s_doc.close()
    return pdf_bytes

def generate_doc(cls: str, idx: int):
    uid = f"v3_{cls}_{idx:04d}"
    pii = []
    fields = {}

    if cls == "invoice":
        num = f"INV-2028{idx:04d}"
        dt = fake.date_between(start_date="-1y", end_date="today").isoformat()
        amt = round(random.uniform(500.0, 25000.0), 2)
        ven = fake.company()
        ein = f"{random.randint(10, 99)}-{random.randint(1000000, 9999999)}"
        phone = fake.phone_number()
        email = fake.email()

        fields = {"invoice_number": num, "invoice_date": dt, "total_amount": amt, "vendor_name": ven}
        pii = [
            {"type": "US_EIN", "value": ein},
            {"type": "PHONE_NUMBER", "value": phone},
            {"type": "EMAIL_ADDRESS", "value": email}
        ]
        text = (
            f"ENTERPRISE INVOICE STATEMENT\n"
            f"Invoice Number: {num}\n"
            f"Invoice Date: {dt}\n"
            f"Vendor Name: {ven}\n"
            f"Taxpayer EIN: {ein}\n"
            f"Contact Phone: {phone}\n"
            f"Accounts Email: {email}\n"
            f"Total Amount: ${amt:.2f}\n"
            f"Terms: Payable within 30 days of receipt.\n"
        )

    elif cls == "contract":
        cid = f"CNT-2028{idx:04d}"
        dt = fake.date_between(start_date="-1y", end_date="today").isoformat()
        p1 = fake.company()
        p2 = fake.company()
        p1_rep = fake.name()
        email = fake.email()

        fields = {"contract_id": cid, "effective_date": dt, "parties": f"{p1} & {p2}"}
        pii = [
            {"type": "PERSON", "value": p1_rep},
            {"type": "EMAIL_ADDRESS", "value": email}
        ]
        text = (
            f"MASTER SERVICES AGREEMENT\n"
            f"Contract ID: {cid}\n"
            f"Effective Date: {dt}\n"
            f"First Party: {p1}\n"
            f"Second Party: {p2}\n"
            f"Authorized Signatory: {p1_rep}\n"
            f"Notification Email: {email}\n"
            f"Subject: Enterprise procurement covenant\n"
        )

    elif cls == "kyc_form":
        name = fake.name()
        dob = fake.date_of_birth(minimum_age=21, maximum_age=75).isoformat()
        pass_no = f"{random.choice('ABCDEFGHJKLMNPRSTUVWXYZ')}{random.randint(10000000, 99999999)}"
        nid = f"NID-{random.randint(10000000, 99999999)}"
        phone = fake.phone_number()
        email = fake.email()
        nat = fake.country()

        fields = {"customer_name": name, "date_of_birth": dob, "id_number": pass_no, "nationality": nat}
        pii = [
            {"type": "PERSON", "value": name},
            {"type": "PASSPORT", "value": pass_no},
            {"type": "NATIONAL_ID", "value": nid},
            {"type": "PHONE_NUMBER", "value": phone},
            {"type": "EMAIL_ADDRESS", "value": email}
        ]
        text = (
            f"CUSTOMER DUE DILIGENCE DOSSIER\n"
            f"Full Name: {name}\n"
            f"Date of Birth: {dob}\n"
            f"Passport No: {pass_no}\n"
            f"National ID: {nid}\n"
            f"Nationality: {nat}\n"
            f"Mobile Phone: {phone}\n"
            f"Electronic Mail: {email}\n"
            f"AML Verification: Compliant\n"
        )

    elif cls == "bank_statement":
        holder = fake.name()
        acct = f"{random.randint(1000000000, 9999999999)}"
        dt = fake.date_between(start_date="-1y", end_date="today").isoformat()
        bal = round(random.uniform(1500.0, 75000.0), 2)
        iban = f"US{random.randint(10, 99)}ABCD{random.randint(1000000000000000, 9999999999999999)}"
        phone = fake.phone_number()

        fields = {"account_number": acct, "statement_period": f"{dt} to {dt}", "closing_balance": bal}
        pii = [
            {"type": "PERSON", "value": holder},
            {"type": "IBAN_CODE", "value": iban},
            {"type": "PHONE_NUMBER", "value": phone}
        ]
        text = (
            f"DEPOSITORY ACCOUNT SUMMARY\n"
            f"Account Holder: {holder}\n"
            f"Account Number: {acct}\n"
            f"International IBAN: {iban}\n"
            f"Statement Period: {dt} to {dt}\n"
            f"Ending Balance: ${bal:.2f}\n"
            f"Support Hotline: {phone}\n"
        )

    elif cls == "medical_report":
        p_name = fake.name()
        pid = f"PAT-{random.randint(100000, 999999)}"
        dt = fake.date_between(start_date="-1y", end_date="today").isoformat()
        doc_name = f"Dr. {fake.name()}"
        lic = f"MD-{random.randint(100000, 999999)}"
        diag = "Essential stage 1 hypertension requiring metabolic monitoring"
        phone = fake.phone_number()

        fields = {"patient_id": pid, "diagnosis": diag, "doctor_name": doc_name}
        pii = [
            {"type": "PERSON", "value": p_name},
            {"type": "PERSON", "value": doc_name},
            {"type": "MEDICAL_LICENSE", "value": lic},
            {"type": "PHONE_NUMBER", "value": phone}
        ]
        text = (
            f"CLINICAL CONSULTATION SUMMARY\n"
            f"Patient Name: {p_name}\n"
            f"Medical Record #: {pid}\n"
            f"Report Date: {dt}\n"
            f"Lead Physician: {doc_name}\n"
            f"Clinician State License: {lic}\n"
            f"Clinic Phone: {phone}\n"
            f"Diagnosis: {diag}\n"
        )

    elif cls == "purchase_order":
        po = f"PO-2028{idx:04d}"
        dt = fake.date_between(start_date="-1y", end_date="today").isoformat()
        amt = round(random.uniform(300.0, 18000.0), 2)
        ven = fake.company()
        buyer = fake.company()
        agent = fake.name()
        phone = fake.phone_number()

        fields = {"po_number": po, "order_date": dt, "total_amount": amt, "vendor_name": ven}
        pii = [
            {"type": "PERSON", "value": agent},
            {"type": "PHONE_NUMBER", "value": phone}
        ]
        text = (
            f"OFFICIAL PURCHASE REQUISITION\n"
            f"PO Number: {po}\n"
            f"Order Date: {dt}\n"
            f"Vendor Name: {ven}\n"
            f"Buyer Organization: {buyer}\n"
            f"Purchasing Agent: {agent}\n"
            f"Vendor Phone: {phone}\n"
            f"Order Total: ${amt:.2f}\n"
        )

    elif cls == "letter":
        s_name = fake.name()
        r_name = fake.name()
        dt = fake.date_between(start_date="-1y", end_date="today").isoformat()
        subj = "Executive Memorandum on Operational Governance"
        email = fake.email()

        fields = {"sender": s_name, "recipient": r_name, "date": dt, "subject": subj}
        pii = [
            {"type": "PERSON", "value": s_name},
            {"type": "PERSON", "value": r_name},
            {"type": "EMAIL_ADDRESS", "value": email}
        ]
        text = (
            f"FORMAL CORRESPONDENCE MEMORANDUM\n"
            f"Date: {dt}\n"
            f"Sender Name: {s_name}\n"
            f"Recipient Name: {r_name}\n"
            f"Sender Email: {email}\n"
            f"Subject: {subj}\n"
            f"Dear {r_name},\n"
            f"This letter serves as formal notice of the revised operational parameters.\n"
            f"Sincerely,\n{s_name}\n"
        )

    elif cls == "claim_form":
        cid = f"CLM-2028{idx:04d}"
        dt = fake.date_between(start_date="-1y", end_date="today").isoformat()
        c_name = fake.name()
        amt = round(random.uniform(400.0, 12000.0), 2)
        ssn = f"{random.randint(100, 999)}-{random.randint(10, 99)}-{random.randint(1000, 9999)}"
        nid = f"NID-{random.randint(10000000, 99999999)}"
        phone = fake.phone_number()

        fields = {"claim_id": cid, "incident_date": dt, "claimant_name": c_name, "claim_amount": amt}
        pii = [
            {"type": "PERSON", "value": c_name},
            {"type": "US_SSN", "value": ssn},
            {"type": "NATIONAL_ID", "value": nid},
            {"type": "PHONE_NUMBER", "value": phone}
        ]
        text = (
            f"INSURANCE LOSS SETTLEMENT CLAIM\n"
            f"Claim ID: {cid}\n"
            f"Incident Date: {dt}\n"
            f"Claimant Full Name: {c_name}\n"
            f"Taxpayer SSN: {ssn}\n"
            f"National ID: {nid}\n"
            f"Contact Telephone: {phone}\n"
            f"Settlement Claim Amount: ${amt:.2f}\n"
        )

    else: # unknown
        noise_words = [fake.word() for _ in range(35)]
        text = "GENERAL UNSTRUCTURED PAYLOAD\n" + " ".join(noise_words)
        fields = {}
        pii = []

    # Save JSON ground truth
    meta = {
        "doc_id": uid,
        "doc_type": cls,
        "fields": fields,
        "pii_entities": pii
    }
    with open(OUT_DIR / f"{uid}.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    # Save PDF
    deg_choice = random.choice(["none", "skew", "noise", "blur"])
    pdf_bytes = render_scan_pdf(text, deg=deg_choice)
    with open(OUT_DIR / f"{uid}.pdf", "wb") as f:
        f.write(pdf_bytes)

def main():
    print(f"Generating 360 documents for fresh val-v3 in {OUT_DIR} (Seed: {SEED})...")
    for cls in CLASSES:
        for idx in range(1, DOCS_PER_CLASS + 1):
            generate_doc(cls, idx)
    print("Generation complete.")

if __name__ == "__main__":
    main()
