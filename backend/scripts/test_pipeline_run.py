import sys
import os
import json

sys.path.insert(0, os.path.abspath("."))
from app.core.generalized_pipeline import GeneralizedDocumentPipeline

def main():
    pipeline = GeneralizedDocumentPipeline()
    test_dir = os.path.abspath("test_files")
    files = sorted([f for f in os.listdir(test_dir) if f.lower().endswith(".pdf")])
    
    print(f"Found {len(files)} files in {test_dir}:")
    for fname in files:
        fpath = os.path.join(test_dir, fname)
        result = pipeline.process_file(fpath)
        print("=" * 80)
        print(f"FILE: {fname}")
        print("=" * 80)
        print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
