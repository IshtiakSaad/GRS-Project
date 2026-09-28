"""The audit hash chain: tamper evidence for the audit log.

Every minute one job takes the unsealed rows, gives each the next sequence number and
row_hash = SHA-256(prev_hash + canonical content). Changing, inserting or deleting any sealed
row breaks every hash after it. Each batch also leaves an anchor (the last hash), and the
anchor is copied to object storage; in production that bucket is write-once (Object Lock) on
another host, so rewriting the whole chain would also mean rewriting copies nobody can change.

The database trigger already refuses changes to sealed rows by the application's roles; the
chain is what catches someone who can bypass the trigger (a DBA, a restored backup).
"""

import hashlib
import json
from dataclasses import dataclass

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.db import connection, transaction
from django.db.models.functions import Now

from .models import GENESIS_HASH, AuditAnchor, AuditLog

BATCH = 1000
LOCK_KEY = 7_201_001  # pg advisory lock: one sealer at a time, the chain has one tail


def content(row: AuditLog) -> bytes:
    """Everything a row says, in a fixed form. Seal columns other than seal_seq are excluded."""
    return json.dumps(
        {
            "seq": row.seal_seq,
            "id": row.id,
            "created_at": row.created_at.isoformat(),
            "actor": row.actor_id,
            "actor_role": row.actor_role,
            "action": row.action,
            "target": [row.target_type, row.target_id],
            "request": row.request_id,
            "data": row.data,
            "ip": row.ip,
            "request_uid": row.request_uid,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode()


def row_hash(prev_hash: str, row: AuditLog) -> str:
    return hashlib.sha256(prev_hash.encode() + content(row)).hexdigest()


def _tail() -> tuple[int, str]:
    last = (
        AuditLog.objects.filter(seal_seq__isnull=False)
        .order_by("-seal_seq")
        .values_list("seal_seq", "row_hash")
        .first()
    )
    return last or (0, GENESIS_HASH)


def seal(batch: int = BATCH) -> int:
    """Seal up to `batch` rows in insertion order. Returns how many were sealed."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [LOCK_KEY])
            if not cursor.fetchone()[0]:
                return 0  # another sealer is running
        seq, prev = _tail()
        rows = list(AuditLog.objects.filter(sealed_at__isnull=True).order_by("id")[:batch])
        if not rows:
            return 0
        first = seq + 1
        for row in rows:
            seq += 1
            row.seal_seq = seq
            row.prev_hash = prev
            row.row_hash = prev = row_hash(prev, row)
            AuditLog.objects.filter(pk=row.pk, created_at=row.created_at).update(
                seal_seq=seq, prev_hash=row.prev_hash, row_hash=row.row_hash, sealed_at=Now()
            )
        AuditAnchor.objects.create(
            first_seal_seq=first,
            last_seal_seq=seq,
            last_row_hash=prev,
            object_key=f"anchors/{seq:012d}.json",
        )
    return len(rows)


def store_anchors() -> int:
    """Copy anchors not yet stored outside the database. A store outage leaves them pending;
    the next run tries again."""
    from apps.collab.storage import internal

    client = internal()
    bucket = settings.S3_AUDIT_BUCKET
    stored = 0
    for anchor in AuditAnchor.objects.filter(stored_at__isnull=True).order_by("last_seal_seq"):
        body = json.dumps(
            {
                "first_seal_seq": anchor.first_seal_seq,
                "last_seal_seq": anchor.last_seal_seq,
                "last_row_hash": anchor.last_row_hash,
                "created_at": anchor.created_at.isoformat(),
            }
        ).encode()
        try:
            try:
                reply = client.put_object(Bucket=bucket, Key=anchor.object_key, Body=body)
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") != "NoSuchBucket":
                    raise
                client.create_bucket(Bucket=bucket)
                reply = client.put_object(Bucket=bucket, Key=anchor.object_key, Body=body)
        except (BotoCoreError, ClientError):
            break
        AuditAnchor.objects.filter(pk=anchor.pk).update(
            object_version=reply.get("VersionId"), stored_at=Now()
        )
        stored += 1
    return stored


@dataclass
class Verdict:
    ok: bool
    checked: int
    broken_at: int | None = None  # the first seal_seq that does not match
    reason: str = ""


def verify() -> Verdict:
    """Walk the whole chain and check every anchor against it."""
    prev, expected, checked = GENESIS_HASH, 1, 0
    hashes: dict[int, str] = {}
    anchors = dict(AuditAnchor.objects.values_list("last_seal_seq", "last_row_hash"))
    rows = AuditLog.objects.filter(seal_seq__isnull=False).order_by("seal_seq")
    for row in rows.iterator(chunk_size=2000):
        if row.seal_seq != expected:
            return Verdict(False, checked, expected, "a sealed row is missing")
        if row.prev_hash != prev or row_hash(prev, row) != row.row_hash:
            return Verdict(False, checked, row.seal_seq, "the row does not match its hash")
        if row.seal_seq in anchors:
            hashes[row.seal_seq] = row.row_hash
        prev, expected, checked = row.row_hash, expected + 1, checked + 1
    for seq, anchored in anchors.items():
        if hashes.get(seq) != anchored:
            return Verdict(False, checked, seq, "the chain differs from its anchor")
    return Verdict(True, checked)
