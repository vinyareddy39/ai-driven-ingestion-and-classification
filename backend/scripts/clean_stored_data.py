import os
import glob
import sqlite3
import shutil

# 1. Inspect existing DB counts
db_path = 'data/ecm_pipeline.db'
before_counts = {}
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    for t in tables:
        try:
            cur.execute(f"SELECT count(*) FROM {t}")
            before_counts[t] = cur.fetchone()[0]
        except:
            pass
    conn.close()

# File counts before
storage_files = len(os.listdir('data/storage')) if os.path.exists('data/storage') else 0
downloads_files = len(os.listdir('data/downloads')) if os.path.exists('data/downloads') else 0
cache_exists = os.path.exists('data/ocr_cache_val_v3.json')

print('BEFORE COUNTS:')
print('  Database tables & rows:', before_counts)
print(f'  data/storage: {storage_files} files')
print(f'  data/downloads: {downloads_files} files')
print(f'  data/ocr_cache_val_v3.json exists: {cache_exists}')

# 2. Delete storage files
if os.path.exists('data/storage'):
    shutil.rmtree('data/storage')
os.makedirs('data/storage', exist_ok=True)

# 3. Delete download files
if os.path.exists('data/downloads'):
    shutil.rmtree('data/downloads')
os.makedirs('data/downloads', exist_ok=True)

# 4. Delete cache
if os.path.exists('data/ocr_cache_val_v3.json'):
    os.remove('data/ocr_cache_val_v3.json')

# 5. Delete and recreate SQLite database clean
for f in glob.glob('data/*.db*'):
    if 'backup' not in f:
        try:
            os.remove(f)
            print(f'Removed {f}')
        except Exception as e:
            print(f'Could not remove {f}: {e}')

print('\nAFTER COUNTS:')
storage_after = len(os.listdir('data/storage'))
downloads_after = len(os.listdir('data/downloads'))
cache_after = os.path.exists('data/ocr_cache_val_v3.json')
print(f'  data/storage: {storage_after} files')
print(f'  data/downloads: {downloads_after} files')
print(f'  data/ocr_cache_val_v3.json exists: {cache_after}')
