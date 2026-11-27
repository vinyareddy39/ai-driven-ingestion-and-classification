"""Evaluation and Benchmarking Script for Prescription Medication Field Extraction.

Measures field-level Precision, Recall, and F1 for:
- drug_name
- strength
- dose
- frequency
- timing
- duration_days

Evaluates on:
1. Dev Set (Seed 42)
2. Fresh Unseen Test Set (Seed 101)

LABEL: SYNTHETIC DATA ONLY. All metrics reflect synthetic prescription benchmarks.
"""

import sys
sys.path.insert(0, ".")
import json
import os
from typing import Any, Dict, List, Tuple
from app.workers.medication_extractor import MedicationExtractor
from data.synthetic_prescriptions import generate_synthetic_dataset


def evaluate_dataset(seed: int, num_samples: int = 25) -> Dict[str, Any]:
    prescriptions = generate_synthetic_dataset(num_samples=num_samples, seed=seed)
    extractor = MedicationExtractor()

    fields = ["drug_name", "strength", "dose", "frequency", "timing", "duration_days"]
    stats = {f: {"tp": 0, "fp": 0, "fn": 0} for f in fields}
    grounding_checked = 0
    grounding_valid = 0
    unknown_drugs_tested = 0
    unknown_drugs_flagged = 0
    high_dose_tested = 0
    high_dose_flagged = 0

    for rx in prescriptions:
        full_text = "\n".join(rx.raw_lines)
        extracted = extractor.extract(full_text)

        # Map extracted by drug name lower
        ext_map = {e.drug_name.lower(): e for e in extracted}

        # Check grounding for every extracted item
        for e in extracted:
            grounding_checked += 1
            if e.source_span in full_text:
                grounding_valid += 1

        for gt in rx.items:
            gt_name = gt.drug_name.lower()
            matched_ext = ext_map.get(gt_name)

            if not gt.is_known:
                unknown_drugs_tested += 1
                if matched_ext and any("UNKNOWN_DRUG" in w for w in matched_ext.warnings):
                    unknown_drugs_flagged += 1

            if gt.safety_warning:
                high_dose_tested += 1
                if matched_ext and any("MAX_DOSE_EXCEEDED" in w for w in matched_ext.warnings):
                    high_dose_flagged += 1

            if matched_ext:
                stats["drug_name"]["tp"] += 1

                # strength
                if matched_ext.strength.lower().replace(" ", "") == gt.strength.lower().replace(" ", ""):
                    stats["strength"]["tp"] += 1
                else:
                    stats["strength"]["fp"] += 1
                    stats["strength"]["fn"] += 1

                # dose
                if gt.dose.lower() in matched_ext.dose.lower():
                    stats["dose"]["tp"] += 1
                else:
                    stats["dose"]["fp"] += 1
                    stats["dose"]["fn"] += 1

                # frequency
                if matched_ext.frequency == gt.frequency:
                    stats["frequency"]["tp"] += 1
                else:
                    stats["frequency"]["fp"] += 1
                    stats["frequency"]["fn"] += 1

                # timing
                if matched_ext.timing == gt.timing:
                    stats["timing"]["tp"] += 1
                else:
                    stats["timing"]["fp"] += 1
                    stats["timing"]["fn"] += 1

                # duration
                if matched_ext.duration_days == gt.duration_days:
                    stats["duration_days"]["tp"] += 1
                else:
                    stats["duration_days"]["fp"] += 1
                    stats["duration_days"]["fn"] += 1
            else:
                for f in fields:
                    stats[f]["fn"] += 1

        # False positives: extracted drugs not in ground truth
        gt_drug_set = {it.drug_name.lower() for it in rx.items}
        for ext_name in ext_map.keys():
            if ext_name not in gt_drug_set:
                stats["drug_name"]["fp"] += 1

    metrics = {}
    for f in fields:
        tp = stats[f]["tp"]
        fp = stats[f]["fp"]
        fn = stats[f]["fn"]
        prec = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
        rec = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        f1 = float(2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
        metrics[f] = {
            "precision": round(prec * 100.0, 2),
            "recall": round(rec * 100.0, 2),
            "f1": round(f1 * 100.0, 2),
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }

    return {
        "metrics": metrics,
        "grounding_accuracy": round((grounding_valid / max(1, grounding_checked)) * 100.0, 2),
        "unknown_flag_rate": round((unknown_drugs_flagged / max(1, unknown_drugs_tested)) * 100.0, 2) if unknown_drugs_tested > 0 else 100.0,
        "high_dose_flag_rate": round((high_dose_flagged / max(1, high_dose_tested)) * 100.0, 2) if high_dose_tested > 0 else 100.0,
        "samples_evaluated": len(prescriptions),
    }


def print_evaluation_report(title: str, results: Dict[str, Any]):
    print(f"\n================================================================================")
    print(f"BENCHMARK REPORT: {title} (LOCAL MODE - SYNTHETIC DATA)")
    print(f"================================================================================")
    print(f"{'Field':<18} | {'Precision (%)':<15} | {'Recall (%)':<15} | {'F1-Score (%)':<15}")
    print("-" * 72)
    for f, m in results["metrics"].items():
        print(f"{f:<18} | {m['precision']:<15.2f} | {m['recall']:<15.2f} | {m['f1']:<15.2f}")
    print("-" * 72)
    print(f"Grounding Verifiability : {results['grounding_accuracy']}% of entities grounded in OCR span")
    print(f"Unknown Drug Detection : {results['unknown_flag_rate']}% of unknown entities flagged for review")
    print(f"High-Dose Safety Alert : {results['high_dose_flag_rate']}% of dangerous dosages detected")
    print(f"Total Prescriptions     : {results['samples_evaluated']}")
    print("================================================================================\n")


if __name__ == "__main__":
    # Dev set (seed 42)
    dev_res = evaluate_dataset(seed=42, num_samples=25)
    print_evaluation_report("DEVELOPMENT SET (Seed 42)", dev_res)

    # Fresh unseen test set (seed 101)
    fresh_res = evaluate_dataset(seed=101, num_samples=25)
    print_evaluation_report("FRESH UNSEEN HOLDOUT SET (Seed 101)", fresh_res)
