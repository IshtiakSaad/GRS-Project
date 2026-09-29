"""The off-host store: a versioned, write-once (Object Lock) bucket on another system, holding
the audit chain's checkpoints (and, from PostgreSQL, the WAL archive and base backups).

The server can add objects but not destroy them: its credentials allow no deletion of object
versions and no change to a lock, and a locked version cannot be deleted by anyone before its
date (COMPLIANCE) or without a separate bypass permission (GOVERNANCE). So an attacker with
root on the server, who can rewrite the database, still cannot rewrite what was copied here.

In production the bucket is on AWS S3 and credentials come from the instance's role (nothing is
stored); locally it is a bucket on the SeaweedFS container, which supports the same locks.
"""

from datetime import timedelta
from functools import cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings
from django.utils import timezone


@cache
def client():
    return boto3.client(
        "s3",
        endpoint_url=settings.OFFSITE_S3_ENDPOINT or None,  # None: AWS itself
        region_name=settings.OFFSITE_S3_REGION,
        # Empty: the default chain (the EC2 instance role), so no key is kept on the server.
        aws_access_key_id=settings.OFFSITE_S3_ACCESS_KEY or None,
        aws_secret_access_key=settings.OFFSITE_S3_SECRET_KEY or None,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if settings.OFFSITE_S3_ENDPOINT else "virtual"},
            connect_timeout=3,
            read_timeout=10,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def put_locked(key: str, body: bytes) -> str | None:
    """Store `body` under `key`, locked for OFFSITE_LOCK_DAYS. Returns the version id."""
    params = {"Bucket": settings.OFFSITE_S3_BUCKET, "Key": key, "Body": body}
    if settings.OFFSITE_LOCK_MODE:
        params["ObjectLockMode"] = settings.OFFSITE_LOCK_MODE
        params["ObjectLockRetainUntilDate"] = timezone.now() + timedelta(
            days=settings.OFFSITE_LOCK_DAYS
        )
    return client().put_object(**params).get("VersionId")


def versions(prefix: str):
    """Every version of every object under `prefix`, as (key, version id). A key written twice
    has two versions; both are returned, since an overwrite is exactly what tampering looks like.
    """
    paginator = client().get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=settings.OFFSITE_S3_BUCKET, Prefix=prefix):
        for version in page.get("Versions", []):
            yield version["Key"], version["VersionId"]


def read(key: str, version: str) -> bytes:
    reply = client().get_object(Bucket=settings.OFFSITE_S3_BUCKET, Key=key, VersionId=version)
    return reply["Body"].read()


def ensure_bucket() -> str:
    """Create the bucket, versioned and lockable, if it is missing (local only: in production it
    is created by hand and the server may not create buckets). Returns what was done."""
    bucket = settings.OFFSITE_S3_BUCKET
    try:
        client().head_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket", "NotFound"):
            raise
        client().create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
        return "created"
    lock = client().get_object_lock_configuration(Bucket=bucket)["ObjectLockConfiguration"]
    if lock.get("ObjectLockEnabled") != "Enabled":
        raise RuntimeError(f"bucket {bucket} exists without Object Lock; anchors would be mutable")
    return "exists"
