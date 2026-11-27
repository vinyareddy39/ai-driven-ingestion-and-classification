"""
Seeded generator for 30 Tricky Evaluation Documents & Immutably Hashed Answer Key.
- 10 Forms, 10 Invoices, 10 Letters
- 15 Digital PDFs, 5 Scanned Images, 5 Rotated Images (90/180/270), 5 Tilted Photos
- Reproducible with fixed random seed (42).
"""
import os
import random
import hashlib
import json
import cv2
import numpy as np
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

random.seed(42)
np.random.seed(42)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "tests-data", "seeded_eval_30")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Templates for Forms, Invoices, and Letters
DOC_SPECS = []

# 10 Forms
form_titles = [
    "Patient Registration Form",
    "Employee Onboarding Form",
    "Credit Card Application",
    "KYC Identity Verification",
    "Commercial Loan Request",
    "Health Insurance Claim",
    "Membership Enrollment",
    "Student Admission Record",
    "Equipment Permit Application",
    "Vendor Vendor Compliance Form"
]
for i, title in enumerate(form_titles):
    DOC_SPECS.append({
        "id": f"eval_{i+1:02d}_form",
        "category": "form",
        "title": title,
        "lines": [
            ("heading", title),
            ("pair", "Applicant Name", f"Person_{i+1} Alexander Smith"),
            ("pair", "Reference ID", f"APP-{2024000 + i*13}"),
            ("pair", "Submission Date", f"2024-0{1 + (i % 9):02d}-15"),
            ("pair", "Social Security Number", f"9{random.randint(10, 99):02d}-{random.randint(10, 99):02d}-{random.randint(1000, 9999):04d}"),
            ("pair", "Contact Email", f"applicant{i+1}@examplecorp.org"),
            ("pair", "Annual Income", f"${45000 + i * 4200:,.2f}"),
            ("pair", "Residential Address", f"{100 + i * 25} North Elm Boulevard Suite {i + 1}"),
            ("heading", "Authorization and Agreement Terms"),
            ("pair", "Agreement Status", "Accepted and Signed in Full"),
        ]
    })

# 10 Invoices
inv_titles = [
    "Enterprise Consulting Invoice",
    "Hardware Lease Invoice",
    "Legal Advisory Remittance",
    "Freight Shipping Billing",
    "Cloud Infrastructure Bill",
    "Facility Maintenance Invoice",
    "Office Supplies Remittance",
    "Software License Invoice",
    "Marketing Services Invoice",
    "Security Audit Billing"
]
for i, title in enumerate(inv_titles):
    DOC_SPECS.append({
        "id": f"eval_{i+11:02d}_invoice",
        "category": "invoice",
        "title": title,
        "lines": [
            ("heading", title),
            ("pair", "Invoice Number", f"INV-{88000 + i * 19}"),
            ("pair", "Invoice Date", f"2024-1{i % 3:01d}-10"),
            ("pair", "Client Organization", f"Global Enterprise Partners {i+1} LLC"),
            ("pair", "Billing Contact", f"billing.director{i+1}@globalpartners.net"),
            ("pair", "Payment Card", f"4111 1111 1111 {1000 + i * 111}"),
            ("pair", "Subtotal Due", f"${12500 + i * 1350:,.2f}"),
            ("pair", "Tax Surcharge", f"${850 + i * 95:,.2f}"),
            ("pair", "Total Amount Due", f"${13350 + i * 1445:,.2f}"),
            ("heading", "Payment Remittance Instructions"),
            ("pair", "Bank Account Number", f"ACCT-{990000 + i * 31}"),
        ]
    })

# 10 Letters
letter_titles = [
    "Formal Employment Verification",
    "Commercial Inquiry Letter",
    "Legal Settlement Notice",
    "Strategic Partnership Memo",
    "Employment Termination Notice",
    "Executive Resignation Letter",
    "Academic Recommendation Letter",
    "Annual Audit Confirmation",
    "Account Closure Notification",
    "Research Grant Award Letter"
]
for i, title in enumerate(letter_titles):
    DOC_SPECS.append({
        "id": f"eval_{i+21:02d}_letter",
        "category": "letter",
        "title": title,
        "lines": [
            ("heading", title),
            ("pair", "Sender Organization", f"Apex Advisory Group {i+1}"),
            ("pair", "Dispatch Date", f"2024-05-{10 + i:02d}"),
            ("pair", "Recipient Name", f"Dr. Jordan Taylor {i+1}"),
            ("pair", "Official Subject", f"Official Notice Regarding Contract Review {i+1}"),
            ("pair", "Taxpayer ID", f"9{random.randint(10, 99):02d}-{random.randint(10, 99):02d}-{random.randint(1000, 9999):04d}"),
            ("heading", "Detailed Statement and Formal Terms"),
            ("pair", "Authorized Signature", f"Chief Legal Counsel Officer {i+1}"),
            ("pair", "Confirmation Code", f"AUTH-SEC-{55000 + i * 47}"),
        ]
    })


def create_base_pdf(spec, file_path):
    c = canvas.Canvas(file_path, pagesize=letter)
    width, height = letter
    y = height - 60
    
    for item in spec["lines"]:
        kind = item[0]
        if kind == "heading":
            c.setFont("Helvetica-Bold", 14)
            y -= 15
            c.drawString(60, y, item[1])
            y -= 25
        elif kind == "pair":
            c.setFont("Helvetica", 11)
            line_str = f"{item[1]}: {item[2]}"
            c.drawString(60, y, line_str)
            y -= 22
            
    c.save()


def pdf_to_image(pdf_path):
    import fitz
    doc = fitz.open(pdf_path)
    page = doc[0]
    pix = page.get_pixmap(dpi=150)
    img_data = pix.tobytes("png")
    doc.close()
    nparr = np.frombuffer(img_data, np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)


def add_photo_effects(img):
    """Simulate phone photograph: tilt, slight perspective warp, lighting gradient."""
    h, w = img.shape[:2]
    # Small perspective tilt
    src_pts = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dx1, dy1 = random.randint(8, 15), random.randint(6, 12)
    dx2, dy2 = random.randint(10, 18), random.randint(8, 14)
    dst_pts = np.float32([
        [dx1, dy1],
        [w - dx2, dy2],
        [w - random.randint(5, 12), h - random.randint(5, 10)],
        [random.randint(5, 10), h - random.randint(6, 12)]
    ])
    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped = cv2.warpPerspective(img, M, (w, h), borderValue=(248, 245, 240))
    
    # Add subtle lighting shadow gradient
    x = np.linspace(0.85, 1.05, w)
    y = np.linspace(0.90, 1.0, h)
    xx, yy = np.meshgrid(x, y)
    vignette = (xx * yy)[:, :, np.newaxis]
    photo = np.clip(warped.astype(np.float32) * vignette, 0, 255).astype(np.uint8)
    return photo


answer_key = {}

for idx, spec in enumerate(DOC_SPECS):
    doc_id = spec["id"]
    base_pdf_path = os.path.join(OUTPUT_DIR, f"{doc_id}_temp.pdf")
    create_base_pdf(spec, base_pdf_path)
    
    # Assign format:
    # 0..14: Digital PDF (15 docs)
    # 15..19: Clean Scanned Image (5 docs)
    # 20..24: Rotated Image (5 docs: 90, 180, 270)
    # 25..29: Photographed with tilt/shadow (5 docs)
    if idx < 15:
        final_filename = f"{doc_id}.pdf"
        final_path = os.path.join(OUTPUT_DIR, final_filename)
        os.replace(base_pdf_path, final_path)
        format_type = "digital_pdf"
    elif idx < 20:
        final_filename = f"{doc_id}_scan.png"
        final_path = os.path.join(OUTPUT_DIR, final_filename)
        img = pdf_to_image(base_pdf_path)
        cv2.imwrite(final_path, img)
        os.remove(base_pdf_path)
        format_type = "clean_scan_image"
    elif idx < 25:
        # Rotated 90, 180, or 270
        angle = [90, 180, 270, 90, 270][idx - 20]
        final_filename = f"{doc_id}_rot{angle}.png"
        final_path = os.path.join(OUTPUT_DIR, final_filename)
        img = pdf_to_image(base_pdf_path)
        if angle == 90:
            rot_img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        elif angle == 180:
            rot_img = cv2.rotate(img, cv2.ROTATE_180)
        else:
            rot_img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        cv2.imwrite(final_path, rot_img)
        os.remove(base_pdf_path)
        format_type = f"rotated_{angle}"
    else:
        final_filename = f"{doc_id}_photo.png"
        final_path = os.path.join(OUTPUT_DIR, final_filename)
        img = pdf_to_image(base_pdf_path)
        photo_img = add_photo_effects(img)
        cv2.imwrite(final_path, photo_img)
        os.remove(base_pdf_path)
        format_type = "tilted_photo"

    # Expected fields
    expected_fields = []
    for item in spec["lines"]:
        if item[0] == "heading":
            expected_fields.append({
                "label": "",
                "value": item[1],
                "type": "heading"
            })
        elif item[0] == "pair":
            expected_fields.append({
                "label": item[1],
                "value": item[2],
                "type": "pair"
            })

    answer_key[final_filename] = {
        "doc_id": doc_id,
        "format_type": format_type,
        "category": spec["category"],
        "title": spec["title"],
        "line_count": len(spec["lines"]),
        "expected_fields": expected_fields,
    }

# Save answer key to disk
key_path = os.path.join(OUTPUT_DIR, "answer_key.json")
with open(key_path, "w", encoding="utf-8") as f:
    json.dump(answer_key, f, indent=2)

with open(key_path, "rb") as f:
    key_sha256 = hashlib.sha256(f.read()).hexdigest()

print(f"Generated 30 evaluation documents in: {OUTPUT_DIR}")
print(f"Answer key saved to: {key_path}")
print(f"ANSWER_KEY_SHA256: {key_sha256}")
