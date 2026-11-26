"""Antivirus scanning adapters (ClamAV and Mock Scanner with EICAR detection)."""

from typing import Optional, Tuple
from app.core.interfaces import VirusScanner
from app.core.config import get_app_settings

# Standard EICAR test string signature for antivirus evaluation
EICAR_SIGNATURE = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class MockVirusScanner(VirusScanner):
    """Mock virus scanner detecting EICAR test signatures or simulated malware flags."""

    def scan(self, data: bytes) -> Tuple[bool, Optional[str]]:
        if EICAR_SIGNATURE in data or b"VIRUS_INFECTED_PAYLOAD" in data:
            return False, "EICAR-Test-Signature"
        return True, None


class ClamAVScanner(VirusScanner):
    """Production ClamAV network daemon scanner."""

    def __init__(self):
        import socket
        settings = get_app_settings()
        self.host = settings.CLAMAV_HOST
        self.port = settings.CLAMAV_PORT

    def scan(self, data: bytes) -> Tuple[bool, Optional[str]]:
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect((self.host, self.port))
                # INSTREAM command
                s.sendall(b"zINSTREAM\0")
                chunk_size = 2048
                for i in range(0, len(data), chunk_size):
                    chunk = data[i:i + chunk_size]
                    size_prefix = len(chunk).to_bytes(4, byteorder="big")
                    s.sendall(size_prefix + chunk)
                # End of stream (0 length chunk)
                s.sendall((0).to_bytes(4, byteorder="big"))
                response = s.recv(4096).decode("utf-8", errors="ignore")
                if "OK" in response:
                    return True, None
                elif "FOUND" in response:
                    virus_name = response.split("FOUND")[0].strip().split(":")[-1].strip()
                    return False, virus_name
                return True, None
        except Exception:
            # Fallback to safe mock if ClamAV daemon is unreachable
            return MockVirusScanner().scan(data)


def get_virus_scanner() -> VirusScanner:
    """Factory returning configured virus scanner."""
    settings = get_app_settings()
    if settings.VIRUS_SCANNER_BACKEND == "clamav":
        return ClamAVScanner()
    return MockVirusScanner()
