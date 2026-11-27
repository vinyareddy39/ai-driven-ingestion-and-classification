import os
import time
import requests

BASE_URL = 'http://127.0.0.1:8000'
login = requests.post(f'{BASE_URL}/api/login', json={'email': 'testuser2@example.com', 'password': 'password123'})
token = login.json()['token']
headers = {'Authorization': f'Bearer {token}'}

fpath = 'C:/ml/backend/tests-data/seeded_eval_30/eval_01_form.pdf'
with open(fpath, 'rb') as fp:
    b_res = requests.post(f'{BASE_URL}/api/batches', files=[('files', ('eval_01_form.pdf', fp, 'application/pdf'))], headers=headers)
batch_data = b_res.json()
batch_id = batch_data['id']
print('Batch created:', batch_id)

start_res = requests.post(f'{BASE_URL}/api/batches/{batch_id}/start', headers=headers)
print('Start status:', start_res.status_code)

file_id = None
for i in range(25):
    time.sleep(1)
    status_res = requests.get(f'{BASE_URL}/api/batches/{batch_id}', headers=headers).json()
    f = status_res['files'][0]
    stage = f.get('stage')
    fields_cnt = len(f.get('fields', []))
    print(f'Poll {i+1}: stage={stage}, fields={fields_cnt}')
    if stage == 'Done':
        file_id = f['id']
        print(f'FILE DONE! batch_id={batch_id}, file_id={file_id}')
        break

if not file_id:
    print('Failed to reach Done in time')
