"""Evaluate OCR transcription accuracy: TrOCR-Base vs TrOCR-Small against ground truth.

Calculates:
- Character Error Rate (CER)
- Word Error Rate (WER)
- Extracted Field Accuracy (Invoice Number, Date, Total Amount, SSN)
"""

import os
import sys
import fitz
import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.bench_ocr import detect_text_lines, get_trocr_model, run_trocr_on_crops
from app.workers.stages import stage_classify, stage_extract_fields, stage_pii_detect


GROUND_TRUTH_TEXT = """INVOICE
Invoice Number: INV-2026-8891
Invoice Date: 2026-11-12
Due Date: 2026-12-12
Vendor: Apex Healthcare Systems
Vendor Address: 100 Medical Center Blvd, Suite 400
Customer: Jane Doe
Email: jane.doe@example.com
Phone: (555) 234-5678
Address: 742 Evergreen Terrace, Springfield, IL 62704
SSN: 000-12-3456

Description                       Qty    Unit Price    Total
Comprehensive Consultation          1       $250.00    $250.00
Blood Chemistry Screening           1       $180.00    $180.00
Diagnostic Imaging Service          1       $520.00    $520.00
Medication Delivery Support         2        $25.00     $50.00
Subtotal:                                            $1000.00
Tax (8%):                                              $80.00
Total Amount:                                        $1080.00

Payment Terms: Net 30 Days.
Thank you for your business."""


def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def compute_cer(gt: str, pred: str) -> float:
    d = levenshtein_distance(gt, pred)
    return d / max(1, len(gt))


def compute_wer(gt: str, pred: str) -> float:
    gt_words = gt.split()
    pred_words = pred.split()
    d = levenshtein_distance(" ".join(gt_words), " ".join(pred_words))
    # Approximate word-level Levenshtein
    m, n = len(gt_words), len(pred_words)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if gt_words[i - 1].lower() == pred_words[j - 1].lower() else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return dp[m][n] / max(1, m)


def evaluate_accuracy():
    img_bgr = cv2.imread("data/test/scan_sample.png")
    # Resize to 200 DPI
    h, w = img_bgr.shape[:2]
    img_200dpi = cv2.resize(img_bgr, (int(w * 200 / 300), int(h * 200 / 300)))
    boxes = detect_text_lines(img_200dpi)

    crops = []
    for x, y, bw, bh in boxes:
        if bw < 10 or bh < 6:
            continue
        crop = img_200dpi[y : y + bh, x : x + bw]
        crops.append(Image.fromarray(crop))

    models = [
        ("microsoft/trocr-base-printed", "TrOCR-Base"),
        ("microsoft/trocr-small-printed", "TrOCR-Small"),
    ]

    for model_id, model_label in models:
        processor, model = get_trocr_model(model_id, device="cuda", fp16=True)
        texts = run_trocr_on_crops(crops, processor, model, device="cuda", batch_size=16, fp16=True)
        predicted_text = "\n".join(texts)

        cer = compute_cer(GROUND_TRUTH_TEXT, predicted_text)
        wer = compute_wer(GROUND_TRUTH_TEXT, predicted_text)

        # Pipeline field extraction accuracy
        cls_res = stage_classify(predicted_text)
        fields, confs, valid = stage_extract_fields(predicted_text, "invoice")
        pii = stage_pii_detect(predicted_text)

        print(f"\n{'='*60}")
        print(f"Model: {model_label} ({model_id})")
        print(f"  Character Error Rate (CER): {cer * 100:.2f}% (Accuracy: {(1 - cer) * 100:.2f}%)")
        print(f"  Word Error Rate (WER)     : {wer * 100:.2f}% (Accuracy: {(1 - wer) * 100:.2f}%)")
        print(f"  Predicted Class           : {cls_res['predicted_class']} (Confidence: {cls_res['confidence']:.2f})")
        print(f"  Extracted Invoice Number  : {fields.get('invoice_number')}")
        print(f"  Extracted Invoice Date    : {fields.get('invoice_date')}")
        print(f"  Extracted Total Amount    : {fields.get('total_amount')}")
        print(f"  PII Detected              : {pii['pii_detected']} (Types: {pii['pii_types']})")
        print(f"{'='*60}")


if __name__ == "__main__":
    evaluate_accuracy()
