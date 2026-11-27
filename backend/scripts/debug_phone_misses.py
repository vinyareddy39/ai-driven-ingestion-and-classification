import json
from pathlib import Path
from app.adapters.pii import get_pii_detector

det = get_pii_detector()
misses = []
for p in Path('data/dataset/val').glob('*.json'):
    d = json.load(open(p, encoding='utf-8'))
    phones = [x['value'] for x in d.get('pii_entities', []) if x['type'] == 'PHONE_NUMBER']
    if phones:
        ocr_file = Path('data/dataset/val_ocr_cache') / f"{d['doc_id']}.json"
        if not ocr_file.exists(): continue
        ocr = json.load(open(ocr_file, encoding='utf-8'))['full_text']
        pred = [e.entity_type for e in det.detect(ocr)]
        if 'PHONE_NUMBER' not in pred:
            misses.append((d['doc_id'], phones[0], ocr))

print(f'Total phone misses: {len(misses)}')
for did, ph, ocr in misses[:5]:
    print(f'Doc: {did} | Expected: {ph}')
    lines = [l for l in ocr.split('\n') if 'phone' in l.lower() or 'contact' in l.lower() or 'tele' in l.lower()]
    print('  OCR snippet:', lines)
