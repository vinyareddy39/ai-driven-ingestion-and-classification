"""Seeded Synthetic Prescription Dataset Generator.

Generates structured synthetic prescriptions (typed text and simulated noisy scans)
paired with exhaustive ground truth JSON for clinical extraction benchmarking.
LABEL: SYNTHETIC DATA ONLY - DOES NOT REPRESENT REAL PATIENT HEALTH DATA.
"""

import json
import os
import random
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class GroundTruthItem:
    drug_name: str
    strength: str
    dose: str
    frequency: str
    timing: str
    duration_days: Optional[int]
    is_known: bool = True
    safety_warning: Optional[str] = None


@dataclass
class SyntheticPrescription:
    rx_id: str
    doctor_name: str
    clinic_name: str
    patient_name: str
    date_str: str
    raw_lines: List[str]
    items: List[GroundTruthItem]


DRUG_CATALOG = [
    {"name": "Paracetamol", "strengths": ["500mg", "650mg", "1000mg"], "forms": ["tab", "tablet"], "doses": ["1 tab", "2 tabs"], "known": True},
    {"name": "Amoxicillin", "strengths": ["250mg", "500mg", "875mg"], "forms": ["capsule", "cap"], "doses": ["1 cap", "1 capsule"], "known": True},
    {"name": "Ibuprofen", "strengths": ["200mg", "400mg", "600mg"], "forms": ["tab", "tablet"], "doses": ["1 tab", "1 tablet"], "known": True},
    {"name": "Metformin", "strengths": ["500mg", "850mg", "1000mg"], "forms": ["tab"], "doses": ["1 tab"], "known": True},
    {"name": "Atorvastatin", "strengths": ["10mg", "20mg", "40mg"], "forms": ["tab"], "doses": ["1 tab"], "known": True},
    {"name": "Cetirizine", "strengths": ["5mg", "10mg"], "forms": ["tab"], "doses": ["1 tab"], "known": True},
    {"name": "Azithromycin", "strengths": ["250mg", "500mg"], "forms": ["tab"], "doses": ["1 tab"], "known": True},
    {"name": "Pantoprazole", "strengths": ["20mg", "40mg"], "forms": ["tab"], "doses": ["1 tab"], "known": True},
    {"name": "Amlodipine", "strengths": ["2.5mg", "5mg", "10mg"], "forms": ["tab"], "doses": ["1 tab"], "known": True},
    {"name": "Levothyroxine", "strengths": ["25mcg", "50mcg", "100mcg"], "forms": ["tab"], "doses": ["1 tab"], "known": True},
    {"name": "Zulomib", "strengths": ["25mg"], "forms": ["tab"], "doses": ["1 tab"], "known": False},  # Fictional unknown drug
    {"name": "Xanodril", "strengths": ["50mg"], "forms": ["cap"], "doses": ["1 cap"], "known": False}, # Fictional unknown drug
]

FREQUENCIES = [
    ("OD", ["OD", "once daily", "1 x d"]),
    ("BD", ["BD", "twice daily", "2 x d", "BID"]),
    ("TDS", ["TDS", "thrice daily", "3 x d", "three times daily"]),
    ("QID", ["QID", "four times daily", "4 x d"]),
    ("HS", ["HS", "at bedtime", "night only"]),
    ("SOS", ["SOS", "PRN", "as needed", "when required"]),
]

TIMINGS = [
    ("after meals", ["after meals", "pc", "after food"]),
    ("before meals", ["before meals", "ac", "before food"]),
    ("with meals", ["with meals", "with food"]),
    ("empty stomach", ["empty stomach"]),
    ("at bedtime", ["at bedtime", "at night"]),
]

DURATIONS = [
    (3, ["for 3 days", "x 3 days", "3d"]),
    (5, ["for 5 days", "x 5 days", "5 days"]),
    (7, ["for 7 days", "x 7 days", "1 week", "7d"]),
    (10, ["for 10 days", "x 10 days", "10d"]),
    (14, ["for 14 days", "for 2 weeks", "x 14 days"]),
    (30, ["for 30 days", "for 1 month", "1 month"]),
]


def generate_synthetic_dataset(num_samples: int = 25, seed: int = 42) -> List[SyntheticPrescription]:
    """Generate deterministic synthetic prescriptions with ground truth."""
    rng = random.Random(seed)
    doctors = ["Dr. Robert Chen, MD", "Dr. Sarah Jenkins, MD", "Dr. Amit Patel, MBBS", "Dr. Emily Vance, DO"]
    clinics = ["Metro Health Family Clinic", "St. Jude Outpatient Center", "Highland Medical Pavilion", "Downtown Health Partners"]
    patients = ["John Doe", "Jane Smith", "Michael Johnson", "Emily Davis", "David Wilson", "Sarah Martinez"]

    prescriptions = []
    for i in range(num_samples):
        rx_id = f"synth-rx-{seed}-{i + 1:03d}"
        doc = rng.choice(doctors)
        clinic = rng.choice(clinics)
        pat = rng.choice(patients)
        date_str = f"2026-11-{rng.randint(1, 28):02d}"

        # 1 to 3 items per prescription
        num_items = rng.randint(1, 3)
        chosen_drugs = rng.sample(DRUG_CATALOG, num_items)

        raw_lines = [
            f"{clinic}",
            f"{doc} - Medical Practitioner",
            f"Date: {date_str}   Patient: {pat}",
            "Rx:",
        ]

        gt_items: List[GroundTruthItem] = []
        for drug_info in chosen_drugs:
            strength = rng.choice(drug_info["strengths"])
            dose = rng.choice(drug_info["doses"])
            norm_freq, freq_variants = rng.choice(FREQUENCIES)
            freq_text = rng.choice(freq_variants)
            norm_timing, timing_variants = rng.choice(TIMINGS)
            timing_text = rng.choice(timing_variants)
            dur_days, dur_variants = rng.choice(DURATIONS)
            dur_text = rng.choice(dur_variants)

            # High dose edge case check for Paracetamol
            warning = None
            if drug_info["name"] == "Paracetamol" and strength == "1000mg" and norm_freq in ["QID", "TDS"]:
                warning = "MAX_DOSE_EXCEEDED"

            gt_item = GroundTruthItem(
                drug_name=drug_info["name"],
                strength=strength,
                dose=dose,
                frequency=norm_freq,
                timing=norm_timing,
                duration_days=dur_days,
                is_known=drug_info["known"],
                safety_warning=warning,
            )
            gt_items.append(gt_item)

            # Build line text (simulating varying doctor notation styles)
            style = rng.randint(1, 3)
            if style == 1:
                line = f"- {drug_info['name']} {strength} - {dose} {freq_text} {timing_text} {dur_text}"
            elif style == 2:
                line = f"{drug_info['forms'][0].capitalize()}. {drug_info['name']} {strength} | {dose} | {freq_text} | {timing_text} | {dur_text}"
            else:
                line = f"{drug_info['name']} {strength}, {dose}, {freq_text}, {dur_text} ({timing_text})"

            raw_lines.append(line)

        raw_lines.append("\nSignature: __________________")
        prescriptions.append(
            SyntheticPrescription(
                rx_id=rx_id,
                doctor_name=doc,
                clinic_name=clinic,
                patient_name=pat,
                date_str=date_str,
                raw_lines=raw_lines,
                items=gt_items,
            )
        )

    return prescriptions


def save_synthetic_dataset(prescriptions: List[SyntheticPrescription], output_dir: str) -> None:
    """Save dataset as plain text files alongside ground truth JSON."""
    os.makedirs(output_dir, exist_ok=True)
    index_data = []

    for rx in prescriptions:
        txt_path = os.path.join(output_dir, f"{rx.rx_id}.txt")
        json_path = os.path.join(output_dir, f"{rx.rx_id}.json")

        text_content = "\n".join(rx.raw_lines)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text_content)

        gt_dict = {
            "rx_id": rx.rx_id,
            "doctor": rx.doctor_name,
            "patient": rx.patient_name,
            "clinic": rx.clinic_name,
            "date": rx.date_str,
            "items": [asdict(it) for it in rx.items],
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(gt_dict, f, indent=2)

        index_data.append({"rx_id": rx.rx_id, "items_count": len(rx.items)})

    with open(os.path.join(output_dir, "dataset_index.json"), "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2)


if __name__ == "__main__":
    out_dir = os.path.join(os.getcwd(), "data", "synthetic_prescriptions")
    ds = generate_synthetic_dataset(num_samples=25, seed=42)
    save_synthetic_dataset(ds, out_dir)
    print(f"Generated {len(ds)} synthetic prescriptions in {out_dir}")

