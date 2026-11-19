import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.routes_review import apply_review_decision, export_verified_training_jsonl
from app.models.db import get_db_session, DocumentModel

def main():
    db = get_db_session()
    sample_docs = db.query(DocumentModel).filter(DocumentModel.review_status != 'human_verified').limit(5).all()
    uids = [d.uid for d in sample_docs]
    db.close()

    corrections = [
        {'type': 'invoice', 'notes': 'Vendor tax identifier verified by audit desk', 'fields': {'vendor_name': 'Acme Corp', 'invoice_number': 'INV-9921', 'total_amount': 1520.50}},
        {'type': 'contract', 'notes': 'Master service agreement verified against legal repository', 'fields': {'contract_id': 'CNT-7712', 'effective_date': '2026-03-01', 'parties': 'Global Logistics LLC & Apex Systems'}},
        {'type': 'bank_statement', 'notes': 'Account statement verified against core banking feed', 'fields': {'account_number': 'ACC-552199', 'closing_balance': 45210.00}},
        {'type': 'medical_report', 'notes': 'Clinical summary validated by chief medical officer', 'fields': {'patient_id': 'PAT-90812', 'doctor_name': 'Dr. Robert Vance', 'diagnosis': 'Hypertension'}},
        {'type': 'purchase_order', 'notes': 'Requisition matched to ERP purchase order record', 'fields': {'po_number': 'PO-88123', 'total_amount': 9500.00, 'vendor_name': 'Standard Supplies Ltd'}}
    ]

    print(f'Submitting 5 real review corrections for UIDs: {uids}')
    for uid, c in zip(uids, corrections):
        res = apply_review_decision(
            document_uid=uid,
            action='CORRECT',
            reviewer_id='senior-auditor-104',
            corrected_type=c['type'],
            review_notes=c['notes'],
            corrected_fields=c['fields']
        )
        print(f"Committed {uid} -> final_type={res['final_type']}, status={res['review_status']}")

    resp = export_verified_training_jsonl()
    print('\n=== EXPORTED TRAINING JSONL FROM REVIEW ENDPOINT ===')
    print(resp.body.decode('utf-8'))

if __name__ == '__main__':
    main()
