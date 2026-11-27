# Production Operations Runbook: ECM Document Ingestion Engine

## 1. System Services & Restart Procedures

### A. Worker Processes
- **Local / Systemd Process**:
  ```bash
  # Restart worker pool
  systemctl restart ecm-worker.service
  # Tail worker logs
  journalctl -u ecm-worker.service -f
  ```
- **Local Development / Standalone Execution**:
  ```powershell
  .venv311\Scripts\python.exe -m uvicorn app.api.app:app --host 0.0.0.0 --port 8000
  ```

### B. Redis Queue Health & Streams Recovery
If Redis crashes or ungracefully terminates:
1. Verify Redis connectivity: `redis-cli ping` -> `PONG`.
2. Inspect pending consumer groups:
   ```bash
   redis-cli XPENDING ecm:queue:live ecm-workers
   ```
3. Claim stuck messages exceeding 60-second processing window:
   ```bash
   redis-cli XAUTOCLAIM ecm:queue:live ecm-workers worker-1 60000 0-0 COUNT 50
   ```

---

## 2. Dead-Letter Queue (DLQ) Handling & Message Re-injection

When a document permanently fails processing (e.g. OCR timeout after 3 exponential backoffs or virus quarantine), it is routed to `ecm:queue:dlq`.

### A. Inspecting Failed Payloads
```bash
# Query DLQ depth
curl -s http://localhost:8000/metrics | grep 'ecm_queue_depth{queue="dlq"}'

# Read top 5 DLQ messages
redis-cli XREVRANGE ecm:queue:dlq + - COUNT 5
```

### B. DLQ Remediation & Re-injection
Once the underlying issue is resolved (e.g. OCR engine restarted or upstream dependency restored):
```powershell
# Re-inject DLQ messages back into live queue
.venv311\Scripts\python.exe scripts/reprocess_dlq.py --max-messages 50
```

---

## 3. Reprocessing Procedures

### A. Reprocessing by Metadata Query
To re-evaluate documents affected by an updated classifier or extractor:
```bash
POST /reprocess/by-query
Content-Type: application/json

{
  "query": {
    "classifier_version": "v1.0",
    "confidence_max": 0.85
  },
  "priority": "low",
  "concurrency": 4
}
```

### B. Protection of Human-Verified Ground Truth
- **Strict Invariant**: Any field populated in `humanVerifiedFields` is immutable during automated reprocessing.
- If an updated model predicts a conflicting value, an audit conflict event (`DIFF_DISCREPANCY`) is emitted to the compliance trail, leaving the human-verified field unchanged.

---

## 4. Model Rollout & Zero-Downtime Rollback

### A. Safe Canary Rollout
1. Place candidate weights at `models/candidate_v3.joblib`.
2. Update `config/pipeline.yaml`:
   ```yaml
   models:
     classifier_version: "v3.0.0-rc1"
     canary_percentage: 10
   ```
3. Monitor `ecm_pipeline_stp_rate` and `ecm_review_queue_size` in Grafana for 2 hours.
4. If STP drops by $>5\%$, trigger automated rollback.

### B. Instant Rollback
```bash
# Revert config to stable v2 model
sed -i 's/v3.0.0-rc1/v2.0.0/g' config/pipeline.yaml
# Hot reload config via API
curl -X POST http://localhost:8000/admin/reload-config
```

---

## 5. Swapping in Cloud OCR & Data Residency Sovereignty

### A. Configuring Cloud Vision / AWS Textract
In `config/pipeline.yaml`:
```yaml
ocr:
  engine: "google_cloud_vision" # options: "tesseract", "google_cloud_vision", "aws_textract"
  credentials_file: "/vault/secrets/gcp_vision_sa.json"
```

### B. Data Residency Enforcement Guardrails
As documented in `/docs/discovery.md`, the following classes are **strictly forbidden** from cloud processing:
- `kyc_form` (Statutory identity documents)
- `bank_statement` (Financial account statements)
- `medical_report` (HIPAA / Protected Health Information)
- `claim_form` (Policyholder claims)

The pre-processing worker inspects document metadata and disallows routing to external cloud APIs for restricted classes, automatically falling back to the local Tesseract OCR engine.