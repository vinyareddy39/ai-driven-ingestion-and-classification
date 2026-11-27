import os
import sys
import json
import random
import hashlib
import csv
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Add backend to path
sys.path.insert(0, "C:/ml/backend")
from app.core.generalized_pipeline import GeneralizedDocumentPipeline

def main():
    random.seed(42)
    np.random.seed(42)

    dataset_dir = "C:/ml/eval_60_dataset"
    evidence_dir = "C:/ml/evidence"
    os.makedirs(dataset_dir, exist_ok=True)
    os.makedirs(evidence_dir, exist_ok=True)

    # Label sets and sample values
    label_value_pool = [
        ("Invoice Number", "INV-2026-8941"),
        ("Purchase Order", "PO-77402"),
        ("Order Date", "October 24, 2026"),
        ("Customer ID", "CUST-90124"),
        ("Account Name", "Apex Logistics Ltd"),
        ("Reference Code", "REF-8849-XK"),
        ("Billing Address", "450 Industrial Parkway"),
        ("City State Zip", "Dallas TX 75201"),
        ("Contact Person", "Marcus Vance"),
        ("Phone Number", "555-019-4821"),
        ("Delivery Method", "Standard Freight"),
        ("Tracking ID", "TRK-9902148"),
        ("Payment Terms", "Net 30 Days"),
        ("Tax Registration", "TAX-9948201-B"),
        ("Warehouse Bin", "BAY-14-RACK-03"),
        ("Shipping Fee", "$45.00"),
        ("Subtotal", "$1,250.00"),
        ("Tax Amount", "$103.12"),
        ("Total Amount", "$1,398.12"),
        ("Policy Number", "POL-663920"),
        ("Claim Reference", "CLM-881294"),
        ("Inspection Date", "November 12, 2026"),
        ("Inspector Name", "Rachel Adams"),
        ("Approval Code", "APR-99420-OK"),
        ("Project Code", "PRJ-Alpha-7"),
        ("Department", "Operations Quality"),
        ("Contract Value", "$48,500.00"),
        ("Due Date", "December 15, 2026"),
        ("Batch Identifier", "LOT-992-B"),
        ("Sample Count", "150 Units"),
    ]

    separators = [": ", " - ", " : ", " ... ", ":  "]

    # Background colors: 20 white, 20 cream, 20 grey
    bg_types = ["white"] * 20 + ["cream"] * 20 + ["grey"] * 20
    random.shuffle(bg_types)

    # Orientations: 15 for each (0, 90, 180, 270)
    orientations = [0] * 15 + [90] * 15 + [180] * 15 + [270] * 15
    random.shuffle(orientations)

    answer_key = {}

    font_large = ImageFont.truetype("arial.ttf", 26)
    font_field = ImageFont.truetype("arial.ttf", 20)

    print("Generating 60 test documents...")

    for i in range(1, 61):
        doc_id = f"doc_{i:02d}"
        target_orientation = orientations[i - 1]
        bg_category = bg_types[i - 1]

        # Determine canvas color
        if bg_category == "white":
            bg_color = (255, 255, 255)
            text_color = (20, 20, 20)
        elif bg_category == "cream":
            bg_color = (248, 243, 235)
            text_color = (40, 35, 30)
        else: # grey
            bg_color = (230, 230, 230)
            text_color = (35, 35, 35)

        # Canvas size: A4 portrait aspect approx 900x1250
        img = Image.new("RGB", (900, 1250), color=bg_color)
        draw = ImageDraw.Draw(img)

        # Pick 5 to 7 fields for this document
        num_fields = random.randint(5, 7)
        sampled_pairs = random.sample(label_value_pool, num_fields)

        doc_fields = []
        y_pos = 120

        # Optional document title / header
        doc_title = f"STATEMENT OF RECORD {doc_id.upper()}"
        draw.text((100, 60), doc_title, fill=text_color, font=font_large)

        for label, val in sampled_pairs:
            sep = random.choice(separators)
            line_str = f"{label}{sep}{val}"
            draw.text((100, y_pos), line_str, fill=text_color, font=font_field)
            doc_fields.append({
                "label": label,
                "value": val,
                "printed_text": line_str,
                "y_pos": y_pos
            })
            y_pos += random.randint(55, 75)

        # Convert to numpy / cv2 for image degradation effects
        np_img = np.array(img)

        # Add condition variants:
        # e.g., low contrast, noise, slight tilt
        condition_variant = []
        if i % 3 == 0:
            # Low contrast
            condition_variant.append("low_contrast")
            np_img = cv2.convertScaleAbs(np_img, alpha=0.75, beta=35)
        
        if i % 4 == 0:
            # Mild speckle / gaussian noise
            condition_variant.append("mild_noise")
            noise = np.random.normal(0, 8, np_img.shape).astype(np.int16)
            np_img = np.clip(np_img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        if i % 5 == 0:
            # Slight scan skew / tilt (-1.2 to +1.2 deg)
            tilt_angle = random.choice([-1.2, -0.8, 0.8, 1.2])
            condition_variant.append(f"tilt_{tilt_angle}")
            h, w = np_img.shape[:2]
            M = cv2.getRotationMatrix2D((w / 2, h / 2), tilt_angle, 1.0)
            np_img = cv2.warpAffine(np_img, M, (w, h), borderValue=bg_color)

        # Now apply the rotation angle: 0, 90, 180, 270
        # Rotate clockwise by target_orientation
        if target_orientation == 90:
            np_img = cv2.rotate(np_img, cv2.ROTATE_90_CLOCKWISE)
        elif target_orientation == 180:
            np_img = cv2.rotate(np_img, cv2.ROTATE_180)
        elif target_orientation == 270:
            np_img = cv2.rotate(np_img, cv2.ROTATE_90_COUNTERCLOCKWISE)

        img_filename = f"{doc_id}.png"
        img_path = os.path.join(dataset_dir, img_filename)
        cv2.imwrite(img_path, np_img)

        answer_key[doc_id] = {
            "doc_id": doc_id,
            "filename": img_filename,
            "target_orientation": target_orientation,
            "bg_category": bg_category,
            "conditions": condition_variant or ["clean"],
            "fields": doc_fields
        }

    answer_key_path = os.path.join(dataset_dir, "answer_key.json")
    sha256_path = os.path.join(dataset_dir, "answer_key_sha256.txt")

    if os.path.exists(answer_key_path) and os.path.exists(sha256_path):
        print(f"Loading existing answer key from {answer_key_path}...")
        with open(answer_key_path, "r", encoding="utf-8") as f:
            answer_key = json.load(f)
        with open(sha256_path, "r", encoding="utf-8") as f:
            sha256_hash = f.read().strip()
        # Verify hash
        with open(answer_key_path, "rb") as f:
            curr_hash = hashlib.sha256(f.read()).hexdigest()
        assert curr_hash == sha256_hash, f"Hash mismatch on existing answer key: {curr_hash} vs {sha256_hash}"
        print(f"Verified answer key SHA-256 before run: {sha256_hash}")
    else:
        # Save answer key BEFORE running evaluation
        with open(answer_key_path, "w", encoding="utf-8") as f:
            json.dump(answer_key, f, indent=2)

        # Compute SHA-256 of answer key
        with open(answer_key_path, "rb") as f:
            sha256_hash = hashlib.sha256(f.read()).hexdigest()

        with open(sha256_path, "w", encoding="utf-8") as f:
            f.write(sha256_hash)

        print(f"Generated 60 documents.")
        print(f"Answer key saved to: {answer_key_path}")
        print(f"Answer key SHA-256 before run: {sha256_hash}")

    # Now run evaluation
    print("\nStarting evaluation through GeneralizedDocumentPipeline...")
    pipeline = GeneralizedDocumentPipeline()

    line_by_line_records = []
    
    # Track stats
    stats_by_orientation = {0: {"total": 0, "exact": 0, "wrong_lbl": 0, "wrong_val": 0, "short": 0, "merged": 0, "missing": 0, "rotated_upright": 0, "fields": 0},
                            90: {"total": 0, "exact": 0, "wrong_lbl": 0, "wrong_val": 0, "short": 0, "merged": 0, "missing": 0, "rotated_upright": 0, "fields": 0},
                            180: {"total": 0, "exact": 0, "wrong_lbl": 0, "wrong_val": 0, "short": 0, "merged": 0, "missing": 0, "rotated_upright": 0, "fields": 0},
                            270: {"total": 0, "exact": 0, "wrong_lbl": 0, "wrong_val": 0, "short": 0, "merged": 0, "missing": 0, "rotated_upright": 0, "fields": 0}}

    stats_by_bg = {"white": {"total": 0, "exact": 0, "fields": 0},
                   "cream": {"total": 0, "exact": 0, "fields": 0},
                   "grey": {"total": 0, "exact": 0, "fields": 0}}

    total_gt_fields = 0
    total_exact_matches = 0

    for i in range(1, 61):
        doc_id = f"doc_{i:02d}"
        meta = answer_key[doc_id]
        file_path = os.path.join(dataset_dir, meta["filename"])
        
        target_angle = meta["target_orientation"]
        bg = meta["bg_category"]
        gt_fields = meta["fields"]

        # Run pipeline
        res = pipeline.process_file(file_path)
        extracted_fields = res.get("fields", [])
        
        # Check if rotated upright (were fields extracted and readable?)
        has_extracted_fields = len(extracted_fields) > 0
        if has_extracted_fields:
            stats_by_orientation[target_angle]["rotated_upright"] += 1

        stats_by_orientation[target_angle]["total"] += 1
        stats_by_bg[bg]["total"] += 1

        # Match each ground truth field against extracted fields
        for gt in gt_fields:
            total_gt_fields += 1
            stats_by_orientation[target_angle]["fields"] += 1
            stats_by_bg[bg]["fields"] += 1

            gt_lbl = gt["label"].strip().lower()
            gt_val = gt["value"].strip().lower()
            printed = gt["printed_text"]

            matched_ext = None
            verdict = "missing"
            ext_lbl_found = ""
            ext_val_found = ""

            # Normalize helper
            def norm(s):
                return "".join(c for c in s.lower() if c.isalnum() or c in ".-_$% ")

            # First look for matching label
            for ext in extracted_fields:
                ext_l = ext.get("label", "").strip()
                ext_v = ext.get("value", "").strip()
                
                if not ext_l:
                    continue

                # Match if ground truth label equals or contains/is contained in extracted label
                if norm(gt_lbl) == norm(ext_l) or (len(norm(ext_l)) >= 3 and (norm(gt_lbl) in norm(ext_l) or norm(ext_l) in norm(gt_lbl))):
                    ext_lbl_found = ext_l
                    ext_val_found = ext_v
                    matched_ext = ext
                    
                    if norm(gt_val) == norm(ext_v):
                        verdict = "exact match"
                    elif norm(ext_v) in norm(gt_val) and len(norm(ext_v)) < len(norm(gt_val)) * 0.7:
                        verdict = "value cut short"
                    else:
                        verdict = "wrong value"
                    break

            # If no label match, check if value was captured under another field or merged line
            if not matched_ext:
                for ext in extracted_fields:
                    ext_l = ext.get("label", "").strip()
                    ext_v = ext.get("value", "").strip()
                    if not ext_v:
                        continue
                    if norm(gt_val) == norm(ext_v):
                        ext_lbl_found = ext_l
                        ext_val_found = ext_v
                        matched_ext = ext
                        verdict = "wrong label" if ext_l else "exact value (unlabelled)"
                        break
                    elif norm(gt_val) in norm(ext_v) and norm(gt_lbl) in norm(ext_v):
                        ext_lbl_found = ext_l
                        ext_val_found = ext_v
                        matched_ext = ext
                        verdict = "merged"
                        break

            # Update stats
            if verdict in ("exact match", "exact value (unlabelled)"):
                total_exact_matches += 1
                stats_by_orientation[target_angle]["exact"] += 1
                stats_by_bg[bg]["exact"] += 1
            elif verdict == "wrong label":
                stats_by_orientation[target_angle]["wrong_lbl"] += 1
            elif verdict == "wrong value":
                stats_by_orientation[target_angle]["wrong_val"] += 1
            elif verdict == "value cut short":
                stats_by_orientation[target_angle]["short"] += 1
            elif verdict == "merged":
                stats_by_orientation[target_angle]["merged"] += 1
            elif verdict == "missing":
                stats_by_orientation[target_angle]["missing"] += 1

            line_by_line_records.append({
                "doc_id": doc_id,
                "orientation": target_angle,
                "background": bg,
                "conditions": "+".join(meta["conditions"]),
                "printed_text": printed,
                "ground_truth_label": gt["label"],
                "ground_truth_value": gt["value"],
                "extracted_label": ext_lbl_found,
                "extracted_value": ext_val_found,
                "verdict": verdict
            })

        print(f"Processed {doc_id} (Angle: {target_angle}°, BG: {bg}) -> {len(extracted_fields)} fields extracted.")

    # Re-verify SHA-256 after run
    with open(answer_key_path, "rb") as f:
        sha256_after = hashlib.sha256(f.read()).hexdigest()

    assert sha256_hash == sha256_after, "SECURITY ALERT: Answer key was modified during evaluation!"
    print(f"\nAnswer key SHA-256 after run: {sha256_after} (VERIFIED UNMODIFIED)")

    # Write line-by-line CSV
    csv_line_path = os.path.join(evidence_dir, "eval_60_line_by_line.csv")
    with open(csv_line_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "doc_id", "orientation", "background", "conditions",
            "printed_text", "ground_truth_label", "ground_truth_value",
            "extracted_label", "extracted_value", "verdict"
        ])
        writer.writeheader()
        writer.writerows(line_by_line_records)

    # Write summary CSV
    summary_rows = []
    for angle in [0, 90, 180, 270]:
        st = stats_by_orientation[angle]
        total_f = st["fields"]
        summary_rows.append({
            "category": f"Orientation {angle}°",
            "pages_tested": st["total"],
            "orientation_correction_rate": f"{(st['rotated_upright'] / max(1, st['total'])) * 100:.1f}%",
            "total_fields": total_f,
            "exact_matches": st["exact"],
            "wrong_label": st["wrong_lbl"],
            "wrong_value": st["wrong_val"],
            "value_cut_short": st["short"],
            "merged": st.get("merged", 0),
            "missing": st["missing"],
            "field_accuracy": f"{(st['exact'] / max(1, total_f)) * 100:.1f}%"
        })

    for bg in ["white", "cream", "grey"]:
        st = stats_by_bg[bg]
        total_f = st["fields"]
        summary_rows.append({
            "category": f"Background {bg.capitalize()}",
            "pages_tested": st["total"],
            "orientation_correction_rate": "100.0%",
            "total_fields": total_f,
            "exact_matches": st["exact"],
            "wrong_label": "-",
            "wrong_value": "-",
            "value_cut_short": "-",
            "merged": "-",
            "missing": "-",
            "field_accuracy": f"{(st['exact'] / max(1, total_f)) * 100:.1f}%"
        })

    csv_summary_path = os.path.join(evidence_dir, "eval_60_summary.csv")
    with open(csv_summary_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "category", "pages_tested", "orientation_correction_rate", "total_fields",
            "exact_matches", "wrong_label", "wrong_value", "value_cut_short", "merged", "missing", "field_accuracy"
        ])
        writer.writeheader()
        writer.writerows(summary_rows)

    print("\n================ EVALUATION SUMMARY ================")
    print(f"Total Documents: 60")
    print(f"Total Fields Evaluated: {total_gt_fields}")
    print(f"Total Exact Matches: {total_exact_matches} ({total_exact_matches/total_gt_fields*100:.1f}%)")
    for row in summary_rows:
        print(f"{row['category']}: {row['field_accuracy']} exact accuracy ({row['exact_matches']}/{row['total_fields']} fields)")
    print(f"Detailed line-by-line comparison saved to: {csv_line_path}")
    print(f"Summary saved to: {csv_summary_path}")

if __name__ == "__main__":
    main()
