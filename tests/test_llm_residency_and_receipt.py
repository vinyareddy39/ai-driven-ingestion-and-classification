"""Unit tests for Stage 3: LLM Data Residency Router, Receipt Extractor, and AI Services."""

import pytest
from unittest.mock import MagicMock, patch

from app.workers.llm_client import (
    LLMResidencyRouter,
    LocalLLMClient,
    HostedLLMClient,
    ReceiptExtractor,
    RESTRICTED_CLASSES,
)


class TestLLMResidencyRouter:
    """Verify data residency invariants across all document classes."""

    def test_restricted_classes_never_route_to_hosted(self):
        """Restricted classes (medical, KYC, banking, claims, prescriptions) must never use hosted APIs."""
        mock_local = MagicMock(spec=LocalLLMClient)
        mock_local.is_available.return_value = False  # Local is offline!

        mock_hosted = MagicMock(spec=HostedLLMClient)
        mock_hosted.is_available.return_value = True   # Hosted is online!

        router = LLMResidencyRouter(local_client=mock_local, hosted_client=mock_hosted)

        for restricted in RESTRICTED_CLASSES:
            backend, client = router.route(restricted)
            # Must NOT route to hosted despite hosted being online
            assert backend == "deterministic_fallback", f"{restricted} routed to {backend}!"
            assert client is None

            # Execution check
            res = router.execute_with_residency(restricted, "Extract diagnosis")
            assert res["status"] == "FALLBACK_TO_DETERMINISTIC"
            assert "residency policy prevents hosted API routing" in res["reason"]

    def test_restricted_classes_route_to_local_when_available(self):
        """When local LLM is available, restricted classes route to local."""
        mock_local = MagicMock(spec=LocalLLMClient)
        mock_local.is_available.return_value = True
        mock_local.complete.return_value = {"prescription": {"drug": "Amoxicillin"}}

        mock_hosted = MagicMock(spec=HostedLLMClient)
        mock_hosted.is_available.return_value = True

        router = LLMResidencyRouter(local_client=mock_local, hosted_client=mock_hosted)

        for restricted in RESTRICTED_CLASSES:
            backend, client = router.route(restricted)
            assert backend == "local"
            assert client is mock_local

    def test_low_risk_receipt_allowed_hosted_when_configured(self):
        """Low risk classes like receipt may route to hosted when configured."""
        mock_local = MagicMock(spec=LocalLLMClient)
        mock_local.is_available.return_value = False

        mock_hosted = MagicMock(spec=HostedLLMClient)
        mock_hosted.is_available.return_value = True

        router = LLMResidencyRouter(local_client=mock_local, hosted_client=mock_hosted)

        backend, client = router.route("receipt")
        assert backend == "hosted"
        assert client is mock_hosted


class TestReceiptExtractor:
    """Verify deterministic, grounded receipt field extractor on synthetic receipts."""

    @pytest.fixture
    def extractor(self):
        return ReceiptExtractor()

    def test_synthetic_supermarket_receipt(self, extractor):
        ocr_text = """
        METRO SUPERMARKET #402
        123 Market Street, Suite A
        Date: 2026-05-12
        Cashier: John D.
        -----------------------------
        MILK 1L                 $2.50
        BREAD WHOLE WHEAT       $3.20
        ORGANIC EGGS DOZ        $4.50
        SUBTOTAL                $10.20
        SALES TAX               $0.82
        TOTAL AMOUNT DUE        $11.02
        -----------------------------
        THANK YOU FOR SHOPPING!
        """
        result = extractor.extract(ocr_text)
        fields = result["fields"]
        grounding = result["grounding"]

        assert fields["merchant_name"] == "METRO SUPERMARKET #402"
        assert fields["date"] == "2026-05-12"
        assert fields["total_amount"] == 11.02
        assert fields["tax_amount"] == 0.82
        assert fields["currency"] == "USD"

        # Verify grounding spans
        assert "TOTAL AMOUNT DUE" in grounding["total_amount"]
        assert "SALES TAX" in grounding["tax_amount"]
        assert "2026-05-12" in grounding["date"]

    def test_synthetic_euro_cafe_receipt_dd_mm_yyyy(self, extractor):
        ocr_text = """
        CAFE CENTRAL WIEN
        Herrengasse 14, Wien
        Datum: 15/04/2026
        -----------------------------
        2x Melange              €9.60
        1x Apfelstrudel         €6.40
        MwSt / Tax              €1.60
        GESAMTBETRAG TOTAL      €16.00
        Vielen Dank!
        """
        result = extractor.extract(ocr_text)
        fields = result["fields"]

        assert fields["merchant_name"] == "CAFE CENTRAL WIEN"
        # 15/04/2026 -> 2026-04-15
        assert fields["date"] == "2026-04-15"
        assert fields["total_amount"] == 16.00
        assert fields["tax_amount"] == 1.60
        assert fields["currency"] == "EUR"

    def test_empty_receipt_handling(self, extractor):
        result = extractor.extract("")
        assert result == {}
