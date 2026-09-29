"""Who among staff looked at which request.

- Opening, changing or downloading from a request: one event each.
- A list page: one LIST event naming every request it showed, so bulk browsing is visible to
  auditors even when each row was allowed.
- Citizens reading their own requests are not logged: the tracker watches staff.

The write happens in the request that did the looking. If it fails, that request fails: an
unrecorded look is exactly what this exists to prevent.
"""

from django.db import connection

from apps.accounts.models import Role
from apps.common.request_id import get_request_id

from .models import AccessEvent, AccessKind

STAFF = (Role.OFFICER, Role.ADMIN)


def _is_staff(user) -> bool:
    return getattr(user, "role", None) in STAFF


def record(user, request, kind: str = AccessKind.VIEW, *, reason=None, note=None) -> None:
    if not _is_staff(user):
        return
    AccessEvent.objects.create(
        actor=user,
        actor_role=user.role,
        actor_department_id=user.department_id,
        kind=kind,
        request=request,
        break_glass_reason=reason,
        break_glass_note=note,
        request_uid=get_request_id(),
    )


def record_list(user, request_ids: list[int]) -> None:
    """One event and one item per request shown, in a single statement: the items carry the
    event's own timestamp, so they land in the same partition."""
    if not _is_staff(user) or not request_ids:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH e AS (
                INSERT INTO access_event
                    (actor_id, actor_role, actor_department_id, kind, item_count, request_uid)
                VALUES (%s, %s, %s, 'LIST', %s, %s)
                RETURNING id, created_at
            )
            INSERT INTO access_event_item (event_id, request_id, created_at)
            SELECT e.id, r, e.created_at FROM e, unnest(%s::bigint[]) AS r
            """,
            [
                user.pk,
                user.role,
                user.department_id,
                len(request_ids),
                get_request_id(),
                list(request_ids),
            ],
        )
