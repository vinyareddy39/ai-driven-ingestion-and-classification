# Enterprise ECM Pipeline End-to-End Verification & Holdout 2 Test Report

**Environment**: Local Windows 11 host (`local mode only`, no Docker daemon active)  
**Tesseract Engine**: Official UB-Mannheim Tesseract OCR v5.4.0.20240606 (AVX2, tessdata_best `eng`)  
**Holdout Evaluation**: Fresh Holdout 2 (Seed `20261119`), 360 pure 300 DPI rasterized scans evaluated in a single unseen pass.

---

## 1. Target Compliance Summary (Fresh Holdout 2)

| Metric | Target | Result (Holdout 2) | Status | Notes |
| :--- | :---: | :---: | :---: | :--- |
| **Classification Accuracy (Auto-Accepted)** | $\ge 95\%$ | **100.00%** (276/276) | **PASS** | 0 misclassifications accepted straight-through |
| **Overall Classification Accuracy** | N/A | **98.89%** (356/360) | **PASS** | Hard negatives (letters mentioning invoices) routed to review |
| **Field Extraction Accuracy** | $\ge 90\%$ | **90.78%** (1,162/1,280) | **PASS** | Evaluated on degraded 300 DPI scans |
| **PII Detection Recall** | $\ge 98\%$ | **99.21%** (754/760) | **PASS** | Label-anchored regex + Presidio NER |
| **PII Detection Precision** | $\ge 80\%$ | **80.73%** (754/934) | **PASS** | Tuned score threshold 0.75 + boilerplate suppression |
| **Straight-Through Processing (STP) Rate** | $\ge 70\%$ | **76.67%** (276/360) | **PASS** | High-sensitivity PII routed safely to human review |
| **Audit Trail Completeness** | $100\%$ | **100.00%** (360/360) | **PASS** | Model name, version, confidence, and status recorded |

---

## 2. Evidence Outputs (Command Logs)

### A. Tesseract Verification & Sample OCR Assets
```
tesseract v5.4.0.20240606
 leptonica-1.84.1
  libgif 5.2.1 : libjpeg 8d (libjpeg-turbo 3.0.1) : libpng 1.6.43 : libtiff 4.6.0 : zlib 1.3 : libwebp 1.4.0 : libopenjp2 2.5.2
 Found AVX2
 Found AVX
 Found FMA
 Found SSE4.1
 Found libarchive 3.7.4 zlib/1.3.1 liblzma/5.6.1 bz2lib/1.0.8 liblz4/1.9.4 libzstd/1.5.6

100% of scan assets processed via official UB-Mannheim Tesseract 5.4.0.20240606
```

### B. Dataset Leakage & Jaccard Shingle Audit
- Train: 1,080 documents
- Validation: 360 documents
- Holdout 2: 360 documents
- File Name Collisions: **0** across all split pairs
- Document ID Collisions: **0** across all split pairs
- Binary SHA-256 Collisions: **0** across all split pairs
- Mean 4-gram Jaccard Similarity: **0.0131**
- Max Jaccard Similarity: **0.8000** (between standard boilerplate syllabi in unknown class)

### C. Holdout 2 Confusion Matrix (True \ Predicted)
```
                 invoice contrac kyc_for bank_st medical purchas  letter claim_f unknown
invoice               40       0       0       0       0       0       0       0       0
contract               0      40       0       0       0       0       0       0       0
kyc_form               0       0      40       0       0       0       0       0       0
bank_statement         0       0       0      40       0       0       0       0       0
medical_report         0       0       0       0      40       0       0       0       0
purchase_order         0       0       0       0       0      40       0       0       0
letter                 0       0       0       0       0       0      36       0       4
claim_form             0       0       0       0       0       0       0      40       0
unknown                0       0       0       0       0       0       0       0      40
```

### D. Per-Class Metrics
```
Class                Precision      Recall    F1-Score   Support   Field Accuracy
invoice                100.00%     100.00%     100.00%        40          100.00%
contract               100.00%     100.00%     100.00%        40          100.00%
kyc_form               100.00%     100.00%     100.00%        40           90.62%
bank_statement         100.00%     100.00%     100.00%        40           83.75%
medical_report         100.00%     100.00%     100.00%        40           83.75%
purchase_order         100.00%     100.00%     100.00%        40          100.00%
letter                 100.00%      90.00%      94.74%        40           68.75%
claim_form             100.00%     100.00%     100.00%        40           99.38%
unknown                 90.91%     100.00%      95.24%        40              N/A
```

### E. PII Entity Performance
```
Entity Type               TP      FN      FP      Recall   Precision
IBAN_CODE                 40       0       0     100.00%     100.00%
MEDICAL_LICENSE           40       0       1     100.00%      97.56%
NATIONAL_ID                0       0      38       0.00%       0.00%
PASSPORT                  40       0       0     100.00%     100.00%
PERSON                   277       3     126      98.93%      68.73%
PHONE_NUMBER             158       2      15      98.75%      91.33%
US_EIN                    40       0       0     100.00%     100.00%
US_SSN                   159       1       0      99.38%     100.00%
```

### F. Load Test Results (Local Mode Only)
- Tested Workload: 20 warm-up documents + 520 benchmark documents (Total: 540 documents)
- Errors: **0** (520/520 successful)
- Sustained Throughput: **2.86 docs/sec** (~10,288 docs/hour)
- Daily Capacity Equivalent: **~246,920 docs/day** (Target: 50,000 docs/day)
- Mean End-to-End Latency: **1,395.62 ms**
- Median (p50) Latency: **1,295.59 ms**
- p95 Latency: **2,412.88 ms**
- p99 Latency: **2,768.22 ms**
- Stage Latency Breakdown:
  - OCR (Tesseract 5.4.0): **1,332.13 ms** (95.5% of pipeline latency)
  - PII Detection (Presidio NER + Regex): **45.82 ms** (3.3%)
  - Audit Trail Recording: **15.74 ms** (1.1%)
  - Classification (TF-IDF + Logistic Regression): **1.76 ms** (0.1%)
  - Field Extraction: **0.14 ms** (0.0%)
  - Decision Gate: **0.02 ms** (0.0%)
