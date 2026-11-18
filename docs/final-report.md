# Final Engineering Acceptance Report: AI Document Ingestion & Classification Pipeline

## 1. Acceptance Evaluation Matrix & Target Verification

All benchmarks were evaluated under strict production invariants:
- Targets and thresholds were **not modified** to force passes (high-risk $\ge 0.95$, low-risk $\ge 0.90$).
- Holdouts 2 and 3 were categorized strictly as **`[DEVELOPMENT SET]`**.
- Evaluation executed under **Python 3.11.9**.

| Benchmark Metric | Production Target | Measured Result | Evaluation Split / Dataset | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Classification Accuracy (Auto-Accepted)** | $\ge 95.0\%$ | **98.24%** | Holdout 3 [DEVELOPMENT SET] | **PASS** |
| **Cross-Family Field Accuracy** | $\ge 85.0\%$ | **87.14%** (976 / 1120) | Template Family Cross-Test | **PASS** |
| **Field Accuracy (Familiar Layouts)** | $\ge 90.0\%$ | **93.83%** (1201 / 1280)| Holdout 2 [DEVELOPMENT SET] | **PASS** |
| **Real Document Field Baseline** | Baseline to beat | **22.00%** (44 / 200) | ICDAR 2019 SROIE Receipts (Dev 50) | **RECORDED** |
| **PERSON PII Precision** | $\ge 80.0\%$ | **85.09%** (371 / 436) | Holdout 3 [DEVELOPMENT SET] | **PASS** |
| **PERSON PII Recall** | $\ge 90.0\%$ | **92.75%** (371 / 400) | Holdout 3 [DEVELOPMENT SET] | **PASS** |
| **Overall PII Detection Recall** | $\ge 98.0\%$ (Synthetic) | **94.19%** (1005 / 1067)| Holdout 3 [DEVELOPMENT SET] | **GAP RECORDED** |
| **Overall PII Detection Precision**| $\ge 80.0\%$ | **91.45%** (1005 / 1099)| Holdout 3 [DEVELOPMENT SET] | **PASS** |
| **Out-of-Domain Safety Rejection** | 100% Review (0% STP)| **100.0%** (0% STP) | FUNSD Real Forms Dev Split | **PASS** |
| **Audit Completeness on Assets** | 100.0% | **100.0%** (10/10 audited)| 10 Random Production Assets | **PASS** |
| **Pipeline Throughput** | $\ge 0.58$ docs/sec | **5.97 docs/sec** | 540 Unique Document Load Test | **PASS (10.3x)** |
| **End-to-End Latency (p95)** | $\le 1000$ ms | **210.01 ms** | Sustained Load Benchmark | **PASS** |

---

## 2. Real Document Benchmarks (SROIE & FUNSD)

1. **ICDAR 2019 SROIE (50 Scanned Receipts Dev Half)**:
   - `vendor_name`: 56.00% (28 / 50)
   - `invoice_date`: 0.00% (0 / 50 - Malaysian date formats like `DD/MM/YYYY`)
   - `total_amount`: 32.00% (16 / 50 - Currency symbol artifacts e.g. `RM`)
   - `vendor_address`: 0.00% (0 / 50 - Multi-line unstructured wraps without labels)
   - Overall Field Extraction: 22.00% (44 / 200)
   - Decision Gate Safety: 49 / 50 (98%) routed to `unknown`, 1 / 50 (2%) routed to `invoice`. 0% STP.
2. **ICDAR FUNSD (30 Hand-Audited Real Forms)**:
   - Decision Gate: 100% routed safely to Human Review Queue (0% STP).
   - Hand-checked PII Precision: 90.48% (57 True Positives / 63 Flagged Entities).

---

## 3. Financial Cost & Throughput Modeling

- **Execution Mode**: Local zero-shot schema extraction and regex grounding.
- **Cost per Document**: **$0.0000** (Zero external cloud API fees).
- **Measured Sustained Throughput**: 5.97 documents/second (21,484 documents/hour).
- **Backlog Processing Schedule (5,000,000 Documents)**:
  - Single worker node: 9.7 days continuous processing.
  - Multi-worker pool (10 concurrent nodes @ 50 docs/sec): **27.7 hours** total elapsed time.
  - Compute Infrastructure Cost: Standard on-premises server node ($0 cloud API cost).

---

## 4. Known Limits & Edge Cases

1. **Unstructured Multi-line Receipt Parsing**: Real scanned thermal receipts frequently omit field labels for store addresses and line items. The line-based key-value extractor succeeds on structured `Label: Value` forms (87.14% cross-family accuracy) but achieves only 22.00% on unstructured retail receipts.
2. **Date Format Diversity**: SROIE receipts predominantly utilize Commonwealth date conventions (`DD/MM/YYYY` and `DD-Mon-YY`). The current parser defaults to ISO-8601 (`YYYY-MM-DD`) and US formats (`MM/DD/YYYY`).
3. **Windows Tesseract Binary Integrity**: UB-Mannheim binary releases on GitHub do not publish an independent signed cryptographic checksum manifest. The installer (`SHA-256: C885FFF6998E...`) is verified from GitHub Releases but remains officially marked "unverified".

---

## 5. Security & Compliance Findings

- **PII Leakage in Application Logs**: Verified **0 leaks** across 100% of tested log streams using `scripts/verify_no_pii_in_logs.py`. All SSNs, credit cards, and sensitive identifiers are masked via `PIISanitizingLogFilter`.
- **Dependency Vulnerability Audit (`pip-audit`)**: Clean pass (**0 known vulnerabilities found** across all production libraries after upgrading base build tools `pip 26.3` and `setuptools 84.2.1`).
- **Data Residency Enforcement**: Architecture strictly blocks cloud AI processing for statutory restricted classes (`kyc_form`, `bank_statement`, `medical_report`, `claim_form`).

---

## 6. What Is Not Production-Ready

1. **Docker Host Pipe Binding on Windows Host**: Docker Desktop service (`com.docker.service`) requires Windows Administrator elevation to bind `//./pipe/dockerDesktopLinuxEngine`. Running on a production Linux host (systemd + native Docker socket) is required for containerized deployment.
2. **Live Nuxeo REST Server**: Contract tests pass against `FakeECM` and `NuxeoAdapter(stub_mode=True)`. Live enterprise deployment requires connecting to an authenticated Nuxeo cluster with the `AIClassification` schema deployed.
3. **Receipt Localization**: SROIE receipts require adding a multi-region date parser (`dateutil.parser` with fuzzy day-first logic) and OCR bounding box clustering for multi-line vendor addresses.