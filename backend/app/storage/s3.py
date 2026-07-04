"""S3-совместимое хранилище (Yandex Object Storage) для pipeline-данных."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any, TypeVar

from botocore.config import Config
from botocore.exceptions import ClientError
from pydantic import BaseModel

from app.config import Settings

logger = logging.getLogger(__name__)

_s3_warned = False

T = TypeVar("T", bound=BaseModel)

DATA_PREFIXES = ("raw/", "parsed/", "extracted/", "artifacts/")
DATA_SUBDIRS = ("raw", "parsed", "extracted", "artifacts")


class S3ObjectInfo(BaseModel):
    """Метаданные объекта S3 из list_objects_v2."""

    key: str
    etag: str
    size: int


def _warn_once(message: str, *args: object) -> None:
    global _s3_warned
    if not _s3_warned:
        logger.warning(message, *args)
        _s3_warned = True


class S3Storage:
    """Клиент S3 с graceful degradation при отсутствии кредов или недоступности бакета."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any = None
        self._available = False

        if not settings.s3_configured:
            _warn_once("S3 not configured — pipeline will use local data/ only")
            return

        import boto3

        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            config=Config(
                retries={"max_attempts": 3, "mode": "adaptive"},
                connect_timeout=10,
                read_timeout=60,
            ),
        )

        try:
            self._client.head_bucket(Bucket=settings.s3_bucket)
            self._available = True
            logger.info("S3 storage available: bucket=%s", settings.s3_bucket)
        except ClientError:
            _warn_once(
                "S3 bucket unavailable (%s) — pipeline will use local data/ only",
                settings.s3_bucket,
            )

    @property
    def available(self) -> bool:
        return self._available

    @property
    def bucket(self) -> str:
        return self._settings.s3_bucket

    def upload_file(self, local_path: Path, key: str) -> None:
        if not self._available or self._client is None:
            return
        logger.info("S3 upload: bucket=%s key=%s", self.bucket, key)
        self._client.upload_file(
            Filename=str(local_path),
            Bucket=self.bucket,
            Key=key,
        )

    def download_file(self, key: str, local_path: Path) -> None:
        if not self._available or self._client is None:
            return
        local_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("S3 download: bucket=%s key=%s", self.bucket, key)
        self._client.download_file(
            Bucket=self.bucket,
            Key=key,
            Filename=str(local_path),
        )

    def upload_jsonl(self, records: list[BaseModel], key: str) -> None:
        if not self._available or self._client is None:
            return
        body = "\n".join(record.model_dump_json() for record in records)
        if body:
            body += "\n"
        logger.info("S3 put_object: bucket=%s key=%s lines=%d", self.bucket, key, len(records))
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/x-ndjson",
        )

    def iter_jsonl(self, key: str, model: type[T]) -> Iterator[T]:
        if not self._available or self._client is None:
            return iter(())
        response = self._client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        for raw_line in body.iter_lines():
            line = raw_line.decode("utf-8").strip()
            if line:
                yield model.model_validate_json(line)

    def list_objects(self, prefix: str) -> list[S3ObjectInfo]:
        if not self._available or self._client is None:
            return []
        objects: list[S3ObjectInfo] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                objects.append(
                    S3ObjectInfo(
                        key=key,
                        etag=str(obj.get("ETag", "")).strip('"'),
                        size=int(obj.get("Size", 0)),
                    )
                )
        return objects

    def list_keys(self, prefix: str) -> list[str]:
        return [obj.key for obj in self.list_objects(prefix)]

    def exists(self, key: str) -> bool:
        if not self._available or self._client is None:
            return False
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def sync_prefix_down(self, prefix: str, local_dir: Path) -> int:
        if not self._available:
            return 0
        local_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for key in self.list_keys(prefix):
            relative = key[len(prefix) :] if key.startswith(prefix) else key
            if not relative:
                continue
            self.download_file(key, local_dir / relative)
            count += 1
        logger.info("S3 sync_prefix_down: prefix=%s local_dir=%s files=%d", prefix, local_dir, count)
        return count

    def sync_prefix_up(self, prefix: str, local_dir: Path) -> int:
        if not self._available or not local_dir.is_dir():
            return 0
        count = 0
        prefix_norm = prefix if prefix.endswith("/") else f"{prefix}/"
        for local_path in local_dir.rglob("*"):
            if not local_path.is_file():
                continue
            relative = local_path.relative_to(local_dir).as_posix()
            self.upload_file(local_path, f"{prefix_norm}{relative}")
            count += 1
        logger.info("S3 sync_prefix_up: prefix=%s local_dir=%s files=%d", prefix_norm, local_dir, count)
        return count

    def sync_embeddings_down(self, local_dir: Path) -> int:
        return self.sync_prefix_down("embeddings/", local_dir)

    def sync_embeddings_up(self, local_dir: Path) -> int:
        return self.sync_prefix_up("embeddings", local_dir)

    def push_data_dir(self, data_root: Path) -> int:
        if not self._available:
            return 0
        count = 0
        for subdir in DATA_SUBDIRS:
            local_subdir = data_root / subdir
            if not local_subdir.is_dir():
                continue
            for local_path in local_subdir.rglob("*"):
                if local_path.is_file():
                    relative = local_path.relative_to(local_subdir).as_posix()
                    key = f"{subdir}/{relative}"
                    self.upload_file(local_path, key)
                    count += 1
        logger.info("S3 push_data_dir: data_root=%s files=%d", data_root, count)
        return count

    def pull_data_dir(self, data_root: Path) -> int:
        if not self._available:
            return 0
        count = 0
        for prefix in DATA_PREFIXES:
            subdir = prefix.rstrip("/")
            count += self.sync_prefix_down(prefix, data_root / subdir)
        logger.info("S3 pull_data_dir: data_root=%s files=%d", data_root, count)
        return count
