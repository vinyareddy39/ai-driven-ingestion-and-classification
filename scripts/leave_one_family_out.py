"""Leave-One-Template-Family-Out Cross-Evaluation.

Experiment 1: Train & tune on Template Family V1, evaluate on Family V2 (Holdout 3).
Experiment 2: Train & tune on Template Family V2, evaluate on Family V1 (Holdout 2).
Reports per-class classification precision/recall and per-field extraction accuracy.
"""

import json
from pathlib import Path
from collections import defaultdict
import difflib
import sys
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.workers.generic_extractor import GenericKeyValueExtractor, clean_ocr_field_text, clean_ocr_date, clean_ocr_amount

ALL_CLASSES = [
    "invoice", "contract", "kyc_form", "bank_statement",
    "medical_report", "purchase_order", "letter", "claim_form", "unknown"
]

EVAL_FIELDS_MAP = {
    "invoice": ["invoice_number", "invoice_date", "total_amount", "vendor_name"],
    "contract": ["contract_id", "effective_date", "parties"],
    "kyc_form": ["customer_name", "date_of_birth", "id_number"],
    "bank_statement": ["account_number", "statement_period", "closing_balance"],
    "medical_report": ["patient_id", "diagnosis", "doctor_name"],
    "purchase_order": ["po_number", "order_date", "total_amount", "vendor_name"],
    "letter": ["sender", "recipient", "date", "subject"],
    "claim_form": ["claim_id", "claimant_name", "incident_date", "claim_amount"],
}

# V1-only synonyms (standard baseline labels)
SYNONYMS_V1_ONLY = {
    "invoice": {
        "invoice_number": ["invoice number", "invoice no", "inv #", "bill no", "invoice #", "inv no"],
        "invoice_date": ["invoice date", "date of issue", "issue date", "date"],
        "total_amount": ["total amount", "balance due", "grand total", "total due", "total"],
        "vendor_name": ["vendor name", "billed by", "supplier name", "supplier", "vendor"],
    },
    "contract": {
        "contract_id": ["contract id", "contract no", "agreement no", "contract #"],
        "effective_date": ["effective date", "execution date", "date"],
        "parties": ["parties", "first party", "party one", "party two"],
    },
    "kyc_form": {
        "customer_name": ["customer name", "full name", "legal name", "applicant name", "name"],
        "id_number": ["passport #", "passport no", "id number", "national id", "document id"],
        "date_of_birth": ["birthdate", "date of birth", "dob", "birth date"],
    },
    "bank_statement": {
        "account_number": ["account number", "acct #", "account no", "acct number"],
        "statement_period": ["statement period", "reporting cycle", "period"],
        "closing_balance": ["closing balance", "ending balance", "final balance"],
    },
    "medical_report": {
        "patient_id": ["patient id", "medical record no", "mrn", "patient ref"],
        "diagnosis": ["primary diagnosis", "diagnosis", "clinical findings", "assessment"],
        "doctor_name": ["attending physician", "doctor", "physician", "attending clinician"],
    },
    "purchase_order": {
        "po_number": ["po number", "order number", "p.o. #", "po #"],
        "order_date": ["po date", "order date", "purchase date", "date"],
        "vendor_name": ["vendor name", "supplier name", "supplier", "vendor"],
        "total_amount": ["order total", "total cost", "total purchase amount", "total"],
    },
    "letter": {
        "sender": ["from", "sender", "originator"],
        "recipient": ["to", "recipient", "addressee"],
        "date": ["date", "letter date"],
        "subject": ["subject", "re", "regarding"],
    },
    "claim_form": {
        "claim_id": ["claim id", "claim no", "claim #"],
        "incident_date": ["incident date", "date of loss", "date of occurrence"],
        "claimant_name": ["claimant name", "claimant", "insured party"],
        "claim_amount": ["claim amount", "total claimed amount", "requested amount"],
    },
}

# V2-only synonyms (curated strictly for V2 variations)
SYNONYMS_V2_ONLY = {
    "invoice": {
        "invoice_number": ["billing identifier", "billing ref", "reference folio"],
        "invoice_date": ["billing timestamp", "date of invoicing", "issued date"],
        "total_amount": ["remittance total", "net due", "amount payable"],
        "vendor_name": ["vendor organization", "payee / supplier", "payee", "remit to"],
    },
    "contract": {
        "contract_id": ["agreement ref", "covenant reference #", "contract tracking code", "instrument number"],
        "effective_date": ["commencement date", "effective covenant date"],
        "parties": ["principal signatories", "counterparties", "engaged parties", "disclosing entity"],
    },
    "kyc_form": {
        "customer_name": ["subject full legal name", "applicant complete name", "full identity name"],
        "id_number": ["legal passport serial", "national passport no", "identification travel passport #"],
        "date_of_birth": ["birth registration date", "date of birth (dob)"],
    },
    "bank_statement": {
        "account_number": ["account reference code", "depository ledger identifier", "settlement account #"],
        "statement_period": ["reporting interval", "accounting interval", "reporting timeframe"],
        "closing_balance": ["closing settlement balance", "closing period ledger", "ending depository balance"],
    },
    "medical_report": {
        "patient_id": ["patient clinical identifier", "medical record #", "patient medical id"],
        "diagnosis": ["primary clinical findings", "clinician evaluation / diagnosis", "assessment / impression", "impression"],
        "doctor_name": ["attending clinician", "lead physician", "practitioner", "provider attestation"],
    },
    "purchase_order": {
        "po_number": ["po reference no", "po reference #", "reference no", "procurement tracking #", "order slip code", "requisition tracking folio"],
        "order_date": ["issuance date", "requisition date", "procurement authorization date"],
        "vendor_name": ["authorized vendor", "supplier entity", "supplier organization"],
        "total_amount": ["aggregate commitment", "authorized requisition sum", "total purchase value", "aggregate requisition value"],
    },
    "letter": {
        "sender": ["transmitted by", "originator / from", "dispatched by"],
        "recipient": ["deliver to", "recipient / to"],
        "date": ["dispatch date", "correspondence date", "date of notice"],
        "subject": ["subject header", "re / in reference to", "subject matter"],
    },
    "claim_form": {
        "claim_id": ["policy claim docket", "claim record id", "claim reference #"],
        "incident_date": ["loss occurrence date"],
        "claimant_name": ["claimant full name", "policyholder / claimant", "applicant"],
        "claim_amount": ["settlement demand", "claimed compensation", "claimed loss amount"],
    },
}


def build_classifier(texts, labels):
    features = FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), max_features=10000, sublinear_tf=True)),
        ("char", TfidfVectorizer(ngram_range=(3, 5), analyzer="char_wb", max_features=15000, sublinear_tf=True)),
    ])
    clf = Pipeline([
        ("features", features),
        ("classifier", LogisticRegression(C=5.0, max_iter=1000, class_weight="balanced", random_state=42))
    ])
    clf.fit(texts, labels)
    return clf


def run_experiment(exp_name: str, train_docs: list, test_docs: list, syn_dict: dict):
    print("=" * 80)
    print(f"LEAVE-ONE-FAMILY-OUT: {exp_name.upper()}")
    print("=" * 80)
    print(f"Training Documents: {len(train_docs)} | Evaluation Documents: {len(test_docs)}")

    train_texts = [d["text"] for d in train_docs]
    train_labels = [d["doc_type"] for d in train_docs]
    clf = build_classifier(train_texts, train_labels)

    # Classify & Extract on test set
    extractor = GenericKeyValueExtractor()
    extractor.synonyms = syn_dict

    y_true = []
    y_pred = []
    field_stats = defaultdict(lambda: {"correct": 0, "total": 0})
    class_field_stats = defaultdict(lambda: defaultdict(lambda: {"correct": 0, "total": 0}))

    for doc in test_docs:
        gt_type = doc["doc_type"]
        text = doc["text"]
        gt_fields = doc["fields"]

        pred_type = clf.predict([text])[0]
        y_true.append(gt_type)
        y_pred.append(pred_type)

        extracted, confs = extractor.extract(text, pred_type)

        if gt_type != "unknown":
            for fk in EVAL_FIELDS_MAP.get(gt_type, []):
                fv = gt_fields.get(fk)
                if fv is None:
                    continue
                field_stats[fk]["total"] += 1
                class_field_stats[gt_type][fk]["total"] += 1

                ext_val = extracted.get(fk)
                match = False
                if ext_val is not None:
                    if str(ext_val).lower().strip() == str(fv).lower().strip():
                        match = True
                    elif isinstance(fv, float) and isinstance(ext_val, (int, float)) and abs(ext_val - fv) < 0.05:
                        match = True
                    elif difflib.SequenceMatcher(None, str(ext_val).lower().strip(), str(fv).lower().strip()).ratio() >= 0.80:
                        match = True
                if match:
                    field_stats[fk]["correct"] += 1
                    class_field_stats[gt_type][fk]["correct"] += 1

    # Print Classification Results
    print("\n1. CLASSIFICATION PERFORMANCE PER CLASS")
    print("-" * 75)
    print(f"{'Class':<20} {'Correct':<10} {'Total':<10} {'Recall':<12}")
    print("-" * 75)
    cls_counts = defaultdict(lambda: {"correct": 0, "total": 0})
    for yt, yp in zip(y_true, y_pred):
        cls_counts[yt]["total"] += 1
        if yt == yp:
            cls_counts[yt]["correct"] += 1

    for c in ALL_CLASSES:
        st = cls_counts[c]
        rec = (st["correct"] / st["total"] * 100) if st["total"] > 0 else 0
        print(f"{c:<20} {st['correct']:5d}      {st['total']:5d}      {rec:6.2f}%")

    overall_cls = sum(st["correct"] for st in cls_counts.values()) / max(1, sum(st["total"] for st in cls_counts.values())) * 100
    print("-" * 75)
    print(f"{'OVERALL CLASSIFICATION':<20} {sum(st['correct'] for st in cls_counts.values()):5d}      {len(y_true):5d}      {overall_cls:6.2f}%\n")

    # Print Extraction Results
    print("2. FIELD EXTRACTION ACCURACY PER CLASS & FIELD")
    print("-" * 75)
    for c in ALL_CLASSES:
        if c == "unknown": continue
        c_tot = sum(class_field_stats[c][fk]["total"] for fk in class_field_stats[c])
        c_cor = sum(class_field_stats[c][fk]["correct"] for fk in class_field_stats[c])
        c_acc = (c_cor / c_tot * 100) if c_tot > 0 else 0
        print(f"Class: {c:<18} [{c_cor:3d}/{c_tot:3d} = {c_acc:6.2f}%]")
        for fk, st in sorted(class_field_stats[c].items()):
            f_acc = (st["correct"] / st["total"] * 100) if st["total"] > 0 else 0
            print(f"  - {fk:<22} {st['correct']:3d}/{st['total']:3d} ({f_acc:6.2f}%)")

    tot_f_cor = sum(st["correct"] for st in field_stats.values())
    tot_f_tot = sum(st["total"] for st in field_stats.values())
    overall_ext = (tot_f_cor / tot_f_tot * 100) if tot_f_tot > 0 else 0
    print("-" * 75)
    print(f"OVERALL FIELD EXTRACTION ACCURACY: {tot_f_cor}/{tot_f_tot} = {overall_ext:.2f}%\n")


def load_dataset_records(dir_path: str, cache_file: str = None) -> list:
    p = Path(dir_path)
    files = sorted([f for f in p.glob("*.json") if f.name != "manifest.json"])
    cache = {}
    if cache_file and Path(cache_file).exists():
        cache = json.load(open(cache_file, encoding="utf-8"))
    records = []
    for f in files:
        meta = json.load(open(f, encoding="utf-8"))
        did = meta["doc_id"]
        text = cache.get(did, {}).get("full_text") or meta.get("full_text") or meta.get("text", "")
        records.append({
            "doc_id": did,
            "doc_type": meta["doc_type"],
            "text": text,
            "fields": meta.get("fields", {})
        })
    return records


if __name__ == "__main__":
    # Load V1 Family (Train + Val + Holdout 2)
    v1_train = load_dataset_records("data/dataset/train")
    v1_val = load_dataset_records("data/dataset/val")
    v1_holdout2 = load_dataset_records("data/dataset/holdout2", "data/ocr_cache_holdout2.json")
    v1_all = v1_train + v1_val

    # Load V2 Family (Holdout 3)
    v2_all = load_dataset_records("data/dataset/holdout3", "data/ocr_cache_holdout3.json")

    # Run Exp 1: Train on V1, Evaluate on V2 with V1-only synonyms (Unseen generalization)
    run_experiment("Exp 1: Train & Tune on V1 -> Evaluate on V2 (Holdout 3, V1-only Synonyms)", v1_all, v2_all, SYNONYMS_V1_ONLY)

    # Run Exp 2: Train on V2, Evaluate on V1 (Holdout 2) with V2-only synonyms
    run_experiment("Exp 2: Train & Tune on V2 -> Evaluate on V1 (Holdout 2, V2-only Synonyms)", v2_all, v1_holdout2, SYNONYMS_V2_ONLY)
