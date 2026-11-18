import json
from pathlib import Path
from collections import defaultdict
from app.workers.stages import stage_extract_fields

test_dir = Path('data/dataset/locked_test')
json_files = sorted(test_dir.glob('*.json'))

field_stats = defaultdict(lambda: {'expected': 0, 'correct': 0, 'failures': []})

for jf in json_files:
    with open(jf, 'r', encoding='utf-8') as f:
        gt = json.load(f)
    doc_type = gt['doc_type']
    text = gt.get('text', '')
    gt_fields = gt.get('fields', {})
    
    ext_fields, _, _ = stage_extract_fields(text, doc_type)
    for k, v in gt_fields.items():
        field_key = f"{doc_type}.{k}"
        field_stats[field_key]['expected'] += 1
        ext_val = ext_fields.get(k)
        
        is_match = False
        if ext_val is not None:
            if str(ext_val).lower().strip() == str(v).lower().strip():
                is_match = True
            elif isinstance(v, float) and isinstance(ext_val, (int, float)) and abs(ext_val - v) < 0.01:
                is_match = True
        
        if is_match:
            field_stats[field_key]['correct'] += 1
        else:
            field_stats[field_key]['failures'].append({
                'doc_id': gt.get('doc_id'),
                'expected': v,
                'extracted': ext_val,
                'full_text': text,
            })

print("=== PER-FIELD ACCURACY RANKING ===")
ranked = sorted(field_stats.items(), key=lambda x: (x[1]['correct'] / max(1, x[1]['expected'])))
for fk, st in ranked:
    acc = (st['correct'] / st['expected']) * 100
    c = st['correct']
    e = st['expected']
    print(f"{fk:32s}: {c:2d}/{e:2d} ({acc:5.1f}%)")

print("\n=== TOP 10 WORST FIELDS AND 3 SAMPLES EACH ===")
for fk, st in ranked[:10]:
    acc = (st['correct'] / st['expected']) * 100
    print(f"\n--- Field: {fk} (Accuracy: {acc:.1f}%) ---")
    for sample in st['failures'][:3]:
        exp = sample['expected']
        ext = sample['extracted']
        doc_id = sample['doc_id']
        txt = sample['full_text']
        # Find lines in text matching expected
        matching_lines = [line.strip() for line in txt.split('\n') if str(exp).lower() in line.lower() or fk.split('.')[1].replace('_', ' ') in line.lower()]
        snippet = " | ".join(matching_lines[:2])
        print(f"  [{doc_id}] Expected: {exp!r} | Extracted: {ext!r}")
        print(f"    Snippet: {snippet}")
