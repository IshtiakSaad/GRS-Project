"""Identity flows. Views translate HTTP to these calls; every rule lives here.

Two principles run through this file:
- Responses do not reveal whether a phone number has an account (register, login, password
  reset answer the same way, after the same amount of hashing).
- Anything that changes a credential revokes every session and is audited.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.common.errors import AppError
from apps.notifications import services as notifications
from apps.notifications.models import Channel

from . import otp, sessions, throttle, tokens, totp
from .models import OtpPurpose, RecoveryCode, RefreshSession, Role, User

DORMANT_AFTER = timedelta(days=180)
RECOVERY_CODES = 10
EMAIL_TOKEN_MAX_AGE = 24 * 3600


# --- errors -----------------------------------------------------------------------------------


def _invalid_credentials() -> AppError:
    return AppError("INVALID_CREDENTIALS", _("Phone number or password is incorrect."), 401)


def _invalid_code() -> AppError:
    return AppError("INVALID_CODE", _("The code is incorrect or has expired."), 400)


def _delayed(seconds: int) -> AppError:
    return AppError(
        "LOGIN_DELAYED",
        _("Too many failed attempts. Try again in %(minutes)s minutes.")
        % {"minutes": max(1, -(-seconds // 60))},
        429,
        wait=seconds,
    )


def check_password_rules(password: str, phone: str = "", full_name: str = "") -> None:
    """Raises AppError(VALIDATION_ERROR) listing what is wrong with a new password."""
    try:
        validate_password(password, User(phone=phone, full_name=full_name))
    except ValidationError as exc:
        raise AppError(
            "VALIDATION_ERROR", _("Some fields are invalid."), 400, {"password": exc.messages}
        ) from exc


def _by_phone(phone: str) -> User | None:
    return User.objects.filter(phone=phone).first()


# --- devices ----------------------------------------------------------------------------------
# A device token is issued at the first successful login on a device. It is signed and bound to
# the account, so it cannot be forged or moved to another account.


def issue_device_token(user: User, device_id: str) -> str:
    return signing.dumps({"u": str(user.public_id), "d": device_id}, salt="grs.device")


def read_device_token(token, user: User) -> str | None:
    if not isinstance(token, str) or len(token) > 512:
        return None
    try:
        data = signing.loads(token, salt="grs.device")
    except signing.BadSignature:
        return None
    return data.get("d") if data.get("u") == str(user.public_id) else None


# --- registration -----------------------------------------------------------------------------


def register(phone: str, password: str, full_name: str, language: str) -> None:
    """Same response and the same hashing cost whether or not the phone has an account."""
    check_password_rules(password, phone, full_name)
    existing = _by_phone(phone)
    if existing is None:
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    phone, password, full_name=full_name, preferred_language=language
                )
                otp.issue(user, OtpPurpose.VERIFY_PHONE)
            return
        except IntegrityError:  # registered a moment ago by a concurrent request
            existing = User.objects.get(phone=phone)
    else:
        make_password(password)  # equal cost to the branch above
    _warn_existing_owner(existing)


def _warn_existing_owner(user: User) -> None:
    """Tell the real owner, at most once an hour, so the warning cannot be used to spam them."""
    if not user.is_active:
        return
    try:
        first = cache.add(f"register-warned:{user.pk}", 1, timeout=3600)
    except Exception:  # noqa: BLE001 - cache down: skip the warning rather than risk spam
        return
    if first:
        notifications.queue(user, "register_attempt", {})


def verify_phone(phone: str, code) -> None:
    if not otp.verify(phone, OtpPurpose.VERIFY_PHONE, code):
        raise _invalid_code()
    User.objects.filter(phone=phone, phone_verified_at__isnull=True).update(
        phone_verified_at=timezone.now()
    )


def resend_phone_code(phone: str) -> None:
    user = User.objects.filter(phone=phone, phone_verified_at__isnull=True, is_active=True).first()
    if user is not None:
        otp.issue(user, OtpPurpose.VERIFY_PHONE)  # over the limit: silently nothing


# --- login ------------------------------------------------------------------------------------


def login(
    phone: str,
    password: str,
    *,
    device_token=None,
    trust_mode=None,
    user_agent: str = "",
    http_request=None,
) -> dict:
    user = _by_phone(phone)
    if user is None:
        wait = throttle.phantom_wait_seconds(phone)
        if wait:
            raise _delayed(wait)
        make_password(password)  # same cost as a real check
        throttle.phantom_record_failure(phone)
        raise _invalid_credentials()

    device_id = read_device_token(device_token, user)
    bucket = device_id or throttle.UNKNOWN_DEVICE
    wait = throttle.wait_seconds(user, bucket)
    if wait:
        raise _delayed(wait)  # before hashing: a delayed guess costs no CPU

    if not user.check_password(password) or not user.is_active:
        throttle.record_failure(user, bucket)
        audit.record("auth.login_failed", target=user, http_request=http_request)
        raise _invalid_credentials()
    throttle.clear(user, bucket)

    device_id = device_id or secrets.token_hex(16)
    mode = sessions.trust_mode_for(user, trust_mode)
    result = {"device_token": issue_device_token(user, device_id)}
    if user.totp_enabled_at is not None:
        result.update(mfa_required=True, mfa_token=tokens.issue_mfa(user, device_id, mode))
        return result

    with transaction.atomic():
        issued = sessions.start(
            user, device_id=device_id, trust_mode=mode, mfa=False, user_agent=user_agent
        )
        _logged_in(user, "auth.login", http_request)
    result.update(mfa_required=False, **issued.as_dict())
    return result


def _logged_in(user: User, action: str, http_request) -> None:
    User.objects.filter(pk=user.pk).update(last_login=timezone.now())
    audit.record(action, actor=user, target=user, http_request=http_request)


def _user_from_mfa_token(mfa_token) -> tuple[User, dict]:
    try:
        claims = tokens.read_mfa(mfa_token if isinstance(mfa_token, str) else "")
    except tokens.TokenError as exc:
        raise AppError(
            "MFA_TOKEN_INVALID", _("Your login has expired. Please log in again."), 401
        ) from exc
    user = User.objects.filter(public_id=claims["sub"], is_active=True).first()
    if user is None or user.token_version != claims["ver"] or user.totp_enabled_at is None:
        raise AppError("MFA_TOKEN_INVALID", _("Your login has expired. Please log in again."), 401)
    return user, claims


def verify_second_factor(mfa_token, code, *, user_agent: str = "", http_request=None) -> dict:
    user, claims = _user_from_mfa_token(mfa_token)
    wait = throttle.wait_seconds(user, "2fa")
    if wait:
        raise _delayed(wait)
    secret = totp.decrypt_secret(user.totp_secret_encrypted or "")
    code = otp.clean_code(code)
    counter = (
        totp.matching_counter(secret, code, user.totp_last_counter) if secret and code else None
    )
    # The conditional update is what stops replay: two requests with one code cannot both win.
    accepted = counter is not None and (
        User.objects.filter(pk=user.pk)
        .exclude(totp_last_counter__gte=counter)
        .update(totp_last_counter=counter)
        == 1
    )
    if not accepted:
        throttle.record_failure(user, "2fa")
        audit.record("auth.2fa_failed", target=user, http_request=http_request)
        raise _invalid_code()
    throttle.clear(user, "2fa")
    return _finish_mfa_login(user, claims, user_agent, http_request, "auth.login_2fa")


def use_recovery_code(mfa_token, code, *, user_agent: str = "", http_request=None) -> dict:
    user, claims = _user_from_mfa_token(mfa_token)
    wait = throttle.wait_seconds(user, "2fa")
    if wait:
        raise _delayed(wait)
    if not _spend_recovery_code(user, code):
        throttle.record_failure(user, "2fa")
        audit.record("auth.recovery_failed", target=user, http_request=http_request)
        raise _invalid_code()
    throttle.clear(user, "2fa")
    return _finish_mfa_login(user, claims, user_agent, http_request, "auth.login_recovery_code")


def _finish_mfa_login(user, claims, user_agent, http_request, action) -> dict:
    with transaction.atomic():
        issued = sessions.start(
            user,
            device_id=claims.get("dev"),
            trust_mode=claims["trust"],
            mfa=True,
            user_agent=user_agent,
        )
        _logged_in(user, action, http_request)
    return issued.as_dict()


# --- two-factor enrolment ---------------------------------------------------------------------


# Recovery codes use the password hasher, not an HMAC: an HMAC keyed by SECRET_KEY would void
# every administrator's codes the day that key is rotated. The recovery route is rare and runs
# on the bulkhead, so ten slow comparisons there cost nothing at peak.


def _normalise_recovery(code) -> str:
    return str(code or "").replace("-", "").replace(" ", "").upper()[:32]


def _store_recovery_codes(user: User, codes: list[str]) -> None:
    RecoveryCode.objects.filter(user=user).delete()
    RecoveryCode.objects.bulk_create(
        RecoveryCode(user=user, code_hash=make_password(_normalise_recovery(c))) for c in codes
    )


def _spend_recovery_code(user: User, code) -> bool:
    typed = _normalise_recovery(code)
    for row in RecoveryCode.objects.filter(user=user, used_at__isnull=True):
        if check_password(typed, row.code_hash):
            # Conditional: of two requests racing with one code, only one spends it.
            return (
                RecoveryCode.objects.filter(pk=row.pk, used_at__isnull=True).update(
                    used_at=timezone.now()
                )
                == 1
            )
    return False


def _reauthenticate(user: User, password: str) -> None:
    """Sensitive changes need the password again, so a stolen access token is not enough."""
    wait = throttle.wait_seconds(user, "reauth")
    if wait:
        raise _delayed(wait)
    if not user.check_password(password):
        throttle.record_failure(user, "reauth")
        message = _("Current password is incorrect.")
        raise AppError("INVALID_CREDENTIALS", message, 400, {"current_password": [message]})
    throttle.clear(user, "reauth")


def begin_totp_setup(user: User) -> dict:
    if user.totp_enabled_at is not None:
        raise AppError("TOTP_ALREADY_ENABLED", _("Two-step login is already on."), 409)
    secret = totp.new_secret()
    User.objects.filter(pk=user.pk).update(totp_secret_encrypted=totp.encrypt_secret(secret))
    return {"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, user.phone)}


def confirm_totp_setup(
    user: User, password: str, code, *, user_agent: str = "", http_request=None
) -> dict:
    """Turns two-step login on. Every other session ends: they were not opened with it.

    It issues a new session, so it asks for the password: otherwise a stolen 10-minute access
    token could be turned into a 12-hour session.
    """
    if user.totp_enabled_at is not None:
        raise AppError("TOTP_ALREADY_ENABLED", _("Two-step login is already on."), 409)
    _reauthenticate(user, password)
    secret = totp.decrypt_secret(user.totp_secret_encrypted or "")
    code = otp.clean_code(code)
    counter = totp.matching_counter(secret, code, None) if secret and code else None
    if counter is None:
        raise _invalid_code()
    codes = [_new_recovery_code() for _ in range(RECOVERY_CODES)]
    with transaction.atomic():
        user.totp_enabled_at = timezone.now()
        user.totp_last_counter = counter
        user.token_version += 1
        user.save(update_fields=["totp_enabled_at", "totp_last_counter", "token_version"])
        _store_recovery_codes(user, codes)
        sessions.revoke_all(user, "totp_enabled")
        issued = sessions.start(
            user,
            device_id=None,
            trust_mode=sessions.trust_mode_for(user, None),
            mfa=True,
            user_agent=user_agent,
        )
        audit.record("auth.totp_enabled", actor=user, target=user, http_request=http_request)
    return {"recovery_codes": codes, **issued.as_dict()}


def _new_recovery_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I to misread
    raw = "".join(secrets.choice(alphabet) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def enrol_admin_totp(user: User) -> tuple[str, list[str]]:
    """For the createadmin command: an admin cannot exist without a second factor."""
    secret = totp.new_secret()
    codes = [_new_recovery_code() for _ in range(RECOVERY_CODES)]
    user.totp_secret_encrypted = totp.encrypt_secret(secret)
    user.totp_enabled_at = timezone.now()
    return secret, codes


# --- password ---------------------------------------------------------------------------------


def request_password_reset(phone: str) -> None:
    """Always answers the same. A number unused for 180 days may have been reissued by the
    operator to someone else (SIM recycling), so it gets no code: its owner must visit a help
    desk with their national ID."""
    user = User.objects.filter(phone=phone, is_active=True).first()
    if user is None:
        return
    last_seen = user.last_login or user.created_at
    if timezone.now() - last_seen > DORMANT_AFTER:
        return
    otp.issue(user, OtpPurpose.RESET_PASSWORD)


def confirm_password_reset(phone: str, code, new_password: str, http_request=None) -> None:
    check_password_rules(new_password, phone)
    if not otp.verify(phone, OtpPurpose.RESET_PASSWORD, code):
        raise _invalid_code()
    user = User.objects.get(phone=phone)
    with transaction.atomic():
        # The code arrived on this phone, so the phone is proven too.
        user.phone_verified_at = user.phone_verified_at or timezone.now()
        _set_password(user, new_password, "password_reset", http_request)
        user.save(update_fields=["phone_verified_at"])


def change_password(
    user: User, current: str, new: str, *, family_id, user_agent: str = "", http_request=None
) -> dict:
    _reauthenticate(user, current)
    check_password_rules(new, user.phone, user.full_name)
    current_session = RefreshSession.objects.filter(family_id=family_id).first()
    with transaction.atomic():
        _set_password(user, new, "password_change", http_request)
        issued = sessions.start(
            user,
            device_id=current_session.device_id if current_session else None,
            trust_mode=sessions.trust_mode_for(
                user, current_session.trust_mode if current_session else None
            ),
            mfa=bool(current_session and current_session.mfa),
            user_agent=user_agent,
        )
    return issued.as_dict()


def _set_password(user: User, password: str, reason: str, http_request) -> None:
    user.set_password(password)
    user.token_version += 1
    user.save(update_fields=["password", "token_version"])
    sessions.revoke_all(user, reason)
    audit.record(f"auth.{reason}", actor=user, target=user, http_request=http_request)
    notifications.queue(user, "password_changed", {})


def logout(family_id) -> None:
    sessions.revoke_family(family_id, "logout")


# --- email (optional; verified by a signed link) ---------------------------------------------


def set_email(user: User, email: str | None) -> None:
    email = (email or "").strip().lower() or None
    if email == user.email:
        return
    with transaction.atomic():
        user.email = email
        user.email_verified_at = None
        try:
            with transaction.atomic():
                user.save(update_fields=["email", "email_verified_at"])
        except IntegrityError as exc:
            raise AppError(
                "EMAIL_IN_USE",
                _("This email is used by another account."),
                409,
                {"email": [_("This email is used by another account.")]},
            ) from exc
        if email:
            token = signing.dumps({"u": str(user.public_id), "e": email}, salt="grs.email")
            link = f"{settings.PUBLIC_BASE_URL}/verify-email#token={token}"
            notifications.queue(
                user, "verify_email", {"link": link, "token": token}, channel=Channel.EMAIL
            )


def verify_email(token) -> None:
    try:
        data = signing.loads(str(token or ""), salt="grs.email", max_age=EMAIL_TOKEN_MAX_AGE)
    except signing.BadSignature as exc:
        raise _invalid_code() from exc
    # The token names the address it was sent to: if the email was changed since, it is void.
    user = User.objects.filter(public_id=data.get("u"), email=data.get("e")).first()
    if user is None:
        raise _invalid_code()
    if user.email_verified_at is None:
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])


# --- administration ---------------------------------------------------------------------------


def create_admin(phone: str, full_name: str, password: str) -> tuple[User, str, list[str]]:
    """Used by the createadmin management command on the host (design §4.2)."""
    check_password_rules(password, phone, full_name)
    with transaction.atomic():
        user = User(phone=phone, full_name=full_name, role=Role.ADMIN)
        user.set_password(password)
        secret, codes = enrol_admin_totp(user)
        user.phone_verified_at = timezone.now()
        user.save()
        _store_recovery_codes(user, codes)
        audit.record("auth.admin_created", target=user)
    return user, secret, codes
