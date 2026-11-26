import sqlite3
from app.core.generalized_pipeline import GeneralizedDocumentPipeline

conn = sqlite3.connect('data/ecm_pipeline.db')
c = conn.cursor()
c.execute("SELECT id, original_name, stored_path FROM files WHERE batch_id='da660896-dda0-4aa4-8a2a-1f704823d64c'")
pipe = GeneralizedDocumentPipeline()
for fid, name, path in c.fetchall():
    try:
        res = pipe.process_file(path)
        print(f"{name} ({fid}): SUCCESS, type={res.get('type')}, fields={len(res.get('fields', []))}")
    except Exception as e:
        print(f"{name} ({fid}): FAILED, error={e}")
