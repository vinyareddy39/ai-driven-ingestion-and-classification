"""Locust load test simulating continuous ingestion up to 50,000 docs/day equivalent."""

import random
from locust import HttpUser, between, task


class ECMIngestUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(3)
    def ingest_document(self):
        """Simulate real-time live ingestion of document."""
        dummy_content = b"%PDF-1.4 synthetic benchmark payload " + str(random.random()).encode()
        files = {"file": ("benchmark_doc.pdf", dummy_content, "application/pdf")}
        self.client.post("/ingest", files=files)

    @task(1)
    def trigger_reprocessing(self):
        """Simulate concurrent low-priority bulk reprocessing job."""
        self.client.post(
            "/reprocess",
            json={"min_confidence": 0.80, "target_types": ["invoice", "contract"], "dry_run": False},
        )

    @task(2)
    def inspect_metrics(self):
        """Simulate monitoring scraper polling Prometheus metrics."""
        self.client.get("/metrics")
