"""Storage adapters for raw assets (MinIO / S3 and Local Filesystem)."""

import os
from pathlib import Path
from typing import Optional
from app.core.interfaces import Storage
from app.core.config import get_app_settings


class LocalFileStorage(Storage):
    """Local filesystem implementation of Storage interface."""

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            base_dir = os.path.join(os.getcwd(), "data", "storage")
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, key: str) -> Path:
        # Key is typically sha256 or sha256.ext
        return self.base_dir / key

    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        target = self._get_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as f:
            f.write(data)
        return str(target.as_posix())

    def get(self, key: str) -> bytes:
        target = self._get_path(key)
        if not target.exists():
            raise FileNotFoundError(f"Storage key not found: {key}")
        with open(target, "rb") as f:
            return f.read()

    def exists(self, key: str) -> bool:
        return self._get_path(key).exists()

    def delete(self, key: str) -> bool:
        target = self._get_path(key)
        if target.exists():
            target.unlink()
            return True
        return False


class MinioStorage(Storage):
    """MinIO / S3 S3-compatible implementation of Storage interface."""

    def __init__(self):
        from minio import Minio
        settings = get_app_settings()
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.bucket = settings.MINIO_BUCKET
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        import io
        stream = io.BytesIO(data)
        self.client.put_object(
            bucket_name=self.bucket,
            object_name=key,
            data=stream,
            length=len(data),
            content_type=content_type,
        )
        return f"s3://{self.bucket}/{key}"

    def get(self, key: str) -> bytes:
        response = self.client.get_object(self.bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, key: str) -> bool:
        try:
            self.client.stat_object(self.bucket, key)
            return True
        except Exception:
            return False

    def delete(self, key: str) -> bool:
        try:
            self.client.remove_object(self.bucket, key)
            return True
        except Exception:
            return False


def get_storage_adapter() -> Storage:
    """Factory creating configured storage adapter."""
    settings = get_app_settings()
    if settings.STORAGE_BACKEND == "minio":
        try:
            return MinioStorage()
        except Exception:
            # Graceful fallback to local if MinIO container is offline
            return LocalFileStorage()
    return LocalFileStorage()
