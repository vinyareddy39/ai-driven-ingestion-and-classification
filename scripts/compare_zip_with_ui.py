import zipfile
import json
import os
import csv

zip_path = "evidence/20261126_212000/raw_outputs/batch1_export.zip"
ui_json_path = "evidence/20261126_212000/raw_outputs/ui_scraped_results.json"
out_comparison = "evidence/20261126_212000/raw_outputs/zip_vs_ui_comparison.json"

if not os.path.exists(zip_path):
    print(f"Zip file {zip_path} not found")
    exit(0)

with open(ui_json_path, "r", encoding="utf-8") as f:
    ui_data = json.load(f)

b1_ui_files = set(item["file_name"] for item in ui_data.get("batch1_extra_files", []))

with zipfile.ZipFile(zip_path, "r") as z:
    zip_names = z.namelist()
    
# Check original_documents in zip
zip_docs = set(os.path.basename(n) for n in zip_names if n.startswith("original_documents/") and not n.endswith("/"))

overlap = b1_ui_files.intersection(zip_docs)
match_rate = len(overlap) / max(1, len(b1_ui_files))

result = {
    "batch1_ui_files_count": len(b1_ui_files),
    "zip_files_count": len(zip_docs),
    "matching_files_count": len(overlap),
    "match_rate": round(match_rate, 4),
    "zip_has_index_csv": "index.csv" in zip_names,
    "status": "MATCH" if match_rate >= 0.9 else "PARTIAL"
}

with open(out_comparison, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)

print(f"ZIP vs UI comparison: {result['status']}, Match Rate: {match_rate*100:.1f}%")
