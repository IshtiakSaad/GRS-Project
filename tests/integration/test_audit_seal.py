import json

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from django.conf import settings
from django.core.management import CommandError, call_command
from django.db import connection

from apps.audit import offsite, sealing
from apps.audit import services as audit
from apps.audit.models import GENESIS_HASH, AuditAnchor, AuditLog

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _offsite_bucket():
    offsite.ensure_bucket()


def _log(n=3):
    for i in range(n):
        audit.record("test.action", data={"i": i, "text": "আবেদন"})


def _tamper(sql, params=()):
    """What someone who can bypass the trigger (the table owner, a DBA) could do."""
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE audit_log DISABLE TRIGGER audit_log_guard")
        cursor.execute(sql, params)
        cursor.execute("ALTER TABLE audit_log ENABLE TRIGGER audit_log_guard")


def test_rows_are_chained_in_order():
    _log(3)
    assert sealing.seal() == 3
    rows = list(AuditLog.objects.order_by("seal_seq"))
    assert [r.seal_seq for r in rows] == [1, 2, 3]
    assert rows[0].prev_hash == GENESIS_HASH
    assert rows[1].prev_hash == rows[0].row_hash and rows[2].prev_hash == rows[1].row_hash
    anchor = AuditAnchor.objects.get()
    assert (anchor.first_seal_seq, anchor.last_seal_seq) == (1, 3)
    assert anchor.last_row_hash == rows[2].row_hash
    assert sealing.verify().ok


def test_the_next_batch_continues_the_chain():
    _log(2)
    sealing.seal()
    _log(2)
    assert sealing.seal() == 2
    assert sealing.seal() == 0  # nothing left, no empty anchor
    assert AuditAnchor.objects.count() == 2
    verdict = sealing.verify()
    assert (verdict.ok, verdict.checked) == (True, 4)


def test_batches_are_bounded():
    _log(5)
    assert sealing.seal(batch=2) == 2
    assert AuditLog.objects.filter(sealed_at__isnull=True).count() == 3


def test_a_changed_row_is_detected():
    _log(3)
    sealing.seal()
    _tamper("UPDATE audit_log SET data = '{\"i\": 99}' WHERE seal_seq = 2")
    verdict = sealing.verify()
    assert (verdict.ok, verdict.broken_at, verdict.checked) == (False, 2, 1)


def test_a_deleted_row_is_detected():
    _log(3)
    sealing.seal()
    _tamper("DELETE FROM audit_log WHERE seal_seq = 2")
    verdict = sealing.verify()
    assert (verdict.ok, verdict.broken_at, verdict.reason) == (False, 2, "a sealed row is missing")


def test_a_rewritten_chain_still_differs_from_its_anchor():
    """Re-hashing every row after an edit makes the chain consistent again, but not the anchor."""
    _log(2)
    sealing.seal()
    _tamper("UPDATE audit_log SET data = '{\"i\": 99}' WHERE seal_seq = 2")
    row = AuditLog.objects.get(seal_seq=2)
    _tamper(
        "UPDATE audit_log SET row_hash = %s WHERE seal_seq = 2",
        [sealing.row_hash(row.prev_hash, row)],
    )
    verdict = sealing.verify()
    assert (verdict.ok, verdict.reason) == (False, "the chain differs from its anchor")


def test_the_trigger_still_refuses_changes_to_sealed_rows():
    _log(1)
    sealing.seal()
    with pytest.raises(Exception, match="sealed and immutable"):
        AuditLog.objects.update(action="changed")


def test_only_one_sealer_runs_at_a_time(as_worker):
    """The chain has one tail: a second sealer backs off instead of forking it."""
    _log(1)
    as_worker.execute("SELECT pg_advisory_lock(%s)", [sealing.LOCK_KEY])  # another sealer
    try:
        assert sealing.seal() == 0
    finally:
        as_worker.execute("SELECT pg_advisory_unlock(%s)", [sealing.LOCK_KEY])
    assert sealing.seal() == 1


def test_anchors_are_copied_off_the_host_and_locked():
    _log(2)
    sealing.seal()
    assert sealing.store_anchors() == 1
    anchor = AuditAnchor.objects.get()
    assert anchor.stored_at is not None
    assert anchor.object_key.startswith(f"anchors/{sealing.chain_id()}/")
    stored = json.loads(offsite.read(anchor.object_key, anchor.object_version))
    assert stored["last_row_hash"] == anchor.last_row_hash
    assert sealing.store_anchors() == 0
    # Locked: the server's own credentials cannot delete the copy.
    with pytest.raises(ClientError):
        offsite.client().delete_object(
            Bucket=settings.OFFSITE_S3_BUCKET,
            Key=anchor.object_key,
            VersionId=anchor.object_version,
        )


def test_a_store_outage_leaves_anchors_pending(monkeypatch):
    def down(key, body):
        raise EndpointConnectionError(endpoint_url="http://storage:8333")

    monkeypatch.setattr(offsite, "put_locked", down)
    _log(1)
    sealing.seal()
    assert sealing.store_anchors() == 0
    assert AuditAnchor.objects.get().stored_at is None


def _rewrite_row_2_and_its_anchor():
    """Root on the server: edit a sealed row, re-hash it, and fix the database's anchor to match.
    Everything inside the database is consistent again."""
    _tamper("UPDATE audit_log SET data = '{\"i\": 99}' WHERE seal_seq = 2")
    row = AuditLog.objects.get(seal_seq=2)
    new_hash = sealing.row_hash(row.prev_hash, row)
    _tamper("UPDATE audit_log SET row_hash = %s WHERE seal_seq = 2", [new_hash])
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE audit_anchor DISABLE TRIGGER USER")
        cursor.execute("UPDATE audit_anchor SET last_row_hash = %s", [new_hash])
        cursor.execute("ALTER TABLE audit_anchor ENABLE TRIGGER USER")


def test_rewriting_the_database_and_its_anchors_is_caught_off_the_host():
    _log(2)
    sealing.seal()
    sealing.store_anchors()
    _rewrite_row_2_and_its_anchor()
    assert sealing.verify(offsite_check=False).ok  # the database alone is fooled
    verdict = sealing.verify()
    assert (verdict.ok, verdict.broken_at) == (False, 2)
    assert verdict.reason == "the chain differs from its anchor"


def test_overwriting_the_off_host_copy_is_caught():
    """A new version can be written, but the locked old one stays and still disagrees."""
    _log(2)
    sealing.seal()
    sealing.store_anchors()
    anchor = AuditAnchor.objects.get()
    _rewrite_row_2_and_its_anchor()
    forged = {"last_seal_seq": 2, "last_row_hash": AuditLog.objects.get(seal_seq=2).row_hash}
    offsite.put_locked(anchor.object_key, json.dumps(forged).encode())
    assert not sealing.verify().ok


def test_cutting_off_the_end_of_the_chain_is_caught():
    _log(2)
    sealing.seal()
    _log(2)
    sealing.seal()
    sealing.store_anchors()
    _tamper("DELETE FROM audit_log WHERE seal_seq > 2")
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE audit_anchor DISABLE TRIGGER USER")
        cursor.execute("DELETE FROM audit_anchor WHERE last_seal_seq > 2")
        cursor.execute("ALTER TABLE audit_anchor ENABLE TRIGGER USER")
    assert sealing.verify(offsite_check=False).ok
    verdict = sealing.verify()
    assert (verdict.ok, verdict.reason) == (False, "the chain ends before its anchors do")
    # A restored backup legitimately ends before the newest anchors.
    assert sealing.verify(allow_newer=True).ok


def test_anchors_missing_off_the_host_are_caught(settings):
    """Pointed at the wrong bucket, verification must not pass on an empty folder."""
    _log(1)
    sealing.seal()
    sealing.store_anchors()
    settings.OFFSITE_S3_BUCKET = "offsite-elsewhere"
    offsite.client.cache_clear()
    offsite.ensure_bucket()
    verdict = sealing.verify()
    assert (verdict.ok, verdict.reason) == (
        False,
        "an anchor recorded as copied is not off the host",
    )


def test_the_off_host_store_being_down_is_an_error_not_a_pass(monkeypatch):
    _log(1)
    sealing.seal()

    def down(prefix):
        raise EndpointConnectionError(endpoint_url="http://storage:8333")

    monkeypatch.setattr(offsite, "versions", down)
    with pytest.raises(CommandError, match="could not read the off-host anchors"):
        call_command("verify_audit")


def test_the_task_seals_and_stores():
    from apps.audit.tasks import seal_audit_log

    _log(2)
    assert seal_audit_log() == {"sealed": 2, "anchors_stored": 1}


def test_the_verify_command(capsys):
    _log(2)
    sealing.seal()
    sealing.store_anchors()
    call_command("verify_audit")
    assert "intact: 2 rows, checked against its off-host anchors" in capsys.readouterr().out
    _tamper("UPDATE audit_log SET action = 'x' WHERE seal_seq = 1")
    with pytest.raises(CommandError, match="broken at seal_seq 1"):
        call_command("verify_audit")
