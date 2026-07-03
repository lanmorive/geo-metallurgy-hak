"""Тесты S3Storage: degradation, mocked boto3, безопасность логов."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.schemas.ontology import ExtractionResult, ParsedChunk
from app.storage import s3 as s3_module
from app.storage.s3 import S3Storage


@pytest.fixture(autouse=True)
def reset_s3_warned() -> None:
    s3_module._s3_warned = False


def _empty_s3_settings() -> Settings:
    return Settings(
        s3_endpoint_url="",
        s3_region="ru-central1",
        s3_bucket="",
        s3_access_key_id="",
        s3_secret_access_key="",
    )


def _configured_s3_settings() -> Settings:
    return Settings(
        s3_endpoint_url="https://storage.yandexcloud.net",
        s3_region="ru-central1",
        s3_bucket="test-bucket",
        s3_access_key_id="test-key-id",
        s3_secret_access_key="super-secret-value",
    )


def test_unconfigured_storage_not_available() -> None:
    storage = S3Storage(_empty_s3_settings())
    assert storage.available is False

    storage.upload_file(Path("/tmp/x"), "raw/x.pdf")
    storage.download_file("raw/x.pdf", Path("/tmp/x"))
    storage.upload_jsonl([], "parsed/x.jsonl")
    assert list(storage.iter_jsonl("parsed/x.jsonl", ParsedChunk)) == []
    assert storage.list_keys("raw/") == []
    assert storage.exists("raw/x.pdf") is False
    assert storage.sync_prefix_down("raw/", Path("/tmp/raw")) == 0
    assert storage.push_data_dir(Path("/tmp/data")) == 0
    assert storage.pull_data_dir(Path("/tmp/data")) == 0


@patch("boto3.client")
def test_storage_available_when_bucket_reachable(mock_boto_client: MagicMock) -> None:
    client = MagicMock()
    mock_boto_client.return_value = client

    storage = S3Storage(_configured_s3_settings())
    assert storage.available is True
    client.head_bucket.assert_called_once_with(Bucket="test-bucket")
    mock_boto_client.assert_called_once()
    call_kwargs = mock_boto_client.call_args.kwargs
    assert call_kwargs["endpoint_url"] == "https://storage.yandexcloud.net"
    assert call_kwargs["region_name"] == "ru-central1"
    assert call_kwargs["aws_access_key_id"] == "test-key-id"
    assert call_kwargs["aws_secret_access_key"] == "super-secret-value"


@patch("boto3.client")
def test_storage_unavailable_when_bucket_unreachable(mock_boto_client: MagicMock) -> None:
    from botocore.exceptions import ClientError

    client = MagicMock()
    client.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "403", "Message": "Forbidden"}},
        "HeadBucket",
    )
    mock_boto_client.return_value = client

    storage = S3Storage(_configured_s3_settings())
    assert storage.available is False


@patch("boto3.client")
def test_upload_jsonl_mocked(mock_boto_client: MagicMock) -> None:
    client = MagicMock()
    mock_boto_client.return_value = client

    storage = S3Storage(_configured_s3_settings())
    records = [
        ParsedChunk(doc_id="doc1", source_path="raw/doc1.pdf", text="hello"),
    ]
    storage.upload_jsonl(records, "parsed/doc1.jsonl")

    client.put_object.assert_called_once()
    call_kwargs = client.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == "test-bucket"
    assert call_kwargs["Key"] == "parsed/doc1.jsonl"
    body = call_kwargs["Body"].decode("utf-8")
    assert '"doc_id":"doc1"' in body
    assert body.endswith("\n")


@patch("boto3.client")
def test_sync_prefix_down_mocked(mock_boto_client: MagicMock, tmp_path: Path) -> None:
    client = MagicMock()
    mock_boto_client.return_value = client

    paginator = MagicMock()
    client.get_paginator.return_value = paginator
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "extracted/a.jsonl"}, {"Key": "extracted/b.jsonl"}]},
    ]

    storage = S3Storage(_configured_s3_settings())
    count = storage.sync_prefix_down("extracted/", tmp_path)

    assert count == 2
    assert client.download_file.call_count == 2
    client.download_file.assert_any_call(
        Bucket="test-bucket",
        Key="extracted/a.jsonl",
        Filename=str(tmp_path / "a.jsonl"),
    )


@patch("boto3.client")
def test_iter_jsonl_mocked(mock_boto_client: MagicMock) -> None:
    client = MagicMock()
    mock_boto_client.return_value = client

    line = ParsedChunk(
        doc_id="doc1", source_path="raw/doc1.pdf", text="chunk text"
    ).model_dump_json()
    body = MagicMock()
    body.iter_lines.return_value = [line.encode("utf-8")]
    client.get_object.return_value = {"Body": body}

    storage = S3Storage(_configured_s3_settings())
    chunks = list(storage.iter_jsonl("parsed/doc1.jsonl", ParsedChunk))

    assert len(chunks) == 1
    assert chunks[0].doc_id == "doc1"
    assert chunks[0].text == "chunk text"


@patch("boto3.client")
def test_no_secrets_in_logs(
    mock_boto_client: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    client = MagicMock()
    mock_boto_client.return_value = client

    with caplog.at_level("INFO"):
        storage = S3Storage(_configured_s3_settings())
        storage.upload_jsonl(
            [ExtractionResult(doc_id="d1", entities=[], relations=[])],
            "extracted/d1.jsonl",
        )

    log_text = caplog.text
    assert "super-secret-value" not in log_text
    assert "test-key-id" not in log_text
    assert "test-bucket" in log_text
    assert "extracted/d1.jsonl" in log_text
