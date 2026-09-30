"""Administration. Every change is audited with what it was before.

Holidays, suspensions and a category's target days are inputs to every open deadline,
so changing them schedules a recompute of the open requests they affect.
"""

import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils.translation import gettext as _

from apps.accounts import otp, sessions
from apps.accounts.models import OtpPurpose, Role, User
from apps.audit import services as audit
from apps.common.errors import AppError
from apps.directory.models import Category, Department, Holiday, SlaSuspension

logger = logging.getLogger(__name__)


def _recompute_later(**scope) -> None:
    """After commit, in the worker. If the broker is down, recompute here instead: holidays
    change rarely, and a stale deadline is worse than a slow admin request."""
    from apps.sla import services as sla
    from apps.sla.tasks import recompute_due_dates

    def run():
        try:
            recompute_due_dates.delay(**scope)
        except Exception:  # noqa: BLE001 - any broker failure
            logger.warning("broker down; recomputing deadlines inline for %s", scope)
            sla.recompute_open(**scope)

    transaction.on_commit(run)


def _snapshot(obj, fields) -> dict:
    return {f: str(getattr(obj, f)) if getattr(obj, f) is not None else None for f in fields}


def _in_use(field: str) -> AppError:
    message = _("This code is already used.")
    return AppError("CODE_IN_USE", message, 409, {field: [message]})


# --- departments and categories ---------------------------------------------------------------

DEPARTMENT_FIELDS = ("code", "name_bn", "name_en", "is_active")
CATEGORY_FIELDS = ("code", "name_bn", "name_en", "target_working_days", "is_active")


def department(code: str) -> Department:
    found = Department.objects.filter(code=code).first()
    if found is None:
        raise Http404
    return found


def _department_ref(code: str) -> Department:
    """A department named in a request body: unknown is invalid input, not a missing page."""
    found = Department.objects.filter(code=code).first()
    if found is None:
        message = _("Choose an existing department.")
        raise AppError("VALIDATION_ERROR", message, 400, {"department": [message]})
    return found


def create_department(admin: User, data: dict, http_request=None) -> Department:
    try:
        with transaction.atomic():
            dept = Department.objects.create(**data)
            audit.record(
                "admin.department.create",
                actor=admin,
                target=dept,
                data={"after": _snapshot(dept, DEPARTMENT_FIELDS)},
                http_request=http_request,
            )
            return dept
    except IntegrityError as exc:
        raise _in_use("code") from exc


def update_department(admin: User, code: str, data: dict, http_request=None) -> Department:
    with transaction.atomic():
        dept = Department.objects.select_for_update().filter(code=code).first()
        if dept is None:
            raise Http404
        before = _snapshot(dept, DEPARTMENT_FIELDS)
        for name, value in data.items():
            setattr(dept, name, value)
        dept.save(update_fields=list(data) or None)
        audit.record(
            "admin.department.update",
            actor=admin,
            target=dept,
            data={"before": before, "after": _snapshot(dept, DEPARTMENT_FIELDS)},
            http_request=http_request,
        )
        return dept


def create_category(admin: User, data: dict, http_request=None) -> Category:
    dept = _department_ref(data.pop("department"))
    try:
        with transaction.atomic():
            category = Category.objects.create(department=dept, **data)
            audit.record(
                "admin.category.create",
                actor=admin,
                target=category,
                data={"department": dept.code, "after": _snapshot(category, CATEGORY_FIELDS)},
                http_request=http_request,
            )
            return category
    except IntegrityError as exc:
        raise _in_use("code") from exc


def update_category(admin: User, code: str, data: dict, http_request=None) -> Category:
    with transaction.atomic():
        category = (
            Category.objects.select_for_update().select_related("department").filter(code=code)
        ).first()
        if category is None:
            raise Http404
        before = _snapshot(category, CATEGORY_FIELDS)
        for name, value in data.items():
            setattr(category, name, value)
        category.save(update_fields=list(data) or None)
        audit.record(
            "admin.category.update",
            actor=admin,
            target=category,
            data={"before": before, "after": _snapshot(category, CATEGORY_FIELDS)},
            http_request=http_request,
        )
        if before["target_working_days"] != str(category.target_working_days):
            _recompute_later(category_id=category.pk)
        return category


# --- holidays and suspensions -----------------------------------------------------------------


def create_holiday(admin: User, data: dict, http_request=None) -> Holiday:
    try:
        with transaction.atomic():
            holiday = Holiday.objects.create(created_by=admin, **data)
            audit.record(
                "admin.holiday.create",
                actor=admin,
                target=holiday,
                data={"date": str(holiday.date), "name_en": holiday.name_en},
                http_request=http_request,
            )
            _recompute_later()
            return holiday
    except IntegrityError as exc:
        message = _("This date is already a holiday.")
        raise AppError("HOLIDAY_EXISTS", message, 409, {"date": [message]}) from exc


def delete_holiday(admin: User, day, http_request=None) -> None:
    with transaction.atomic():
        holiday = Holiday.objects.select_for_update().filter(date=day).first()
        if holiday is None:
            raise Http404
        audit.record(
            "admin.holiday.delete",
            actor=admin,
            target=holiday,
            data={"date": str(holiday.date), "name_en": holiday.name_en},
            http_request=http_request,
        )
        holiday.delete()
        _recompute_later()


def create_suspension(admin: User, data: dict, http_request=None) -> SlaSuspension:
    code = data.pop("department", None)
    scope = _department_ref(code) if code else None
    with transaction.atomic():
        suspension = SlaSuspension.objects.create(scope_department=scope, created_by=admin, **data)
        audit.record(
            "admin.sla_suspension.create",
            actor=admin,
            target=suspension,
            data={
                "department": code,
                "starts_on": str(suspension.starts_on),
                "ends_on": str(suspension.ends_on),
                "reason": suspension.reason,
            },
            http_request=http_request,
        )
        _recompute_later(department_id=scope.pk if scope else None)
        return suspension


def delete_suspension(admin: User, pk: int, http_request=None) -> None:
    with transaction.atomic():
        suspension = SlaSuspension.objects.select_for_update().filter(pk=pk).first()
        if suspension is None:
            raise Http404
        scope_id = suspension.scope_department_id
        audit.record(
            "admin.sla_suspension.delete",
            actor=admin,
            target=suspension,
            data={"starts_on": str(suspension.starts_on), "ends_on": str(suspension.ends_on)},
            http_request=http_request,
        )
        suspension.delete()
        _recompute_later(department_id=scope_id)


# --- staff accounts ---------------------------------------------------------------------------


def user_by_public_id(public_id) -> User:
    user = User.objects.select_related("department").filter(public_id=public_id).first()
    if user is None:
        raise Http404
    return user


def create_officer(admin: User, data: dict, http_request=None) -> User:
    """No password is chosen by anyone but the officer: the account starts without one, and a
    reset code goes to the officer's own phone (POST /auth/password/reset/confirm)."""
    dept = _department_ref(data["department"])
    if not dept.is_active:
        message = _("This department is not active.")
        raise AppError("VALIDATION_ERROR", message, 400, {"department": [message]})
    try:
        with transaction.atomic():
            officer = User.objects.create_user(
                data["phone"],
                None,  # unusable until the officer sets their own
                full_name=data["full_name"],
                role=Role.OFFICER,
                department=dept,
            )
            audit.record(
                "admin.user.create",
                actor=admin,
                target=officer,
                data={"role": Role.OFFICER, "department": dept.code},
                http_request=http_request,
            )
            _send_setup_code(officer, "staff_welcome")
            return officer
    except IntegrityError as exc:
        message = _("This phone number already has an account.")
        raise AppError("PHONE_IN_USE", message, 409, {"phone": [message]}) from exc


def update_user(admin: User, public_id, data: dict, http_request=None) -> User:
    with transaction.atomic():
        user = (
            User.objects.select_for_update(of=("self",))
            .select_related("department")
            .filter(public_id=public_id)
            .first()
        )
        if user is None:
            raise Http404
        if user.pk == admin.pk and "is_active" in data:
            raise AppError("CANNOT_CHANGE_SELF", _("You cannot deactivate your own account."), 409)
        before = {
            "full_name": user.full_name,
            "is_active": user.is_active,
            "department": user.department.code if user.department_id else None,
        }
        if "department" in data:
            if user.role != Role.OFFICER:
                message = _("Only officers belong to a department.")
                raise AppError("VALIDATION_ERROR", message, 400, {"department": [message]})
            user.department = _department_ref(data["department"])
        if "full_name" in data:
            user.full_name = data["full_name"]
        ended_sessions = False
        if "is_active" in data and data["is_active"] != user.is_active:
            user.is_active = data["is_active"]
            if not user.is_active:
                user.token_version += 1  # every access token dies on its next request
                ended_sessions = True
        user.save()
        if ended_sessions:
            sessions.revoke_all(user, "deactivated")
        audit.record(
            "admin.user.update",
            actor=admin,
            target=user,
            data={
                "before": before,
                "after": {
                    "full_name": user.full_name,
                    "is_active": user.is_active,
                    "department": user.department.code if user.department_id else None,
                },
            },
            http_request=http_request,
        )
        return user


def reset_password(admin: User, public_id, http_request=None) -> None:
    """For a staff member who is locked out or whose password may be known to someone else.
    The old password stops working at once; a reset code goes to their own phone."""
    with transaction.atomic():
        user = User.objects.select_for_update().filter(public_id=public_id).first()
        if user is None:
            raise Http404
        if user.role == Role.CITIZEN:
            raise AppError(
                "NOT_ALLOWED",
                _("Citizens reset their own password, or at a help desk with their ID."),
                403,
            )
        user.set_unusable_password()
        user.token_version += 1
        user.save(update_fields=["password", "token_version"])
        sessions.revoke_all(user, "admin_reset")
        audit.record(
            "admin.user.reset_password", actor=admin, target=user, http_request=http_request
        )
        _send_setup_code(user, "staff_reset")


def _send_setup_code(user: User, template: str) -> None:
    """The SMS says what happened and links to the page that sets the password, with the phone
    filled in: a new officer has never seen the site, and "Forgot password" is the wrong door
    for someone who never had one."""
    link = f"{settings.PUBLIC_BASE_URL}/set-password/?phone={user.phone.removeprefix('+88')}"
    otp.issue(
        user,
        OtpPurpose.RESET_PASSWORD,
        template=template,
        lifetime=otp.STAFF_SETUP_LIFETIME,
        extra={"link": link},
    )
