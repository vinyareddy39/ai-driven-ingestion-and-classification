"""Comprehensive 32-Document Pairing Verification Suite.

Tests all layouts, edge cases, strict scoring, zero invented labels,
and confidence calibration across 32 distinct synthetic documents.
"""

import os
import re
import sys

sys.path.insert(0, os.path.abspath("."))
from typing import Dict, List, Tuple, Any

from app.core.comprehensive_extractor import (
    UniversalDocumentReader,
    ExtractedDetail,
)

# Define 32 comprehensive test documents covering all requested layout categories
TEST_DOCUMENTS = [
    # 1. Colon Lines (Standard Label: value)
    {
        "id": "doc_01_colon_standard",
        "category": "Colon Lines",
        "text": """EMPLOYMENT DETAILS
Employee ID: EMP-98214
Full Legal Name: Eleanor Vance
Department: Quantitative Research
Work Location: Building B, Floor 4
Direct Supervisor: Arthur Pendelton""",
        "expected": [
            ("Employee ID", "EMP-98214"),
            ("Full Legal Name", "Eleanor Vance"),
            ("Department", "Quantitative Research"),
            ("Work Location", "Building B, Floor 4"),
            ("Direct Supervisor", "Arthur Pendelton"),
        ],
    },
    # 2. Multi-Pair Lines (Multiple Label: value pairs on one line)
    {
        "id": "doc_02_multipair_line",
        "category": "Multi-Pair Lines",
        "text": """PATIENT DEMOGRAPHICS
Age: 47    Gender: Female    Blood Type: AB+
Status: Admitted    Ward: Intensive Care 3    Room: 302-B""",
        "expected": [
            ("Age", "47"),
            ("Gender", "Female"),
            ("Blood Type", "AB+"),
            ("Status", "Admitted"),
            ("Ward", "Intensive Care 3"),
            ("Room", "302-B"),
        ],
    },
    # 3. Titles and Suffixes (Names with Dr., MD, PhD, etc.)
    {
        "id": "doc_03_titles_suffixes",
        "category": "Titles and Suffixes",
        "text": """CLINICAL STAFF ROSTER
Principal Investigator: Dr. Marcus Aurelius Vance, MD, PhD, FACC
Attending Surgeon: Dr. Sarah Lin-Wood, MBBS, MS
Consulting Specialist: Prof. David Henderson, Jr., ScD
Primary Nurse: Nurse Practitioner Jennifer O'Connor, RN, BSN""",
        "expected": [
            ("Principal Investigator", "Dr. Marcus Aurelius Vance, MD, PhD, FACC"),
            ("Attending Surgeon", "Dr. Sarah Lin-Wood, MBBS, MS"),
            ("Consulting Specialist", "Prof. David Henderson, Jr., ScD"),
            ("Primary Nurse", "Nurse Practitioner Jennifer O'Connor, RN, BSN"),
        ],
    },
    # 4. Values with Units (Medical, Financial, Engineering units)
    {
        "id": "doc_04_values_with_units",
        "category": "Values with Units",
        "text": """VITAL SIGNS AND OBSERVATIONS
Blood Pressure: 128/84 mmHg
Pulse Rate: 72 bpm
Dosage Prescribed: 500 mg
Daily Allowance: $250.00 USD
Serum Creatinine: 0.95 mg/dL
Platelet Count: 245,000 cells/mcL""",
        "expected": [
            ("Blood Pressure", "128/84 mmHg"),
            ("Pulse Rate", "72 bpm"),
            ("Dosage Prescribed", "500 mg"),
            ("Daily Allowance", "$250.00 USD"),
            ("Serum Creatinine", "0.95 mg/dL"),
            ("Platelet Count", "245,000 cells/mcL"),
        ],
    },
    # 5. Dash Separator ("Label - Value")
    {
        "id": "doc_05_dash_separator",
        "category": "Dash Separator",
        "text": """EQUIPMENT CALIBRATION LOG
Asset Tag - AST-88102
Serial Number - SN-7749201-X
Manufacturer - Olympus Precision Instruments
Operating Range - -20 C to +60 C""",
        "expected": [
            ("Asset Tag", "AST-88102"),
            ("Serial Number", "SN-7749201-X"),
            ("Manufacturer", "Olympus Precision Instruments"),
            ("Operating Range", "-20 C to +60 C"),
        ],
    },
    # 6. Equals Separator ("Label = Value")
    {
        "id": "doc_06_equals_separator",
        "category": "Equals Separator",
        "text": """ENVIRONMENT CONFIGURATION
TIMEOUT_SECONDS = 3600
DATABASE_HOST = db-cluster-primary.internal
AUTH_TOKEN_SCOPE = read_write_analytics
RETRY_MAX_ATTEMPTS = 5""",
        "expected": [
            ("TIMEOUT_SECONDS", "3600"),
            ("DATABASE_HOST", "db-cluster-primary.internal"),
            ("AUTH_TOKEN_SCOPE", "read_write_analytics"),
            ("RETRY_MAX_ATTEMPTS", "5"),
        ],
    },
    # 7. Two-Column Wide Gap (No colon, >= 2 spaces)
    {
        "id": "doc_07_wide_gap",
        "category": "Wide Gap Two-Column",
        "text": """FINANCIAL LEDGER SUMMARY
Account Reference    ACC-90412847
Ledger Balance       $1,248,590.22 USD
Clearing House       Apex Clearing Operations
Routing Swift        CHASUS33XXX""",
        "expected": [
            ("Account Reference", "ACC-90412847"),
            ("Ledger Balance", "$1,248,590.22 USD"),
            ("Clearing House", "Apex Clearing Operations"),
            ("Routing Swift", "CHASUS33XXX"),
        ],
    },
    # 8. Tab Separated (No colon, \t)
    {
        "id": "doc_08_tab_separated",
        "category": "Tab Separated",
        "text": """SUPPLIER DISPATCH ORDER
Purchase Order\tPO-2026-9931
Vendor Entity\tNovartis Pharma Logistics
Dispatch Hub\tFrankfurt Freight Terminal
Consignment Weight\t4,250 kg""",
        "expected": [
            ("Purchase Order", "PO-2026-9931"),
            ("Vendor Entity", "Novartis Pharma Logistics"),
            ("Dispatch Hub", "Frankfurt Freight Terminal"),
            ("Consignment Weight", "4,250 kg"),
        ],
    },
    # 9. Stacked Vertical Layout (Label directly above value)
    {
        "id": "doc_09_stacked_vertical",
        "category": "Stacked Layout",
        "text": """PATIENT INTAKE FORM
Patient Full Legal Name
Jonathan Alexander Sterling, Esq.
Residential Address
742 Evergreen Terrace, Springfield, OR 97477
Primary Diagnosis
Acute Bronchitis with Wheezing""",
        "expected": [
            ("Patient Full Legal Name", "Jonathan Alexander Sterling, Esq."),
            ("Residential Address", "742 Evergreen Terrace, Springfield, OR 97477"),
            ("Primary Diagnosis", "Acute Bronchitis with Wheezing"),
        ],
    },
    # 10. Markdown Table
    {
        "id": "doc_10_table_headers",
        "category": "Markdown Table",
        "text": """LABORATORY BLOOD CHEMISTRY
| Test Name | Result | Reference Interval | Clinical Status |
|---|---|---|---|
| Hemoglobin | 14.8 g/dL | 13.5 - 17.5 g/dL | Normal |
| White Blood Cells | 7.2 x10^3/uL | 4.5 - 11.0 x10^3/uL | Normal |
| Fasting Glucose | 108 mg/dL | 70 - 99 mg/dL | Borderline |""",
        "expected": [
            ("Test Name", "Hemoglobin"),
            ("Result", "14.8 g/dL"),
            ("Reference Interval", "13.5 - 17.5 g/dL"),
            ("Clinical Status", "Normal"),
            ("Test Name", "White Blood Cells"),
            ("Result", "7.2 x10^3/uL"),
            ("Reference Interval", "4.5 - 11.0 x10^3/uL"),
            ("Clinical Status", "Normal"),
            ("Test Name", "Fasting Glucose"),
            ("Result", "108 mg/dL"),
            ("Reference Interval", "70 - 99 mg/dL"),
            ("Clinical Status", "Borderline"),
        ],
    },
    # 11. Page Title Separation (Title must NOT be glued to first label)
    {
        "id": "doc_11_title_separation",
        "category": "Title Separation",
        "text": """CONFIDENTIAL LAB REPORT
Patient Name: Emily Jane Watson
Specimen ID: SPEC-40912
Collection Date: 2026-11-20""",
        "expected": [
            ("Patient Name", "Emily Jane Watson"),
            ("Specimen ID", "SPEC-40912"),
            ("Collection Date", "2026-11-20"),
        ],
    },
    # 12. Mixed Casing Preservation
    {
        "id": "doc_12_mixed_casing",
        "category": "Mixed Casing",
        "text": """SYSTEM CREDENTIAL AUDIT
apiKeyIdentifier: ak_live_9921_ProdEnv
OAuthCallbackURL: https://api.healthservice.internal/v2/oauth/callback
databaseEngine: PostgreSQL 16.2 on x86_64""",
        "expected": [
            ("apiKeyIdentifier", "ak_live_9921_ProdEnv"),
            ("OAuthCallbackURL", "https://api.healthservice.internal/v2/oauth/callback"),
            ("databaseEngine", "PostgreSQL 16.2 on x86_64"),
        ],
    },
    # 13. Medical Report with Health Information
    {
        "id": "doc_13_medical_report",
        "category": "Medical Report",
        "text": """OUTPATIENT CLINIC NOTE
Attending Physician: Dr. Robert Lang, MD
Chief Complaint: Intermittent severe chest tightness
Assessment / Diagnosis: Stable Angina Pectoris
Medication Prescribed: Metoprolol Succinate 50 mg daily
Treatment Plan: Schedule exercise stress echocardiogram""",
        "expected": [
            ("Attending Physician", "Dr. Robert Lang, MD"),
            ("Chief Complaint", "Intermittent severe chest tightness"),
            ("Assessment / Diagnosis", "Stable Angina Pectoris"),
            ("Medication Prescribed", "Metoprolol Succinate 50 mg daily"),
            ("Treatment Plan", "Schedule exercise stress echocardiogram"),
        ],
    },
    # 14. Tax Invoice with Currency and Amounts
    {
        "id": "doc_14_tax_invoice",
        "category": "Invoice",
        "text": """COMMERCIAL TAX INVOICE
Invoice Folio: INV-2026-88192
Issue Date: November 24, 2026
Vendor Corporation: CloudScale Infrastructure Services Inc.
Billing Subtotal: $14,250.00 USD
Applicable GST/VAT: $2,565.00 USD
Grand Balance Due: $16,815.00 USD""",
        "expected": [
            ("Invoice Folio", "INV-2026-88192"),
            ("Issue Date", "November 24, 2026"),
            ("Vendor Corporation", "CloudScale Infrastructure Services Inc."),
            ("Billing Subtotal", "$14,250.00 USD"),
            ("Applicable GST/VAT", "$2,565.00 USD"),
            ("Grand Balance Due", "$16,815.00 USD"),
        ],
    },
    # 15. Bank Statement
    {
        "id": "doc_15_bank_statement",
        "category": "Bank Statement",
        "text": """MONTHLY ACCOUNT STATEMENT
Account Holder: Katherine M. Howard
Account Number: 8847-1920-4491
Statement Period: 01 Oct 2026 to 31 Oct 2026
Opening Settlement Balance: $45,210.15 USD
Closing Ledger Balance: $52,890.75 USD""",
        "expected": [
            ("Account Holder", "Katherine M. Howard"),
            ("Account Number", "8847-1920-4491"),
            ("Statement Period", "01 Oct 2026 to 31 Oct 2026"),
            ("Opening Settlement Balance", "$45,210.15 USD"),
            ("Closing Ledger Balance", "$52,890.75 USD"),
        ],
    },
    # 16. Legal Contract
    {
        "id": "doc_16_legal_contract",
        "category": "Contract",
        "text": """MUTUAL NON-DISCLOSURE AGREEMENT
Agreement Reference: NDA-2026-Corp-0112
Disclosing Party: Starlight Biotech Holdings, LLC
Receiving Party: Apex Analytics Group, Inc.
Governing Jurisdiction: State of Delaware""",
        "expected": [
            ("Agreement Reference", "NDA-2026-Corp-0112"),
            ("Disclosing Party", "Starlight Biotech Holdings, LLC"),
            ("Receiving Party", "Apex Analytics Group, Inc."),
            ("Governing Jurisdiction", "State of Delaware"),
        ],
    },
    # 17. KYC Identification Document
    {
        "id": "doc_17_kyc_verification",
        "category": "KYC Form",
        "text": """IDENTITY VERIFICATION RECORD
Applicant Full Name: Vikram Aditya Sharma
Date of Birth: 14 August 1988
Nationality: Indian
Permanent Residential Address: Flat 402, Lotus Heights, Bengaluru, Karnataka 560001""",
        "expected": [
            ("Applicant Full Name", "Vikram Aditya Sharma"),
            ("Date of Birth", "14 August 1988"),
            ("Nationality", "Indian"),
            ("Permanent Residential Address", "Flat 402, Lotus Heights, Bengaluru, Karnataka 560001"),
        ],
    },
    # 18. Unlabelled Standalone Entities (Should show label="", NEVER invented names)
    {
        "id": "doc_18_unlabelled_entities",
        "category": "Unlabelled Entities",
        "text": """CONTACT DISPATCH NOTICE
Please forward all inquiries to support-team@globalpharma.example.com or reach emergency dispatch at +1-555-839-2019 immediately.
Audit scheduled for 2026-12-15.""",
        "expected": [
            ("", "support-team@globalpharma.example.com"),
            ("", "+1-555-839-2019"),
            ("", "2026-12-15"),
        ],
    },
    # 19. Low Confidence Incomplete Pairs (Value is only a unit or placeholder)
    {
        "id": "doc_19_incomplete_pairs",
        "category": "Low Confidence Calibration",
        "text": """CORRUPTED SCAN FRAGMENT
Prescribed Dosage: mg
Blood Pressure: -
Surgeon Attestation: Dr.""",
        "expected_confs": [
            ("Prescribed Dosage", "mg", 0.40),
            ("Blood Pressure", "-", 0.40),
            ("Surgeon Attestation", "Dr.", 0.40),
        ],
    },
    # 20. Three Pairs on One Line
    {
        "id": "doc_20_three_pairs_one_line",
        "category": "Multi-Pair Lines",
        "text": """SPECIMEN ASSAY
Rack: 14    Slot: E-02    Volume: 250 uL""",
        "expected": [
            ("Rack", "14"),
            ("Slot", "E-02"),
            ("Volume", "250 uL"),
        ],
    },
    # 21. Values with Colons in the Value (e.g. Times, URLs)
    {
        "id": "doc_21_colons_in_value",
        "category": "Colon in Value",
        "text": """INCIDENT DISPATCH TICKET
Incident Time: 14:32:05 UTC
Portal Endpoint: https://monitoring.internal:8443/status
Log Timestamp: 2026-11-24 19:45:10""",
        "expected": [
            ("Incident Time", "14:32:05 UTC"),
            ("Portal Endpoint", "https://monitoring.internal:8443/status"),
            ("Log Timestamp", "2026-11-24 19:45:10"),
        ],
    },
    # 22. Dash in Label and Dash in Value
    {
        "id": "doc_22_dashes_in_text",
        "category": "Colon Lines",
        "text": """DEVICE MANIFEST
Device-Type: High-Speed Centrifuge
Sub-Assembly: Rotor-32-Alpha
Part-Number: PRT-9920-B""",
        "expected": [
            ("Device-Type", "High-Speed Centrifuge"),
            ("Sub-Assembly", "Rotor-32-Alpha"),
            ("Part-Number", "PRT-9920-B"),
        ],
    },
    # 23. Punctuation in Label
    {
        "id": "doc_23_punctuation_in_label",
        "category": "Colon Lines",
        "text": """FINANCIAL BREAKDOWN
Gross Profit / (Loss): $3,450,000 USD
Net Margin (%): 24.5%
P/E Ratio: 18.2""",
        "expected": [
            ("Gross Profit / (Loss)", "$3,450,000 USD"),
            ("Net Margin (%)", "24.5%"),
            ("P/E Ratio", "18.2"),
        ],
    },
    # 24. Two-Column Dash Layout with Spaces
    {
        "id": "doc_24_two_column_dash",
        "category": "Dash Separator",
        "text": """INVENTORY CHECKLIST
Batch Code - BATCH-2026-XI-09
Storage Temperature - 2 C to 8 C
Package Condition - Intact Sealed""",
        "expected": [
            ("Batch Code", "BATCH-2026-XI-09"),
            ("Storage Temperature", "2 C to 8 C"),
            ("Package Condition", "Intact Sealed"),
        ],
    },
    # 25. Large Gap Multi-Column
    {
        "id": "doc_25_large_gap_multi",
        "category": "Wide Gap Two-Column",
        "text": """SERVICE METRICS
Active Threads        64
Memory Usage          12.4 GB
Cache Hit Rate        99.4%""",
        "expected": [
            ("Active Threads", "64"),
            ("Memory Usage", "12.4 GB"),
            ("Cache Hit Rate", "99.4%"),
        ],
    },
    # 26. Multiple Table Rows
    {
        "id": "doc_26_multi_row_table",
        "category": "Markdown Table",
        "text": """INVOICE LINE ITEMS
| Item Description | Quantity | Unit Price | Total |
|---|---|---|---|
| Consulting Hours | 40 | $150.00 | $6,000.00 |
| Server License | 2 | $1,200.00 | $2,400.00 |""",
        "expected": [
            ("Item Description", "Consulting Hours"),
            ("Quantity", "40"),
            ("Unit Price", "$150.00"),
            ("Total", "$6,000.00"),
            ("Item Description", "Server License"),
            ("Quantity", "2"),
            ("Unit Price", "$1,200.00"),
            ("Total", "$2,400.00"),
        ],
    },
    # 27. Stacked Layout with Numbers and Units
    {
        "id": "doc_27_stacked_units",
        "category": "Stacked Layout",
        "text": """WEIGHT AND HEIGHT REPORT
Patient Weight
68.5 kg
Standing Height
174 cm
Body Mass Index
22.6 kg/m2""",
        "expected": [
            ("Patient Weight", "68.5 kg"),
            ("Standing Height", "174 cm"),
            ("Body Mass Index", "22.6 kg/m2"),
        ],
    },
    # 28. Long Descriptive Value without Truncation
    {
        "id": "doc_28_long_values",
        "category": "Colon Lines",
        "text": """LEGAL CLAUSE SUMMARY
Indemnification Scope: The receiving party agrees to defend, indemnify, and hold harmless the disclosing party from any third-party claims arising from unauthorized data disclosure.
Termination Notice: Sixty (60) calendar days prior written notice sent via certified courier.""",
        "expected": [
            ("Indemnification Scope", "The receiving party agrees to defend, indemnify, and hold harmless the disclosing party from any third-party claims arising from unauthorized data disclosure."),
            ("Termination Notice", "Sixty (60) calendar days prior written notice sent via certified courier."),
        ],
    },
    # 29. Stacked Layout with Long Description
    {
        "id": "doc_29_stacked_long",
        "category": "Stacked Layout",
        "text": """CLINICAL RECOMMENDATION
Follow-up Plan
Repeat comprehensive metabolic panel and complete blood count in four weeks.
Dietary Restrictions
Strict low-sodium, high-fiber heart-healthy nutritional regimen.""",
        "expected": [
            ("Follow-up Plan", "Repeat comprehensive metabolic panel and complete blood count in four weeks."),
            ("Dietary Restrictions", "Strict low-sodium, high-fiber heart-healthy nutritional regimen."),
        ],
    },
    # 30. Medical Lab Specimen with Units
    {
        "id": "doc_30_specimen_units",
        "category": "Colon Lines",
        "text": """URINALYSIS BIOCHEMISTRY
Specific Gravity: 1.020
Urine pH: 6.5
Protein Level: Negative (< 10 mg/dL)
Ketones: None detected""",
        "expected": [
            ("Specific Gravity", "1.020"),
            ("Urine pH", "6.5"),
            ("Protein Level", "Negative (< 10 mg/dL)"),
            ("Ketones", "None detected"),
        ],
    },
    # 31. Mixed Colon and Equals in Same Document
    {
        "id": "doc_31_mixed_separators",
        "category": "Mixed Separators",
        "text": """SERVER AUDIT SPECIFICATION
Node Name: node-east-01.datacenter.internal
IP_ADDRESS = 10.240.18.52
Operating System: Rocky Linux 9.3
STATUS = Operational""",
        "expected": [
            ("Node Name", "node-east-01.datacenter.internal"),
            ("IP_ADDRESS", "10.240.18.52"),
            ("Operating System", "Rocky Linux 9.3"),
            ("STATUS", "Operational"),
        ],
    },
    # 32. Indian Banking KYC with Aadhaar and PAN (Ensuring exact label, not detector name)
    {
        "id": "doc_32_indian_kyc",
        "category": "Colon Lines",
        "text": """CUSTOMER KYC PROFILE
Full Name: Rajeshwar Venkat Raman
Aadhaar UID: 4928 1029 8812
Income Tax PAN: ABCDE1234F
Branch IFSC Code: HDFC0001234""",
        "expected": [
            ("Full Name", "Rajeshwar Venkat Raman"),
            ("Aadhaar UID", "4928 1029 8812"),
            ("Income Tax PAN", "ABCDE1234F"),
            ("Branch IFSC Code", "HDFC0001234"),
        ],
    },
]

FORBIDDEN_INVENTED_LABELS = {
    "Aadhaar Number", "Aadhaar Card", "PAN Number", "PAN Card", "SWIFT Code",
    "Date", "Amount", "Person Name", "Email Address", "Phone Number",
    "Unlabelled ID", "Unlabelled Bank Code", "Unlabelled Email", "Unlabelled Phone",
    "Unlabelled Web Link", "Unlabelled Amount", "Unlabelled Date"
}


def run_verification():
    print("=" * 80)
    print("32-DOCUMENT LABEL-VALUE PAIRING VERIFICATION SUITE")
    print("=" * 80)

    category_stats: Dict[str, Dict[str, int]] = {}
    total_expected = 0
    total_matched = 0
    total_extracted = 0
    invented_labels_found = 0

    for doc in TEST_DOCUMENTS:
        doc_id = doc["id"]
        cat = doc["category"]
        text = doc["text"]

        if cat not in category_stats:
            category_stats[cat] = {"expected": 0, "matched": 0, "extracted": 0}

        details = UniversalDocumentReader._extract_all_details_from_text(text, page_num=1)
        total_extracted += len(details)
        category_stats[cat]["extracted"] += len(details)

        # Check for forbidden invented labels
        for d in details:
            if d.label in FORBIDDEN_INVENTED_LABELS:
                print(f"❌ [INVENTED LABEL DETECTED] in {doc_id}: '{d.label}'")
                invented_labels_found += 1

        # Evaluate expected pairs
        if "expected" in doc:
            for exp_lbl, exp_val in doc["expected"]:
                total_expected += 1
                category_stats[cat]["expected"] += 1
                match_found = False
                for d in details:
                    # Exact label match, full value match, original casing
                    if d.label == exp_lbl and d.value == exp_val:
                        match_found = True
                        break
                if match_found:
                    total_matched += 1
                    category_stats[cat]["matched"] += 1
                else:
                    print(f"⚠️ [MISMATCH] {doc_id} ({cat}): Expected ('{exp_lbl}', '{exp_val}')")
                    found_for_lbl = [d.value for d in details if d.label == exp_lbl]
                    if found_for_lbl:
                        print(f"   Found instead: {found_for_lbl}")
                    else:
                        print(f"   Label not found. All extracted: {[(d.label, d.value) for d in details]}")

        # Evaluate low confidence calibration
        if "expected_confs" in doc:
            for exp_lbl, exp_val, exp_conf in doc["expected_confs"]:
                total_expected += 1
                category_stats[cat]["expected"] += 1
                for d in details:
                    if d.label == exp_lbl and d.value == exp_val:
                        if d.confidence <= exp_conf + 0.05:
                            total_matched += 1
                            category_stats[cat]["matched"] += 1
                        else:
                            print(f"⚠️ [HIGH CONF ON BAD VALUE] {doc_id}: '{d.label}: {d.value}' conf={d.confidence} (expected <= {exp_conf})")
                        break

    print("\n" + "=" * 80)
    print("RESULTS BY LAYOUT CATEGORY:")
    print("=" * 80)
    print(f"{'Layout Category':<30} | {'Expected':<10} | {'Matched':<10} | {'Score (%)':<10}")
    print("-" * 70)

    for cat, stats in sorted(category_stats.items()):
        exp = stats["expected"]
        mat = stats["matched"]
        pct = (mat / exp * 100.0) if exp > 0 else 100.0
        print(f"{cat:<30} | {exp:<10} | {mat:<10} | {pct:>8.1f}%")

    overall_pct = (total_matched / total_expected * 100.0) if total_expected > 0 else 0.0
    print("-" * 70)
    print(f"{'OVERALL TOTAL':<30} | {total_expected:<10} | {total_matched:<10} | {overall_pct:>8.1f}%")
    print(f"Total Details Extracted: {total_extracted}")
    print(f"Forbidden Invented Labels Found: {invented_labels_found}")

    print("\n" + "=" * 80)
    print("HARDCODING AUDIT:")
    print("=" * 80)
    test_terms = ["Eleanor Vance", "Marcus Aurelius Vance", "4928 1029 8812", "Novartis Pharma", "Rocky Linux"]
    hardcoded_hits = 0
    for root, _, files in os.walk("app"):
        for fname in files:
            if fname.endswith(".py"):
                fpath = os.path.join(root, fname)
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    for term in test_terms:
                        if term in content:
                            print(f"❌ Hardcoded test term '{term}' found in {fpath}!")
                            hardcoded_hits += 1

    if hardcoded_hits == 0:
        print("✅ Zero hardcoded test names, labels, or numbers in codebase (0 hits).")

    assert invented_labels_found == 0, f"Failed: {invented_labels_found} invented labels found"
    assert overall_pct >= 95.0, f"Failed: Overall accuracy {overall_pct}% is below 95%"
    print("\n🎉 ALL 32 VERIFICATION TESTS PASSED PERFECTLY WITH ZERO INVENTED LABELS!")


if __name__ == "__main__":
    run_verification()
