import json
from pathlib import Path

h3_dir = Path("data/dataset/holdout3")
unknown_files = sorted([f for f in h3_dir.glob("h3_unknown_*.json")])

categories = {
    "quote": [],
    "purchase_requisition": [],
    "letter_invoice_dispute": [],
    "lookalike_unknown": []
}

for uf in unknown_files:
    with open(uf, "r", encoding="utf-8") as f:
        meta = json.load(f)
    text = meta["full_text"]
    if "QUOTATION" in text or "ESTIMATE" in text:
        categories["quote"].append((meta["doc_id"], text))
    elif "REQUISITION DRAFT" in text or "INT-REQ" in text:
        categories["purchase_requisition"].append((meta["doc_id"], text))
    elif "OFFICE OF LEGAL COUNSEL" in text or "Disputed Billing" in text:
        categories["letter_invoice_dispute"].append((meta["doc_id"], text))
    else:
        categories["lookalike_unknown"].append((meta["doc_id"], text))

print("=" * 80)
print("HARD NEGATIVES AUDIT (HOLDOUT 3: 40 DOCUMENTS)")
print("=" * 80)
for cat, items in categories.items():
    print(f"\nCategory: {cat.upper()} (Count: {len(items)})")
    if items:
        sample_id, sample_text = items[0]
        print(f"Sample Document: {sample_id}")
        print("Sample Text:")
        for line in sample_text.strip().split("\n")[:8]:
            print(f"  | {line}")
print("=" * 80)
