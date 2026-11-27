# Database & Infrastructure Operations Runbook

**Environment**: Local (SQLite) & Cloud (PostgreSQL on Render)  
**Target Schema**: Document Ingestion, Presidio PII, Patient Prescriptions, Adherence Timetables  

---

## 1. Database Architecture & Portability
The database layer uses portable SQLAlchemy declarative models.
- **Local Engine**: SQLite (`sqlite:///./data/ecm_pipeline.db`).
- **Production Engine**: PostgreSQL 16+ (`postgresql+psycopg2://...`).
- **Schema Migrations**: Version-controlled via Alembic (`alembic/versions/`).
  - Base document schema: `07595e940744`
  - Prescription & timetable tables: `a1b2c3d4e5f6`
  - Prescription sha256 & encrypted raw text: `b2c3d4e5f6a1`
  - Batch ID, ownership, and composite retention indices: `c3d4e5f6a1b2`

---

## 2. Backup Procedures

### 2.1 Local SQLite Backup
To generate a hot, consistent snapshot without locking write operations:
```powershell
# Create timestamped atomic backup using SQLite online backup API
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
python -c "
import sqlite3, os
src = sqlite3.connect('data/ecm_pipeline.db')
dst = sqlite3.connect(f'data/backups/ecm_backup_{timestamp}.db')
src.backup(dst)
dst.close()
src.close()
print('Backup complete.')
"
```

### 2.2 Production PostgreSQL (Render Managed Postgres)
Render provides automated daily snapshots. For manual or pre-deployment backups:

1. **Obtain Connection String**:
   Retrieve the external database connection string from Render Dashboard -> PostgreSQL -> Connect -> External Connection String:
   `postgresql://ecm_user:SECRET@dpg-xxxxx.render.com/ecm_db`

2. **Execute Logical Dump**:
   ```bash
   pg_dump -Fc -v --no-owner --no-privileges \
     -d "$DATABASE_URL" \
     -f "ecm_prod_backup_$(date +%Y%m%d_%H%M%S).dump"
   ```

3. **Verify Dump Integrity**:
   ```bash
   pg_restore --list "ecm_prod_backup.dump" | head -n 25
   ```

---

## 3. Restoration Procedures

### 3.1 Local SQLite Restore
```powershell
# Stop backend service
Stop-Process -Name python -ErrorAction SilentlyContinue

# Restore backup file
Copy-Item -Path "data/backups/ecm_backup_TARGET.db" -Destination "data/ecm_pipeline.db" -Force

# Verify integrity
python -c "import sqlite3; c = sqlite3.connect('data/ecm_pipeline.db'); print(c.execute('PRAGMA integrity_check').fetchall())"
```

### 3.2 Production PostgreSQL Restore
```bash
# 1. Terminate active sessions (if performing full rollback)
psql "$DATABASE_URL" -c "
  SELECT pg_terminate_backend(pid) 
  FROM pg_stat_activity 
  WHERE datname = 'ecm_db' AND pid <> pg_backend_pid();
"

# 2. Restore schema and data
pg_restore -v --clean --if-exists --no-owner --no-privileges \
  -d "$DATABASE_URL" \
  "ecm_prod_backup_TARGET.dump"

# 3. Re-run Alembic to ensure migration state
alembic upgrade head
```

---

## 4. Query Performance & Index Plan Verification
The composite index `idx_doc_model_conf` accelerates low-confidence document queries for human review and retraining:
```sql
EXPLAIN QUERY PLAN
SELECT uid, file_name, classifier_version, confidence
FROM ecm_documents
WHERE classifier_version = 'v1.2' AND confidence < 0.8;
```
**Execution Plan**:
`SEARCH ecm_documents USING INDEX idx_doc_model_conf (classifier_version=? AND confidence<?)`
