import sqlite3
import os

db_path = "data/ecm_pipeline.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("UPDATE files SET error = NULL WHERE error LIKE '%Fast Lane%' OR error LIKE '%connect to text LLMs%'")
    rows = c.rowcount
    conn.commit()
    conn.close()
    print(f"Cleaned {rows} file records with Fast Lane error.")
else:
    print("DB file not found.")
