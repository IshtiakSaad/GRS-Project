"""The audit hash chain: tamper evidence for the audit log.

Every minute one job takes the unsealed rows, gives each the next sequence number and
row_hash = SHA-256(prev_hash + canonical content). Changing, inserting or deleting any sealed
row breaks every hash after it. Each batch also leaves an anchor (the last hash), and the
anchor is copied to the off-host store (`offsite.py`): a write-once bucket on another system,
so rewriting the chain would also mean rewriting locked copies nobody can change.

The database trigger already refuses changes to sealed rows by the application's roles; the
chain is what catches someone who can bypass the trigger (a DBA, root on the server, a doctored
backup). `verify()` checks the chain against the off-host copies, not only against the
database's own anchor table, which that person could rewrite too.

Anchors are stored under the chain's id (the first row's hash), so a database rebuilt from
scratch (the demo's nightly reset) starts a new folder instead of colliding with the old one.
"""

import hashlib
import json
from dataclasses import dataclass

from botocore.exceptions import BotoCoreError, ClientError
from django.db import connection, transaction
from django.db.models.functions import Now

from . import offsite
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


def chain_id() -> str | None:
    """Names this chain: the start of its first row's hash. None before anything is sealed."""
    first = AuditLog.objects.filter(seal_seq=1).values_list("row_hash", flat=True).first()
    return first[:16] if first else None


def anchor_prefix(chain: str) -> str:
    return f"anchors/{chain}/"


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
        chain = rows[0].row_hash[:16] if first == 1 else chain_id()
        AuditAnchor.objects.create(
            first_seal_seq=first,
            last_seal_seq=seq,
            last_row_hash=prev,
            object_key=f"{anchor_prefix(chain)}{seq:012d}.json",
        )
    return len(rows)


def store_anchors() -> int:
    """Copy anchors not yet stored off the host, locked. A store outage leaves them pending
    (the monitor alerts after 10 minutes); the next run tries again."""
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
            version = offsite.put_locked(anchor.object_key, body)
        except (BotoCoreError, ClientError):
            break
        AuditAnchor.objects.filter(pk=anchor.pk).update(object_version=version, stored_at=Now())
        stored += 1
    return stored


@dataclass
class Verdict:
    ok: bool
    checked: int
    broken_at: int | None = None  # the first seal_seq that does not match
    reason: str = ""


class OffsiteUnavailable(Exception):
    pass


def _offsite_anchors(chain: str) -> dict[int, set[str]]:
    """Every hash the off-host store holds for this chain, by sequence number, from every
    version of every object (an overwritten anchor shows up as a second, different hash)."""
    found: dict[int, set[str]] = {}
    try:
        for key, version in offsite.versions(anchor_prefix(chain)):
            body = json.loads(offsite.read(key, version))
            found.setdefault(int(body["last_seal_seq"]), set()).add(body["last_row_hash"])
    except (BotoCoreError, ClientError) as exc:
        raise OffsiteUnavailable(str(exc)) from exc
    return found


def verify(offsite_check: bool = True, allow_newer: bool = False) -> Verdict:
    """Walk the whole chain and check it against every anchor: the database's own and, unless
    `offsite_check` is off, the locked copies off the host. `allow_newer` accepts off-host
    anchors past the end of the chain, for checking a restored backup that is older than them.
    Raises OffsiteUnavailable if the off-host store cannot be read."""
    anchors: dict[int, set[str]] = {}
    for seq, hash_ in AuditAnchor.objects.values_list("last_seal_seq", "last_row_hash"):
        anchors.setdefault(seq, set()).add(hash_)
    chain = chain_id()
    if offsite_check and chain:
        remote = _offsite_anchors(chain)
        # Recorded as copied but not there: the wrong bucket, or copies that were never made.
        copied = AuditAnchor.objects.filter(
            stored_at__isnull=False, object_key__startswith=anchor_prefix(chain)
        ).values_list("last_seal_seq", flat=True)
        missing = sorted(set(copied) - set(remote))
        if missing:
            return Verdict(False, 0, missing[0], "an anchor recorded as copied is not off the host")
        for seq, hashes in remote.items():
            anchors.setdefault(seq, set()).update(hashes)

    prev, expected, checked = GENESIS_HASH, 1, 0
    rows = AuditLog.objects.filter(seal_seq__isnull=False).order_by("seal_seq")
    for row in rows.iterator(chunk_size=2000):
        if row.seal_seq != expected:
            return Verdict(False, checked, expected, "a sealed row is missing")
        if row.prev_hash != prev or row_hash(prev, row) != row.row_hash:
            return Verdict(False, checked, row.seal_seq, "the row does not match its hash")
        if row.seal_seq in anchors and anchors.pop(row.seal_seq) != {row.row_hash}:
            return Verdict(False, checked, row.seal_seq, "the chain differs from its anchor")
        prev, expected, checked = row.row_hash, expected + 1, checked + 1
    if anchors and not allow_newer:
        first = min(anchors)
        return Verdict(False, checked, first, "the chain ends before its anchors do")
    return Verdict(True, checked)
