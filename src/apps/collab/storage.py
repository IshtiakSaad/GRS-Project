"""The object store, spoken to only through the S3 API, so the server stays replaceable.

Signing a URL is local computation: creating an upload or download link works even while the
store is down (design N4). Only the verifier and cleanup talk to the store itself.
"""

from datetime import timedelta
from functools import cache
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings

UPLOAD_TTL = timedelta(minutes=15)  # time to start the upload; 3G may need a while
DOWNLOAD_TTL = timedelta(minutes=5)
CHUNK = 64 * 1024


@cache
def _client(endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=2,
            read_timeout=10,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def internal():
    return _client(settings.S3_ENDPOINT)


def public():
    return _client(settings.S3_PUBLIC_ENDPOINT)


def upload_url(key: str, content_type: str, size: int) -> str:
    """A PUT URL bound to one key, one content type and one exact size: the store refuses a
    body of any other length (the header is part of the signature)."""
    return public().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.S3_BUCKET,
            "Key": key,
            "ContentType": content_type,
            "ContentLength": size,
        },
        ExpiresIn=int(UPLOAD_TTL.total_seconds()),
    )


def download_url(key: str, filename: str, content_type: str) -> str:
    # Always a download, never rendered inline by the browser: an uploaded file must not be
    # able to run as a page on any of our origins.
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    return public().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.S3_BUCKET,
            "Key": key,
            "ResponseContentDisposition": disposition,
            "ResponseContentType": content_type,
        },
        ExpiresIn=int(DOWNLOAD_TTL.total_seconds()),
    )


def size_of(key: str) -> int | None:
    """The stored object's size, or None if nothing was uploaded."""
    try:
        head = internal().head_object(Bucket=settings.S3_BUCKET, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    return head["ContentLength"]


def chunks(key: str):
    body = internal().get_object(Bucket=settings.S3_BUCKET, Key=key)["Body"]
    try:
        yield from body.iter_chunks(CHUNK)
    finally:
        body.close()


def delete(key: str) -> None:
    internal().delete_object(Bucket=settings.S3_BUCKET, Key=key)
