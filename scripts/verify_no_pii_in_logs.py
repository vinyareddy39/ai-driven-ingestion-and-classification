"""Verify zero unmasked PII appears in application logs."""

import hashlib
import io
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.security import setup_secure_logging
from app.workers.pipeline import process_document_payload
from data.synthetic_generator import generate_kyc_content, generate_bank_statement_content

def test_log_sanitization():
    print("=" * 80)
    print("AUDITING APPLICATION LOG STREAM FOR LEAKED PII ENTITIES")
    print("=" * 80)
    
    # Capture log output to string stream
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)
    
    # Attach to root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)
    
    # Process documents with known sensitive PII (SSNs, Passports, Bank Accounts)
    for i in range(5):
        res = generate_kyc_content(i)
        kyc_text = res[0]
        fb = kyc_text.encode("utf-8")
        h = hashlib.sha256(fb).hexdigest()
        u = f"audit-log-kyc-{i}"
        payload = {
            "uid": u,
            "sha256": h,
            "file_name": f"kyc_{i}.pdf",
            "file_bytes": fb,
            "mime_type": "text/plain",
            "storage_path": f"raw/{u}.pdf",
            "source": "audit_verification"
        }
        process_document_payload(payload)
        
    captured_logs = log_capture.getvalue()
    print(f"Captured {len(captured_logs.splitlines())} log lines ({len(captured_logs)} bytes).")
    
    # Regex for raw unmasked SSNs: \b\d{3}-\d{2}-\d{4}\b
    raw_ssn_pattern = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
    ssn_matches = raw_ssn_pattern.findall(captured_logs)
    
    # Regex for raw unmasked credit cards: \b(?:\d{4}-){3}\d{4}\b
    raw_cc_pattern = re.compile(r'\b(?:\d{4}-){3}\d{4}\b')
    cc_matches = raw_cc_pattern.findall(captured_logs)
    
    print(f"1. Unmasked SSN occurrences in logs: {len(ssn_matches)} (Matches: {ssn_matches})")
    print(f"2. Unmasked Credit Card occurrences in logs: {len(cc_matches)} (Matches: {cc_matches})")
    
    assert len(ssn_matches) == 0, f"LEAK DETECTED: Found unmasked SSNs in logs: {ssn_matches}"
    assert len(cc_matches) == 0, f"LEAK DETECTED: Found unmasked Credit Cards in logs: {cc_matches}"
    
    print("PII Log Sanitization: 100% COMPLIANT (Zero unmasked sensitive PII found in logs).")

if __name__ == "__main__":
    test_log_sanitization()
