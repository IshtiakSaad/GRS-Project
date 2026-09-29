"""Every (state, action, actor) cell, through the HTTP API.

The expected answers are written out from the rules here, independently of the
engine's own RULES table, so a wrong rule in the engine cannot also be a wrong expectation.
"""

import pytest

from apps.audit.models import AuditLog
from apps.service_requests.models import RequestEvent, Status

from .helpers import act, cast, in_state

pytestmark = pytest.mark.django_db

S = Status
OPEN = {S.SUBMITTED, S.ASSIGNED, S.IN_PROGRESS, S.AWAITING_CITIZEN}
HAS_OFFICER = {S.ASSIGNED, S.IN_PROGRESS, S.AWAITING_CITIZEN, S.RESOLVED, S.REJECTED}

# action: (from states, who, to state or None for unchanged)
ALLOWED = {
    "submit": ({S.DRAFT}, {"owner"}, S.SUBMITTED),
    "assign": ({S.SUBMITTED}, {"admin"}, S.ASSIGNED),
    "reassign": ({S.ASSIGNED, S.IN_PROGRESS}, {"admin"}, None),
    "start": ({S.ASSIGNED}, {"assigned"}, S.IN_PROGRESS),
    "request_info": ({S.IN_PROGRESS}, {"assigned"}, S.AWAITING_CITIZEN),
    "respond": ({S.AWAITING_CITIZEN}, {"owner"}, S.IN_PROGRESS),
    "resume": ({S.AWAITING_CITIZEN}, {"assigned"}, S.IN_PROGRESS),
    "resolve": ({S.IN_PROGRESS}, {"assigned"}, S.RESOLVED),
    "reject": (OPEN, {"assigned", "admin"}, S.REJECTED),
    "withdraw": (OPEN, {"owner"}, S.WITHDRAWN),
    "reopen": ({S.RESOLVED, S.REJECTED}, {"owner"}, S.SUBMITTED),
}
ACTORS = ["owner", "stranger", "assigned", "colleague", "outsider", "admin"]


def body_for(action, c) -> dict:
    return {
        "assign": {"officer": str(c.colleague.public_id)},
        "reassign": {"officer": str(c.colleague.public_id), "reason": "Leave."},
        "request_info": {"reason_code": "MISSING_DOCUMENT", "message": "Send the form."},
        "respond": {"message": "Here it is."},
        "resume": {"reason": "Found it."},
        "resolve": {"note": "Corrected."},
        "reject": {"reason_code": "INCOMPLETE", "note": "Form missing."},
        "reopen": {"reason": "Still wrong."},
    }.get(action, {})


def expected(state, actor, action) -> int:
    if actor in ("stranger", "outsider"):
        return 404  # outside their scope: not even its existence is confirmed
    if state == S.DRAFT and actor != "owner":
        return 404  # drafts are private
    states, who, _ = ALLOWED[action]
    if actor not in who or (actor == "assigned" and state not in HAS_OFFICER):
        return 403
    return 200 if state in states else 409


def test_the_matrix_covers_every_action_the_api_offers():
    from apps.service_requests.serializers import ACTION_INPUTS

    assert set(ALLOWED) == set(ACTION_INPUTS)


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("action", list(ALLOWED))
@pytest.mark.parametrize("state", list(Status))
def test_transition(api, as_user, state, action, actor):
    c = cast()
    request = in_state(c, state)
    events = RequestEvent.objects.filter(request=request).count()

    response = act(as_user(c.by_name(actor)), request, action, body_for(action, c))

    want = expected(state, actor, action)
    assert response.status_code == want, response.content
    request.refresh_from_db()
    if want != 200:
        assert request.status == state
        assert request.version == 1
        assert RequestEvent.objects.filter(request=request).count() == events
        return
    target = ALLOWED[action][2] or state
    assert request.status == target
    assert request.version == 2
    assert response["ETag"] == '"2"'
    event = RequestEvent.objects.filter(request=request).latest("id")
    assert (event.event_type, event.from_status, event.to_status) == (action, state, target)
    assert AuditLog.objects.filter(request=request, action=f"request.{action}").exists()
