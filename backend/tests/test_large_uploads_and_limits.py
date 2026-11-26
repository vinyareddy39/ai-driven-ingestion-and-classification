"""Comprehensive tests validating streaming large uploads, MAX_UPLOAD_MB enforcement, and rejection handling."""

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.api.app import app
from app.core.config import get_app_settings
from app.adapters.storage import get_storage_adapter


def _create_synthetic_pdf_bytes(target_size_bytes: int) -> bytes:
    """Generate a valid synthetic PDF with exact byte padding."""
    header = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    footer = b"\nxref\n0 3\n0000000000 65535 f \n0000000009 00000 n \ntrailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n50\n%%EOF\n"
    needed_padding = max(0, target_size_bytes - len(header) - len(footer))
    # Fill with repeated comment bytes
    padding = b"% " + b"X" * max(0, needed_padding - 3) + b"\n"
    content = header + padding + footer
    return content[:target_size_bytes] if len(content) > target_size_bytes else content


@pytest.fixture
def auth_headers():
    from app.core.auth import get_configured_tokens
    tokens = get_configured_tokens()
    admin_token = None
    for tok, role in tokens.items():
        if role == "admin":
            admin_token = tok
            break
    if not admin_token:
        admin_token = list(tokens.keys())[0] if tokens else "secret-token-12345"
    return {"Authorization": f"Bearer {admin_token}"}


def test_synthetic_files_accepted_sizes(auth_headers):
    """Assert that 1 MB, 24 MB, 26 MB (previously rejected by 25MB limit), and 60 MB files are accepted."""
    client = TestClient(app)
    storage = get_storage_adapter()

    # Sizes in MB
    test_sizes = [
        (1, 1 * 1024 * 1024),
        (24, 24 * 1024 * 1024),
        (26, 26 * 1024 * 1024),
        (60, 60 * 1024 * 1024),
    ]

    for size_mb, size_bytes in test_sizes:
        data = _create_synthetic_pdf_bytes(size_bytes)
        file_name = f"synth_{size_mb}mb.pdf"
        files = {"file": (file_name, data, "application/pdf")}

        resp = client.post("/ingest", files=files, headers=auth_headers)
        assert resp.status_code == 202, f"Failed for size {size_mb} MB: {resp.text}"

        json_data = resp.json()
        assert json_data["status"] == "QUEUED"
        assert json_data["file_name"] == file_name
        assert len(json_data["sha256"]) == 64
        assert json_data["uid"] is not None

        # Confirm asset was safely stored
        assert storage.exists(json_data["sha256"])
        # Clean up storage asset
        storage.delete(json_data["sha256"])


def test_file_just_over_max_upload_returns_413_and_leaves_no_partial_file(auth_headers, monkeypatch):
    """Assert that an oversized file returns 413 and deletes any partial streaming temp file."""
    # Set limit to 5 MB for fast testing
    monkeypatch.setenv("MAX_UPLOAD_MB", "5")
    import app.core.settings as settings_module
    settings_module._cached_settings = None  # Reset singleton cache

    client = TestClient(app)
    settings = get_app_settings()
    assert settings.MAX_UPLOAD_MB == 5

    temp_dir = Path(settings.STORAGE_LOCAL_DIR) / "_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    before_tmp_files = set(temp_dir.glob("*.tmp"))

    # Generate 6 MB file (1 MB over the 5 MB limit)
    oversized_data = _create_synthetic_pdf_bytes(6 * 1024 * 1024)
    files = {"file": ("oversized_6mb.pdf", oversized_data, "application/pdf")}

    resp = client.post("/ingest", files=files, headers=auth_headers)
    assert resp.status_code == 413, resp.text
    assert "File exceeds maximum allowed size of 5 MB" in resp.json()["detail"]

    # Verify NO partial file was leaked
    after_tmp_files = set(temp_dir.glob("*.tmp"))
    assert after_tmp_files == before_tmp_files, f"Leaked temporary files found: {after_tmp_files - before_tmp_files}"

    # Reset singleton
    settings_module._cached_settings = None


def test_empty_file_rejected(auth_headers):
    """Assert that a zero-byte upload is rejected with 400 Bad Request."""
    client = TestClient(app)
    files = {"file": ("empty.pdf", b"", "application/pdf")}

    resp = client.post("/ingest", files=files, headers=auth_headers)
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()


def test_corrupt_pdf_rejected(auth_headers):
    """Assert that a corrupt PDF without valid header is rejected with 400 Bad Request."""
    client = TestClient(app)
    files = {"file": ("corrupt.pdf", b"NOT_A_REAL_PDF_HEADER_JUST_GARBAGE", "application/pdf")}

    resp = client.post("/ingest", files=files, headers=auth_headers)
    assert resp.status_code == 400
    assert "corrupt" in resp.json()["detail"].lower()


def test_unsupported_file_type_rejected(auth_headers):
    """Assert that an executable or unlisted extension is rejected with 400 Bad Request."""
    client = TestClient(app)
    files = {"file": ("malicious_payload.exe", b"MZ\x90\x00BinaryExeContent", "application/x-msdownload")}

    resp = client.post("/ingest", files=files, headers=auth_headers)
    assert resp.status_code == 400
    assert "unsupported file type" in resp.json()["detail"].lower()
