import json
from pathlib import Path

for p in sorted(list(Path('data/dataset/val').glob('bank_statement_*.json')))[:5]:
    d = json.load(open(p, encoding='utf-8'))
    ocr = json.load(open(Path('data/dataset/val_ocr_cache') / f"{d['doc_id']}.json", encoding='utf-8'))['full_text']
    iban = [x['value'] for x in d['pii_entities'] if x['type'] == 'IBAN_CODE'][0]
    lines = [l for l in ocr.split('\n') if 'iban' in l.lower() or 'ban' in l.lower()]
    print(f"{d['doc_id']} | Expected: {iban} | OCR: {lines}")
