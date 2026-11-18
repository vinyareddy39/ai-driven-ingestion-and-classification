"""Unit tests for PII masking and log sanitization."""

import logging
from app.core.security import PIISanitizingLogFilter, mask_string, sanitize_dict_for_logging


def test_mask_string_ssn():
    raw = "User SSN is 123-45-6789 in report."
    masked = mask_string(raw)
    assert "123-45-6789" not in masked
    assert "***-**-6789" in masked


def test_mask_string_credit_card():
    raw = "Customer paid using 4111-2222-3333-4444 on file."
    masked = mask_string(raw)
    assert "4111-2222-3333-4444" not in masked
    assert "4444" in masked


def test_sanitize_dict_for_logging():
    data = {
        "user": "Alice",
        "ssn": "987-65-4321",
        "credit_card": "1234-5678-9012-3456",
        "nested": {"notes": "Call 555-123-4567 regarding loan"},
    }
    sanitized = sanitize_dict_for_logging(data)
    assert sanitized["ssn"] == "[REDACTED_PII]"
    assert sanitized["credit_card"] == "[REDACTED_PII]"
    assert "555-123-4567" not in sanitized["nested"]["notes"]


def test_logging_filter():
    logger = logging.getLogger("test_logger")
    logger.setLevel(logging.INFO)
    log_filter = PIISanitizingLogFilter()
    logger.addFilter(log_filter)

    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Processing customer SSN 000-11-2222",
        args=(),
        exc_info=None,
    )
    log_filter.filter(record)
    assert "000-11-2222" not in record.msg
