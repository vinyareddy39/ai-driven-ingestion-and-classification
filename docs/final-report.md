# Final Engineering Acceptance Report: AI Document Ingestion & Classification Pipeline

## 1. Project Phase Status Summary

Per project standing rules, no phase is marked PASS unless every exit criterion is met with raw command output evidence.

| Phase | Description | Status | Reason & Exit Criteria Evidence |
| :--- | :--- | :--- | :--- |
| **Phase 0** | Discovery & Real-World Baseline | **PASS** | `docs/discovery.md` written with schemas, risk tiers, ACLs, data residency, volume, and real SROIE/FUNSD baselines. |
| **Phase 1** | Ingestion & Core Pipeline | **NOT MET** | Windows host lacks elevated Windows Admin permissions to bind Docker named pipe `//./pipe/dockerDesktopLinuxEngine`. Full pipeline runs in **LOCAL MODE**. Real services test suite blocked until run on Linux Docker host. |
| **Phase 2** | Classification, Extraction & PII | **PARTIAL (OPEN)** | Classifier achieves 98.24% on Holdout 3 [DEVELOPMENT SET]. Bidirectional leave-one-family-out cross-family accuracy is **79.30%** (v2 $\rightarrow$ v1) and **94.20%** (v1 $\rightarrow$ v2), failing the $\ge 85\%$ cross-family threshold. Overall PII recall is **95.22%** (1,016 / 1,067 TP), missing the $\ge 98.0\%$ requirement. Remains **OPEN**. |
| **Phase 3** | Review Desk & Governance | **PARTIAL** | FastAPI endpoints verified; human review correction export to JSONL and active learning retrain demonstrated. Review floor 0.60 enforced. Production Nuxeo live integration tested via contracts and in-memory stubs. |
| **Phase 4** | Deployment, Hardening & Blind Eval | **NOT MET** | Blind set `data/blind/` remains strictly sealed and untouched. Phase 4 cannot execute until Phase 1 and 2 exit criteria are fully satisfied. |

---

## 2. PII Reconciliation & Ground-Truth Entity Counts

### Direct Ground-Truth Entity Audit from Holdout 3 JSON Files (360 Documents)
Ground truth entities counted directly from `data/dataset/holdout3/*.json`:
- `PERSON`: 400
- `PHONE_NUMBER`: 320
- `EMAIL_ADDRESS`: 107
- `US_EIN`: 80
- `US_SSN`: 40
- `PASSPORT`: 40
- `MEDICAL_LICENSE`: 40
- `IBAN_CODE`: 40
**Total True Ground-Truth Entities**: **1,067**

### Retraction & Explanation of Historical Discrepancy
In an earlier diagnostic summary, entity counts were reported as "SSN 150, NATIONAL_ID 140", while omitting US_EIN, MEDICAL_LICENSE, and IBAN_CODE.
- **Cause**: That diagnostic script used a coarse heuristic classifier that lumped corporate EINs (80), medical licenses (40), and customer IDs into generic "SSN" and "NATIONAL_ID" buckets.
- **Correction**: Those counts are **formally retracted**. The canonical count is exactly 1,067 entities across the 8 classes above.

### Unified Shared Matcher Evaluation (Holdout 3 [DEVELOPMENT SET])
```text
================================================================================
UNIFIED PII EVALUATION ON HOLDOUT 3 [DEVELOPMENT SET] - ALL 8 ENTITIES
================================================================================
Entity Type        | GT     | Det    | TP     | FP     | Recall %   | Precision % 
---------------------------------------------------------------------------
EMAIL_ADDRESS      | 107    | 102    | 99     | 3      |    92.52% |      97.06%
IBAN_CODE          | 40     | 40     | 40     | 0      |   100.00% |     100.00%
MEDICAL_LICENSE    | 40     | 38     | 38     | 0      |    95.00% |     100.00%
PASSPORT           | 40     | 40     | 40     | 0      |   100.00% |     100.00%
PERSON             | 400    | 489    | 379    | 110    |    94.75% |      77.51%
PHONE_NUMBER       | 320    | 349    | 307    | 42     |    95.94% |      87.97%
US_EIN             | 80     | 76     | 76     | 0      |    95.00% |     100.00%
US_SSN             | 40     | 37     | 37     | 0      |    92.50% |     100.00%
---------------------------------------------------------------------------
OVERALL            | 1067   | 1171   | 1016   | 155    |    95.22% |      86.76%

Target Verification:
  Target: Recall >= 98.0%, Precision >= 80.0%
  Overall Recall   : 95.22% -> NOT MET (Phase 2 remains OPEN)
  Overall Precision: 86.76% -> PASS
```

---

## 3. Extractor Call Path Audit & Metric Reconciliation

### Call Path Trace
```text
Function: stage_extract_fields (app.workers.stages:249)
Call trace inside stage_extract_fields:
  1. extractor = GenericKeyValueExtractor()  [from app.workers.generic_extractor]
  2. extracted, confidences = extractor.extract(text, doc_type)
  3. Supplementary hardcoded regex fallbacks per document type
Conclusion: The pipeline stage currently invokes GenericKeyValueExtractor() + regex fallbacks,
            NOT SemanticGroundedExtractor or LLMFieldExtractor.
```

### Comparative Field Accuracy on Holdout 3 Cached Tesseract OCR Text
```text
Class Name         | Total Fields | (a) Pipeline    | (b) SemanticGrounded | (c) Regex/Synonym 
--------------------------------------------------------------------------------------------
bank_statement     | 120          |  120/120  (100.00%) |  111/120  (92.50%) |  120/120  (100.00%)
claim_form         | 160          |  152/160  (95.00%) |  152/160  (95.00%) |  152/160  (95.00%)
contract           | 120          |  114/120  (95.00%) |  114/120  (95.00%) |  114/120  (95.00%)
invoice            | 160          |  155/160  (96.88%) |  154/160  (96.25%) |  155/160  (96.88%)
kyc_form           | 120          |  120/120  (100.00%) |  120/120  (100.00%) |  120/120  (100.00%)
letter             | 160          |  148/160  (92.50%) |  144/160  (90.00%) |  148/160  (92.50%)
medical_report     | 120          |  114/120  (95.00%) |  102/120  (85.00%) |  114/120  (95.00%)
purchase_order     | 160          |  159/160  (99.38%) |  158/160  (98.75%) |  159/160  (99.38%)
OVERALL            | 1120         | 1082/1120 (96.61%) | 1055/1120 (94.20%) | 1082/1120 (96.61%)
```

### Reconciliation of Metric Divergence (87.14% vs 94.20% vs 55.98%)
1. **94.20% (1,055 / 1,120)**: Evaluated using `SemanticGroundedExtractor` (with regex fallback) on true ground-truth fields.
2. **87.14% (976 / 1,120)**: Evaluated in early prototype using static `CLASS_SCHEMAS` dictionary where denominator was inflated or evaluated without fuzzy/synonym matching on complex multi-line entities.
3. **55.98% (627 / 1,120)**: Result of feature ablation (`scripts/ablate_extractor_feature.py`) where regex fallback was disabled and 50% of synonym descriptions were ablated, demonstrating the degradation without label mapping.

---

## 4. Bidirectional Leave-One-Family-Out Cross-Family Generalization

Evaluated with frozen extractor code, descriptions, and config:
- **Direction 1 (Tune on v1, Evaluate on v2 / Holdout 3)**: **94.20%** (1,055 / 1,120)
- **Direction 2 (Tune on v2, Evaluate on v1 / Holdout 2)**: **79.30%** (1,015 / 1,280)

```text
Class Name         | Direction 1 (v1 -> v2 Holdout 3) | Direction 2 (v2 -> v1 Holdout 2)
                   | Accurate / Expected  Field %     | Accurate / Expected  Field % 
------------------------------------------------------------------------------------
bank_statement     |  111 / 120  ( 92.50%)            |  107 / 160  ( 66.88%)        
claim_form         |  152 / 160  ( 95.00%)            |  160 / 160  (100.00%)        
contract           |  114 / 120  ( 95.00%)            |   80 / 160  ( 50.00%)        
invoice            |  154 / 160  ( 96.25%)            |  147 / 160  ( 91.88%)        
kyc_form           |  120 / 120  (100.00%)            |  134 / 160  ( 83.75%)        
letter             |  144 / 160  ( 90.00%)            |  144 / 160  ( 90.00%)        
medical_report     |  102 / 120  ( 85.00%)            |  136 / 160  ( 85.00%)        
purchase_order     |  158 / 160  ( 98.75%)            |  107 / 160  ( 66.88%)        
------------------------------------------------------------------------------------
OVERALL            | 1055 / 1120 ( 94.20%)            | 1015 / 1280 ( 79.30%)        
```
*Conclusion*: Direction 2 achieves 79.30% (< 85%), with `contract` dropping to 50.00% and `purchase_order`/`bank_statement` dropping to 66.88% due to schema key differences between families (`first_party`/`second_party` vs `parties`, `buyer_name` vs `vendor_name`).

---

## 5. Weak Field Diagnoses with Raw OCR Text

1. **`medical_report.patient_id`** (14 failures on Holdout 3):
   - In OCR text: `Patient Name: Jennifer Ewing Medical Record #: PT-20270001`
   - Failure: Token overlap on `patient` causes parser to match `Patient Name:` first and extract `"Jennifer"`.
2. **`bank_statement.account_number`** (9 failures on Holdout 3):
   - In OCR text: `Primary Beneficiary: Emma Nguyen... Depository Account #: 5513822520`
   - Failure: Parser matched `Primary Beneficiary:` when checking `account_holder` or fuzzy label matching, extracting `"Emma"`.
3. **`letter.sender`** (7 failures on Holdout 3):
   - In OCR text: `Transmitted By: Tyler Hansen... Sender Email: tommymartin@yahoo.com`
   - Failure: Literal label token `sender` in `Sender Email:` extracted the email address rather than `Transmitted By:`.

---

## 6. Real Document Baseline (SROIE Scanned Receipts)

- **Dataset**: ICDAR 2019 SROIE (100 real scanned retail receipts; 50 Dev / 50 Sealed).
- **Classification Routing**: 49 / 50 (98.0%) routed to `unknown`, 1 / 50 (2.0%) routed to `invoice`. Straight-Through Processing: **0.0%**.
- **Field Extraction Accuracy (Dev Half)**:
  - `vendor_name`: 56.00% (28 / 50)
  - `invoice_date`: 54.00% (27 / 50 with ISO normalization)
  - `total_amount`: 30.00% (15 / 50)
  - `vendor_address`: 0.00% (0 / 50 - unstructured wrap)
  - **Overall**: 35.00% (70 / 200)
- **Documented Decision**: `vendor_address` is **formally dropped from schema**. SROIE receipts route safely to the Human Review Queue.

---

## 7. Real Tesseract Raster Scan Load Test & Concurrent Bulk Benchmark

- **OCR Engine**: `HybridPyMuPDF-Tesseract v2.4.0` / UB-Mannheim Tesseract `v5.4.0.20240606`.
- **Tesseract Binary Path**: `C:\ml\tools\tesseract_ub\tesseract.exe`.
- **Payload Format**: High-resolution raster scan image-only PDFs (1 page per document, no digital text streams).
- **Per-Document Sample OCR Times**: 770.0 ms, 908.6 ms, 860.3 ms, 878.5 ms, 951.2 ms (all in hundreds of ms).

---

## 8. LLM Extractor Status & Retraction of Prior Simulated Numbers

1. **Formal Retraction**: The previous turn's reported LLM extractor numbers (1 ms latency, modeled tokens) were generated from an analytical simulation without calling a live model backend. **Those numbers are formally withdrawn.**
2. **Configuration Audit**:
   - Environment file `.env` does not exist (`Test-Path .env -> False`).
   - No local model endpoint (`LOCAL_LLM_URL`, Ollama, vLLM) or hosted model API keys (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) are present in environment variables.
3. **Execution Decision**: Per the strict directive (*"Never simulate or mock a component and report it as real. If none exists, STOP this section and say so."*), LLM extraction is stopped without simulation or mocking. Real evaluation remains blocked until an endpoint or API key is provisioned.
