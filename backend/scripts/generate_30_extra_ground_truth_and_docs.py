import os
import json
import hashlib
import time
from datetime import datetime, timezone
import fitz
import numpy as np
import cv2

GT_DIR = "evidence/20261126_212000/ground_truth"
DOCS_DIR = "test_inputs/extra_30"
MANIFEST_PATH = "evidence/20261126_212000/file_timestamps_manifest.json"

os.makedirs(GT_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)

# Copy base 40 ground truth
src_gt = "evidence/20261126_160500/expected_answers"
if os.path.exists(src_gt):
    for f in os.listdir(src_gt):
        if f.endswith(".json"):
            with open(os.path.join(src_gt, f), "r", encoding="utf-8") as rf:
                data = json.load(rf)
            with open(os.path.join(GT_DIR, f), "w", encoding="utf-8") as wf:
                json.dump(data, wf, indent=2)

extra_specs = [
    # 1-5 Noisy / Skewed Image scans
    {"name": "syn_extra_01_noisy_receipt.png", "kind": "receipt", "type": "image_noisy", "text": "STARBUCKS STORE #1042\nTOTAL: $14.85\nDATE: 2026-11-20\nTAX: $1.20\nITEMS: 2", "fields": {"STORE": "#1042", "TOTAL": "$14.85", "DATE": "2026-11-20"}},
    {"name": "syn_extra_02_skewed_invoice.png", "kind": "invoice", "type": "image_skewed", "text": "ACME INDUSTRIAL SUPPLIES\nINVOICE: INV-9901\nAMOUNT DUE: $4,500.00\nDUE DATE: 2026-12-15", "fields": {"INVOICE": "INV-9901", "AMOUNT DUE": "$4,500.00", "DUE DATE": "2026-12-15"}},
    {"name": "syn_extra_03_faint_receipt.png", "kind": "receipt", "type": "image_faint", "text": "CENTRAL PARKING GARAGE\nHOURS: 4\nFEE: $24.00\nPLATE: 7XYZ89", "fields": {"FEE": "$24.00", "HOURS": "4", "PLATE": "7XYZ89"}},
    {"name": "syn_extra_04_shadowed_bill.png", "kind": "utility_bill", "type": "image_shadow", "text": "CITY WATER DEPT\nACCOUNT: 4490182\nBALANCE: $88.50\nSERVICE TO: NOV 2026", "fields": {"ACCOUNT": "4490182", "BALANCE": "$88.50"}},
    {"name": "syn_extra_05_stained_memo.png", "kind": "letter", "type": "image_stained", "text": "INTERNAL AUDIT NOTICE\nDATE: 2026-11-25\nAUDITOR: JOHN DOE\nSTATUS: IN PROGRESS", "fields": {"DATE": "2026-11-25", "AUDITOR": "JOHN DOE", "STATUS": "IN PROGRESS"}},
    
    # 6-10 Image-only PDFs (scanned raster in PDF container)
    {"name": "syn_extra_06_image_only_contract.pdf", "kind": "contract", "type": "pdf_image_only", "text": "MASTER SERVICES AGREEMENT\nBETWEEN: DELTA CORP AND EPSILON LLC\nEFFECTIVE: 2026-11-01\nGOVERNING LAW: DELAWARE", "fields": {"BETWEEN": "DELTA CORP AND EPSILON LLC", "EFFECTIVE": "2026-11-01", "GOVERNING LAW": "DELAWARE"}},
    {"name": "syn_extra_07_image_only_statement.pdf", "kind": "bank_statement", "type": "pdf_image_only", "text": "FIRST HORIZON BANK\nSTATEMENT PERIOD: 2026-10-01 TO 2026-10-31\nCLOSING BALANCE: $32,450.12", "fields": {"STATEMENT PERIOD": "2026-10-01 TO 2026-10-31", "CLOSING BALANCE": "$32,450.12"}},
    {"name": "syn_extra_08_image_only_invoice.pdf", "kind": "invoice", "type": "pdf_image_only", "text": "LOGISTICS FORWARDING CORP\nBILL TO: ABC ENTERPRISE\nINVOICE: LF-8821\nTOTAL: $1,280.00", "fields": {"INVOICE": "LF-8821", "TOTAL": "$1,280.00"}},
    {"name": "syn_extra_09_image_only_medical.pdf", "kind": "medical_report", "type": "pdf_image_only", "text": "METROPOLITAN HOSPITAL\nPATIENT: SAMUEL GREEN\nDIAGNOSIS: HYPERTENSION\nDATE: 2026-11-18", "fields": {"PATIENT": "SAMUEL GREEN", "DIAGNOSIS": "HYPERTENSION", "DATE": "2026-11-18"}},
    {"name": "syn_extra_10_image_only_kyc.pdf", "kind": "kyc_form", "type": "pdf_image_only", "text": "CLIENT VERIFICATION FORM\nFULL NAME: MARIA SANTOS\nCITIZENSHIP: UNITED STATES\nOCCUPATION: ARCHITECT", "fields": {"FULL NAME": "MARIA SANTOS", "CITIZENSHIP": "UNITED STATES", "OCCUPATION": "ARCHITECT"}},
    
    # 11-15 Multi-page documents
    {"name": "syn_extra_11_multipage_contract_3p.pdf", "kind": "contract", "type": "pdf_multipage", "pages": 3, "text": "COMMERCIAL LEASE AGREEMENT\nTENANT: OMEGA SYSTEMS\nRENT: $8,500/MONTH\nTERM: 36 MONTHS", "fields": {"TENANT": "OMEGA SYSTEMS", "RENT": "$8,500/MONTH", "TERM": "36 MONTHS"}},
    {"name": "syn_extra_12_multipage_invoice_2p.pdf", "kind": "invoice", "type": "pdf_multipage", "pages": 2, "text": "GLOBAL TECH HARDWARE\nINVOICE NO: GTH-55102\nTOTAL PAYABLE: $15,900.00\nDUE DATE: 2026-12-30", "fields": {"INVOICE NO": "GTH-55102", "TOTAL PAYABLE": "$15,900.00"}},
    {"name": "syn_extra_13_multipage_statement_2p.pdf", "kind": "bank_statement", "type": "pdf_multipage", "pages": 2, "text": "PACIFIC STANDARD BANK\nACCOUNT NO: 987654321\nBEGINNING BALANCE: $10,000.00\nENDING BALANCE: $18,400.00", "fields": {"ACCOUNT NO": "987654321", "ENDING BALANCE": "$18,400.00"}},
    {"name": "syn_extra_14_multipage_report_4p.pdf", "kind": "medical_report", "type": "pdf_multipage", "pages": 4, "text": "COMPREHENSIVE ONCOLOGY REPORT\nPATIENT ID: ONC-4412\nPHYSICIAN: DR. EMILY VANCE\nFINDING: REMISSION", "fields": {"PATIENT ID": "ONC-4412", "PHYSICIAN": "DR. EMILY VANCE"}},
    {"name": "syn_extra_15_multipage_customs_2p.pdf", "kind": "customs_declaration", "type": "pdf_multipage", "pages": 2, "text": "IMPORT CUSTOMS ENTRY\nPORT OF ENTRY: LOS ANGELES\nDECLARANT: PACIFIC IMPORT LLC\nDUTY ASSESSED: $450.00", "fields": {"PORT OF ENTRY": "LOS ANGELES", "DUTY ASSESSED": "$450.00"}},

    # 16-20 No-label documents (unlabelled data / pure text / tables without explicit headers)
    {"name": "syn_extra_16_nolabel_values.pdf", "kind": "unknown", "type": "pdf_nolabel", "text": "98401294\n2026-11-20\n492.50\nAPPROVED", "fields": {}},
    {"name": "syn_extra_17_nolabel_address_block.pdf", "kind": "letter", "type": "pdf_nolabel", "text": "JOHNATHAN DOE\n452 EVERGREEN TERRACE\nSPRINGFIELD IL 62704\nCONFIDENTIAL", "fields": {}},
    {"name": "syn_extra_18_nolabel_code_dump.pdf", "kind": "unknown", "type": "pdf_nolabel", "text": "0x4A 0x2B 0x9F 0x01\nCHECKSUM: 0xEE41\nBUFFER: 1024", "fields": {}},
    {"name": "syn_extra_19_nolabel_receipt_rows.pdf", "kind": "receipt", "type": "pdf_nolabel", "text": "BURGER 8.50\nFRIES 3.50\nSODA 2.00\nTOTAL 14.00", "fields": {"TOTAL": "14.00"}},
    {"name": "syn_extra_20_nolabel_shipping_coords.pdf", "kind": "shipping_note", "type": "pdf_nolabel", "text": "BAY 4 SHELF 12\nCONTAINER #89012\nWEIGHT 450KG", "fields": {}},

    # 21-25 Unknown-kind documents
    {"name": "syn_extra_21_astronomy_telescope_log.pdf", "kind": "unknown", "type": "pdf_unknown", "text": "MAUNA KEA OBSERVATORY LOG\nTARGET: NGC 4565\nEXPOSURE: 1800 SECONDS\nFILTER: H-ALPHA\nSEEING: 0.65 ARCSEC", "fields": {"TARGET": "NGC 4565", "EXPOSURE": "1800 SECONDS"}},
    {"name": "syn_extra_22_culinary_recipe.pdf", "kind": "unknown", "type": "pdf_unknown", "text": "ARTISAN SOURDOUGH BREAD\nFLOUR: 500G\nWATER: 350G\nSTARTER: 100G\nSALT: 10G\nFERMENTATION: 4 HOURS", "fields": {"FLOUR": "500G", "WATER": "350G"}},
    {"name": "syn_extra_23_chess_pgn_game.pdf", "kind": "unknown", "type": "pdf_unknown", "text": "CHESS TOURNAMENT ROUND 4\nWHITE: KASPAROV\nBLACK: ANAND\nRESULT: 1/2-1/2\nECO: B90\nMOVES: 1.e4 c5 2.Nf3 d6", "fields": {"WHITE": "KASPAROV", "BLACK": "ANAND", "RESULT": "1/2-1/2"}},
    {"name": "syn_extra_24_poetry_anthology.pdf", "kind": "unknown", "type": "pdf_unknown", "text": "SONNET OF THE STARS\nUPON THE MOUNTAIN HEIGHTS SO HIGH\nTHE SILENT STARS TRAVERSE THE SKY\nTRANSCENDING ALL OF HUMAN CARE", "fields": {}},
    {"name": "syn_extra_25_weather_station_telemetry.pdf", "kind": "unknown", "type": "pdf_unknown", "text": "METEOROLOGICAL STATION 994\nTEMP: 14.2 C\nHUMIDITY: 78%\nPRESSURE: 1013.2 HPA\nWIND: 12 KNOTS NW", "fields": {"TEMP": "14.2 C", "PRESSURE": "1013.2 HPA"}},

    # 26-30 Standard multi-structure business documents
    {"name": "syn_extra_26_equipment_lease.pdf", "kind": "contract", "type": "pdf_business", "text": "CATERPILLAR EXCAVATOR LEASE\nLESSOR: HEAVY EQUIP RENTALS\nLESSEE: BUILDERS CORP\nMONTHLY RATE: $3,200", "fields": {"LESSOR": "HEAVY EQUIP RENTALS", "MONTHLY RATE": "$3,200"}},
    {"name": "syn_extra_27_hotel_folio.pdf", "kind": "receipt", "type": "pdf_business", "text": "GRAND HYATT HOTEL\nGUEST: DAVID MILLER\nROOM 408\nCHECK IN: 2026-11-20\nTOTAL CHARGES: $840.00", "fields": {"GUEST": "DAVID MILLER", "TOTAL CHARGES": "$840.00"}},
    {"name": "syn_extra_28_consulting_invoice.pdf", "kind": "invoice", "type": "pdf_business", "text": "STRATEGY PARTNERS LLC\nINVOICE #: SP-2026-99\nCLIENT: FINTECH GLOBAL\nTOTAL DUE: $22,500.00", "fields": {"INVOICE #": "SP-2026-99", "TOTAL DUE": "$22,500.00"}},
    {"name": "syn_extra_29_credit_card_statement.pdf", "kind": "bank_statement", "type": "pdf_business", "text": "PLATINUM REWARDS CARD\nSTATEMENT DATE: 2026-11-15\nNEW BALANCE: $1,420.55\nMINIMUM PAYMENT: $35.00", "fields": {"STATEMENT DATE": "2026-11-15", "NEW BALANCE": "$1,420.55"}},
    {"name": "syn_extra_30_certificate_completion.pdf", "kind": "certificate", "type": "pdf_business", "text": "CERTIFICATE OF COMPLETION\nAWARDED TO: SARAH CONNOR\nPROGRAM: ADVANCED MACHINE LEARNING\nDATE: 2026-11-22", "fields": {"AWARDED TO": "SARAH CONNOR", "DATE": "2026-11-22"}}
]

manifest = {"generated_at": datetime.now(timezone.utc).isoformat(), "files": {}}

for spec in extra_specs:
    fn = spec["name"]
    fp = os.path.join(DOCS_DIR, fn)
    gt_fn = fn.rsplit(".", 1)[0] + ".json"
    gt_fp = os.path.join(GT_DIR, gt_fn)
    
    # 1. Generate ground truth
    gt_data = {
        "file": fn,
        "expected_type": spec["kind"],
        "expected_routing": f"{spec['kind'].upper()}_PROCESSING_SYSTEM" if spec["kind"] != "unknown" else "MANUAL_TRIAGE_QUEUE",
        "expected_fields": spec.get("fields", {}),
        "full_text": spec.get("text", "")
    }
    with open(gt_fp, "w", encoding="utf-8") as gf:
        json.dump(gt_data, gf, indent=2)

    # 2. Generate actual file
    if fn.endswith(".png"):
        # Create image using opencv
        img = np.ones((800, 600, 3), dtype=np.uint8) * 255
        # draw text
        y = 50
        for line in spec["text"].split("\n"):
            cv2.putText(img, line, (40, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
            y += 40
        if "noisy" in spec["type"]:
            noise = np.random.normal(0, 25, img.shape).astype(np.uint8)
            img = cv2.add(img, noise)
        elif "skewed" in spec["type"]:
            M = cv2.getRotationMatrix2D((300, 400), 5.0, 1.0)
            img = cv2.warpAffine(img, M, (600, 800), borderValue=(255, 255, 255))
        elif "faint" in spec["type"]:
            img = cv2.addWeighted(img, 0.3, np.ones_like(img)*255, 0.7, 0)
        cv2.imwrite(fp, img)
    else:
        # Create PDF using PyMuPDF
        doc = fitz.open()
        num_pages = spec.get("pages", 1)
        for p in range(num_pages):
            page = doc.new_page(width=595, height=842)
            if "image_only" in spec["type"]:
                # insert raster image into page without text layer
                img = np.ones((1000, 750, 3), dtype=np.uint8) * 255
                y = 80
                for line in spec["text"].split("\n"):
                    cv2.putText(img, line, (50, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20, 20, 20), 2)
                    y += 50
                _, img_bytes = cv2.imencode(".png", img)
                page.insert_image(page.rect, stream=img_bytes.tobytes())
            else:
                page.insert_text((50, 60), f"Page {p+1} of {num_pages}", fontsize=9, color=(0.4, 0.4, 0.4))
                y = 100
                for line in spec["text"].split("\n"):
                    page.insert_text((50, y), line, fontsize=12, color=(0, 0, 0))
                    y += 24
        doc.save(fp)
        doc.close()

    # Record manifest
    with open(fp, "rb") as f_in:
        content_hash = hashlib.sha256(f_in.read()).hexdigest()
    stat = os.stat(fp)
    manifest["files"][fn] = {
        "size_bytes": stat.st_size,
        "sha256": content_hash,
        "created_timestamp": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
        "ground_truth_file": gt_fn
    }

with open(MANIFEST_PATH, "w", encoding="utf-8") as mf:
    json.dump(manifest, mf, indent=2)

print(f"Generated 30 extra test documents in {DOCS_DIR}")
print(f"Ground truth saved to {GT_DIR}")
print(f"Timestamps manifest recorded at {MANIFEST_PATH}")
