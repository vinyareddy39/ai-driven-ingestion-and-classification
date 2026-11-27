import os
import sys
import json
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.ocr import HybridOCREngine

def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

def calculate_cer(reference: str, hypothesis: str) -> float:
    # Normalize whitespaces for fair CER comparison
    ref_clean = "".join(reference.split())
    hyp_clean = "".join(hypothesis.split())
    if not ref_clean:
        return 0.0 if not hyp_clean else 1.0
    dist = levenshtein_distance(ref_clean, hyp_clean)
    return dist / len(ref_clean)

def run_cer_benchmark(val_dir: str = "data/dataset/val", max_samples: int = 50, psm: int = None, use_preprocessing: bool = False):
    engine = HybridOCREngine()
    val_path = Path(val_dir)
    json_files = sorted(list(val_path.glob("*.json")))[:max_samples]
    
    total_cer = 0.0
    total_chars = 0
    total_dist = 0
    t0 = time.time()
    
    print(f"Running CER Benchmark on {len(json_files)} val samples (PSM={psm}, Advanced Preprocessing={use_preprocessing})...")
    for jf in json_files:
        with open(jf, "r", encoding="utf-8") as f:
            meta = json.load(f)
        pdf_path = val_path / meta["file_name"]
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
            
        res = engine.extract_text(pdf_bytes, "pdf")
        gt_text = meta.get("text", "")
        
        ref_clean = "".join(gt_text.split())
        hyp_clean = "".join(res.full_text.split())
        dist = levenshtein_distance(ref_clean, hyp_clean)
        
        total_dist += dist
        total_chars += len(ref_clean)
        
    duration = time.time() - t0
    macro_cer = (total_dist / total_chars) * 100.0 if total_chars > 0 else 0.0
    print(f"Results: Total Chars={total_chars}, Total Distance={total_dist}, Macro CER={macro_cer:.2f}% | Time={duration:.2f}s ({duration/len(json_files):.2f}s/doc)")
    return macro_cer

if __name__ == "__main__":
    run_cer_benchmark()
