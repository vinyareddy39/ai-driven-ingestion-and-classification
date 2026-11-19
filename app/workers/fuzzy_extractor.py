"""Generic Fuzzy Label Matcher for Key-Value Extraction.

Matches OCR text labels against a canonical schema dictionary using:
1. Character normalization (O/0, I/l/1/|, S/5, B/8, Z/2)
2. Bounded Levenshtein edit distance <= 2
3. Strictly grounded extraction from the OCR text
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from app.workers.generic_extractor import (
    SCHEMA_SYNONYMS,
    clean_ocr_field_text,
    clean_ocr_date,
    clean_ocr_amount
)

# Canonical schema label dictionary
CANONICAL_SCHEMA: Dict[str, Dict[str, List[str]]] = {
    k: {f: list(labels) for f, labels in v.items()}
    for k, v in SCHEMA_SYNONYMS.items()
}
# Canonical additions for standard field labeling
CANONICAL_SCHEMA["letter"]["sender"].extend(["sender name", "originator name", "dispatched by name"])
CANONICAL_SCHEMA["letter"]["recipient"].extend(["recipient name", "addressee name", "deliver to name"])
CANONICAL_SCHEMA["contract"]["parties"] = ["principal signatories", "counterparties", "engaged parties", "parties"]
CANONICAL_SCHEMA["contract"]["party_one"] = ["party one", "first party", "disclosing entity"]
CANONICAL_SCHEMA["contract"]["party_two"] = ["party two", "second party", "receiving entity"]

def normalize_label(s: str) -> str:
    """Normalize OCR character confusions and non-alphanumerics."""
    s = s.lower()
    trans = str.maketrans({'0': 'o', '1': 'i', 'l': 'i', '|': 'i', '5': 's', '8': 'b', '2': 'z'})
    s = s.translate(trans)
    return re.sub(r'[^a-z0-9]', '', s)

def levenshtein_dist(s1: str, s2: str, max_dist: int = 2) -> int:
    """Bounded Levenshtein distance with early exit."""
    if abs(len(s1) - len(s2)) > max_dist:
        return max_dist + 1
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1] * (len(s2) + 1)
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr[j + 1] = min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost)
        prev = curr
        if min(prev) > max_dist:
            return max_dist + 1
    return prev[len(s2)]

class GenericFuzzyExtractor:
    """Extracts schema-defined fields from text using generic fuzzy label matching."""

    def __init__(self):
        self.canonical_targets: Dict[str, List[Tuple[str, str, str]]] = {}
        for dt, flds in CANONICAL_SCHEMA.items():
            self.canonical_targets[dt] = []
            for fld, labels in flds.items():
                for lbl in labels:
                    self.canonical_targets[dt].append((fld, lbl, normalize_label(lbl)))

    def extract(self, text: str, doc_type: str) -> Tuple[Dict[str, Any], Dict[str, float]]:
        if doc_type not in self.canonical_targets or not text.strip():
            return {}, {}

        colons = [m.start() for m in re.finditer(r'[:;]', text)]
        if not colons:
            return {}, {}

        all_labels = []
        targets = self.canonical_targets[doc_type]

        for cp in colons:
            preceding = text[:cp].strip()
            words = preceding.split()
            if not words:
                continue

            best_fld = None
            best_score = 0.0
            best_phrase = None

            # Check phrases up to 6 words preceding separator
            for k in range(min(6, len(words)), 0, -1):
                phrase = ' '.join(words[-k:])
                norm_p = normalize_label(phrase)
                if not norm_p:
                    continue

                # 1. Exact canonical label match
                matched = False
                for fld, orig_lbl, c_norm in targets:
                    if norm_p == c_norm:
                        best_fld = fld
                        best_score = 1.0 + 0.05 * k
                        best_phrase = phrase
                        matched = True
                        break
                if matched:
                    break

                # 2. Fuzzy edit distance <= 2 with OCR normalization
                for fld, orig_lbl, c_norm in targets:
                    if len(c_norm) >= 4 and abs(len(norm_p) - len(c_norm)) <= 2:
                        d = levenshtein_dist(norm_p, c_norm, max_dist=2)
                        if d <= 2:
                            score = 0.90 - 0.05 * d + 0.02 * k
                            if score > best_score:
                                best_score = score
                                best_fld = fld
                                best_phrase = phrase

            if not best_phrase:
                best_phrase = ' '.join(words[-min(2, len(words)):])
            lbl_start = text.rfind(best_phrase, 0, cp)
            if lbl_start != -1:
                all_labels.append((lbl_start, cp + 1, best_fld, best_score, best_phrase))

        all_labels.sort(key=lambda x: x[0])
        pruned = []
        last_end = -1
        for start, cp, fld, score, phrase in all_labels:
            if start >= last_end:
                pruned.append((start, cp, fld, score, phrase))
                last_end = cp

        extracted: Dict[str, Any] = {}
        confs: Dict[str, float] = {}
        raw_scores: Dict[str, float] = {}

        for i in range(len(pruned)):
            start, val_start, fld, score, phrase = pruned[i]
            val_end = pruned[i+1][0] if i + 1 < len(pruned) else len(text)
            val = text[val_start:val_end].strip()
            if '\n' in val:
                val = val.split('\n')[0].strip()
            val = re.split(r'\s+[|]\s+', val)[0].strip()

            if fld:
                if 'date' in fld or 'period' in fld or 'birth' in fld:
                    cleaned = clean_ocr_date(val)
                elif any(x in fld for x in ['amount', 'total', 'balance']):
                    cleaned = clean_ocr_amount(val)
                else:
                    cleaned = clean_ocr_field_text(val)
                    if cleaned:
                        if 'subject' in fld:
                            cleaned = re.sub(r'\s+(?:Dear|Attention|Attn|This\s+letter|Formal\s+notice).*$', '', cleaned, flags=re.I).strip()
                        elif 'id' in fld or 'number' in fld or 'folio' in fld:
                            tokens = cleaned.split() if cleaned else []
                            cleaned = tokens[0] if tokens else cleaned
                        elif 'name' in fld or 'doctor' in fld or 'claimant' in fld or 'sender' in fld or 'recipient' in fld:
                            cleaned = re.sub(r'\s+(?:Clinician|Medical|License|State|Contact|Telephone|Phone|Emergency|Direct|Email|Anti-Money|Loss|Settlement).*$', '', cleaned, flags=re.I).strip()

                if cleaned is not None and raw_scores.get(fld, 0.0) < score:
                    extracted[fld] = cleaned
                    raw_scores[fld] = score
                    confs[fld] = round(min(0.95, score), 3)

        # Cross-field aliases
        if 'full_name' in extracted and 'customer_name' not in extracted:
            extracted['customer_name'] = extracted['full_name']
            confs['customer_name'] = confs['full_name']
        if 'customer_name' in extracted and 'full_name' not in extracted:
            extracted['full_name'] = extracted['customer_name']
            confs['full_name'] = confs['customer_name']
        if 'po_date' in extracted and 'order_date' not in extracted:
            extracted['order_date'] = extracted['po_date']
            confs['order_date'] = confs['po_date']
        if 'party_one' in extracted and 'party_two' in extracted and 'parties' not in extracted:
            extracted['parties'] = f"{extracted['party_one']} & {extracted['party_two']}"
            confs['parties'] = min(confs['party_one'], confs['party_two'])

        return extracted, confs
