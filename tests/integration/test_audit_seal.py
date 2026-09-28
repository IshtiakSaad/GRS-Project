import pytest
from botocore.exceptions import EndpointConnectionError
from django.core.management import CommandError, call_command
from django.db import connection

from apps.audit import sealing
from apps.audit import services as audit
from apps.audit.models import GENESIS_HASH, AuditAnchor, AuditLog
from apps.collab import storage

pytestmark = pytest.mark.django_db


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


def test_anchors_are_copied_out_of_the_database():
    _log(2)
    sealing.seal()
    assert sealing.store_anchors() == 1
    anchor = AuditAnchor.objects.get()
    assert anchor.stored_at is not None
    stored = storage.internal().get_object(Bucket="audit-anchors", Key=anchor.object_key)
    assert anchor.last_row_hash in stored["Body"].read().decode()
    assert sealing.store_anchors() == 0


def test_a_store_outage_leaves_anchors_pending(monkeypatch):
    class Down:
        def put_object(self, **kwargs):
            raise EndpointConnectionError(endpoint_url="http://storage:8333")

    monkeypatch.setattr(storage, "internal", lambda: Down())
    _log(1)
    sealing.seal()
    assert sealing.store_anchors() == 0
    assert AuditAnchor.objects.get().stored_at is None


def test_the_task_seals_and_stores():
    from apps.audit.tasks import seal_audit_log

    _log(2)
    assert seal_audit_log() == {"sealed": 2, "anchors_stored": 1}


def test_the_verify_command(capsys):
    _log(2)
    sealing.seal()
    call_command("verify_audit")
    assert "intact: 2 rows" in capsys.readouterr().out
    _tamper("UPDATE audit_log SET action = 'x' WHERE seal_seq = 1")
    with pytest.raises(CommandError, match="broken at seal_seq 1"):
        call_command("verify_audit")
