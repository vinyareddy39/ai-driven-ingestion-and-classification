import os
import sys
import time
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scratch', 'testgen'))
import run_and_score

def wait_and_rescore():
    print("Monitoring database queue until all files finish reading...")
    db_path = os.path.join(os.path.dirname(__file__), '..', 'backend', 'data', 'ecm_pipeline.db')
    
    for i in range(120):
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT status, count(*) FROM files WHERE status IN ('queued', 'processing', 'Reading', 'Waiting', 'reading') GROUP BY status")
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            print("All files finished reading!")
            break
        print(f"[{i*3}s] Active reading jobs remaining: {dict(rows)}")
        time.sleep(3)

    print("\nFetching latest file records from database for all 129 test files...")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        SELECT f.name, f.document_type, f.type_confidence, f.status, f.extracted_data
        FROM files f
    """)
    file_map = {}
    for name, doc_type, type_conf, status, ext_data in c.fetchall():
        import json
        fields_dict = {}
        if ext_data:
            try:
                data = json.loads(ext_data)
                # Extracted fields can be in fields list
                for fld in data.get("fields", []):
                    lbl = (fld.get("label") or "").strip()
                    val = (fld.get("value") or "").strip()
                    conf = fld.get("conf", 1.0)
                    if lbl:
                        fields_dict[lbl] = (val, conf)
            except Exception:
                pass
        
        file_map[name] = {
            "file": name,
            "type": doc_type or "unknown",
            "type_confidence": type_conf or 0.0,
            "status": status or "unknown",
            "fields": fields_dict
        }
    conn.close()

    print(f"Loaded {len(file_map)} files from database.")
    run_and_score.score_results(file_map)

if __name__ == '__main__':
    wait_and_rescore()
