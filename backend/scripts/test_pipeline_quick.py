import sys, os
sys.path.insert(0, 'C:/ml/backend')
from app.core.generalized_pipeline import GeneralizedDocumentPipeline

pipe = GeneralizedDocumentPipeline()
res = pipe.process_file('C:/ml/backend/tests-data/seeded_eval_30/eval_01_form.pdf')
fields = res.get('fields', [])
print('Extracted fields count:', len(fields))
for idx, f in enumerate(fields):
    print(f'  {idx+1}: [{f.get("label")}] = "{f.get("value")}" (conf={f.get("confidence")})')
