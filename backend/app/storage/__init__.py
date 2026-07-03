"""Хранилище pipeline-данных."""

from __future__ import annotations

from app.config import settings
from app.storage.s3 import S3Storage

_storage: S3Storage | None = None


def get_storage() -> S3Storage:
    global _storage
    if _storage is None:
        _storage = S3Storage(settings)
    return _storage


__all__ = ["S3Storage", "get_storage"]
