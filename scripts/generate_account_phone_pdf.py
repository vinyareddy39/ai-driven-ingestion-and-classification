import os
import sys
sys.path.insert(0, os.path.abspath("."))
import fitz

def generate_pdf():
    os.makedirs("data", exist_ok=True)
    pdf_path = os.path.abspath("data/test_account_phone_doc.pdf")
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # Standard Letter size

    # Title
    page.insert_text(fitz.Point(50, 60), "FIRST NATIONAL COMMERCIAL BANK", fontsize=18, fontname="helv", color=(0.05, 0.2, 0.4))
    page.insert_text(fitz.Point(50, 80), "ACCOUNT STATEMENT & CONTACT RECORD", fontsize=12, fontname="helv", color=(0.3, 0.3, 0.3))
    page.draw_line(fitz.Point(50, 90), fitz.Point(562, 90), color=(0.7, 0.7, 0.7), width=1)

    # Details
    lines = [
        ("Account Holder:", "Katherine M. Howard"),
        ("Account Number:", "8847-1920-4491-002"),
        ("Routing Transit Number:", "021000021"),
        ("Customer Phone:", "+1-555-839-2019"),
        ("Support Email:", "service-desk@firstnational.example.com"),
        ("Statement Date:", "November 24, 2026"),
        ("Available Balance:", "$45,210.75 USD"),
        ("Total Interest Paid:", "$1,240.50 USD"),
        ("Branch Code:", "BR-9041"),
        ("Customer Reference ID:", "REF-99201488"),
    ]

    y = 125
    for label, val in lines:
        page.insert_text(fitz.Point(50, y), label, fontsize=11, fontname="helv", color=(0.1, 0.1, 0.1))
        page.insert_text(fitz.Point(230, y), val, fontsize=11, fontname="helv", color=(0.0, 0.0, 0.0))
        y += 28

    doc.save(pdf_path)
    doc.close()
    print(f"Generated test PDF: {pdf_path}")

if __name__ == "__main__":
    generate_pdf()
