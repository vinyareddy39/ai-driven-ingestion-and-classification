import os
import json
from pathlib import Path
from collections import Counter

dataset_dir = Path("data/dataset")
target_dirs = ["train", "val", "locked_test", "special", "holdout", "holdout2", "holdout3", "holdout4", "val_v3"]

for d_name in target_dirs:
    sub = dataset_dir / d_name
    if not sub.exists():
        continue
    
    # check if annotations.json or metadata.json exists
    ann_file = sub / "annotations.json"
    meta_file = sub / "metadata.json"
    ground_truth = sub / "ground_truth.json"

    counts = Counter()
    pdf_count = len(list(sub.glob("*.pdf")))
    json_count = len(list(sub.glob("*.json")))

    if ann_file.exists():
        with open(ann_file) as f:
            data = json.load(f)
            for item in data:
                counts[item.get("doc_type", "unknown")] += 1
    elif ground_truth.exists():
        with open(ground_truth) as f:
            data = json.load(f)
            for k, v in data.items():
                if isinstance(v, dict):
                    counts[v.get("doc_type", "unknown")] += 1
    else:
        # scan json files
        for f in sub.glob("*.json"):
            try:
                with open(f) as fp:
                    d = json.load(fp)
                    if isinstance(d, dict) and "doc_type" in d:
                        counts[d["doc_type"]] += 1
            except:
                pass

    print(f"=== {d_name} ===")
    print(f"PDFs: {pdf_count}, JSONs: {json_count}")
    for dt, cnt in sorted(counts.items()):
        print(f"  {dt}: {cnt}")
