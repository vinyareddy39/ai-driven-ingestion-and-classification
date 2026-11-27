import json
from pathlib import Path
from collections import defaultdict
from app.workers.stages import stage_pii_detect

test_dir = Path('data/dataset/locked_test')
json_files = sorted(test_dir.glob('*.json'))

missed = defaultdict(list)
per_type_counts = defaultdict(lambda: {'gt': 0, 'tp': 0, 'fn': 0})

for jf in json_files:
    with open(jf, 'r', encoding='utf-8') as f:
        gt = json.load(f)
    text = gt.get('text', '')
    gt_pii = gt.get('pii_entities', [])
    pii_res = stage_pii_detect(text)
    pred_types = set(pii_res['pii_types'])
    
    for p in gt_pii:
        ptype = p['type']
        pval = p['value']
        per_type_counts[ptype]['gt'] += 1
        if ptype in pred_types:
            per_type_counts[ptype]['tp'] += 1
        else:
            per_type_counts[ptype]['fn'] += 1
            missed[ptype].append((gt['doc_id'], pval))

print("=== PII RECALL PER ENTITY TYPE ===")
for ptype, c in sorted(per_type_counts.items()):
    rec = (c['tp'] / max(1, c['gt'])) * 100
    tp = c['tp']
    gt_c = c['gt']
    print(f"{ptype:20s}: {tp}/{gt_c} ({rec:5.1f}%)")

print("\n=== MISSED ENTITIES ===")
for ptype, sample_list in missed.items():
    print(f"Type {ptype}: {len(sample_list)} misses")
    for doc_id, val in sample_list[:5]:
        print(f"   [{doc_id}] Value: {val!r}")
