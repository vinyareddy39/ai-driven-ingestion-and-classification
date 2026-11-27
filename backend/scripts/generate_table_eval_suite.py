"""
Generate 15 synthetic PDF documents with tables of varying shapes:
- 3 to 8 columns
- With and without ruled lines
- Multi-line descriptions
- Totals blocks under tables
- Lines where description and number share a line (same-line pairing)
- Full expected.json ground truth for each file
"""

import os
import json
import fitz  # PyMuPDF

OUT_DIR = "table_eval_suite"
INPUTS_DIR = os.path.join(OUT_DIR, "inputs")
EXPECTED_DIR = os.path.join(OUT_DIR, "expected")
os.makedirs(INPUTS_DIR, exist_ok=True)
os.makedirs(EXPECTED_DIR, exist_ok=True)

DOC_SPECS = [
    {
        "id": "doc_01_invoice_3col_ruled",
        "title": "ACME INDUSTRIAL SERVICES",
        "doc_type": "invoice",
        "header_fields": [
            ("Invoice Number", "INV-2026-8801"),
            ("Invoice Date", "2026-11-20"),
            ("Due Date", "2026-12-20"),
        ],
        "same_line_pairs": [
            ("Expedited Freight Surcharge", "$45.00"),
            ("Environmental Handling Fee", "$18.50"),
        ],
        "headers": ["Description", "Qty", "Amount"],
        "rows": [
            ["Heavy duty hydraulic filter replacement", "2", "340.00"],
            ["Synthetic compressor lubricant 20L", "4", "480.00"],
            ["High pressure brass control valve", "1", "125.00"],
        ],
        "ruled": True,
        "totals": [
            ("Subtotal", "$945.00"),
            ("Tax Amount", "$75.60"),
            ("Total Due", "$1,084.10"),
        ]
    },
    {
        "id": "doc_02_invoice_4col_unruled",
        "title": "VERTEX CLOUD CONSULTING",
        "doc_type": "invoice",
        "header_fields": [
            ("Invoice Ref", "VCS-99410"),
            ("Date", "2026-11-21"),
            ("Client Account", "ACC-44912"),
        ],
        "same_line_pairs": [
            ("Client Partner Discount", "-$150.00"),
            ("Travel Reimbursement", "$85.00"),
        ],
        "headers": ["Service Item", "Hours", "Hourly Rate", "Total"],
        "rows": [
            ["Architecture assessment & planning", "10", "150.00", "1500.00"],
            ["Database migration script execution", "8", "150.00", "1200.00"],
            ["Security audit & penetration review", "6", "175.00", "1050.00"],
        ],
        "ruled": False,
        "totals": [
            ("Subtotal", "$3,750.00"),
            ("Total Due", "$3,685.00"),
        ]
    },
    {
        "id": "doc_03_purchase_order_5col_ruled",
        "title": "GLOBAL DYNAMICS HARDWARE",
        "doc_type": "purchase_order",
        "header_fields": [
            ("PO Number", "PO-77312"),
            ("Order Date", "2026-11-18"),
            ("Vendor Code", "VND-1002"),
        ],
        "same_line_pairs": [
            ("Standard Ground Shipping", "$28.00"),
        ],
        "headers": ["Line", "SKU", "Item Description", "Unit Price", "Line Total"],
        "rows": [
            ["1", "SKU-9921", "Titanium fastener bolt set", "45.00", "450.00"],
            ["2", "SKU-3381", "Reinforced steel mounting bracket", "22.50", "450.00"],
            ["3", "SKU-1120", "Industrial silicone sealant pack", "15.00", "150.00"],
        ],
        "ruled": True,
        "totals": [
            ("Subtotal", "$1,050.00"),
            ("Total Order Amount", "$1,078.00"),
        ]
    },
    {
        "id": "doc_04_inventory_6col_ruled",
        "title": "APEX LOGISTICS WAREHOUSE",
        "doc_type": "inventory_report",
        "header_fields": [
            ("Report Number", "INV-REP-5541"),
            ("Audit Date", "2026-11-19"),
        ],
        "same_line_pairs": [
            ("Warehouse Location", "Building B-4"),
        ],
        "headers": ["Item ID", "Item Name", "Category", "In Stock", "Reorder Level", "Unit Cost"],
        "rows": [
            ["ITM-01", "Ball Bearing 50mm", "Mechanical", "150", "30", "12.50"],
            ["ITM-02", "O-Ring Seal Pack", "Plastics", "420", "100", "3.20"],
            ["ITM-03", "Control Relay 24V", "Electrical", "85", "20", "28.00"],
        ],
        "ruled": True,
        "totals": [
            ("Total Items Tracked", "655"),
        ]
    },
    {
        "id": "doc_05_shipment_manifest_7col_unruled",
        "title": "TRANS-CONTINENTAL CARRIERS",
        "doc_type": "manifest",
        "header_fields": [
            ("Manifest ID", "MAN-88392"),
            ("Dispatch Date", "2026-11-22"),
        ],
        "same_line_pairs": [
            ("Customs Clearance Agent", "Pacific Brokers Ltd"),
        ],
        "headers": ["Tracking", "Package Desc", "Origin", "Dest", "Qty", "Weight", "Tariff"],
        "rows": [
            ["TRK-101", "Precision Sensors Box", "Seattle", "Tokyo", "5", "12.5 kg", "120.00"],
            ["TRK-102", "Optical Cable Spool", "Portland", "Osaka", "2", "34.0 kg", "210.00"],
            ["TRK-103", "Electronic Modules", "Tacoma", "Nagoya", "8", "18.2 kg", "195.00"],
        ],
        "ruled": False,
        "totals": [
            ("Total Pieces", "15"),
            ("Total Tariff", "$525.00"),
        ]
    },
    {
        "id": "doc_06_payroll_statement_8col_ruled",
        "title": "ENTERPRISE PAYROLL SERVICES",
        "doc_type": "payroll",
        "header_fields": [
            ("Payroll Period", "2026-11-01 to 2026-11-15"),
            ("Batch Reference", "PR-BATCH-441"),
        ],
        "same_line_pairs": [
            ("Department Total Hours", "120.00"),
        ],
        "headers": ["ID", "Employee", "Role", "Hours", "Rate", "Gross", "Tax", "Net"],
        "rows": [
            ["E101", "Alex Smith", "Developer", "40.0", "50.00", "2000.00", "400.00", "1600.00"],
            ["E102", "Jordan Lee", "Designer", "40.0", "45.00", "1800.00", "360.00", "1440.00"],
            ["E103", "Morgan Fox", "DevOps", "40.0", "55.00", "2200.00", "440.00", "1760.00"],
        ],
        "ruled": True,
        "totals": [
            ("Total Gross", "$6,000.00"),
            ("Total Net", "$4,800.00"),
        ]
    },
    {
        "id": "doc_07_medical_bill_4col_ruled",
        "title": "METRO HEALTH CLINIC",
        "doc_type": "medical_statement",
        "header_fields": [
            ("Statement ID", "MED-77192"),
            ("Patient ID", "PAT-0091"),
            ("Date of Service", "2026-11-17"),
        ],
        "same_line_pairs": [
            ("Patient Copay Required", "$35.00"),
            ("Primary Insurance Paid", "$480.00"),
        ],
        "headers": ["Service Date", "Description of Care", "Billing Code", "Amount"],
        "rows": [
            ["2026-11-17", "Comprehensive diagnostic consultation", "CPT-99214", "185.00"],
            ["2026-11-17", "Standard blood panel chemistry", "CPT-80053", "120.00"],
            ["2026-11-17", "Diagnostic chest X-Ray complete", "CPT-71046", "210.00"],
        ],
        "ruled": True,
        "totals": [
            ("Total Charges", "$515.00"),
            ("Patient Responsibility", "$35.00"),
        ]
    },
    {
        "id": "doc_08_hotel_folio_4col_unruled",
        "title": "GRAND MERIDIAN HOTEL",
        "doc_type": "receipt",
        "header_fields": [
            ("Folio Number", "FOL-44910"),
            ("Room Number", "Room 408"),
            ("Check-out Date", "2026-11-23"),
        ],
        "same_line_pairs": [
            ("City Hospitality Surcharge", "$14.20"),
        ],
        "headers": ["Posting Date", "Transaction Description", "Reference", "Charge"],
        "rows": [
            ["2026-11-21", "Deluxe King Room Stay Night 1", "RMS-408", "210.00"],
            ["2026-11-22", "Deluxe King Room Stay Night 2", "RMS-408", "210.00"],
            ["2026-11-22", "Room Service Dining Charge", "POS-882", "58.50"],
        ],
        "ruled": False,
        "totals": [
            ("Subtotal Amount", "$478.50"),
            ("Total Billed", "$492.70"),
        ]
    },
    {
        "id": "doc_09_freight_waybill_5col_ruled",
        "title": "OCEANIC FREIGHT FORWARDERS",
        "doc_type": "waybill",
        "header_fields": [
            ("Waybill Number", "WB-992014"),
            ("Vessel Name", "MV Pacific Star"),
            ("Voyage", "VY-402"),
        ],
        "same_line_pairs": [
            ("Port Facility Surcharge", "$65.00"),
        ],
        "headers": ["Item No", "Package Desc", "Dimensions", "Weight Kg", "Freight Cost"],
        "rows": [
            ["1", "Machine parts crate", "120x80x60 cm", "240.0", "380.00"],
            ["2", "Electronic assemblies pallet", "100x120x80 cm", "180.0", "290.00"],
            ["3", "Spare pump housing crate", "90x90x70 cm", "150.0", "240.00"],
        ],
        "ruled": True,
        "totals": [
            ("Total Weight", "570.0 kg"),
            ("Total Freight Due", "$910.00"),
        ]
    },
    {
        "id": "doc_10_repair_estimate_4col_ruled",
        "title": "PRECISION AUTO REPAIR",
        "doc_type": "invoice",
        "header_fields": [
            ("Estimate ID", "EST-33910"),
            ("Vehicle Model", "2022 Ford Transit 350"),
            ("Date", "2026-11-24"),
        ],
        "same_line_pairs": [
            ("Labor Charge 4.0 Hours", "$380.00"),
            ("Disposal Hazardous Fee", "$22.00"),
        ],
        "headers": ["Part Description", "Qty", "Unit Price", "Subtotal"],
        "rows": [
            ["Front ceramic brake pad kit", "1", "95.00", "95.00"],
            ["Front vented rotor assembly", "2", "110.00", "220.00"],
            ["Synthetic brake fluid flush", "2", "18.50", "37.00"],
        ],
        "ruled": True,
        "totals": [
            ("Parts Total", "$352.00"),
            ("Total Estimate", "$754.00"),
        ]
    },
    {
        "id": "doc_11_consulting_invoice_3col_unruled",
        "title": "SUMMIT STRATEGY ADVISORS",
        "doc_type": "invoice",
        "header_fields": [
            ("Invoice No", "SSA-2026-118"),
            ("Invoice Date", "2026-11-25"),
        ],
        "same_line_pairs": [
            ("Fixed Administrative Fee", "$120.00"),
        ],
        "headers": ["Project Phase", "Staff Hours", "Billing Amount"],
        "rows": [
            ["Stakeholder interviews & discovery", "20", "3500.00"],
            ["Market competitive benchmarking", "15", "2625.00"],
            ["Executive presentation & readout", "10", "1750.00"],
        ],
        "ruled": False,
        "totals": [
            ("Professional Fees Total", "$7,875.00"),
            ("Total Amount Due", "$7,995.00"),
        ]
    },
    {
        "id": "doc_12_sales_order_5col_unruled",
        "title": "BEACON OFFICE SUPPLIES",
        "doc_type": "sales_order",
        "header_fields": [
            ("Order Reference", "ORD-88203"),
            ("Order Date", "2026-11-22"),
        ],
        "same_line_pairs": [
            ("Standard Courier Delivery", "$15.00"),
        ],
        "headers": ["SKU", "Item Description", "Qty", "Price", "Ext Price"],
        "rows": [
            ["SUP-101", "Ergonomic mesh office chair", "4", "189.00", "756.00"],
            ["SUP-204", "Electric standing desk converter", "2", "249.00", "498.00"],
            ["SUP-308", "Anti-fatigue comfort standing mat", "4", "45.00", "180.00"],
        ],
        "ruled": False,
        "totals": [
            ("Order Subtotal", "$1,434.00"),
            ("Total Order Value", "$1,449.00"),
        ]
    },
    {
        "id": "doc_13_lab_results_3col_ruled",
        "title": "BIO-ANALYTICAL LABORATORIES",
        "doc_type": "test_report",
        "header_fields": [
            ("Specimen ID", "SPC-991204"),
            ("Collection Date", "2026-11-20"),
        ],
        "same_line_pairs": [
            ("Testing Facility Location", "Main Lab Suite 300"),
        ],
        "headers": ["Analyte / Assay", "Reported Value", "Reference Range"],
        "rows": [
            ["Glucose Fasting Plasma", "92 mg/dL", "70 - 99 mg/dL"],
            ["Cholesterol Total", "178 mg/dL", "125 - 200 mg/dL"],
            ["Triglycerides Fasting", "110 mg/dL", "40 - 150 mg/dL"],
        ],
        "ruled": True,
        "totals": [
            ("Status", "All tests completed within normal parameters"),
        ]
    },
    {
        "id": "doc_14_utility_breakdown_4col_ruled",
        "title": "METROPOLITAN WATER & POWER",
        "doc_type": "utility_bill",
        "header_fields": [
            ("Account Number", "UTIL-440192"),
            ("Statement Date", "2026-11-21"),
        ],
        "same_line_pairs": [
            ("Previous Balance Forward", "$0.00"),
            ("Municipal Infrastructure Fee", "$9.50"),
        ],
        "headers": ["Utility Service", "Meter Read", "Units Used", "Total Charge"],
        "rows": [
            ["Residential Electric Tier 1", "44820 kWh", "450 kWh", "67.50"],
            ["Residential Electric Tier 2", "45020 kWh", "200 kWh", "38.00"],
            ["Clean Water Supply Service", "12080 Gal", "3500 Gal", "42.50"],
        ],
        "ruled": True,
        "totals": [
            ("Usage Charges Total", "$148.00"),
            ("Total Amount Due", "$157.50"),
        ]
    },
    {
        "id": "doc_15_catering_invoice_6col_ruled",
        "title": "SAVORY TABLE CATERING CO",
        "doc_type": "invoice",
        "header_fields": [
            ("Event Invoice ID", "EVT-2026-77"),
            ("Event Date", "2026-11-23"),
            ("Venue", "Harbor View Ballroom"),
        ],
        "same_line_pairs": [
            ("Service Staff Gratuity", "$180.00"),
            ("Linens Rental Surcharge", "$65.00"),
        ],
        "headers": ["Course", "Menu Item Selection", "Guests", "Unit Cost", "Tax Rate", "Total"],
        "rows": [
            ["Appetizer", "Smoked salmon crostini dill", "50", "8.50", "8%", "425.00"],
            ["Entree", "Grilled rosemary beef tenderloin", "50", "28.00", "8%", "1400.00"],
            ["Dessert", "Dark chocolate raspberry mousse", "50", "7.50", "8%", "375.00"],
        ],
        "ruled": True,
        "totals": [
            ("Food Subtotal", "$2,200.00"),
            ("Total Invoice Due", "$2,445.00"),
        ]
    },
]

def generate_pdf(spec):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # Standard A4: 595 x 842 pt
    
    # 1. Top Organization / Title Block (No printed label -> Issuer Name)
    page.insert_text((50, 50), spec["title"], fontsize=14, fontname="helv", color=(0.1, 0.1, 0.2))
    
    # 2. Header Fields (colon separated)
    y = 80
    for lbl, val in spec["header_fields"]:
        page.insert_text((50, y), f"{lbl}: {val}", fontsize=10, fontname="helv", color=(0.2, 0.2, 0.2))
        y += 18
        
    # 3. Same-line pair(s) at left edge and right edge
    y += 10
    for lbl, val in spec.get("same_line_pairs", []):
        page.insert_text((50, y), lbl, fontsize=10, fontname="helv", color=(0.2, 0.2, 0.2))
        # Place value at right aligned x=500
        page.insert_text((480, y), val, fontsize=10, fontname="helv", color=(0.1, 0.1, 0.1))
        y += 18

    # 4. Table
    y += 20
    headers = spec["headers"]
    rows = spec["rows"]
    col_count = len(headers)
    table_left = 50.0
    table_right = 545.0
    total_w = table_right - table_left
    
    col_max_lens = [max(len(str(h)), max(len(str(r[c])) for r in rows)) for c, h in enumerate(headers)]
    total_len = sum(col_max_lens)
    col_widths = [max(45.0, (l / total_len) * total_w) for l in col_max_lens]
    scale = total_w / sum(col_widths)
    col_widths = [w * scale for w in col_widths]
    col_xs = [table_left]
    for w in col_widths[:-1]:
        col_xs.append(col_xs[-1] + w)
    
    # Header row
    header_y = y
    row_height = 24.0
    
    if spec["ruled"]:
        # Background rect for header
        page.draw_rect(fitz.Rect(table_left, header_y - 14, table_right, header_y + 8), color=(0.7, 0.7, 0.7), fill=(0.92, 0.92, 0.95))
        # Top line
        page.draw_line((table_left, header_y - 14), (table_right, header_y - 14), color=(0.4, 0.4, 0.4), width=1)
        # Bottom line
        page.draw_line((table_left, header_y + 8), (table_right, header_y + 8), color=(0.4, 0.4, 0.4), width=1)

    for c_idx, h in enumerate(headers):
        cx = col_xs[c_idx] + 4
        page.insert_text((cx, header_y), h, fontsize=9, fontname="helv", color=(0.1, 0.1, 0.1))
        
    y = header_y + row_height
    for r_idx, row in enumerate(rows):
        current_row_y = y
        for c_idx, val in enumerate(row):
            cx = col_xs[c_idx] + 4
            page.insert_text((cx, current_row_y), str(val), fontsize=9, fontname="helv", color=(0.15, 0.15, 0.15))
        
        if spec["ruled"]:
            # Draw row separator line
            page.draw_line((table_left, current_row_y + 6), (table_right, current_row_y + 6), color=(0.75, 0.75, 0.75), width=0.5)
            
        y += row_height
        
    if spec["ruled"]:
        # Bottom table border
        page.draw_line((table_left, y - row_height + 6), (table_right, y - row_height + 6), color=(0.4, 0.4, 0.4), width=1)

    # 5. Totals Block Under Table
    y += 15
    for t_lbl, t_val in spec.get("totals", []):
        page.insert_text((350, y), t_lbl, fontsize=10, fontname="helv", color=(0.2, 0.2, 0.2))
        page.insert_text((480, y), t_val, fontsize=10, fontname="helv", color=(0.1, 0.1, 0.1))
        y += 18
        
    pdf_path = os.path.join(INPUTS_DIR, f"{spec['id']}.pdf")
    doc.save(pdf_path)
    doc.close()
    
    # Save expected ground truth
    expected_data = {
        "id": spec["id"],
        "title": spec["title"],
        "doc_type": spec["doc_type"],
        "headers": spec["headers"],
        "rows": spec["rows"],
        "same_line_pairs": spec["same_line_pairs"],
        "totals": spec["totals"],
    }
    expected_path = os.path.join(EXPECTED_DIR, f"{spec['id']}.json")
    with open(expected_path, "w", encoding="utf-8") as f:
        json.dump(expected_data, f, indent=2)
        
    print(f"Generated {pdf_path} & {expected_path}")

def main():
    print(f"Generating 15 synthetic table documents in {OUT_DIR}...")
    for spec in DOC_SPECS:
        generate_pdf(spec)
    print("Done! All 15 documents and expected ground truths generated.")

if __name__ == "__main__":
    main()
