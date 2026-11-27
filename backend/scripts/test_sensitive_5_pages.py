import sys
import os
sys.path.insert(0, 'C:/ml/backend')
from app.core.generalized_pipeline import GeneralizedDocumentPipeline

pipeline = GeneralizedDocumentPipeline()
test_docs = ['eval_01_form.pdf', 'eval_02_form.pdf', 'eval_03_form.pdf', 'eval_04_form.pdf', 'eval_05_form.pdf']
eval_dir = 'C:/ml/backend/tests-data/seeded_eval_30'

print('=== 5-PAGE SENSITIVE DETECTOR PROOF ===')
for d in test_docs:
    fpath = os.path.join(eval_dir, d)
    res = pipeline.process_file(fpath)
    fields = res.get('fields', [])
    sens_fields = [f for f in fields if f.get('is_sensitive')]
    print(f'Document: {d}')
    print(f'  Total fields: {len(fields)}')
    print(f'  Sensitive findings: {len(sens_fields)}')
    for sf in sens_fields:
        print(f'    Field "{sf.get("label")}": raw="{sf.get("orig") or sf.get("value")}", masked="{sf.get("masked_value")}", detector={sf.get("detector_tag")}')
    print(f'  Summary text: {res.get("summary")}')
