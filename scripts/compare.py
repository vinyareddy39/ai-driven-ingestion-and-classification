"""Exact case-sensitive comparison of stored fields against ground truth answer key."""

import json
import sqlite3

ANSWER_KEY = {
    "invoice_20280001.pdf": {
        "invoice_number": "INV-20280001",
        "date": "2026-05-15",
        "vendor": "Gross Inc",
        "ein": "22-1240184",
        "phone": "9665580351",
        "email": "tadams@example.net",
        "total": "11792.88",
    },
    "invoice_20280002.pdf": {
        "invoice_number": "INV-20280002",
        "date": "2026-10-07",
        "vendor": "Rose and Sons",
        "ein": "80-1953891",
        "phone": "+1-266-469-5215x9336",
        "email": "micheleduke@example.com",
        "total": "10061.87",
    },
    "invoice_20280003.pdf": {
        "invoice_number": "INV-20280003",
        "date": "2026-11-01",
        "vendor": "Collins-Farrell",
        "ein": "73-4186272",
        "phone": "538.584.7530",
        "email": "gilmorechristopher@example.org",
        "total": "2848.04",
    },
    "invoice_20280004.pdf": {
        "invoice_number": "INV-20280004",
        "date": "2026-07-05",
        "vendor": "Wilson-Lynn",
        "ein": "86-1773133",
        "phone": "(504)596-9855x2031",
        "email": "amedina@example.net",
        "total": "7071.80",
    },
    "invoice_20280005.pdf": {
        "invoice_number": "INV-20280005",
        "date": "2026-04-20",
        "vendor": "Williams-Morris",
        "ein": "93-7898802",
        "phone": "4862670067",
        "email": "xsimpson@example.org",
        "total": "6053.96",
    },
    "invoice_20280006.pdf": {
        "invoice_number": "INV-20280006",
        "date": "2026-03-15",
        "vendor": "Greene, Baker and Mack",
        "ein": "53-3773528",
        "phone": "770-990-1286x10134",
        "email": "jennifer15@example.net",
        "total": "10791.11",
    },
    "invoice_20280007.pdf": {
        "invoice_number": "INV-20280007",
        "date": "2026-04-21",
        "vendor": "Allen, Frazier and Becker",
        "ein": "89-4748831",
        "phone": "(390)218-7271x5812",
        "email": "fordzachary@example.net",
        "total": "16724.03",
    },
    "invoice_20280008.pdf": {
        "invoice_number": "INV-20280008",
        "date": "2026-05-30",
        "vendor": "Oneill, Murray and Jefferson",
        "ein": "33-7313130",
        "phone": "(523)523-9637x2549",
        "email": "connie09@example.com",
        "total": "1225.49",
    },
    "invoice_20280009.pdf": {
        "invoice_number": "INV-20280009",
        "date": "2026-05-06",
        "vendor": "Mcmillan LLC",
        "ein": "49-4729111",
        "phone": "001-694-765-2989",
        "email": "lopezjerry@example.net",
        "total": "22573.78",
    },
    "invoice_20280010.pdf": {
        "invoice_number": "INV-20280010",
        "date": "2026-01-07",
        "vendor": "White-Romero",
        "ein": "70-7264111",
        "phone": "001-948-518-4387x1250",
        "email": "megan12@example.com",
        "total": "21345.14",
    },
}

conn = sqlite3.connect("data/ecm_pipeline.db")
c = conn.cursor()

batch_id = "batch-def18c71a033"
rows = c.execute(
    """
    SELECT file_name, extracted_fields_json, pii_entities_json
    FROM ecm_documents
    WHERE batch_id = ?
    ORDER BY file_name
""",
    (batch_id,),
).fetchall()

field_keys = ["invoice_number", "date", "vendor", "ein", "phone", "email", "total"]

print(
    f"{'File Name':<24} | {'Inv Num':<7} | {'Date':<5} | {'Vendor':<6} | {'EIN':<5} | {'Phone':<5} | {'Email':<5} | {'Total':<5} | Score"
)
print("-" * 88)

total_passed = 0
total_checked = 0

grid_rows = []

for fn, fields_json, pii_json in rows:
    fields = json.loads(fields_json) if fields_json else {}
    expected = ANSWER_KEY.get(fn, {})

    # Extract stored values strictly as stored
    stored_inv_num = fields.get("invoice_number")
    stored_date = fields.get("invoice_date")
    stored_vendor = fields.get("vendor_name")
    stored_ein = fields.get("ein") or fields.get("taxpayer_ein")  # None
    stored_phone = fields.get("phone") or fields.get("contact_phone")  # None
    stored_email = fields.get("email") or fields.get("accounts_email")  # None
    stored_total = (
        str(fields.get("total_amount"))
        if fields.get("total_amount") is not None
        else None
    )

    row_scores = {}

    # Exact matching checks (case-sensitive)
    row_scores["invoice_number"] = stored_inv_num == expected.get(
        "invoice_number"
    )
    row_scores["date"] = stored_date == expected.get("date")
    row_scores["vendor"] = stored_vendor == expected.get("vendor")
    row_scores["ein"] = stored_ein == expected.get("ein")
    row_scores["phone"] = stored_phone == expected.get("phone")
    row_scores["email"] = stored_email == expected.get("email")

    exp_tot = float(expected.get("total", "0").replace(",", ""))
    st_tot = (
        float(stored_total)
        if stored_total and stored_total.replace(".", "", 1).isdigit()
        else -1.0
    )
    row_scores["total"] = abs(st_tot - exp_tot) < 0.01

    row_pass_cnt = sum(1 for v in row_scores.values() if v)
    total_passed += row_pass_cnt
    total_checked += len(field_keys)

    def p(val):
        return "PASS" if val else "FAIL"

    print(
        f"{fn:<24} | {p(row_scores['invoice_number']):<7} | {p(row_scores['date']):<5} | {p(row_scores['vendor']):<6} | {p(row_scores['ein']):<5} | {p(row_scores['phone']):<5} | {p(row_scores['email']):<5} | {p(row_scores['total']):<5} | {row_pass_cnt}/7"
    )

    grid_rows.append(
        {
            "file": fn,
            "scores": row_scores,
            "stored": {
                "invoice_number": stored_inv_num,
                "date": stored_date,
                "vendor": stored_vendor,
                "ein": stored_ein,
                "phone": stored_phone,
                "email": stored_email,
                "total": stored_total,
            },
            "expected": expected,
        }
    )

print("-" * 88)
print(
    f"OVERALL SCORE: {total_passed} / {total_checked} ({round((total_passed/total_checked)*100, 1)}%)"
)
