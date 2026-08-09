from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredMedia:
    storage_ref: str
    sha256: str
    size_bytes: int


class MediaTooLargeError(ValueError):
    pass


class UnsupportedMediaTypeError(ValueError):
    pass


class FileSystemMediaStorage:
    def __init__(self, base_dir: str | Path | None = None, max_bytes: int | None = None):
        self.base_dir = Path(base_dir or os.getenv("CAMPOEDADOS_UPLOAD_DIR", "var/data/uploads"))
        self.max_bytes = max_bytes or int(os.getenv("CAMPOEDADOS_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))

    def store(self, *, content: bytes, filename: str | None, mime_type: str | None) -> StoredMedia:
        if not content:
            raise ValueError("Arquivo vazio.")
        if len(content) > self.max_bytes:
            raise MediaTooLargeError(f"Arquivo excede o limite de {self.max_bytes} bytes.")

        digest = hashlib.sha256(content).hexdigest()
        suffix = Path(filename or "upload.bin").suffix.lower()[:12]
        safe_name = f"{digest}{suffix}"
        target = self.base_dir / digest[:2] / digest[2:4] / safe_name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temp = target.with_suffix(target.suffix + ".tmp")
            temp.write_bytes(content)
            temp.replace(target)

        return StoredMedia(
            storage_ref=str(target),
            sha256=digest,
            size_bytes=len(content),
        )


def get_media_storage() -> FileSystemMediaStorage:
    return FileSystemMediaStorage()
