import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.workers.stages import stage_extract_fields

def main():
    with open('data/ocr_cache_holdout4.json', 'r', encoding='utf-8') as f:
        ocr_cache = json.load(f)

    h4_dir = Path('data/dataset/holdout4')
    json_files = sorted([f for f in h4_dir.glob('*.json') if f.name != 'manifest.json'])
    correct = 0
    total = 0
    by_class = {}
    for jf in json_files:
        with open(jf, 'r', encoding='utf-8') as f:
            gt = json.load(f)
        did = gt['doc_id']
        dt = gt['doc_type']
        if dt not in by_class:
            by_class[dt] = {'c': 0, 't': 0}
        gt_fields = gt.get('fields', {})
        text = ocr_cache.get(did, {}).get('full_text', '')
        extracted, confs, _ = stage_extract_fields(text, dt)
        for k, v in gt_fields.items():
            total += 1
            by_class[dt]['t'] += 1
            ev = extracted.get(k)
            if ev is not None and str(ev).strip() == str(v).strip():
                correct += 1
                by_class[dt]['c'] += 1

    print('=== HOLDOUT 4 RESULTS ===')
    print(f'Overall Accuracy: {correct}/{total} = {correct/total*100:.2f}%')
    for dt, s in sorted(by_class.items()):
        acc = s['c'] / s['t'] * 100 if s['t'] else 0.0
        print(f"  {dt:<18}: {s['c']}/{s['t']} ({acc:.2f}%)")

if __name__ == '__main__':
    main()
