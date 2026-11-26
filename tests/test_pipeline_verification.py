"""Automated Verification Suite for Generalized Document Pipeline.

Executes tests against 8 newly generated synthetic documents covering all required scenarios:
1. Clean digital file
2. Clean image
3. Rotated or skewed noisy scan
4. Image-only PDF
5. Multi-page file with two different documents
6. Table with many columns
7. Document that resembles another type but states it is not (negative evidence)
8. Value that looks sensitive but is not (unrelated label context)
"""

import os
import sys
import unittest
import json

sys.path.insert(0, os.path.abspath("."))
from app.core.generalized_pipeline import GeneralizedDocumentPipeline
from tests.generate_synthetic_docs import create_synthetic_suite


class TestGeneralizedPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = os.path.abspath("data/synthetic_tests")
        create_synthetic_suite(cls.test_dir)
        cls.pipeline = GeneralizedDocumentPipeline()

    def test_01_clean_digital(self):
        """Scenario 1: Clean digital file with embedded text layer."""
        fpath = os.path.join(self.test_dir, "syn_01_clean_digital.pdf")
        res = self.pipeline.process_file(fpath)
        
        self.assertEqual(res["type"], "invoice")
        self.assertGreaterEqual(res["type_confidence"], 0.80)
        self.assertEqual(res["page_conditions"][0]["condition"], "clean (digital)")
        self.assertIn(res["routing"]["destination"], ["AP_INVOICE_PROCESSING", "FINANCE_ACCOUNTS_PAYABLE"])
        self.assertFalse(res["needs_review"])
        self.assertIn("INV-2026-9001", [f["value"] for f in res["fields"]])
        print("\n[PASS] Test 1: Clean Digital File (Invoice) classified accurately at", res["type_confidence"])

    def test_02_clean_image(self):
        """Scenario 2: Clean image document."""
        fpath = os.path.join(self.test_dir, "syn_02_clean_image.png")
        res = self.pipeline.process_file(fpath)
        
        self.assertEqual(res["type"], "medical_report")
        self.assertGreaterEqual(res["type_confidence"], 0.70)
        self.assertIn(res["routing"]["destination"], ["CLINICAL_RECORDS_SYSTEM", "RESTRICTED_HIPAA_SECURE_VAULT"])
        print("\n[PASS] Test 2: Clean Image (Medical Report) classified accurately at", res["type_confidence"])

    def test_03_rotated_skewed_noisy(self):
        """Scenario 3: Rotated, skewed, and noisy scan."""
        fpath = os.path.join(self.test_dir, "syn_03_rotated_skewed_noisy.png")
        res = self.pipeline.process_file(fpath)
        
        cond = res["page_conditions"][0]
        # Auto-orientation or deskew was applied
        self.assertTrue(cond["orientation_degrees"] != 0 or abs(cond["skew_angle"]) > 0.0 or cond["noise_level"] > 0)
        self.assertIsNotNone(res["type"])
        print("\n[PASS] Test 3: Rotated Skewed Noisy Scan handled cleanly (Condition:", cond["condition"], ")")

    def test_04_image_only_pdf(self):
        """Scenario 4: Image-only PDF with zero embedded digital text."""
        fpath = os.path.join(self.test_dir, "syn_04_image_only.pdf")
        res = self.pipeline.process_file(fpath)
        
        self.assertEqual(res["type"], "contract")
        self.assertIn(res["routing"]["destination"], ["LEGAL_CONTRACT_REPOSITORY", "RESTRICTED_LEGAL_COMPLIANCE_VAULT"])
        print("\n[PASS] Test 4: Image-Only PDF processed via OCR into Contract at", res["type_confidence"])

    def test_05_multipage_two_documents(self):
        """Scenario 5: Multi-page file with two different logical documents."""
        fpath = os.path.join(self.test_dir, "syn_05_multipage_two_documents.pdf")
        res = self.pipeline.process_file(fpath)
        
        log_docs = res["logical_documents"]
        self.assertGreaterEqual(len(log_docs), 2)
        doc1 = log_docs[0]
        doc2 = log_docs[1]
        
        self.assertEqual(doc1["start_page"], 1)
        self.assertEqual(doc1["end_page"], 1)
        self.assertEqual(doc1["type"], "invoice")
        
        self.assertEqual(doc2["start_page"], 2)
        self.assertEqual(doc2["end_page"], 2)
        self.assertEqual(doc2["type"], "letter")
        print(f"\n[PASS] Test 5: Multi-Page segmented into 2 logical docs: {doc1['type']} (p1) & {doc2['type']} (p2)")

    def test_06_table_many_columns(self):
        """Scenario 6: Document with a table containing many columns."""
        fpath = os.path.join(self.test_dir, "syn_06_table_many_columns.pdf")
        res = self.pipeline.process_file(fpath)
        
        table_rows = res["table_rows"]
        self.assertGreaterEqual(len(table_rows), 2)
        # Check that row has at least 3 distinct column entries
        first_row = table_rows[0]
        self.assertGreaterEqual(len(first_row.keys()), 3)
        print(f"\n[PASS] Test 6: Table with many columns extracted ({len(table_rows)} rows, columns: {list(first_row.keys())})")

    def test_07_negative_evidence(self):
        """Scenario 7: Document resembles invoice but explicitly states it is NOT (negative evidence)."""
        fpath = os.path.join(self.test_dir, "syn_07_negative_evidence.pdf")
        res = self.pipeline.process_file(fpath)
        
        # Must NOT classify as invoice
        self.assertNotEqual(res["type"], "invoice")
        self.assertTrue(res["needs_review"] or res["type"] == "unknown")
        print(f"\n[PASS] Test 7: Negative evidence respected (Document type is '{res['type']}', NOT 'invoice')")

    def test_08_sensitive_lookalike_unrelated(self):
        """Scenario 8: Value resembles sensitive pattern but is under an unrelated label."""
        fpath = os.path.join(self.test_dir, "syn_08_sensitive_lookalike_unrelated.pdf")
        res = self.pipeline.process_file(fpath)
        
        # Part Number: 987-65-4321 must NOT restrict the document as high-confidence SSN
        self.assertFalse(res["routing"]["is_restricted"])
        print("\n[PASS] Test 8: Value under unrelated label avoided false positive restriction (is_restricted:", res["routing"]["is_restricted"], ")")


if __name__ == "__main__":
    unittest.main()
