"""The single way to write an audit row."""

import ipaddress

from apps.common.request_id import get_request_id

from .models import AuditLog


def client_ip(http_request) -> str | None:
    """The caller's address as Nginx saw it. The API is reachable only through Nginx, which
    overwrites X-Real-IP, so a client cannot choose this value."""
    if http_request is None:
        return None
    raw = http_request.META.get("HTTP_X_REAL_IP") or http_request.META.get("REMOTE_ADDR")
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def record(
    action: str,
    *,
    actor=None,
    target=None,
    request=None,
    data: dict | None = None,
    http_request=None,
) -> AuditLog:
    """Call inside the transaction that makes the change, so the change and its record commit
    or roll back together."""
    return AuditLog.objects.create(
        actor=actor,
        actor_role=getattr(actor, "role", None),
        action=action,
        target_type=target._meta.model_name if target is not None else "",
        target_id=target.pk if target is not None else None,
        request=request,
        data=data or {},
        ip=client_ip(http_request),
        request_uid=get_request_id(),
    )
