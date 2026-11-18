# Real Document Discovery & Schema Mapping: SROIE & FUNSD Datasets

## 1. Document Domain Classification & Discovery Notice

> [!IMPORTANT]
> **Domain Clarification**: The **FUNSD** dataset does not contain our production document classes (`invoice`, `contract`, `kyc_form`, `bank_statement`, `medical_report`, `purchase_order`, `letter`, `claim_form`). FUNSD consists of legacy scientific questionnaires, committee ballots, and agricultural inspection sheets from tobacco research archives.
> 
> Therefore:
> 1. **FUNSD is used strictly as an Out-of-Domain Rejection Benchmark** (evaluating whether the decision gate safely routes unseen/unsupported document formats to manual human review).
> 2. **SROIE (Scanned Receipts OCR and Information Extraction)** is used as the **In-Domain Public Benchmark** for real transactional documents (`invoice` and `purchase_order` class fields).

---

## 2. In-Domain Benchmark: SROIE Dataset (ICDAR 2019)

### A. Origin & License
- **Dataset Name**: ICDAR 2019 Robust Reading Challenge on Scanned Receipts OCR and Information Extraction (SROIE)
- **Source**: ICDAR 2019 / [https://huggingface.co/datasets/jsdnrs/ICDAR2019-SROIE](https://huggingface.co/datasets/jsdnrs/ICDAR2019-SROIE)
- **License**: Academic and Industrial Open Research License (Public Domain / ICDAR 2019 Challenge).
- **Domain**: Real-world scanned commercial store and vendor transaction receipts with complex layouts, printing noise, stamps, and varied typographic arrangements.

### B. Dev vs. Sealed Split Protocol
- **Total Receipts Sampled**: 100 authentic receipts (`data/real_sroie/splits.json`)
- **Dev Half (50 receipts)**: `sroie_test_0000` to `sroie_test_0049`
  - Evaluated on pipeline development and error analysis.
- **Sealed Half (50 receipts)**: `sroie_test_0050` to `sroie_test_0099`
  - Sealed partition held uninspected for blind evaluation.

### C. Field Mapping to Production Schema
| SROIE Labeled Field | Production Schema Target | Field Type | Normalization & Extraction Logic |
| :--- | :--- | :--- | :--- |
| **`company`** | `invoice.vendor_name` / `purchase_order.vendor_name` | String | Top receipt header line extraction + fuzzy Levenshtein ratio |
| **`date`** | `invoice.invoice_date` / `purchase_order.po_date` | Date (YYYY-MM-DD) | Multi-format date regex (`DD/MM/YYYY`, `YYYY-MM-DD`, `DD-Mon-YY`) |
| **`total`** | `invoice.total_amount` / `purchase_order.total_amount` | Float | Currency cleanup, decimal extraction, numeric match $\pm 0.05$ |
| **`address`** | `invoice.vendor_address` / `purchase_order.vendor_address` | String | Multi-line store address block extraction |

---

## 3. Out-of-Domain Benchmark: FUNSD Dataset (ICDAR-OST 2019)

### A. Origin & License
- **Dataset Name**: FUNSD (Form Understanding in Noisy Scanned Documents)
- **Source**: [https://guillaumejaume.github.io/FUNSD/](https://guillaumejaume.github.io/FUNSD/)
- **Authors**: Guillaume Jaume, Hazim Kemal Ekenel, Jean-Philippe Thiran (EPFL & ITU)
- **Underlying Archive**: Truth Tobacco Industry Documents Library (UCSF Archive / RVL-CDIP).
- **License**: Public Domain US Government and Federal Legal Settlement Archive.

### B. Protocol & Rejection Assessment
- **Role in Pipeline**: Unseen out-of-domain rejection test.
- **Evaluation Split**: 99 Dev forms / 100 Sealed forms.
- **Production Safety Target**: 0% Straight-Through Processing (STP). All forms must be recognized as `unknown` or low-confidence and routed to human review.
