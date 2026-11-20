"""Storage adapters for raw assets (Cloudflare R2 / S3, MinIO, and Local Filesystem)."""

import hashlib
import io
import os
from pathlib import Path
import shutil
from typing import Any, Dict, Generator, List, Optional
import uuid

from app.core.interfaces import Storage
from app.core.config import get_app_settings


class LocalFileStorage(Storage):
    """Local filesystem implementation of Storage interface with streaming & multipart support."""

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            base_dir = os.path.join(os.getcwd(), "data", "storage")
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.multipart_dir = self.base_dir / "_multipart"
        self.multipart_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, key: str) -> Path:
        return self.base_dir / key

    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        target = self._get_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as f:
            f.write(data)
        return str(target.as_posix())

    def save_file(self, key: str, file_path: str, content_type: str = "application/octet-stream") -> str:
        target = self._get_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(file_path), str(target))
        return str(target.as_posix())

    def get(self, key: str) -> bytes:
        target = self._get_path(key)
        if not target.exists():
            raise FileNotFoundError(f"Storage key not found: {key}")
        with open(target, "rb") as f:
            return f.read()

    def get_stream(self, key: str, chunk_size: int = 65536) -> Generator[bytes, None, None]:
        """Stream bytes chunk-by-chunk from local disk without loading entire file in memory."""
        target = self._get_path(key)
        if not target.exists():
            raise FileNotFoundError(f"Storage key not found: {key}")
        with open(target, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    def get_object_size(self, key: str) -> int:
        target = self._get_path(key)
        if not target.exists():
            raise FileNotFoundError(f"Storage key not found: {key}")
        return target.stat().st_size

    def exists(self, key: str) -> bool:
        return self._get_path(key).exists()

    def delete(self, key: str) -> bool:
        target = self._get_path(key)
        if target.exists():
            target.unlink()
            return True
        return False

    # Multipart methods for local mode simulation
    def create_multipart_upload(self, key: str, mime_type: str = "application/octet-stream") -> str:
        upload_id = f"local-up-{uuid.uuid4().hex}"
        session_dir = self.multipart_dir / upload_id
        session_dir.mkdir(parents=True, exist_ok=True)
        with open(session_dir / "meta.txt", "w", encoding="utf-8") as f:
            f.write(f"key={key}\nmime={mime_type}\n")
        return upload_id

    def generate_presigned_part_url(
        self, key: str, upload_id: str, part_number: int, expires_in: int = 3600
    ) -> str:
        # In local mode, parts are uploaded via backend endpoint /api/v1/uploads/{upload_id}/parts/{part_number}
        return f"/api/v1/uploads/{upload_id}/parts/{part_number}"

    def upload_part_data(self, upload_id: str, part_number: int, data: bytes) -> str:
        session_dir = self.multipart_dir / upload_id
        session_dir.mkdir(parents=True, exist_ok=True)
        part_file = session_dir / f"part_{part_number}"
        with open(part_file, "wb") as f:
            f.write(data)
        etag = hashlib.md5(data).hexdigest()
        return etag

    def complete_multipart_upload(self, key: str, upload_id: str, parts: List[Dict[str, Any]]) -> str:
        session_dir = self.multipart_dir / upload_id
        if not session_dir.exists():
            raise FileNotFoundError(f"Upload session {upload_id} not found")

        target = self._get_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)

        # Sort parts by part_number
        sorted_parts = sorted(parts, key=lambda p: p.get("PartNumber", p.get("part_number", 0)))
        with open(target, "wb") as outfile:
            for p in sorted_parts:
                num = p.get("PartNumber", p.get("part_number"))
                part_file = session_dir / f"part_{num}"
                if not part_file.exists():
                    raise FileNotFoundError(f"Part {num} not found for upload {upload_id}")
                with open(part_file, "rb") as infile:
                    shutil.copyfileobj(infile, outfile)

        # Clean up temporary parts directory
        try:
            shutil.rmtree(session_dir)
        except OSError:
            pass

        return str(target.as_posix())

    def abort_multipart_upload(self, key: str, upload_id: str) -> bool:
        session_dir = self.multipart_dir / upload_id
        if session_dir.exists():
            try:
                shutil.rmtree(session_dir)
                return True
            except OSError:
                pass
        return False


class S3Storage(Storage):
    """Cloudflare R2 / AWS S3 / MinIO S3-compatible storage adapter with boto3."""

    def __init__(self):
        import boto3
        from botocore.config import Config
        settings = get_app_settings()

        endpoint_url = settings.S3_ENDPOINT_URL or (
            f"http://{settings.MINIO_ENDPOINT}" if hasattr(settings, "MINIO_ENDPOINT") and settings.MINIO_ENDPOINT else None
        )
        access_key = settings.S3_ACCESS_KEY or getattr(settings, "MINIO_ACCESS_KEY", None)
        secret_key = settings.S3_SECRET_KEY or getattr(settings, "MINIO_SECRET_KEY", None)
        region = settings.S3_REGION or "us-east-1"
        self.bucket = settings.S3_BUCKET or getattr(settings, "MINIO_BUCKET", "ecm-raw-assets")

        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

        # Auto-create bucket in local dev/MinIO if missing
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            try:
                self.client.create_bucket(Bucket=self.bucket)
            except Exception:
                pass

    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return f"s3://{self.bucket}/{key}"

    def save_file(self, key: str, file_path: str, content_type: str = "application/octet-stream") -> str:
        self.client.upload_file(
            Filename=str(file_path),
            Bucket=self.bucket,
            Key=key,
            ExtraArgs={"ContentType": content_type},
        )
        try:
            os.unlink(file_path)
        except OSError:
            pass
        return f"s3://{self.bucket}/{key}"

    def get(self, key: str) -> bytes:
        resp = self.client.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read()

    def get_stream(self, key: str, chunk_size: int = 65536) -> Generator[bytes, None, None]:
        """Stream bytes chunk-by-chunk from S3 / R2 without loading whole object in memory."""
        resp = self.client.get_object(Bucket=self.bucket, Key=key)
        body = resp["Body"]
        for chunk in body.iter_chunks(chunk_size):
            if chunk:
                yield chunk

    def get_object_size(self, key: str) -> int:
        resp = self.client.head_object(Bucket=self.bucket, Key=key)
        return int(resp["ContentLength"])

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, key: str) -> bool:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    # Multipart methods for Cloudflare R2 / S3
    def create_multipart_upload(self, key: str, mime_type: str = "application/octet-stream") -> str:
        resp = self.client.create_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            ContentType=mime_type,
        )
        return resp["UploadId"]

    def generate_presigned_part_url(
        self, key: str, upload_id: str, part_number: int, expires_in: int = 3600
    ) -> str:
        """Generate short-lived PUT presigned URL for an upload part."""
        return self.client.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "UploadId": upload_id,
                "PartNumber": part_number,
            },
            ExpiresIn=expires_in,
            HttpMethod="PUT",
        )

    def upload_part_data(self, upload_id: str, part_number: int, data: bytes) -> str:
        # Note: In real S3, client PUTs directly to presigned URL; this helper aids unit tests
        # We need the key corresponding to this upload_id
        resp = self.client.upload_part(
            Bucket=self.bucket,
            Key=upload_id,  # Caller supplies key or passes in key
            UploadId=upload_id,
            PartNumber=part_number,
            Body=data,
        )
        return resp["ETag"]

    def complete_multipart_upload(self, key: str, upload_id: str, parts: List[Dict[str, Any]]) -> str:
        s3_parts = [
            {"PartNumber": p.get("PartNumber", p.get("part_number")), "ETag": p.get("ETag", p.get("etag"))}
            for p in sorted(parts, key=lambda x: x.get("PartNumber", x.get("part_number", 0)))
        ]
        self.client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": s3_parts},
        )
        return f"s3://{self.bucket}/{key}"

    def abort_multipart_upload(self, key: str, upload_id: str) -> bool:
        try:
            self.client.abort_multipart_upload(
                Bucket=self.bucket,
                Key=key,
                UploadId=upload_id,
            )
            return True
        except Exception:
            return False


# Compatibility alias
MinioStorage = S3Storage


def get_storage_adapter() -> Storage:
    """Factory creating configured storage adapter."""
    settings = get_app_settings()
    if settings.STORAGE_BACKEND in ("minio", "s3"):
        try:
            return S3Storage()
        except Exception:
            # Fallback to local file storage if S3 endpoint is not configured/reachable
            return LocalFileStorage()
    return LocalFileStorage()

