from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx


@dataclass(frozen=True)
class StoredMedia:
    storage_ref: str
    sha256: str
    size_bytes: int


class MediaTooLargeError(ValueError):
    pass


class UnsupportedMediaTypeError(ValueError):
    pass


class MediaStorageConfigurationError(RuntimeError):
    pass


class MediaStorage(Protocol):
    def store(self, *, content: bytes, filename: str | None, mime_type: str | None) -> StoredMedia: ...


def _validate_content(content: bytes, max_bytes: int) -> str:
    if not content:
        raise ValueError("Arquivo vazio.")
    if len(content) > max_bytes:
        raise MediaTooLargeError(f"Arquivo excede o limite de {max_bytes} bytes.")
    return hashlib.sha256(content).hexdigest()


def _safe_suffix(filename: str | None) -> str:
    return Path(filename or "upload.bin").suffix.lower()[:12]


class FileSystemMediaStorage:
    def __init__(self, base_dir: str | Path | None = None, max_bytes: int | None = None):
        self.base_dir = Path(base_dir or os.getenv("CAMPOEDADOS_UPLOAD_DIR", "var/data/uploads"))
        self.max_bytes = max_bytes or int(os.getenv("CAMPOEDADOS_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))

    def store(self, *, content: bytes, filename: str | None, mime_type: str | None) -> StoredMedia:
        digest = _validate_content(content, self.max_bytes)
        safe_name = f"{digest}{_safe_suffix(filename)}"
        target = self.base_dir / digest[:2] / digest[2:4] / safe_name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temp = target.with_suffix(target.suffix + ".tmp")
            temp.write_bytes(content)
            temp.replace(target)

        return StoredMedia(storage_ref=str(target), sha256=digest, size_bytes=len(content))


class SupabaseMediaStorage:
    """Armazena anexos em bucket privado do Supabase Storage usando chave server-side."""

    def __init__(
        self,
        *,
        supabase_url: str | None = None,
        service_role_key: str | None = None,
        bucket: str | None = None,
        max_bytes: int | None = None,
        timeout: float = 30.0,
    ):
        self.supabase_url = (supabase_url or os.getenv("SUPABASE_URL", "")).rstrip("/")
        self.service_role_key = service_role_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self.bucket = bucket or os.getenv("CAMPOEDADOS_SUPABASE_STORAGE_BUCKET", "campoedados-staging-media")
        self.max_bytes = max_bytes or int(os.getenv("CAMPOEDADOS_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
        self.timeout = timeout
        if not self.supabase_url or not self.service_role_key or not self.bucket:
            raise MediaStorageConfigurationError(
                "Supabase Storage requer SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY e CAMPOEDADOS_SUPABASE_STORAGE_BUCKET."
            )

    def store(self, *, content: bytes, filename: str | None, mime_type: str | None) -> StoredMedia:
        digest = _validate_content(content, self.max_bytes)
        safe_name = f"{digest}{_safe_suffix(filename)}"
        object_path = f"sha256/{digest[:2]}/{digest[2:4]}/{safe_name}"
        endpoint = f"{self.supabase_url}/storage/v1/object/{self.bucket}/{object_path}"
        headers = {
            "Authorization": f"Bearer {self.service_role_key}",
            "apikey": self.service_role_key,
            "Content-Type": mime_type or "application/octet-stream",
            # O nome é content-addressed; upsert evita falha quando o mesmo anexo for reenviado.
            "x-upsert": "true",
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(endpoint, headers=headers, content=content)
        if response.status_code not in {200, 201}:
            raise RuntimeError(
                f"Falha ao gravar arquivo no Supabase Storage: HTTP {response.status_code}."
            )
        return StoredMedia(
            storage_ref=f"supabase://{self.bucket}/{object_path}",
            sha256=digest,
            size_bytes=len(content),
        )


def media_storage_backend() -> str:
    return os.getenv("CAMPOEDADOS_MEDIA_STORAGE", "filesystem").strip().lower()


def media_storage_is_configured() -> bool:
    backend = media_storage_backend()
    if backend == "filesystem":
        return True
    if backend == "supabase":
        return bool(
            os.getenv("SUPABASE_URL")
            and os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            and os.getenv("CAMPOEDADOS_SUPABASE_STORAGE_BUCKET")
        )
    return False


def get_media_storage() -> MediaStorage:
    backend = media_storage_backend()
    if backend == "filesystem":
        return FileSystemMediaStorage()
    if backend == "supabase":
        return SupabaseMediaStorage()
    raise MediaStorageConfigurationError(f"Backend de mídia desconhecido: {backend}")
