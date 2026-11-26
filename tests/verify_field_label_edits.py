import os
import sys
sys.path.insert(0, os.path.abspath("."))
import requests
import json
from app.models.db import get_db_session, CorrectionModel, FieldModel

session = requests.Session()
login = session.post('http://127.0.0.1:8000/api/login', json={'email': 'testuser2@example.com', 'password': 'password123'})
token = login.json().get('token')
headers = {'Authorization': f'Bearer {token}'}

# 1. Test label suggestions endpoint
sug_resp = session.get('http://127.0.0.1:8000/api/label-suggestions?doc_type=invoice', headers=headers)
print('Suggestions status:', sug_resp.status_code)
sugs = sug_resp.json().get('suggestions', [])
print('First 10 suggestions:', sugs[:10])
assert len(sugs) > 0, 'Should return suggestions'

# 2. Fetch batches to find a file
b_resp = session.get('http://127.0.0.1:8000/api/batches', headers=headers)
batches = b_resp.json()
if batches:
    batch_id = batches[0]['id']
    detail = session.get(f'http://127.0.0.1:8000/api/batches/{batch_id}', headers=headers).json()
    files = detail.get('files', [])
    if files:
        f = files[0]
        file_id = f['id']
        print(f'Testing save on file {file_id}')
        
        # Save edits: edit label from "Invoice Number" to "Custom Invoice Number"
        payload = {
            'fields': [
                {
                    'label': 'Custom Invoice Number',
                    'orig_label': 'Invoice Number',
                    'value': 'INV-9999',
                    'orig': 'INV-1001',
                    'conf': 0.99,
                    'src': 'edited',
                    'is_edited': True,
                    'page': 1
                },
                {
                    'label': '',
                    'orig_label': '',
                    'value': 'Some value with no label',
                    'orig': 'Some value with no label',
                    'conf': 0.95,
                    'src': 'read',
                    'page': 1
                }
            ]
        }
        put_resp = session.put(f'http://127.0.0.1:8000/api/files/{file_id}/fields', headers=headers, json=payload)
        print('Put fields status:', put_resp.status_code, put_resp.json())
        
        # Check database record in corrections
        db = get_db_session()
        corr = db.query(CorrectionModel).filter(CorrectionModel.document_id == file_id).order_by(CorrectionModel.created_at.desc()).first()
        assert corr is not None, 'Correction record must exist'
        print('Saved Correction record:')
        print(' - original_label:', corr.original_label)
        print(' - new_label:', corr.new_label)
        print(' - original_value:', corr.original_value)
        print(' - new_value:', corr.new_value)
        print(' - who_edited:', corr.who_edited)
        print(' - timestamp:', corr.created_at)
        print(' - document_id:', corr.document_id)
        print(' - pipeline_version:', corr.pipeline_version)
        
        # Verify all required fields
        assert corr.original_label == 'Invoice Number'
        assert corr.new_label == 'Custom Invoice Number'
        assert corr.original_value == 'INV-1001'
        assert corr.new_value == 'INV-9999'
        assert corr.who_edited == 'testuser2@example.com'
        assert corr.document_id == file_id
        assert corr.pipeline_version is not None
        assert corr.created_at is not None
        
        # Check fields in batch detail
        refreshed = session.get(f'http://127.0.0.1:8000/api/batches/{batch_id}', headers=headers).json()
        r_file = [x for x in refreshed['files'] if x['id'] == file_id][0]
        print('Refreshed fields count:', len(r_file['fields']))
        for rf in r_file['fields']:
            print(f'  Field: label=\"{rf["label"]}\" orig_label=\"{rf["orig_label"]}\" is_edited={rf["is_edited"]}')
        
        assert r_file['fields'][0]['is_edited'] == True
        print('ALL ASSERTIONS PASSED!')
