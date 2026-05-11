"""S3/MinIO client + KB object persistence.

Gated by `enable_object_store` so test/dev environments without MinIO running
behave as before. Uses boto3's sync client off a thread to keep the request
event loop responsive on large uploads.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.client import Config

from app.core.config import get_settings
from app.core.logging import log

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client


@lru_cache
def get_s3_client() -> S3Client:
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _ensure_bucket_sync(client: S3Client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
        return
    except Exception:
        pass
    try:
        client.create_bucket(Bucket=bucket)
    except Exception as exc:
        log.warning("s3.create_bucket.err", bucket=bucket, err=str(exc))


def _put_sync(bucket: str, key: str, data: bytes, content_type: str) -> None:
    client = get_s3_client()
    _ensure_bucket_sync(client, bucket)
    client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)


async def put_object_bytes(
    *, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream"
) -> str | None:
    """Best-effort upload. Returns the key on success, None on failure.

    No-ops (returns None) if `enable_object_store` is false.
    """
    if not get_settings().enable_object_store:
        return None
    try:
        await asyncio.to_thread(_put_sync, bucket, key, data, content_type)
        return key
    except Exception as exc:
        log.warning("s3.put_object.err", bucket=bucket, key=key, err=str(exc))
        return None
