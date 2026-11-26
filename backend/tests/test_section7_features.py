import unittest
import os
import sys

sys.path.insert(0, os.path.abspath("."))
import fitz
from app.core.layout_extractor import LayoutAwareExtractor, LayoutBlock, LayoutLine, LayoutSpan
from app.core.learned_registry import LearnedRegistry
from app.core.generalized_pipeline import GeneralizedDocumentPipeline

class TestSection7Features(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = os.path.abspath("data/test_sec7")
        os.makedirs(cls.test_dir, exist_ok=True)
        cls.pdf_path = os.path.join(cls.test_dir, "sample_invoice.pdf")
        
        # Build synthetic PDF
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        
        # Prominent header
        page.insert_text((50, 60), "ACME SUPPLIES CORP", fontsize=20, fontname="helv", color=(0,0,0))
        # Form rows
        page.insert_text((50, 110), "Invoice Number: INV-98214", fontsize=11, fontname="helv")
        page.insert_text((50, 130), "Invoice Date: 11/15/2026", fontsize=11, fontname="helv")
        page.insert_text((50, 150), "Due Date: 12/15/2026", fontsize=11, fontname="helv")
        page.insert_text((50, 170), "Customer ID: CUST-4412", fontsize=11, fontname="helv")
        page.insert_text((50, 190), "Subtotal: $4,500.00", fontsize=11, fontname="helv")
        page.insert_text((50, 210), "Tax Amount: $360.00", fontsize=11, fontname="helv")
        page.insert_text((50, 230), "Total Balance: $4,860.00", fontsize=11, fontname="helv")
        page.insert_text((50, 250), "Payment Terms: Net 30", fontsize=11, fontname="helv")
        page.insert_text((50, 270), "Contact Support: 800-555-0199", fontsize=11, fontname="helv")
        page.insert_text((50, 290), "PO Number: PO-8871", fontsize=11, fontname="helv")
        # Mixed value for split suggestion
        page.insert_text((50, 320), "Paid on 11/16/2026 $500.00 via WIRE", fontsize=11, fontname="helv")
        
        # Footer noise (should be skipped)
        page.insert_text((250, 770), "Page 1 of 1", fontsize=8, fontname="helv")
        page.insert_text((50, 780), "Confidential & Proprietary", fontsize=8, fontname="helv")
        
        doc.save(cls.pdf_path)
        doc.close()
        
        cls.pipeline = GeneralizedDocumentPipeline()

    def test_pipeline_execution(self):
        res = self.pipeline.process_file(self.pdf_path)
        
        # 1. Document-level output
        self.assertIn("document_kind", res)
        self.assertIn("summary", res)
        self.assertIn("tags", res)
        self.assertIn("raw_text_by_page", res)
        self.assertIn(1, res["raw_text_by_page"])
        self.assertIn("ACME SUPPLIES CORP", res["raw_text_by_page"][1])
        
        # 2. Key Details partitioning (max 8)
        self.assertLessEqual(len(res["key_details"]), 8)
        self.assertGreater(len(res["more_details"]), 0)
        
        # 3. Grounding span requirement
        for field in res["fields"]:
            self.assertIsNotNone(field.get("grounding_span"))
            span = field["grounding_span"]
            self.assertIn("text", span)
            self.assertIn("bbox", span)
            self.assertIn("page", span)
            
        # 4. Split suggestions
        has_split = any(f.get("split_suggestion") is not None for f in res["fields"])
        self.assertTrue(has_split, "Expected at least one mixed value to have a split suggestion")
        
        # 5. Label generation and registry
        registry = LearnedRegistry()
        gen_result = registry.generate_label_for_detail(
            value="INV-98214",
            context_before="Invoice Number:",
            doc_type="Invoice"
        )
        self.assertIsNotNone(gen_result["suggested_label"])
        self.assertIn("source", gen_result)
        self.assertEqual(gen_result["source"], "generated")
        self.assertIsInstance(gen_result["alternatives"], list)
        
        print("\n[PASS] All Section 7 Pipeline & Layout Extractor tests verified successfully!")

if __name__ == "__main__":
    unittest.main()
