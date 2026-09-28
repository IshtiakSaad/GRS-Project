"""Idempotency-Key with Stripe semantics (design §9.4).

- New key: run the operation and store its response, in the same transaction.
- Same key, same body: return the stored response; nothing runs twice.
- Same key, different body: 422. The client has a bug; guessing which body it meant is worse.
- Same key while the first call is still running: the unique index makes the second call wait
  for the first to commit, then it gets the stored response.

Only successes are stored. A failed call rolls back its record with everything else, so a
retry after an error (a duplicate prompt, a rule refusal) is judged afresh.
"""

import hashlib
import json
import re
from collections.abc import Callable
from datetime import timedelta

from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.db.models.functions import Now
from django.utils.translation import gettext as _

from .errors import AppError
from .models import IdempotencyRecord

TTL = timedelta(hours=24)
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

Result = tuple[int, dict]


def read_key(http_request) -> str:
    key = http_request.headers.get("Idempotency-Key", "")
    if not KEY_RE.match(key):
        raise AppError(
            "IDEMPOTENCY_KEY_REQUIRED",
            _("Send an Idempotency-Key header of 8 to 64 letters, digits, - or _."),
            400,
        )
    return key


def fingerprint(method: str, path: str, body) -> str:
    canonical = json.dumps(
        [method, path, body], sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def once(user, key: str, fp: str, operation: Callable[[], Result]) -> tuple[int, dict, bool]:
    """(status, body, replayed)."""
    with transaction.atomic():
        IdempotencyRecord.objects.filter(
            user=user, key=key, created_at__lt=Now() - TTL
        ).delete()  # an expired key is a new key
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO idempotency_record (user_id, key, fingerprint) VALUES (%s, %s, %s) "
                "ON CONFLICT (user_id, key) DO NOTHING RETURNING id",
                [user.pk, key, fp],
            )
            row = cursor.fetchone()

        if row is None:
            record = IdempotencyRecord.objects.get(user=user, key=key)
            if record.fingerprint != fp:
                raise AppError(
                    "IDEMPOTENCY_KEY_REUSED",
                    _("This Idempotency-Key was already used for a different request."),
                    422,
                )
            return record.response_status, record.response_body, True

        status, body = operation()
        stored = json.loads(json.dumps(body, cls=DjangoJSONEncoder))
        IdempotencyRecord.objects.filter(pk=row[0]).update(
            response_status=status, response_body=stored
        )
        return status, stored, False
