"""Security utilities and PII masking for logs, error messages, and telemetry."""

import logging
import re
from typing import Any, Dict, List, Optional
from app.core.config import get_pipeline_config


# Common PII Regex Patterns for fallback redaction in logs
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
PHONE_PATTERN = re.compile(r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b")
DOB_PATTERN = re.compile(r"\b(?:DOB|Date of Birth|Birthdate):\s*([0-9]{2,4}[-/][0-9]{1,2}[-/][0-9]{1,4})\b", re.IGNORECASE)


def mask_string(text: str, mask_char: str = "*") -> str:
    """Mask sensitive patterns in arbitrary string."""
    if not text:
        return text

    # Redact SSN
    text = SSN_PATTERN.sub(lambda m: mask_char * 3 + "-" + mask_char * 2 + "-" + m.group(0)[-4:], text)
    # Redact Credit Card
    text = CREDIT_CARD_PATTERN.sub(lambda m: mask_char * 12 + m.group(0).replace("-", "").replace(" ", "")[-4:], text)
    # Redact Email
    text = EMAIL_PATTERN.sub(lambda m: m.group(0)[0] + mask_char * 5 + "@" + m.group(0).split("@")[-1], text)
    # Redact Phone
    text = PHONE_PATTERN.sub(lambda m: mask_char * 6 + m.group(0)[-4:], text)
    return text


def sanitize_dict_for_logging(data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively mask sensitive keys and string values in dictionary."""
    sensitive_keys = {
        "ssn", "social_security", "credit_card", "card_number", "password",
        "secret", "token", "auth", "dob", "birthdate", "passport", "id_number"
    }
    sanitized: Dict[str, Any] = {}

    for k, v in data.items():
        k_lower = str(k).lower()
        if any(s in k_lower for s in sensitive_keys):
            sanitized[k] = "[REDACTED_PII]"
        elif isinstance(v, dict):
            sanitized[k] = sanitize_dict_for_logging(v)
        elif isinstance(v, list):
            sanitized[k] = [
                sanitize_dict_for_logging(item) if isinstance(item, dict)
                else (mask_string(str(item)) if isinstance(item, str) else item)
                for item in v
            ]
        elif isinstance(v, str):
            sanitized[k] = mask_string(v)
        else:
            sanitized[k] = v
    return sanitized


class PIISanitizingLogFilter(logging.Filter):
    """Logging filter that ensures zero PII is emitted to application logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_string(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = sanitize_dict_for_logging(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    mask_string(arg) if isinstance(arg, str) else arg for arg in record.args
                )
        return True


def setup_secure_logging(logger_name: Optional[str] = None) -> logging.Logger:
    """Configure secure logger equipped with automatic PII sanitization."""
    logger = logging.getLogger(logger_name)
    has_filter = any(isinstance(f, PIISanitizingLogFilter) for f in logger.filters)
    if not has_filter:
        logger.addFilter(PIISanitizingLogFilter())
    return logger
