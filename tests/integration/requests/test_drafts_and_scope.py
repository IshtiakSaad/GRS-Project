import pytest

from apps.service_requests.models import ServiceRequest, Status
from apps.service_requests.tracking import format_tracking_no
from tests import factories

from ..auth.helpers import error_code
from .helpers import act, cast, draft_body, in_state

pytestmark = pytest.mark.django_db


# --- drafts -----------------------------------------------------------------------------------


def _create(api, cat, **extra):
    return api.post("/api/v1/requests", draft_body(cat, **extra), format="json")


def test_a_citizen_creates_a_draft(as_user):
    c = cast()
    response = _create(as_user(c.owner), c.category)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == Status.DRAFT and body["tracking_no"] is None
    assert body["category"]["code"] == c.category.code
    assert response["ETag"] == '"1"'


def test_staff_cannot_create_drafts_yet(as_user):
    c = cast()
    for user in (c.assigned, c.admin):
        assert _create(as_user(user), c.category).status_code == 403


def test_a_draft_needs_an_offered_service(as_user):
    c = cast()
    api = as_user(c.owner)
    assert error_code(_create(api, c.category, category="NOPE")) == "INVALID_CATEGORY"
    c.category.is_active = False
    c.category.save()
    assert error_code(_create(api, c.category)) == "INVALID_CATEGORY"


def test_beneficiary_and_urgency_rules(as_user):
    c = cast()
    api = as_user(c.owner)
    child = {"name": "তানিয়া", "relation": "CHILD"}
    ok = _create(api, c.category, beneficiary=child)
    assert ok.json()["beneficiary"] == child
    assert _create(api, c.category, beneficiary={"name": "x"}).status_code == 400
    urgent = _create(api, c.category, citizen_urgent=True)
    assert urgent.status_code == 400
    assert "urgency_reason" in urgent.json()["error"]["fields"]


def test_text_is_cleaned_and_invisible_text_is_empty(as_user):
    c = cast()
    api = as_user(c.owner)
    blank = _create(api, c.category, title="​\x00 ")
    assert blank.status_code == 400
    decomposed = "কো"  # vowel sign typed as two code points
    ok = _create(api, c.category, title=f"  নাম {decomposed}\x00 ")
    assert ok.json()["title"] == "নাম কো"


def test_editing_a_draft_needs_the_current_etag(as_user):
    c = cast()
    api = as_user(c.owner)
    draft = in_state(c, Status.DRAFT)
    url = f"/api/v1/requests/{draft.public_id}"
    assert api.patch(url, {"title": "New"}, format="json").status_code == 428
    assert api.patch(url, {"title": "New"}, format="json", HTTP_IF_MATCH='"9"').status_code == 412
    ok = api.patch(url, {"title": "New"}, format="json", HTTP_IF_MATCH='"1"')
    assert ok.status_code == 200
    assert ok.json()["title"] == "New"
    assert ok.json()["description"] == draft.description  # untouched fields stay
    assert ok["ETag"] == '"2"'


def test_a_partial_edit_does_not_reset_other_fields(as_user):
    c = cast()
    draft = factories.draft(
        owner=c.owner, cat=c.category, citizen_urgent=True, urgency_reason="Exam next week."
    )
    as_user(c.owner).patch(
        f"/api/v1/requests/{draft.public_id}", {"title": "New"}, format="json", HTTP_IF_MATCH='"1"'
    )
    draft.refresh_from_db()
    assert (draft.citizen_urgent, draft.urgency_reason) == (True, "Exam next week.")


def test_editing_can_drop_the_beneficiary_and_change_the_service(as_user):
    c = cast()
    api = as_user(c.owner)
    draft = factories.draft(
        owner=c.owner, cat=c.category, beneficiary_name="Tania", beneficiary_relation="CHILD"
    )
    other = factories.category()
    body = {"beneficiary": None, "category": other.code}
    response = api.patch(
        f"/api/v1/requests/{draft.public_id}", body, format="json", HTTP_IF_MATCH='"1"'
    )
    draft.refresh_from_db()
    assert response.json()["beneficiary"] is None
    assert (draft.category_id, draft.department_id) == (other.pk, other.department_id)


def test_a_submitted_request_cannot_be_edited_or_deleted(as_user):
    c = cast()
    api = as_user(c.owner)
    request = in_state(c, Status.SUBMITTED)
    url = f"/api/v1/requests/{request.public_id}"
    edit = api.patch(url, {"title": "x"}, format="json", HTTP_IF_MATCH='"1"')
    assert error_code(edit) == "NOT_A_DRAFT"
    assert error_code(api.delete(url, HTTP_IF_MATCH='"1"')) == "NOT_A_DRAFT"


def test_discarding_a_draft(as_user):
    c = cast()
    draft = in_state(c, Status.DRAFT)
    url = f"/api/v1/requests/{draft.public_id}"
    assert as_user(c.stranger).delete(url, HTTP_IF_MATCH='"1"').status_code == 404
    assert as_user(c.owner).delete(url, HTTP_IF_MATCH='"1"').status_code == 204
    assert not ServiceRequest.objects.filter(pk=draft.pk).exists()


def test_one_account_cannot_pile_up_drafts(as_user):
    c = cast()
    for _ in range(20):
        factories.draft(owner=c.owner, cat=c.category)
    assert error_code(_create(as_user(c.owner), c.category)) == "TOO_MANY_DRAFTS"


# --- who sees what ----------------------------------------------------------------------------


def _ids(response):
    return {row["id"] for row in response.json()["results"]}


def test_lists_are_scoped(as_user):
    c = cast()
    draft = in_state(c, Status.DRAFT)
    mine = in_state(c, Status.SUBMITTED)
    elsewhere = factories.submitted()  # another department, another owner
    assigned_across = factories.submitted(status=Status.ASSIGNED, assigned_officer=c.outsider)

    def seen(user):
        return _ids(as_user(user).get("/api/v1/requests"))

    ids = lambda *rs: {str(r.public_id) for r in rs}  # noqa: E731
    assert seen(c.owner) == ids(draft, mine)
    assert seen(c.stranger) == set()
    assert seen(c.colleague) == ids(mine)
    assert seen(c.outsider) == ids(assigned_across)  # theirs, though another department's
    assert seen(c.admin) >= ids(mine, elsewhere, assigned_across)
    assert str(draft.public_id) not in seen(c.admin)


def test_staff_rows_carry_nothing_personal(as_user):
    c = cast()
    in_state(c, Status.SUBMITTED)
    row = as_user(c.colleague).get("/api/v1/requests").json()["results"][0]
    assert set(row) == {
        "id",
        "tracking_no",
        "category",
        "status",
        "priority",
        "citizen_urgent",
        "due_at",
        "submitted_at",
        "owner_initials",
    }
    assert row["owner_initials"] == "R.U."


def test_list_filter_by_status(as_user):
    c = cast()
    in_state(c, Status.SUBMITTED)
    resolved = in_state(c, Status.RESOLVED)
    api = as_user(c.owner)
    assert _ids(api.get("/api/v1/requests?status=RESOLVED")) == {str(resolved.public_id)}
    assert api.get("/api/v1/requests?status=LOST").status_code == 400


@pytest.mark.parametrize(
    ("who", "code"),
    [
        ("owner", 200),
        ("stranger", 404),
        ("assigned", 200),
        ("colleague", 200),
        ("outsider", 404),
        ("admin", 200),
    ],
)
def test_detail_is_scoped(as_user, who, code):
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    response = as_user(c.by_name(who)).get(f"/api/v1/requests/{request.public_id}")
    assert response.status_code == code
    if code == 404:
        assert b"tracking" not in response.content


def test_citizens_see_the_office_not_the_officer(as_user):
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    body = as_user(c.owner).get(f"/api/v1/requests/{request.public_id}").json()
    assert body["handled_by"]["role"] == "OFFICER"
    assert body["handled_by"]["department"]["code"] == c.category.department.code
    assert c.assigned.full_name not in str(body)
    assert "assigned_officer" not in body and "owner" not in body

    staff = as_user(c.colleague).get(f"/api/v1/requests/{request.public_id}").json()
    assert staff["assigned_officer"]["name"] == c.assigned.full_name
    assert staff["owner"]["phone"] == c.owner.phone


def test_an_officer_keeps_an_assigned_request_from_another_department(as_user):
    c = cast()
    request = factories.submitted(status=Status.ASSIGNED, assigned_officer=c.outsider)
    assert as_user(c.outsider).get(f"/api/v1/requests/{request.public_id}").status_code == 200


def test_conditional_get(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    api = as_user(c.owner)
    url = f"/api/v1/requests/{request.public_id}"
    etag = api.get(url)["ETag"]
    assert api.get(url, HTTP_IF_NONE_MATCH=etag).status_code == 304
    assert api.get(url, HTTP_IF_NONE_MATCH='"0"').status_code == 200


def test_anonymous_callers_see_nothing(api):
    assert api.get("/api/v1/requests").status_code == 401
    assert api.get("/api/v1/queue").status_code == 401


# --- lookup by tracking number ----------------------------------------------------------------


def _bangla(number: str) -> str:
    return number.translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))


def test_lookup_accepts_what_people_type(as_user):
    c = cast()
    number = format_tracking_no(2026, 4213)
    request = in_state(c, Status.SUBMITTED)
    ServiceRequest.objects.filter(pk=request.pk).update(tracking_no=number)
    api = as_user(c.owner)
    for typed in (number, number.replace("-", ""), _bangla(number).replace("-", " ")):
        response = api.get(f"/api/v1/requests/by-tracking/{typed}")
        assert response.status_code == 200, typed
        assert response.json()["id"] == str(request.public_id)


def test_lookup_checks_the_digit_before_the_database(as_user):
    c = cast()
    response = as_user(c.owner).get(
        "/api/v1/requests/by-tracking/26-0004213-0"
    )  # wrong check digit
    assert response.status_code == 400
    assert error_code(response) == "INVALID_TRACKING_NO"


def test_lookup_is_scoped(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    number = format_tracking_no(2026, request.pk + 100000)
    ServiceRequest.objects.filter(pk=request.pk).update(tracking_no=number)
    url = f"/api/v1/requests/by-tracking/{number}"
    assert as_user(c.stranger).get(url).status_code == 404
    assert as_user(c.outsider).get(url).status_code == 404
    assert as_user(c.colleague).get(url).status_code == 200


# --- timeline ---------------------------------------------------------------------------------


def test_citizens_see_the_public_timeline_without_names(as_user):
    c = cast()
    request = in_state(c, Status.IN_PROGRESS)
    act(
        as_user(c.admin),
        request,
        "reassign",
        {"officer": str(c.colleague.public_id), "reason": "Leave."},
    )
    act(as_user(c.colleague), request, "resolve", {"note": "Corrected."})

    citizen = as_user(c.owner).get(f"/api/v1/requests/{request.public_id}/timeline").json()
    assert [e["type"] for e in citizen] == ["resolve"]  # reassignment is internal
    assert citizen[0]["data"] == {"note": "Corrected."}
    assert "actor" not in citizen[0]

    staff = as_user(c.colleague).get(f"/api/v1/requests/{request.public_id}/timeline").json()
    assert [e["type"] for e in staff] == ["reassign", "resolve"]
    assert staff[1]["actor"] == str(c.colleague.public_id)


def test_timeline_is_scoped(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    url = f"/api/v1/requests/{request.public_id}/timeline"
    assert as_user(c.stranger).get(url).status_code == 404


def test_categories_are_public(api):
    c = cast()
    factories.category(is_active=False)
    codes = [row["code"] for row in api.get("/api/v1/categories").json()]
    assert codes == [c.category.code]
