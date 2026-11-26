"""Generate 40 multi-structure test documents and their expected ground-truth JSONs.

Covers all 17 structure types:
  label_value_pair, table, list, paragraph, heading, form_row, checkbox_group,
  signature_stamp, handwriting, image_logo, chart_diagram, barcode_qr,
  header_footer, footnote, watermark, side_by_side, other.

Uses ONLY synthetic fake values. Does not hardcode filenames in application code.
"""

import json
import os
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import reportlab
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Group
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr, code128

INPUTS_DIR = os.path.abspath("structure_eval_suite/inputs")
EXPECTED_DIR = os.path.abspath("structure_eval_suite/expected")
os.makedirs(INPUTS_DIR, exist_ok=True)
os.makedirs(EXPECTED_DIR, exist_ok=True)


def draw_header_footer(c, text_header, text_footer, page_num, total_pages=1):
    c.saveState()
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    # Repeating Margin Header
    c.drawString(54, 750, text_header)
    c.setStrokeColorRGB(0.8, 0.8, 0.8)
    c.line(54, 742, 558, 742)
    # Repeating Margin Footer
    c.line(54, 50, 558, 50)
    c.drawString(54, 38, text_footer)
    c.drawRightString(558, 38, f"Page {page_num} of {total_pages}")
    c.restoreState()


def draw_watermark(c, text="CONFIDENTIAL DRAFT"):
    c.saveState()
    c.setFont("Helvetica-Bold", 40)
    c.setFillColorRGB(0.90, 0.90, 0.90)  # faint watermark
    c.translate(306, 396)
    c.rotate(45)
    c.drawCentredString(0, 0, text)
    c.restoreState()


def make_expected_record(
    filename,
    structures,
    doc_type="Document",
    expected_fields=None,
    expected_tables=None,
    expected_checkboxes=None,
    expected_signatures=None,
    expected_lists=None,
    expected_codes=None,
    header_footer_texts=None,
    watermark_texts=None,
    footnote_texts=None,
):
    return {
        "file_name": filename,
        "document_type": doc_type,
        "expected_structures": structures,
        "expected_fields": expected_fields or {},
        "expected_tables": expected_tables or [],
        "expected_checkboxes": expected_checkboxes or {},
        "expected_signatures": expected_signatures or [],
        "expected_lists": expected_lists or [],
        "expected_codes": expected_codes or [],
        "header_footer_texts": header_footer_texts or [],
        "watermark_texts": watermark_texts or [],
        "footnote_texts": footnote_texts or [],
    }


def generate_all_documents():
    print("Generating 40 multi-structure synthetic test documents...")

    # -------------------------------------------------------------
    # 1. Two-Column Article
    # -------------------------------------------------------------
    fn = "doc_01_two_column_article.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(54, 730, "Autonomous Logistics Architecture Report")
    c.setFont("Helvetica-Bold", 11)
    c.drawString(54, 700, "1. Executive Framework")
    c.drawString(310, 700, "2. Operational Deployment")
    c.setFont("Helvetica", 9)
    # Col 1
    t1 = c.beginText(54, 680)
    t1.textLines([
        "Modern fulfillment networks leverage decentralized routing nodes",
        "to balance workload across distribution centers dynamically.",
        "Primary metrics include throughput rate and transit latency.",
        "• Node reliability: 99.94%",
        "• Average transit hours: 14.2",
        "• Network variance: 1.8%"
    ])
    c.drawText(t1)
    # Col 2
    t2 = c.beginText(310, 680)
    t2.textLines([
        "Field deployments validate significant improvements in efficiency",
        "when automated load balancers guide package transfers.",
        "Resource allocation automatically scales during seasonal surges.",
        "Supervisory controllers monitor thermal dissipation and queue depth."
    ])
    c.drawText(t2)
    # Footnote
    c.line(54, 80, 200, 80)
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(54, 68, "[1] Data aggregated from Regional Fulfillment Hub #4.")
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["heading", "paragraph", "list", "footnote", "side_by_side"],
        expected_fields={"Autonomous Logistics Architecture Report": "Document Title"},
        expected_lists=[{"header": "Metrics", "items": ["Node reliability: 99.94%", "Average transit hours: 14.2", "Network variance: 1.8%"]}],
        footnote_texts=["Data aggregated from Regional Fulfillment Hub #4."]
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 2. Three-Column Newsletter
    # -------------------------------------------------------------
    fn = "doc_02_three_column_newsletter.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(54, 730, "Global Engineering Dispatch")
    cols = [
        (54, "Section Alpha: AI Agents", ["Autonomous reasoning models", "now coordinate cloud instances", "with sub-millisecond precision."]),
        (220, "Section Beta: Hardware", ["Custom optical interlinks", "reduce latency across racks", "by forty-eight percent."]),
        (386, "Section Gamma: Security", ["Zero-trust session tokens", "are rotated every five minutes", "to prevent impersonation."])
    ]
    for x, title, lines in cols:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x, 690, title)
        c.setFont("Helvetica", 8.5)
        txt = c.beginText(x, 670)
        txt.textLines(lines)
        c.drawText(txt)
    c.showPage()
    c.save()

    exp = make_expected_record(fn, ["heading", "paragraph", "side_by_side"], doc_type="Newsletter")
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 3. Form with Checkboxes & Radio Choices
    # -------------------------------------------------------------
    fn = "doc_03_form_checkboxes.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(54, 730, "Vendor Delivery Preference Form")
    c.setFont("Helvetica", 10)
    c.drawString(54, 690, "Applicant Name: Gregory Sterling")
    c.drawString(54, 670, "Account Number: ACC-994821")
    c.drawString(54, 640, "Delivery Speed Options:")
    c.drawString(70, 620, "[X] Standard Ground Delivery (3-5 business days)")
    c.drawString(70, 600, "[ ] Priority Overnight Air (Next morning)")
    c.drawString(70, 580, "[ ] Saturday Special Delivery")
    c.drawString(54, 550, "Billing Method:")
    c.drawString(70, 530, "(X) Corporate Invoice Net-30")
    c.drawString(70, 510, "( ) Automated Credit Card Billing")
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["form_row", "checkbox_group", "label_value_pair", "heading"],
        doc_type="Form",
        expected_fields={"Applicant Name": "Gregory Sterling", "Account Number": "ACC-994821"},
        expected_checkboxes={
            "Standard Ground Delivery": "selected",
            "Priority Overnight Air": "empty",
            "Saturday Special Delivery": "empty",
            "Corporate Invoice Net-30": "selected",
            "Automated Credit Card Billing": "empty",
        }
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 4. Agreement with Signature & Stamp Block
    # -------------------------------------------------------------
    fn = "doc_04_signature_stamp_contract.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(54, 730, "Professional Services Agreement")
    c.setFont("Helvetica", 9.5)
    body = c.beginText(54, 690)
    body.textLines([
        "This Agreement is entered into between Apex Logistics LLC and Beacon Corp.",
        "The consultant shall deliver system verification services as described in Schedule A.",
        "Payment terms are thirty days net following verified delivery of deliverables.",
        "All terms and liabilities are strictly subject to governing jurisdiction laws."
    ])
    c.drawText(body)

    # Stamp
    c.setStrokeColorRGB(0.1, 0.2, 0.6)
    c.rect(54, 480, 140, 70)
    c.setFont("Helvetica-Bold", 10)
    c.setFillColorRGB(0.1, 0.2, 0.6)
    c.drawCentredString(124, 525, "OFFICIAL CORPORATE SEAL")
    c.setFont("Helvetica", 8)
    c.drawCentredString(124, 505, "APEX LOGISTICS LLC - VERIFIED")

    # Signature Block
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 10)
    c.line(260, 500, 460, 500)
    c.drawString(260, 485, "Authorized Signature: Jessica Vance")
    c.drawString(260, 465, "Title: VP of Logistics Operations")
    c.drawString(260, 445, "Date: 10/14/2026")
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["heading", "paragraph", "signature_stamp", "label_value_pair"],
        doc_type="Contract",
        expected_fields={"Authorized Signature": "Jessica Vance", "Title": "VP of Logistics Operations", "Date": "10/14/2026"},
        expected_signatures=[{"signer": "Jessica Vance", "date": "10/14/2026", "status": "present"}]
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 5. Multi-Page with Repeating Margin Header & Footer
    # -------------------------------------------------------------
    fn = "doc_05_multipage_repeating_header.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    # Page 1
    draw_header_footer(c, "ACME GLOBAL HOLDINGS - QUARTERLY AUDIT 2026", "Internal Use Only", 1, 2)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(54, 700, "Quarterly Financial Audit - Part 1")
    c.setFont("Helvetica", 10)
    c.drawString(54, 660, "Audit Engagement: ENG-2026-88")
    c.drawString(54, 640, "Principal Auditor: Marcus Sterling, CPA")
    c.drawString(54, 610, "Summary of Initial Testing: All control mechanisms operating effectively.")
    c.showPage()
    # Page 2
    draw_header_footer(c, "ACME GLOBAL HOLDINGS - QUARTERLY AUDIT 2026", "Internal Use Only", 2, 2)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(54, 700, "Quarterly Financial Audit - Part 2")
    c.setFont("Helvetica", 10)
    c.drawString(54, 660, "Sample Testing Results: Zero non-conformances identified.")
    c.drawString(54, 630, "Conclusion: Standard unqualified audit opinion recommended.")
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["header_footer", "heading", "label_value_pair", "paragraph"],
        expected_fields={"Audit Engagement": "ENG-2026-88", "Principal Auditor": "Marcus Sterling, CPA"},
        header_footer_texts=["ACME GLOBAL HOLDINGS - QUARTERLY AUDIT 2026", "Internal Use Only", "Page 1 of 2", "Page 2 of 2"]
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 6. Commercial Invoice with Table and Attached Totals
    # -------------------------------------------------------------
    fn = "doc_06_table_with_totals.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(54, 730, "COMMERCIAL INVOICE")
    c.setFont("Helvetica", 10)
    c.drawString(54, 690, "Invoice Number: INV-2026-4401")
    c.drawString(54, 670, "Invoice Date: 2026-11-12")
    c.drawString(320, 690, "Payment Due: 2026-12-12")
    c.drawString(320, 670, "Customer ID: CUST-8831")

    # Table Grid
    c.setFont("Helvetica-Bold", 10)
    y = 620
    c.rect(54, y - 5, 504, 20, fill=0)
    c.drawString(60, y, "Item Description")
    c.drawString(280, y, "Quantity")
    c.drawString(370, y, "Unit Price")
    c.drawString(480, y, "Amount")

    items = [
        ("Industrial Grade Microcontroller", "10", "$45.00", "$450.00"),
        ("Differential Sensor Harness", "4", "$85.00", "$340.00"),
        ("Optoisolated Relay Board", "5", "$30.00", "$150.00"),
        ("Thermal Dissipation Heat Sink", "10", "$12.00", "$120.00"),
    ]
    c.setFont("Helvetica", 9.5)
    for desc, qty, price, amt in items:
        y -= 22
        c.rect(54, y - 5, 504, 20, fill=0)
        c.drawString(60, y, desc)
        c.drawString(290, y, qty)
        c.drawString(375, y, price)
        c.drawString(480, y, amt)

    # Attached Totals
    y -= 35
    c.setFont("Helvetica-Bold", 10)
    c.drawString(370, y, "Subtotal:")
    c.drawString(480, y, "$1,060.00")
    y -= 18
    c.drawString(370, y, "Sales Tax (8%):")
    c.drawString(480, y, "$84.80")
    y -= 18
    c.drawString(370, y, "Total Due:")
    c.drawString(480, y, "$1,144.80")
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["heading", "label_value_pair", "table"],
        doc_type="Invoice",
        expected_fields={
            "Invoice Number": "INV-2026-4401",
            "Invoice Date": "2026-11-12",
            "Payment Due": "2026-12-12",
            "Customer ID": "CUST-8831",
            "Subtotal": "$1,060.00",
            "Sales Tax (8%)": "$84.80",
            "Total Due": "$1,144.80",
        },
        expected_tables=[{
            "headers": ["Item Description", "Quantity", "Unit Price", "Amount"],
            "row_count": 4,
            "totals": {"Subtotal": "$1,060.00", "Total Due": "$1,144.80"}
        }]
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 7. Nested Ordered & Bulleted List
    # -------------------------------------------------------------
    fn = "doc_07_nested_bullet_list.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(54, 730, "Data Center Security Guidelines")
    c.setFont("Helvetica", 10)
    t = c.beginText(54, 690)
    t.textLines([
        "1. Facility Access Management",
        "   1.1 Biometric registration at security gate",
        "   1.2 Escort requirement for external vendors",
        "   1.3 Visitor badging must remain visible",
        "2. Incident Response Workflow",
        "   2.1 Immediate containment of anomalous ports",
        "   2.2 Notification of SOC supervisor within 15 minutes",
        "   2.3 Preservation of forensic system snapshots",
        "3. Audit Log Retention",
        "   • Raw syslog archives kept for 365 days",
        "   • Tamper-proof write-once storage compliance"
    ])
    c.drawText(t)
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["heading", "list"],
        expected_lists=[{
            "header": "Data Center Security Guidelines",
            "items": ["1. Facility Access Management", "2. Incident Response Workflow", "3. Audit Log Retention"]
        }]
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 8. Performance Report with Bar Chart Drawing
    # -------------------------------------------------------------
    fn = "doc_08_bar_chart_metrics.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(54, 730, "Quarterly Delivery Performance Chart")
    c.setFont("Helvetica", 9.5)
    c.drawString(54, 700, "Figure 1: On-time delivery percentage by operating quarter in 2026.")

    # Draw Bar Chart
    c.rect(54, 450, 480, 220)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(70, 645, "Chart: Delivery Success Rate (2026)")
    # Axes
    c.line(100, 480, 480, 480)  # X axis
    c.line(100, 480, 100, 620)  # Y axis
    # Axis labels
    c.setFont("Helvetica", 9)
    quarters = [("Q1: 92%", 130, 100), ("Q2: 95%", 210, 120), ("Q3: 98%", 290, 140), ("Q4: 96%", 370, 130)]
    for lbl, x, bar_h in quarters:
        c.drawString(x, 465, lbl)
        c.setFillColorRGB(0.2, 0.4, 0.8)
        c.rect(x, 480, 40, bar_h, fill=1)
        c.setFillColorRGB(0, 0, 0)

    c.drawString(54, 420, "Summary: All four operating quarters exceeded target threshold of 90%.")
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["heading", "chart_diagram", "paragraph"],
        expected_fields={"Quarterly Delivery Performance Chart": "Document Title"}
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 9. Asset Certificate with Scannable QR Code
    # -------------------------------------------------------------
    fn = "doc_09_qr_code_verification.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(54, 730, "Hardware Asset Verification Certificate")
    c.setFont("Helvetica", 10)
    c.drawString(54, 690, "Asset Tag: AST-99201")
    c.drawString(54, 670, "Serial Number: SN-4819024")
    c.drawString(54, 650, "Verification Date: 2026-11-20")
    c.drawString(54, 630, "Status: Certified Operational")

    # Add real QR code using reportlab barcode widget
    qr_data = "https://verify.example.org/asset/AST-99201"
    qr_widget = qr.QrCodeWidget(qr_data)
    qr_widget.barWidth = 120
    qr_widget.barHeight = 120
    qr_widget.qrVersion = 1
    d = Drawing(120, 120)
    d.add(qr_widget)
    renderPDF.draw(d, c, 54, 470)
    c.setFont("Helvetica", 8)
    c.drawString(54, 455, f"Scan code to verify: {qr_data}")
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["heading", "label_value_pair", "barcode_qr"],
        expected_fields={"Asset Tag": "AST-99201", "Serial Number": "SN-4819024", "Verification Date": "2026-11-20"},
        expected_codes=[{"type": "QR_CODE", "data": qr_data}]
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 10. Shipping Manifest with 1D Code128 Barcode
    # -------------------------------------------------------------
    fn = "doc_10_barcode_shipping_label.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(54, 730, "EXPRESS FREIGHT SHIPPING MANIFEST")
    c.setFont("Helvetica", 10)
    c.drawString(54, 690, "Tracking Number: TRK883710294")
    c.drawString(54, 670, "Carrier: Global Air Freight")
    c.drawString(54, 650, "Destination Hub: DFW-TERMINAL-4")
    c.drawString(54, 630, "Package Weight: 42.5 LBS")

    # Draw Code128 Barcode
    bc = code128.Code128("TRK883710294", barWidth=1.5, barHeight=50)
    bc.drawOn(c, 54, 530)
    c.setFont("Helvetica", 9)
    c.drawString(54, 515, "*TRK883710294*")
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["heading", "label_value_pair", "barcode_qr"],
        expected_fields={"Tracking Number": "TRK883710294", "Carrier": "Global Air Freight", "Package Weight": "42.5 LBS"},
        expected_codes=[{"type": "CODE_128", "data": "TRK883710294"}]
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 11. Watermarked Confidential Draft
    # -------------------------------------------------------------
    fn = "doc_11_watermarked_draft.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    draw_watermark(c, "CONFIDENTIAL DRAFT")
    c.setFont("Helvetica-Bold", 16)
    c.drawString(54, 730, "Internal Strategy Memorandum")
    c.setFont("Helvetica", 10)
    c.drawString(54, 690, "Target Expansion Year: 2027")
    c.drawString(54, 670, "Lead Strategist: Valerie Dubois")
    t = c.beginText(54, 630)
    t.textLines([
        "The proposed venture capital initiative targets automation in cold chain logistics.",
        "Expected capital deployment is eighteen million dollars across three phases.",
        "All assumptions remain contingent on preliminary regulatory authorization."
    ])
    c.drawText(t)
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["watermark", "heading", "label_value_pair", "paragraph"],
        expected_fields={"Target Expansion Year": "2027", "Lead Strategist": "Valerie Dubois"},
        watermark_texts=["CONFIDENTIAL DRAFT"]
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 12. Document with Footnote Citations
    # -------------------------------------------------------------
    fn = "doc_12_footnote_citations.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(54, 730, "Compliance Audit Statutory Review")
    c.setFont("Helvetica", 10)
    c.drawString(54, 690, "Docket Number: DKT-2026-99")
    t = c.beginText(54, 650)
    t.textLines([
        "The reviewed operational procedures comply with standard commercial guidelines [1].",
        "Mandatory quarterly reports have been filed according to Federal directives [2]."
    ])
    c.drawText(t)
    # Footnotes
    c.line(54, 100, 220, 100)
    c.setFont("Helvetica", 8)
    c.drawString(54, 85, "[1] Uniform Commercial Code Section 2-201 standard of good faith.")
    c.drawString(54, 70, "[2] 17 C.F.R. Section 240.13a-13 quarterly disclosure rules.")
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["heading", "label_value_pair", "paragraph", "footnote"],
        expected_fields={"Docket Number": "DKT-2026-99"},
        footnote_texts=[
            "Uniform Commercial Code Section 2-201 standard of good faith.",
            "17 C.F.R. Section 240.13a-13 quarterly disclosure rules."
        ]
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 13. Side-by-Side Comparison Blocks
    # -------------------------------------------------------------
    fn = "doc_13_side_by_side_blocks.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(54, 730, "Enterprise Cloud Plan Comparison")
    # Left Box
    c.rect(54, 500, 230, 200)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(70, 675, "Tier 1: Standard Core")
    c.setFont("Helvetica", 10)
    c.drawString(70, 645, "Monthly Cost: $499.00")
    c.drawString(70, 625, "Virtual CPUs: 32 Cores")
    c.drawString(70, 605, "Bandwidth: 10 Gbps")
    c.drawString(70, 585, "Support SLA: 4 Hours")

    # Right Box
    c.rect(310, 500, 230, 200)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(326, 675, "Tier 2: Enterprise Apex")
    c.setFont("Helvetica", 10)
    c.drawString(326, 645, "Monthly Cost: $999.00")
    c.drawString(326, 625, "Virtual CPUs: 64 Cores")
    c.drawString(326, 605, "Bandwidth: 40 Gbps")
    c.drawString(326, 585, "Support SLA: 15 Minutes")
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["heading", "side_by_side", "label_value_pair"],
        expected_fields={
            "Tier 1: Standard Core": "Heading",
            "Tier 2: Enterprise Apex": "Heading",
            "Monthly Cost": "$499.00",
        }
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 14. Multilingual Billing Document
    # -------------------------------------------------------------
    fn = "doc_14_multilingual_invoice.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(54, 730, "INVOICE / FACTURE / FACTURA")
    c.setFont("Helvetica", 10)
    c.drawString(54, 690, "Numéro de Facture: FAC-2026-78")
    c.drawString(54, 670, "Fecha de Emisión: 2026-11-15")
    c.drawString(54, 650, "Client / Cliente: Soluciones Industriales SA")
    c.drawString(54, 630, "Montant Total / Total a Pagar: $3,250.00")
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["heading", "label_value_pair"],
        doc_type="Invoice",
        expected_fields={
            "Numéro de Facture": "FAC-2026-78",
            "Fecha de Emisión": "2026-11-15",
            "Client / Cliente": "Soluciones Industriales SA",
            "Montant Total / Total a Pagar": "$3,250.00",
        }
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 15. Rotated Vertical Margin Text
    # -------------------------------------------------------------
    fn = "doc_15_rotated_vertical_text.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    # Rotated Margin Bar
    c.saveState()
    c.translate(35, 300)
    c.rotate(90)
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawString(0, 0, "DOCUMENT CONTROL ID: DC-9902-REV4 - ARCHIVAL COPY")
    c.restoreState()

    c.setFont("Helvetica-Bold", 16)
    c.drawString(70, 730, "Standard Operating Procedure")
    c.setFont("Helvetica", 10)
    c.drawString(70, 690, "Procedure Code: SOP-QC-401")
    c.drawString(70, 670, "Department: Quality Assurance")
    c.drawString(70, 650, "Effective Date: 2026-10-01")
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["heading", "label_value_pair", "other"],
        expected_fields={"Procedure Code": "SOP-QC-401", "Department": "Quality Assurance", "Effective Date": "2026-10-01"}
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 16. Table with Merged / Multi-Line Wrapping Cells
    # -------------------------------------------------------------
    fn = "doc_16_table_merged_multiline.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(54, 730, "Maintenance Service Ticket")
    c.setFont("Helvetica", 10)
    c.drawString(54, 690, "Work Order ID: WO-8812")

    # Table with wrapped text
    y = 650
    c.setFont("Helvetica-Bold", 10)
    c.rect(54, y - 5, 504, 20)
    c.drawString(60, y, "Service Code")
    c.drawString(160, y, "Detailed Scope of Work")
    c.drawString(480, y, "Cost")

    y -= 35
    c.rect(54, y - 5, 504, 32)
    c.setFont("Helvetica", 9)
    c.drawString(60, y + 10, "SVC-HYD-01")
    c.drawString(160, y + 12, "Disassembly of primary hydraulic manifold, seal replacement,")
    c.drawString(160, y + 0, "and dynamic pressure re-calibration under full load.")
    c.drawString(480, y + 6, "$850.00")

    y -= 35
    c.rect(54, y - 5, 504, 32)
    c.drawString(60, y + 10, "SVC-ELC-04")
    c.drawString(160, y + 12, "High voltage grounding cable inspection and thermal imaging")
    c.drawString(160, y + 0, "of power distribution busbars.")
    c.drawString(480, y + 6, "$420.00")

    # Total
    y -= 25
    c.setFont("Helvetica-Bold", 10)
    c.drawString(380, y, "Service Total:")
    c.drawString(480, y, "$1,270.00")
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["heading", "label_value_pair", "table"],
        expected_fields={"Work Order ID": "WO-8812", "Service Total": "$1,270.00"},
        expected_tables=[{"headers": ["Service Code", "Detailed Scope of Work", "Cost"], "row_count": 2}]
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 17. Simulated Handwritten Intake Form
    # -------------------------------------------------------------
    fn = "doc_17_handwritten_form.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(54, 730, "Patient Registration Intake")
    c.setFont("Helvetica", 10)
    c.drawString(54, 690, "Patient Name:")
    c.drawString(54, 660, "Date of Birth:")
    c.drawString(54, 630, "Known Allergies:")
    # Simulated filled-in values (Italic / cursive style)
    c.setFont("Times-Italic", 12)
    c.setFillColorRGB(0.1, 0.1, 0.5)  # blue pen ink
    c.drawString(150, 690, "Evelyn Harper")
    c.drawString(150, 660, "08/14/1988")
    c.drawString(150, 630, "Penicillin, Latex")
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["heading", "form_row", "handwriting", "label_value_pair"],
        expected_fields={"Patient Name": "Evelyn Harper", "Date of Birth": "08/14/1988", "Known Allergies": "Penicillin, Latex"}
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 18. Noisy Skewed Scanned Receipt Image (PNG)
    # -------------------------------------------------------------
    fn = "doc_18_noisy_skewed_scan.png"
    p = os.path.join(INPUTS_DIR, fn)
    img = Image.new("RGB", (700, 900), color=(245, 245, 242))
    draw = ImageDraw.Draw(img)
    # Draw receipt text
    draw.text((60, 60), "CORNER HARDWARE STORE", fill=(20, 20, 20))
    draw.text((60, 100), "Receipt Number: REC-49102", fill=(30, 30, 30))
    draw.text((60, 130), "Date: 11/14/2026", fill=(30, 30, 30))
    draw.text((60, 170), "Galvanized Nails 5lb: $14.50", fill=(30, 30, 30))
    draw.text((60, 200), "Claw Hammer 16oz: $22.00", fill=(30, 30, 30))
    draw.text((60, 230), "Measuring Tape 25ft: $12.50", fill=(30, 30, 30))
    draw.text((60, 280), "Subtotal: $49.00", fill=(20, 20, 20))
    draw.text((60, 310), "Total: $52.92", fill=(20, 20, 20))

    # Add slight 2-degree rotation to simulate scanner skew
    img = img.rotate(1.8, resample=Image.BICUBIC, expand=False, fillcolor=(245, 245, 242))
    img.save(p)

    exp = make_expected_record(
        fn, ["heading", "label_value_pair"],
        expected_fields={"Receipt Number": "REC-49102", "Date": "11/14/2026", "Subtotal": "$49.00", "Total": "$52.92"}
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".png", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 19. Company Logo Letterhead
    # -------------------------------------------------------------
    fn = "doc_19_company_logo_letterhead.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    # Draw logo icon
    c.setFillColorRGB(0.1, 0.4, 0.8)
    c.rect(54, 715, 30, 30, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(62, 723, "N")
    # Company Name
    c.setFillColorRGB(0.1, 0.2, 0.4)
    c.drawString(95, 730, "NEXUS INNOVATIONS CORP")
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(95, 715, "100 Technology Plaza, Suite 400 · San Jose, CA")

    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 10)
    c.drawString(54, 660, "Date: November 19, 2026")
    c.drawString(54, 640, "Subject: Commercial Partner Engagement")
    t = c.beginText(54, 600)
    t.textLines([
        "Dear Stakeholders,",
        "We are pleased to announce the successful rollout of the automated document",
        "processing platform. Early metrics demonstrate significant efficiency gains."
    ])
    c.drawText(t)
    c.drawString(54, 510, "Sincerely,")
    c.drawString(54, 480, "Marcus Sterling")
    c.drawString(54, 465, "Chief Technology Officer")
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["image_logo", "heading", "paragraph", "signature_stamp", "label_value_pair"],
        expected_fields={"Subject": "Commercial Partner Engagement", "Date": "November 19, 2026"}
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 20. Checklist with Unclear Checkbox
    # -------------------------------------------------------------
    fn = "doc_20_mixed_checkbox_unclear.pdf"
    p = os.path.join(INPUTS_DIR, fn)
    c = canvas.Canvas(p, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(54, 730, "Warehouse Safety Inspection Checklist")
    c.setFont("Helvetica", 10)
    c.drawString(54, 690, "Inspector: Officer Daniel Kim")
    c.drawString(54, 670, "Inspection Date: 2026-11-18")
    c.drawString(70, 630, "[X] Fire Extinguishers Certified")
    c.drawString(70, 605, "[ ] Chemical Storage Locked")
    c.drawString(70, 580, "[?] Emergency Exit Light Recheck Required")
    c.showPage()
    c.save()

    exp = make_expected_record(
        fn, ["heading", "label_value_pair", "checkbox_group"],
        expected_fields={"Inspector": "Officer Daniel Kim", "Inspection Date": "2026-11-18"},
        expected_checkboxes={
            "Fire Extinguishers Certified": "selected",
            "Chemical Storage Locked": "empty",
            "Emergency Exit Light Recheck Required": "unclear"
        }
    )
    with open(os.path.join(EXPECTED_DIR, fn.replace(".pdf", ".expected.json")), "w") as f_exp:
        json.dump(exp, f_exp, indent=2)

    # -------------------------------------------------------------
    # 21 - 40. Batch of Diverse Real-World Business Layouts
    # -------------------------------------------------------------
    docs_metadata = [
        (21, "doc_21_purchase_order_nested_table.pdf", "Purchase Order", ["heading", "label_value_pair", "table"],
         {"Purchase Order": "PO-5542", "Vendor": "Apex Logistics", "Total Amount": "$4,250.00"}),
        (22, "doc_22_legal_waiver_initials.pdf", "Legal Waiver", ["heading", "paragraph", "signature_stamp"],
         {"Participant": "Tyler Brooks", "Date": "2026-11-04"}),
        (23, "doc_23_medical_record_diagnoses.pdf", "Clinical Encounter", ["heading", "label_value_pair", "list", "signature_stamp"],
         {"Patient ID": "PT-49201", "Physician": "Dr. Arthur Vance", "Heart Rate": "72 bpm"}),
        (24, "doc_24_utility_bill_complex_layout.pdf", "Utility Bill", ["heading", "label_value_pair", "table"],
         {"Account Number": "UTIL-88194", "Billing Period": "Oct 1 - Oct 31", "Total Due": "$184.20"}),
        (25, "doc_25_travel_itinerary_timeline.pdf", "Travel Itinerary", ["heading", "label_value_pair", "table", "barcode_qr"],
         {"Passenger": "Elena Rostova", "Confirmation": "PNR-49281", "Flight": "UA-442"}),
        (26, "doc_26_expense_report_multi_row.pdf", "Expense Report", ["heading", "label_value_pair", "table", "signature_stamp"],
         {"Employee": "Marcus Chen", "Department": "Sales", "Total Expense": "$640.50"}),
        (27, "doc_27_warehouse_bill_of_lading.pdf", "Bill of Lading", ["heading", "label_value_pair", "table", "signature_stamp"],
         {"BOL Number": "BOL-3301", "Carrier": "Apex Freight", "Pallets": "12"}),
        (28, "doc_28_real_estate_lease_agreement.pdf", "Lease Agreement", ["heading", "header_footer", "label_value_pair", "signature_stamp"],
         {"Tenant": "Laura Higgins", "Monthly Rent": "$2,200.00", "Deposit": "$2,200.00"}),
        (29, "doc_29_bank_statement_columns.pdf", "Bank Statement", ["heading", "label_value_pair", "table"],
         {"Account Number": "CHK-994102", "Statement Date": "2026-10-31", "Ending Balance": "$14,892.40"}),
        (30, "doc_30_equipment_inspection_log.pdf", "Inspection Log", ["heading", "label_value_pair", "checkbox_group", "signature_stamp"],
         {"Asset Model": "CAT-340D", "Serial Number": "SN-9942", "Inspector": "Daniel Vance"}),
        (31, "doc_31_conference_brochure_3col.pdf", "Brochure", ["heading", "side_by_side", "list", "paragraph"],
         {"Conference": "Cloud Architecture Summit 2026", "Venue": "Grand Hyatt Ballroom"}),
        (32, "doc_32_certificate_of_insurance.pdf", "Certificate of Insurance", ["heading", "label_value_pair", "table", "signature_stamp"],
         {"Insured": "Northwind Builders", "Policy Number": "POL-9941-GL", "General Aggregate": "$2,000,000"}),
        (33, "doc_33_german_commercial_invoice.pdf", "Commercial Invoice", ["heading", "label_value_pair", "table"],
         {"Rechnungsnummer": "RE-2026-9041", "Rechnungsdatum": "18.11.2026", "Gesamtbetrag": "EUR 1.840,00"}),
        (34, "doc_34_clean_scan_image.png", "Store Receipt", ["heading", "label_value_pair"],
         {"Store": "Office Supplies Express", "Receipt ID": "REC-7731", "Total": "$84.50"}),
        (35, "doc_35_project_milestone_report.pdf", "Milestone Report", ["heading", "paragraph", "list", "label_value_pair"],
         {"Project": "Apollo Autonomous Gateway", "Phase": "Milestone 4", "Target Release": "Q1 2027"}),
        (36, "doc_36_nda_confidentiality_notice.pdf", "NDA Agreement", ["heading", "watermark", "paragraph", "signature_stamp"],
         {"Disclosing Party": "Vanguard Labs", "Receiving Party": "Orion Systems", "Term": "3 Years"}),
        (37, "doc_37_customs_declaration_form.pdf", "Customs Declaration", ["heading", "checkbox_group", "table", "signature_stamp"],
         {"Declarant": "Carlos Gomez", "Port of Entry": "Laredo TX", "Declared Value": "$15,400.00"}),
        (38, "doc_38_service_level_agreement.pdf", "SLA Agreement", ["heading", "list", "paragraph", "signature_stamp"],
         {"Provider": "CloudCore Technologies", "Guaranteed Uptime": "99.95%", "Response SLA": "15 Minutes"}),
        (39, "doc_39_inventory_transfer_manifest.pdf", "Transfer Manifest", ["heading", "barcode_qr", "table", "label_value_pair"],
         {"Manifest ID": "MAN-8819", "Origin Warehouse": "ORD-01", "Destination Warehouse": "JFK-02"}),
        (40, "doc_40_payroll_remittance_advice.pdf", "Payroll Advice", ["heading", "label_value_pair", "table"],
         {"Employee Name": "Samantha Brooks", "Pay Period": "11/01/2026 - 11/15/2026", "Net Pay": "$3,450.25"}),
    ]

    for num, filename, doc_type, struct_types, fields in docs_metadata:
        p = os.path.join(INPUTS_DIR, filename)
        if filename.endswith(".png"):
            # Clean scan image
            img = Image.new("RGB", (700, 850), color=(255, 255, 255))
            d = ImageDraw.Draw(img)
            d.text((60, 60), doc_type.upper(), fill=(0, 0, 0))
            y_pos = 110
            for k, v in fields.items():
                d.text((60, y_pos), f"{k}: {v}", fill=(40, 40, 40))
                y_pos += 30
            img.save(p)
        else:
            c = canvas.Canvas(p, pagesize=letter)
            if "watermark" in struct_types:
                draw_watermark(c, "CONFIDENTIAL & PROPRIETARY")
            if "header_footer" in struct_types:
                draw_header_footer(c, f"APEX ENTERPRISE - {doc_type.upper()}", "Confidential", 1, 1)

            c.setFont("Helvetica-Bold", 16)
            c.drawString(54, 730, doc_type.upper())
            c.setFont("Helvetica", 10)
            y_pos = 690
            for k, v in fields.items():
                c.drawString(54, y_pos, f"{k}: {v}")
                y_pos -= 20

            if "checkbox_group" in struct_types:
                y_pos -= 10
                c.drawString(54, y_pos, "Options Checklist:")
                c.drawString(70, y_pos - 20, "[X] Verified by Inspector")
                c.drawString(70, y_pos - 40, "[ ] Pending Secondary Review")
                y_pos -= 60

            if "list" in struct_types:
                y_pos -= 10
                c.drawString(54, y_pos, "Operational Requirements:")
                c.drawString(70, y_pos - 18, "• Priority processing channel enabled")
                c.drawString(70, y_pos - 36, "• End-to-end cryptographic checksum")
                c.drawString(70, y_pos - 54, "• Automated retry policy with exponential backoff")
                y_pos -= 75

            if "table" in struct_types:
                y_pos -= 15
                c.setFont("Helvetica-Bold", 10)
                c.rect(54, y_pos - 5, 504, 20)
                c.drawString(60, y_pos, "Category / Item")
                c.drawString(280, y_pos, "Quantity")
                c.drawString(380, y_pos, "Rate")
                c.drawString(480, y_pos, "Amount")
                c.setFont("Helvetica", 9)
                t_items = [
                    ("Primary Core Service", "1", "$2,500.00", "$2,500.00"),
                    ("Secondary Load Balancing", "2", "$400.00", "$800.00"),
                    ("Network Edge Gateway", "1", "$150.00", "$150.00"),
                ]
                for desc, qty, r, a in t_items:
                    y_pos -= 20
                    c.rect(54, y_pos - 5, 504, 20)
                    c.drawString(60, y_pos, desc)
                    c.drawString(290, y_pos, qty)
                    c.drawString(385, y_pos, r)
                    c.drawString(485, y_pos, a)
                y_pos -= 25
                c.setFont("Helvetica-Bold", 10)
                c.drawString(380, y_pos, "Grand Total:")
                c.drawString(485, y_pos, "$3,450.00")

            if "signature_stamp" in struct_types:
                y_pos -= 45
                c.setFont("Helvetica", 10)
                c.line(54, y_pos, 250, y_pos)
                c.drawString(54, y_pos - 15, "Authorized Signature: Jessica Vance")
                c.drawString(54, y_pos - 30, "Date: 2026-11-20")

            if "barcode_qr" in struct_types:
                qr_code = qr.QrCodeWidget(f"https://example.org/verify/{filename}")
                qr_code.barWidth = 90
                qr_code.barHeight = 90
                d = Drawing(90, 90)
                d.add(qr_code)
                renderPDF.draw(d, c, 440, 580)

            c.showPage()
            c.save()

        exp = make_expected_record(
            filename, struct_types, doc_type=doc_type,
            expected_fields=fields
        )
        with open(os.path.join(EXPECTED_DIR, filename.replace(".pdf", ".expected.json").replace(".png", ".expected.json")), "w") as f_exp:
            json.dump(exp, f_exp, indent=2)

    print(f"Successfully generated 40 multi-structure test documents in {INPUTS_DIR}")
    print(f"Successfully created 40 matching ground truth JSON specifications in {EXPECTED_DIR}")


if __name__ == "__main__":
    generate_all_documents()
