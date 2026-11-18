# Real Document Discovery & Schema Mapping: FUNSD Dataset

## 1. Dataset Origin & License

- **Dataset Name**: FUNSD (Form Understanding in Noisy Scanned Documents)
- **Origin / Source**: ICDAR-OST 2019 / [https://guillaumejaume.github.io/FUNSD/](https://guillaumejaume.github.io/FUNSD/)
- **Authors**: Guillaume Jaume, Hazim Kemal Ekenel, Jean-Philippe Thiran (EPFL & ITU)
- **Underlying Document Corpus**: Truth Tobacco Industry Documents Archive (UCSF Library / RVL-CDIP).
- **License / Terms of Use**: Public Domain / US Government and Federal settlement public archive. Provided openly for academic and industrial document intelligence research.
- **Total Corpus Size**: 199 fully annotated scanned document images (149 train / 50 test).

---

## 2. Dev vs. Sealed Split Protocol

To prevent test-set leakage and preserve an authentic blind evaluation partition:
- **Total Documents**: 199 unique scanned forms
- **Seed**: `20261120` (deterministic pseudo-random permutation)
- **Dev Split (50%)**: 99 documents (`data/real_funsd/splits.json` -> `dev_doc_ids`)
  - Used strictly for baseline pipeline evaluation, error analysis, and discovery.
- **Sealed Split (50%)**: 100 documents (`data/real_funsd/splits.json` -> `sealed_doc_ids`)
  - **SEALED**: Never opened, inspected, tuned on, or evaluated during development.

---

## 3. Label & Schema Mapping to Production Pipeline

FUNSD forms represent authentic multi-industry corporate paperwork (internal memos, correspondence, questionnaires, claim vouchers, inspection reports, purchase authorizations). 

Below is the mapping between FUNSD entity annotations and production ECM classes/fields:

### A. Document Class Mapping
| FUNSD Form Profile | Primary Target Class | Secondary / Fallback Class | Core Identification Features |
| :--- | :--- | :--- | :--- |
| Memos, Circulars, Formal Correspondence | `letter` | `unknown` | "To:", "From:", "Date:", "Subject:", "Memorandum" |
| Requisitions, Vendor Procurement Forms | `purchase_order` | `invoice` | "Supplier:", "Description:", "Quantity", "PO #", "Approved By" |
| Financial Slips, Vouchers, Account Forms | `invoice` | `claim_form` | "Account:", "Total", "Due Date:", "Remit To", "Amount" |
| Questionnaires, Registrations, Applications | `kyc_form` | `unknown` | "Name:", "Date of Birth", "Address:", "Signature", "Affiliation" |
| Expense Requests, Reimbursements | `claim_form` | `invoice` | "Claimant", "Expenses", "Receipt #", "Approved By" |
| Medical/Scientific Trial Records | `medical_report` | `unknown` | "Patient", "Protocol", "Physician", "Diagnosis", "Trial" |
| Legal Agreements, Contracts | `contract` | `unknown` | "Agreement", "Terms", "Parties", "Effective Date" |
| Unstructured / Mixed Format Forms | `unknown` | `unknown` | Low confidence (<0.60), unmatched layout |

### B. Field Key Synonym Mapping
| Production Schema Field | FUNSD Question Annotations | Matching Normalization Strategy |
| :--- | :--- | :--- |
| `date` / `issue_date` / `statement_date` | `date`, `date:`, `dated:`, `day/month/year` | Generic line parser + fuzzy similarity (>0.80) |
| `recipient` / `customer_name` | `to:`, `attention:`, `name:`, `recipient:` | Direct key-value extraction |
| `sender` / `vendor_name` | `from:`, `supplier:`, `originator:`, `division name:` | Header block & key-value line scan |
| `subject` | `subject:`, `re:`, `in reference to:`, `matter:` | Multi-token value until line delimiter |
| `account_number` | `name of account`, `account no:`, `acct #` | Numeric regex + box proximity |
| `amount` / `total_amount` | `amount`, `total`, `balance`, `net amount` | Currency symbol strip + float parse |
