"""Part 3: Data-Driven Field Extraction Utility Analysis and Schema Proposal.

Evaluates candidate fields per document type based on:
1. Downstream workflow step / routing decision usage
2. Business criticality (Required vs Optional)
3. Measured extraction accuracy from Part 2
4. Categorization: KEEP, KEEP WITH REVIEW, MOVE TO RAW TEXT, or DROP
5. Reviewer correction frequencies from the corrections table
6. Produces updated proposal schema file: config/proposed_schema_v3.yaml
"""

import os
import sys
sys.path.insert(0, os.path.abspath("."))
import json
import yaml
import collections
from app.models.db import get_db_session, CorrectionModel

def analyze():
    # Load Part 2 evaluation results
    acc_report_path = "data/verification/accuracy_suite/results/part2_accuracy_report.json"
    field_accuracies = {}
    if os.path.exists(acc_report_path):
        with open(acc_report_path, "r", encoding="utf-8") as f:
            part2 = json.load(f)
            for k, v in part2.get("key_fields", {}).items():
                field_accuracies[k] = v.get("precision", 0.0)

    # Downstream workflow mapping per field concept
    downstream_map = {
        "invoice": {
            "invoice_number": ("AP_INVOICE_PROCESSING", True),
            "invoice_date": ("AP_INVOICE_PROCESSING", True),
            "due_date": ("CASHFLOW_FORECASTING", True),
            "vendor_name": ("VENDOR_MANAGEMENT", True),
            "customer_name": ("ENTITY_VERIFICATION", False),
            "total_amount": ("FINANCE_GENERAL_LEDGER", True),
            "subtotal": ("TAX_RECONCILIATION", False),
            "tax_amount": ("TAX_RECONCILIATION", False)
        },
        "receipt": {
            "receipt_number": ("FINANCE_EXPENSE_MANAGEMENT", True),
            "date": ("FINANCE_EXPENSE_MANAGEMENT", True),
            "merchant_name": ("FINANCE_EXPENSE_MANAGEMENT", True),
            "total_paid": ("FINANCE_EXPENSE_MANAGEMENT", True),
            "payment_method": ("FINANCE_EXPENSE_MANAGEMENT", False)
        },
        "contract": {
            "contract_id": ("LEGAL_CONTRACTS_REPOSITORY", True),
            "effective_date": ("LEGAL_COMPLIANCE", True),
            "first_party": ("LEGAL_COMPLIANCE", True),
            "second_party": ("LEGAL_COMPLIANCE", True),
            "governing_law": ("LEGAL_COMPLIANCE", False),
            "signatory": ("none", False),
            "expiration_date": ("none", False)
        },
        "medical_report": {
            "patient_name": ("RESTRICTED_HIPAA_SECURE_VAULT", True),
            "patient_id": ("RESTRICTED_HIPAA_SECURE_VAULT", True),
            "date_of_birth": ("RESTRICTED_HIPAA_SECURE_VAULT", True),
            "doctor_name": ("CLINICAL_RECORDS_SYSTEM", False),
            "diagnosis": ("CLINICAL_RECORDS_SYSTEM", True),
            "test_date": ("CLINICAL_RECORDS_SYSTEM", False),
            "specimen_type": ("CLINICAL_RECORDS_SYSTEM", False)
        },
        "bank_statement": {
            "account_holder": ("FINANCE_TREASURY_OPERATIONS", True),
            "account_number": ("FINANCE_TREASURY_OPERATIONS", True),
            "opening_balance": ("FINANCE_TREASURY_OPERATIONS", True),
            "closing_balance": ("FINANCE_TREASURY_OPERATIONS", True),
            "statement_period": ("FINANCE_TREASURY_OPERATIONS", False),
            "bank_name": ("FINANCE_TREASURY_OPERATIONS", False)
        },
        "purchase_order": {
            "po_number": ("PROCUREMENT_OPERATIONS", True),
            "vendor_name": ("PROCUREMENT_OPERATIONS", True),
            "order_date": ("PROCUREMENT_OPERATIONS", True),
            "total_amount": ("PROCUREMENT_OPERATIONS", True),
            "shipping_address": ("none", False),
            "buyer_name": ("none", False)
        }
    }

    # Analyze Reviewer Corrections from DB
    db = get_db_session()
    corrections = db.query(CorrectionModel).all()
    edited_field_counts = collections.Counter()
    for c in corrections:
        lbl = c.new_label or c.label or "unknown"
        edited_field_counts[lbl] += 1

    ACCURACY_TARGET = 0.95
    analysis_table = []
    category_counts = collections.defaultdict(int)

    proposed_schema = {
        "version": "3.0.0-proposed",
        "accuracy_target": ACCURACY_TARGET,
        "document_types": {}
    }

    for doc_type, fields in downstream_map.items():
        type_schema = {
            "recommended_fields": [],
            "review_required_fields": [],
            "removed_fields": {}
        }
        for f_name, (workflow_dest, is_required) in fields.items():
            human_label = f_name.replace("_", " ").title()
            
            # Robust lookup across snake_case, human label, and lowercase
            measured_val = None
            for candidate_key in [f_name, human_label, human_label.lower(), f_name.lower()]:
                if candidate_key in field_accuracies:
                    measured_val = field_accuracies[candidate_key]
                    break

            is_measured = measured_val is not None
            measured_acc = measured_val if is_measured else None
            
            # Downstream workflow labeled as assumed unless explicit config source
            workflow_display = f"{workflow_dest} (assumed)" if workflow_dest != "none" else "none"

            # Decision Logic:
            # 1. If workflow is none and not required -> MOVE TO RAW TEXT
            # 2. If not measured -> KEEP WITH REVIEW (or UNMEASURED / KEEP WITH REVIEW)
            # 3. If measured and >= 0.95 -> KEEP
            # 4. If measured and < 0.95 -> KEEP WITH REVIEW
            if workflow_dest == "none":
                if is_required:
                    rec = "KEEP WITH REVIEW"
                else:
                    rec = "MOVE TO RAW TEXT"
            else:
                if not is_measured:
                    rec = "KEEP WITH REVIEW"
                elif measured_acc >= ACCURACY_TARGET:
                    rec = "KEEP"
                else:
                    rec = "KEEP WITH REVIEW"

            category_counts[rec] += 1
            analysis_table.append({
                "doc_type": doc_type,
                "field": f_name,
                "label": human_label,
                "workflow": workflow_display,
                "required": is_required,
                "measured_accuracy": round(measured_acc * 100, 1) if is_measured else "not measured",
                "recommendation": rec
            })

            if rec == "KEEP":
                type_schema["recommended_fields"].append(f_name)
            elif rec == "KEEP WITH REVIEW":
                type_schema["review_required_fields"].append(f_name)
            else:
                type_schema["removed_fields"][f_name] = f"Workflow: {workflow_dest}; Recommendation: {rec}"

        proposed_schema["document_types"][doc_type] = type_schema

    # Save proposal file
    os.makedirs("config", exist_ok=True)
    with open("config/proposed_schema_v3.yaml", "w", encoding="utf-8") as f:
        yaml.dump(proposed_schema, f, sort_keys=False)

    report_data = {
        "accuracy_target": ACCURACY_TARGET,
        "recommendation_summary": dict(category_counts),
        "frequently_edited_fields": dict(edited_field_counts.most_common(5)),
        "fields_table": analysis_table
    }

    with open("data/verification/accuracy_suite/results/part3_field_utility.json", "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    print("\n" + "=" * 70)
    print("PART 3 FIELD EXTRACTION UTILITY ANALYSIS COMPLETE")
    print("Recommendation Breakdown:")
    for k, v in category_counts.items():
        print(f" - {k}: {v} fields")
    print(f"Frequently Edited Fields from Feedback: {dict(edited_field_counts.most_common(5))}")
    print("Saved proposed schema to config/proposed_schema_v3.yaml")
    print("=" * 70)

if __name__ == "__main__":
    analyze()
