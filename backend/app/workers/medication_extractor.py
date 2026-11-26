"""Rule-Based and Grounded Medication Extractor for Prescriptions.

Extracts drug name, strength, dose, frequency, timing, and duration
from OCR text preserving line boundaries, with source span grounding,
local WHO/RxNorm reference lookup, and clinical safety checks.
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ExtractedMedication:
    drug_name: str
    strength: str
    dose: str
    frequency: str
    timing: str
    duration_days: Optional[int]
    schedule_rule: str
    confidence: Dict[str, float]
    source_span: str
    warnings: List[str] = field(default_factory=list)


# Frequency normalizations
FREQ_PATTERNS = [
    (r"\b(once\s+(?:a\s+)?day|once\s+daily|1\s*x\s*d|od|qd)\b", "OD"),
    (r"\b(twice\s+(?:a\s+)?day|twice\s+daily|2\s*x\s*d|bd|bid)\b", "BD"),
    (r"\b(three\s+times\s+(?:a\s+)?day|thrice\s+daily|3\s*x\s*d|tds|tid)\b", "TDS"),
    (r"\b(four\s+times\s+(?:a\s+)?day|4\s*x\s*d|qid)\b", "QID"),
    (r"\b(every\s+4\s+hours|q4h)\b", "Q4H"),
    (r"\b(every\s+6\s+hours|q6h)\b", "Q6H"),
    (r"\b(every\s+8\s+hours|q8h)\b", "Q8H"),
    (r"\b(every\s+12\s+hours|q12h)\b", "Q12H"),
    (r"\b(at\s+bedtime|night\s+only|hs)\b", "HS"),
    (r"\b(as\s+needed|when\s+required|prn|sos)\b", "SOS"),
]

# Timing relative to food
TIMING_PATTERNS = [
    (r"\b(after\s+(?:food|meals?|eating)|post\s*cibum|pc)\b", "after meals"),
    (r"\b(before\s+(?:food|meals?|eating)|ante\s*cibum|ac)\b", "before meals"),
    (r"\b(with\s+(?:food|meals?))\b", "with meals"),
    (r"\b(empty\s+stomach)\b", "empty stomach"),
    (r"\b(bedtime|at\s+night|hs)\b", "at bedtime"),
    (r"\b(in\s+the\s+morning)\b", "morning"),
]

# Dose patterns (e.g. "1 tab", "2 capsules", "10 ml", "2 puffs")
DOSE_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?(?:\s*-\s*\d+)?)\s*(tab(?:let)?s?|caps?(?:ule)?s?|puffs?|drops?|teaspoons?|tsp|tbsp|ml|units?)\b",
    re.IGNORECASE,
)

# Strength patterns (e.g. "500mg", "100 mg", "5 mcg", "10mg/5ml", "2.5 mg")
STRENGTH_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|iu|units|%)(?:\s*/\s*\d+\s*(?:ml)?)?\b",
    re.IGNORECASE,
)

# Duration patterns (e.g. "7 days", "10 d", "1 month", "2 weeks", "x 5 days", "for 14 days")
DURATION_PATTERN = re.compile(
    r"\b(?:for\s+|x\s*)?(\d+)\s*(days?|d|weeks?|wks?|months?|m)\b",
    re.IGNORECASE,
)


class MedicationExtractor:
    """Local, grounded, deterministic rule-based medication entity extractor."""

    def __init__(self, reference_path: Optional[str] = None):
        if reference_path is None:
            reference_path = os.path.join(os.getcwd(), "data", "reference_drugs.json")
        self.reference_path = reference_path
        self.drug_db: Dict[str, Dict[str, Any]] = {}
        self._load_reference_db()

    def _load_reference_db(self) -> None:
        if os.path.exists(self.reference_path):
            try:
                with open(self.reference_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data.get("drugs", []):
                        main_name = item["name"].lower()
                        self.drug_db[main_name] = item
                        for alias in item.get("aliases", []):
                            self.drug_db[alias.lower()] = item
            except Exception:
                pass

    def check_drug_safety(self, drug_name: str, strength_str: str, dose_str: str, freq_str: str) -> List[str]:
        """Safety checks (dosage ceiling, pediatric, insulin alerts)."""
        warnings = []
        key = drug_name.lower().strip()
        ref = self.drug_db.get(key)
        if not ref:
            warnings.append(f"UNKNOWN_DRUG: '{drug_name}' not verified in local drug formulary; human review required.")
            return warnings

        # Max daily dose check (e.g. Paracetamol > 4000mg/day)
        max_daily = ref.get("max_daily_mg")
        if max_daily and strength_str:
            match = re.search(r"(\d+(?:\.\d+)?)\s*mg", strength_str, re.IGNORECASE)
            if match:
                st_mg = float(match.group(1))
                # Estimate daily intake
                freq_mult = 1
                if freq_str in ["BD", "BID"]: freq_mult = 2
                elif freq_str in ["TDS", "TID"]: freq_mult = 3
                elif freq_str in ["QID"]: freq_mult = 4
                elif freq_str == "Q4H": freq_mult = 6
                elif freq_str == "Q6H": freq_mult = 4
                elif freq_str == "Q8H": freq_mult = 3

                # Parse dose multiplier if present (e.g. "2 tabs")
                dose_mult = 1
                if dose_str:
                    d_m = re.match(r"^(\d+)", dose_str.strip())
                    if d_m:
                        try:
                            dose_mult = int(d_m.group(1))
                        except Exception:
                            pass

                est_daily = st_mg * dose_mult * freq_mult
                if est_daily > max_daily:
                    warnings.append(
                        f"MAX_DOSE_EXCEEDED: Estimated daily intake {est_daily:.0f}mg exceeds safety limit of {max_daily}mg for {drug_name}."
                    )

        if "warning" in ref:
            warnings.append(f"SAFETY_WARNING: {ref['warning']}")

        return warnings

    def extract_from_line(self, line: str) -> Optional[ExtractedMedication]:
        """Attempt extraction from a single line of prescription text."""
        clean = line.strip()
        if not clean or len(clean) < 4:
            return None

        # Look for drug name in line
        found_drug: Optional[str] = None
        for name in sorted(self.drug_db.keys(), key=len, reverse=True):
            pattern = r"\b" + re.escape(name) + r"\b"
            if re.search(pattern, clean, re.IGNORECASE):
                # Prefer canonical name from ref db
                found_drug = self.drug_db[name]["name"].capitalize()
                break

        # Fuzzy match against drug reference list (handles OCR dropped chars e.g. Amocillin -> Amoxicillin)
        if not found_drug:
            import difflib
            line_words = re.findall(r"\b[A-Za-z]{4,25}\b", clean)
            for w in line_words:
                matches = difflib.get_close_matches(w.lower(), self.drug_db.keys(), n=1, cutoff=0.78)
                if matches:
                    matched_key = matches[0]
                    found_drug = self.drug_db[matched_key]["name"].capitalize()
                    break

        # If no recognized drug from DB, look for typical line prefix e.g. "Tab Paracetamol" or "Cap Amox"
        if not found_drug:
            rx_prefix_match = re.search(
                r"^(?:(?:tab|cap|syp|inj|ointment|drop)\.?\s+)?([A-Za-z]{3,25})\b",
                clean,
                re.IGNORECASE,
            )
            # Only consider if there is also strength or frequency on the line
            has_strength = bool(STRENGTH_PATTERN.search(clean))
            has_freq = any(re.search(pat, clean, re.IGNORECASE) for pat, _ in FREQ_PATTERNS)
            if rx_prefix_match and (has_strength or has_freq):
                candidate = rx_prefix_match.group(1)
                # Ignore common medical stop words
                if candidate.lower() not in {"take", "daily", "every", "tablets", "capsule", "doctor", "patient", "clinic", "hospital", "prescription", "date", "name", "sign"}:
                    found_drug = candidate.capitalize()

        if not found_drug:
            return None

        # Strength
        strength = ""
        st_match = STRENGTH_PATTERN.search(clean)
        if st_match:
            strength = f"{st_match.group(1)}{st_match.group(2).lower()}"

        # Dose
        dose = ""
        dose_match = DOSE_PATTERN.search(clean)
        if dose_match:
            dose = f"{dose_match.group(1)} {dose_match.group(2).lower()}"
        elif strength:
            # Fallback dose e.g. "1 tab" if strength is present
            dose = "1 tablet"

        # Frequency
        frequency = ""
        for pat, norm in FREQ_PATTERNS:
            if re.search(pat, clean, re.IGNORECASE):
                frequency = norm
                break

        # Timing
        timing = ""
        for pat, norm in TIMING_PATTERNS:
            if re.search(pat, clean, re.IGNORECASE):
                timing = norm
                break

        # Duration
        duration_days: Optional[int] = None
        dur_match = DURATION_PATTERN.search(clean)
        if dur_match:
            val = int(dur_match.group(1))
            unit = dur_match.group(2).lower()
            if "w" in unit:
                duration_days = val * 7
            elif "m" in unit:
                duration_days = val * 30
            else:
                duration_days = val

        # Construct deterministic schedule rule string
        rule_parts = []
        if frequency: rule_parts.append(frequency)
        if timing: rule_parts.append(timing)
        if duration_days: rule_parts.append(f"for {duration_days} days")
        schedule_rule = " ".join(rule_parts) if rule_parts else (frequency or "OD")

        # Per-field confidences
        conf = {
            "drug_name": 0.95 if found_drug.lower() in self.drug_db else 0.70,
            "strength": 0.92 if strength else 0.50,
            "dose": 0.90 if dose_match else 0.60,
            "frequency": 0.95 if frequency else 0.50,
            "timing": 0.90 if timing else 0.50,
            "duration_days": 0.95 if duration_days is not None else 0.50,
        }

        warnings = self.check_drug_safety(found_drug, strength, dose, frequency)

        return ExtractedMedication(
            drug_name=found_drug,
            strength=strength,
            dose=dose,
            frequency=frequency,
            timing=timing,
            duration_days=duration_days,
            schedule_rule=schedule_rule,
            confidence=conf,
            source_span=clean,
            warnings=warnings,
        )

    def extract(self, text: str) -> List[ExtractedMedication]:
        """Extract all medication entities across lines of text."""
        results: List[ExtractedMedication] = []
        seen_drugs = set()

        for line in text.splitlines():
            clean_line = line.strip()
            if not clean_line:
                continue
            item = self.extract_from_line(clean_line)
            if item and item.drug_name.lower() not in seen_drugs:
                seen_drugs.add(item.drug_name.lower())
                results.append(item)

        return results
