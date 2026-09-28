"""Statistics with counter-metrics (design §5.6).

Any number that is published becomes a target, and a target gets gamed. So each primary metric
comes with the numbers that would expose gaming it:

| Primary                 | Counter-metrics                                                   |
|-------------------------|-------------------------------------------------------------------|
| On-time resolution      | info-request rate, median paused time, rejection rate, late       |
|                         | rejections (last 20% of the SLA window)                           |
| Median time to resolve  | reopen rate after resolution, reopen rate after rejection         |
| Throughput per officer  | reassignment rate                                                 |
| Resolution rate         | withdrawn after the deadline passed                               |

Counts are over requests submitted in the period (Asia/Dhaka dates), grouped by department,
category or officer. One query; every aggregate runs over the same filtered set.
"""

from datetime import date, datetime, time, timedelta

from django.db import connection

from apps.sla.calendar import DHAKA

GROUPS = {
    # by: (group column, SQL for the group's code and name)
    "department": (
        "sr.department_id",
        "SELECT id, code, name_en FROM department",
    ),
    "category": (
        "sr.category_id",
        "SELECT id, code, name_en FROM category",
    ),
    "officer": (
        "sr.assigned_officer_id",
        "SELECT id, public_id::text AS code, full_name AS name_en FROM app_user",
    ),
}

_SQL = """
WITH base AS (
    SELECT sr.*, {group_col} AS gkey
    FROM service_request sr
    WHERE sr.status <> 'DRAFT' AND sr.submitted_at >= %(start)s AND sr.submitted_at < %(end)s
),
paused AS (
    SELECT p.request_id, SUM(COALESCE(p.ended_at, now()) - p.started_at) AS total
    FROM sla_pause p JOIN base b ON b.id = p.request_id
    GROUP BY p.request_id
),
events AS (
    SELECT e.request_id, e.event_type, e.from_status
    FROM request_event e JOIN base b ON b.id = e.request_id
    WHERE e.event_type IN ('resolve', 'reject', 'reopen')
),
late AS (
    SELECT DISTINCT a.request_id
    FROM audit_log a JOIN base b ON b.id = a.request_id
    WHERE a.action = 'request.reject' AND (a.data ->> 'late_rejection')::boolean
),
ev AS (
    SELECT b.gkey,
           count(*) FILTER (WHERE e.event_type = 'resolve') AS resolutions,
           count(*) FILTER (WHERE e.event_type = 'reject') AS rejections,
           count(*) FILTER (WHERE e.event_type = 'reopen' AND e.from_status = 'RESOLVED')
               AS reopened_after_resolution,
           count(*) FILTER (WHERE e.event_type = 'reopen' AND e.from_status = 'REJECTED')
               AS reopened_after_rejection
    FROM events e JOIN base b ON b.id = e.request_id
    GROUP BY b.gkey
)
SELECT b.gkey,
       count(*) AS submitted,
       count(*) FILTER (WHERE b.status = ANY(%(open)s)) AS open,
       count(*) FILTER (WHERE b.status = ANY(%(open)s) AND b.due_at < now()) AS overdue,
       count(*) FILTER (WHERE b.status = 'RESOLVED') AS resolved,
       count(*) FILTER (WHERE b.status = 'RESOLVED' AND b.resolved_at <= b.due_at)
           AS resolved_on_time,
       percentile_cont(0.5) WITHIN GROUP (
           ORDER BY extract(epoch FROM b.resolved_at - b.submitted_at)
       ) FILTER (WHERE b.status = 'RESOLVED') AS median_resolve_seconds,
       count(*) FILTER (WHERE b.status = 'REJECTED') AS rejected,
       count(late.request_id) AS late_rejections,
       count(*) FILTER (WHERE b.status = 'WITHDRAWN') AS withdrawn,
       count(*) FILTER (WHERE b.status = 'WITHDRAWN' AND b.closed_at > b.due_at)
           AS withdrawn_after_deadline,
       count(*) FILTER (WHERE b.info_request_count > 0) AS with_info_request,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM paused.total))
           FILTER (WHERE paused.total IS NOT NULL) AS median_paused_seconds,
       count(*) FILTER (WHERE b.reassignment_count > 0) AS reassigned,
       max(ev.resolutions) AS resolutions,
       max(ev.rejections) AS rejections,
       max(ev.reopened_after_resolution) AS reopened_after_resolution,
       max(ev.reopened_after_rejection) AS reopened_after_rejection
FROM base b
LEFT JOIN paused ON paused.request_id = b.id
LEFT JOIN late ON late.request_id = b.id
LEFT JOIN ev ON ev.gkey IS NOT DISTINCT FROM b.gkey
GROUP BY b.gkey
ORDER BY submitted DESC
"""

OPEN = ["SUBMITTED", "ASSIGNED", "IN_PROGRESS", "AWAITING_CITIZEN"]


# The totals row of a period with no requests: SQL returns no row at all for an empty GROUP BY.
_NOTHING = {
    **dict.fromkeys(
        [
            "submitted",
            "open",
            "overdue",
            "resolved",
            "resolved_on_time",
            "rejected",
            "late_rejections",
            "withdrawn",
            "withdrawn_after_deadline",
            "with_info_request",
            "reassigned",
        ],
        0,
    ),
    **dict.fromkeys(
        [
            "median_resolve_seconds",
            "median_paused_seconds",
            "resolutions",
            "rejections",
            "reopened_after_resolution",
            "reopened_after_rejection",
        ]
    ),
}


def _ratio(part, whole) -> float | None:
    return round(part / whole, 4) if whole else None


def _days(seconds) -> float | None:
    return round(seconds / 86400, 2) if seconds is not None else None


def _shape(row: dict) -> dict:
    resolutions = row["resolutions"] or 0
    rejections = row["rejections"] or 0
    return {
        "counts": {
            "submitted": row["submitted"],
            "open": row["open"],
            "overdue": row["overdue"],
            "resolved": row["resolved"],
            "rejected": row["rejected"],
            "withdrawn": row["withdrawn"],
        },
        "primary": {
            "on_time_resolution_rate": _ratio(row["resolved_on_time"], row["resolved"]),
            "median_days_to_resolve": _days(row["median_resolve_seconds"]),
            "resolution_rate": _ratio(row["resolved"], row["submitted"]),
            "resolved": row["resolved"],  # throughput when grouped by officer
        },
        "counter": {
            "info_request_rate": _ratio(row["with_info_request"], row["submitted"]),
            "median_days_paused": _days(row["median_paused_seconds"]),
            "rejection_rate": _ratio(row["rejected"], row["submitted"]),
            "late_rejections": row["late_rejections"],
            "reopen_rate_after_resolution": _ratio(
                row["reopened_after_resolution"] or 0, resolutions
            ),
            "reopen_rate_after_rejection": _ratio(row["reopened_after_rejection"] or 0, rejections),
            "reassignment_rate": _ratio(row["reassigned"], row["submitted"]),
            "withdrawn_after_deadline": row["withdrawn_after_deadline"],
        },
    }


def _fetch(sql: str, params) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [c.name for c in cursor.description]
        return [dict(zip(columns, r, strict=True)) for r in cursor.fetchall()]


def report(by: str, first: date, last: date) -> dict:
    """Requests submitted from `first` to `last` inclusive, Dhaka dates."""
    group_col, names_sql = GROUPS[by]
    start = datetime.combine(first, time.min, DHAKA)
    end = datetime.combine(last + timedelta(days=1), time.min, DHAKA)
    rows = _fetch(_SQL.format(group_col=group_col), {"start": start, "end": end, "open": OPEN})
    keys = [r["gkey"] for r in rows if r["gkey"] is not None]
    names = {}
    if keys:
        found = _fetch(f"SELECT * FROM ({names_sql}) n WHERE id = ANY(%s)", [keys])  # noqa: S608
        names = {n["id"]: {"code": n["code"], "name": n["name_en"]} for n in found}
    groups = [
        {"group": names.get(r["gkey"], {"code": None, "name": None}), **_shape(r)} for r in rows
    ]
    totals = _fetch(
        _SQL.format(group_col="NULL::bigint"), {"start": start, "end": end, "open": OPEN}
    )
    return {
        "by": by,
        "from": first,
        "to": last,
        "totals": _shape(totals[0] if totals else _NOTHING),
        "groups": groups,
    }
