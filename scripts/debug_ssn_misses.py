import json
from pathlib import Path
from app.adapters.pii import get_pii_detector

det = get_pii_detector()
misses = []
for p in Path('data/dataset/val').glob('*.json'):
    d = json.load(open(p, encoding='utf-8'))
    types = [x['type'] for x in d.get('pii_entities', [])]
    if 'US_SSN' in types:
        ocr_file = Path('data/dataset/val_ocr_cache') / f"{d['doc_id']}.json"
        if not ocr_file.exists():
            continue
        ocr = json.load(open(ocr_file, encoding='utf-8'))['full_text']
        pred = [e.entity_type for e in det.detect(ocr)]
        if 'US_SSN' not in pred:
            ssn_gt = [x['value'] for x in d['pii_entities'] if x['type'] == 'US_SSN'][0]
            misses.append((d['doc_id'], ssn_gt, ocr))

print(f'Total SSN misses: {len(misses)}')
for did, ssn, ocr in misses[:5]:
    print(f'Doc: {did} | Expected: {ssn}')
    # find lines with SSN or Taxpayer or digits
    lines = [l for l in ocr.split('\n') if 'ssn' in l.lower() or 'tax' in l.lower()]
    print('  OCR snippet:', lines)
