# 10 Random Asset Audit Compliance Reports (Locked Holdout Scans)


### Asset Audit Report #1: `unknown_0176`
- **Document UID**: `unknown_0176`
- **SHA-256 Checksum**: `61bef4486cf8b3175f6db1902f0501b55e12deeb15260baf6ab600332f4a0e4d`
- **Classified Document Type**: **unknown** (Ground Truth: `unknown`)
- **Classifier Model & Version**: `tfidf_logistic_regression` (`v1.0.0`)
- **OCR Engine & Version**: `Tesseract-OCR` (`4.0.0a0`)
- **Classification Confidence**: **0.9331**
- **PII Entities Detected**: `True` (Types: ['PERSON'])
- **Assigned Retention Class**: `TEMPORARY_QUARANTINE`
- **Assigned Access Control List (ACL)**: `RESTRICTED_REVIEW`
- **Target ECM Workflow**: `MANUAL_TRIAGE`
- **Review Status**: `pending_review`
- **Reviewer / Automated Actor**: `AUTOMATED_INGESTION_ENGINE`
- **Processed Timestamp**: `2026-11-18T08:11:15.788941+00:00`
- **Decision Justification**:
  > Mandatory rule: document classified as unknown must undergo human review

---

### Asset Audit Report #2: `contract_0185`
- **Document UID**: `contract_0185`
- **SHA-256 Checksum**: `57d5d088ebeca96a5c7f954d2241350d10c5dbee477a5939c5ca5ac879d72884`
- **Classified Document Type**: **contract** (Ground Truth: `contract`)
- **Classifier Model & Version**: `tfidf_logistic_regression` (`v1.0.0`)
- **OCR Engine & Version**: `Tesseract-OCR` (`4.0.0a0`)
- **Classification Confidence**: **0.9653**
- **PII Entities Detected**: `True` (Types: ['US_SSN', 'PERSON'])
- **Assigned Retention Class**: `LEGAL_10_YEARS`
- **Assigned Access Control List (ACL)**: `RESTRICTED_REVIEW`
- **Target ECM Workflow**: `HIGH_SENSITIVITY_REVIEW`
- **Review Status**: `pending_review`
- **Reviewer / Automated Actor**: `AUTOMATED_INGESTION_ENGINE`
- **Processed Timestamp**: `2026-11-18T08:11:02.682482+00:00`
- **Decision Justification**:
  > Classifier/PII Conflict: High-sensitivity PII found in low-risk class; enforcing stricter review path

---

### Asset Audit Report #3: `kyc_form_0176`
- **Document UID**: `kyc_form_0176`
- **SHA-256 Checksum**: `8883d1a27c15ba05f42a7067d199c3603ac72d76eec54dcecb3950033257b36e`
- **Classified Document Type**: **kyc_form** (Ground Truth: `kyc_form`)
- **Classifier Model & Version**: `tfidf_logistic_regression` (`v1.0.0`)
- **OCR Engine & Version**: `Tesseract-OCR` (`4.0.0a0`)
- **Classification Confidence**: **0.9293**
- **PII Entities Detected**: `True` (Types: ['PERSON', 'PHONE_NUMBER', 'PASSPORT'])
- **Assigned Retention Class**: `COMPLIANCE_10_YEARS`
- **Assigned Access Control List (ACL)**: `RESTRICTED_KYC`
- **Target ECM Workflow**: `CUSTOMER_ONBOARDING`
- **Review Status**: `auto_accepted`
- **Reviewer / Automated Actor**: `AUTOMATED_INGESTION_ENGINE`
- **Processed Timestamp**: `2026-11-18T08:11:06.903402+00:00`
- **Decision Justification**:
  > Confidence 0.929 >= threshold 0.920 for kyc_form

---

### Asset Audit Report #4: `bank_statement_0199`
- **Document UID**: `bank_statement_0199`
- **SHA-256 Checksum**: `01c880a74a86e6af996d4874d929ee2606562d8bb3f1eb427c3a0c4f5386666f`
- **Classified Document Type**: **bank_statement** (Ground Truth: `bank_statement`)
- **Classifier Model & Version**: `tfidf_logistic_regression` (`v1.0.0`)
- **OCR Engine & Version**: `Tesseract-OCR` (`4.0.0a0`)
- **Classification Confidence**: **0.9707**
- **PII Entities Detected**: `True` (Types: ['IBAN_CODE', 'PERSON'])
- **Assigned Retention Class**: `FINANCIAL_7_YEARS`
- **Assigned Access Control List (ACL)**: `CONFIDENTIAL_FINANCE`
- **Target ECM Workflow**: `TREASURY_RECONCILIATION`
- **Review Status**: `auto_accepted`
- **Reviewer / Automated Actor**: `AUTOMATED_INGESTION_ENGINE`
- **Processed Timestamp**: `2026-11-18T08:10:59.371331+00:00`
- **Decision Justification**:
  > Confidence 0.971 >= threshold 0.920 for bank_statement

---

### Asset Audit Report #5: `bank_statement_0184`
- **Document UID**: `bank_statement_0184`
- **SHA-256 Checksum**: `b9df15e2f5e8a7ed3ef5fb15d158175fbbf4188268e8ed396f6bdbb66e8678ee`
- **Classified Document Type**: **bank_statement** (Ground Truth: `bank_statement`)
- **Classifier Model & Version**: `tfidf_logistic_regression` (`v1.0.0`)
- **OCR Engine & Version**: `Tesseract-OCR` (`4.0.0a0`)
- **Classification Confidence**: **0.9734**
- **PII Entities Detected**: `True` (Types: ['IBAN_CODE', 'PERSON'])
- **Assigned Retention Class**: `FINANCIAL_7_YEARS`
- **Assigned Access Control List (ACL)**: `CONFIDENTIAL_FINANCE`
- **Target ECM Workflow**: `TREASURY_RECONCILIATION`
- **Review Status**: `auto_accepted`
- **Reviewer / Automated Actor**: `AUTOMATED_INGESTION_ENGINE`
- **Processed Timestamp**: `2026-11-18T08:10:58.533038+00:00`
- **Decision Justification**:
  > Confidence 0.973 >= threshold 0.920 for bank_statement

---

### Asset Audit Report #6: `bank_statement_0170`
- **Document UID**: `bank_statement_0170`
- **SHA-256 Checksum**: `1dcaefead2f4dfeaacb78030c7fd07c4a31f89fb8ccd1a52542749cbd15aea27`
- **Classified Document Type**: **bank_statement** (Ground Truth: `bank_statement`)
- **Classifier Model & Version**: `tfidf_logistic_regression` (`v1.0.0`)
- **OCR Engine & Version**: `Tesseract-OCR` (`4.0.0a0`)
- **Classification Confidence**: **0.9722**
- **PII Entities Detected**: `True` (Types: ['IBAN_CODE', 'PERSON'])
- **Assigned Retention Class**: `FINANCIAL_7_YEARS`
- **Assigned Access Control List (ACL)**: `CONFIDENTIAL_FINANCE`
- **Target ECM Workflow**: `TREASURY_RECONCILIATION`
- **Review Status**: `auto_accepted`
- **Reviewer / Automated Actor**: `AUTOMATED_INGESTION_ENGINE`
- **Processed Timestamp**: `2026-11-18T08:10:57.628133+00:00`
- **Decision Justification**:
  > Confidence 0.972 >= threshold 0.920 for bank_statement

---

### Asset Audit Report #7: `contract_0196`
- **Document UID**: `contract_0196`
- **SHA-256 Checksum**: `350633bc1b2fee5764632f0428753e647971e029a1f937ec27f20226f460c3ad`
- **Classified Document Type**: **contract** (Ground Truth: `contract`)
- **Classifier Model & Version**: `tfidf_logistic_regression` (`v1.0.0`)
- **OCR Engine & Version**: `Tesseract-OCR` (`4.0.0a0`)
- **Classification Confidence**: **0.9596**
- **PII Entities Detected**: `True` (Types: ['US_SSN', 'PERSON'])
- **Assigned Retention Class**: `LEGAL_10_YEARS`
- **Assigned Access Control List (ACL)**: `RESTRICTED_REVIEW`
- **Target ECM Workflow**: `HIGH_SENSITIVITY_REVIEW`
- **Review Status**: `pending_review`
- **Reviewer / Automated Actor**: `AUTOMATED_INGESTION_ENGINE`
- **Processed Timestamp**: `2026-11-18T08:11:03.272790+00:00`
- **Decision Justification**:
  > Classifier/PII Conflict: High-sensitivity PII found in low-risk class; enforcing stricter review path

---

### Asset Audit Report #8: `kyc_form_0196`
- **Document UID**: `kyc_form_0196`
- **SHA-256 Checksum**: `5464fc0b806755acedd381ae286682daed0de60ceba12bf92e4489c11c66f5b7`
- **Classified Document Type**: **kyc_form** (Ground Truth: `kyc_form`)
- **Classifier Model & Version**: `tfidf_logistic_regression` (`v1.0.0`)
- **OCR Engine & Version**: `Tesseract-OCR` (`4.0.0a0`)
- **Classification Confidence**: **0.9771**
- **PII Entities Detected**: `True` (Types: ['US_SSN', 'PERSON', 'PASSPORT'])
- **Assigned Retention Class**: `COMPLIANCE_10_YEARS`
- **Assigned Access Control List (ACL)**: `RESTRICTED_KYC`
- **Target ECM Workflow**: `CUSTOMER_ONBOARDING`
- **Review Status**: `auto_accepted`
- **Reviewer / Automated Actor**: `AUTOMATED_INGESTION_ENGINE`
- **Processed Timestamp**: `2026-11-18T08:11:08.025527+00:00`
- **Decision Justification**:
  > Confidence 0.977 >= threshold 0.920 for kyc_form

---

### Asset Audit Report #9: `kyc_form_0162`
- **Document UID**: `kyc_form_0162`
- **SHA-256 Checksum**: `a51b09517109bc414e7da4b3fc391e94da48485c90b5437185355a53faa296ef`
- **Classified Document Type**: **kyc_form** (Ground Truth: `kyc_form`)
- **Classifier Model & Version**: `tfidf_logistic_regression` (`v1.0.0`)
- **OCR Engine & Version**: `Tesseract-OCR` (`4.0.0a0`)
- **Classification Confidence**: **0.9536**
- **PII Entities Detected**: `True` (Types: ['US_SSN', 'PASSPORT', 'PHONE_NUMBER', 'PERSON'])
- **Assigned Retention Class**: `COMPLIANCE_10_YEARS`
- **Assigned Access Control List (ACL)**: `RESTRICTED_KYC`
- **Target ECM Workflow**: `CUSTOMER_ONBOARDING`
- **Review Status**: `auto_accepted`
- **Reviewer / Automated Actor**: `AUTOMATED_INGESTION_ENGINE`
- **Processed Timestamp**: `2026-11-18T08:11:06.097938+00:00`
- **Decision Justification**:
  > Confidence 0.954 >= threshold 0.920 for kyc_form

---

### Asset Audit Report #10: `medical_report_0174`
- **Document UID**: `medical_report_0174`
- **SHA-256 Checksum**: `c4ec1f997d4152ebe117896bb93c9af31b06604a400a2e0f993eadc7d0823be3`
- **Classified Document Type**: **medical_report** (Ground Truth: `medical_report`)
- **Classifier Model & Version**: `tfidf_logistic_regression` (`v1.0.0`)
- **OCR Engine & Version**: `Tesseract-OCR` (`4.0.0a0`)
- **Classification Confidence**: **0.9562**
- **PII Entities Detected**: `True` (Types: ['US_SSN', 'PERSON', 'MEDICAL_LICENSE'])
- **Assigned Retention Class**: `HEALTH_RECORD_PERMANENT`
- **Assigned Access Control List (ACL)**: `RESTRICTED_MEDICAL`
- **Target ECM Workflow**: `CLINICAL_REVIEW`
- **Review Status**: `auto_accepted`
- **Reviewer / Automated Actor**: `AUTOMATED_INGESTION_ENGINE`
- **Processed Timestamp**: `2026-11-18T08:11:11.152148+00:00`
- **Decision Justification**:
  > Confidence 0.956 >= threshold 0.920 for medical_report

---
