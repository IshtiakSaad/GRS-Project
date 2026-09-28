from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower

from apps.common.db import created_at_field, in_choices
from apps.common.ids import uuid7

# Bangladeshi mobile numbers in E.164. 010 is an unassigned prefix, used for demo numbers.
PHONE_E164_REGEX = r"^\+8801[0-9]{9}$"


class Role(models.TextChoices):
    CITIZEN = "CITIZEN"
    OFFICER = "OFFICER"
    ADMIN = "ADMIN"


class Language(models.TextChoices):
    BN = "bn"
    EN = "en"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone, password=None, **fields):
        user = self.model(phone=phone, **fields)
        user.set_password(password)  # None gives an unusable password (assisted accounts)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    """One account is one person with their own phone number (stakeholder decision D3)."""

    public_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    phone = models.CharField(max_length=16, unique=True)
    email = models.EmailField(max_length=254, null=True, blank=True)
    full_name = models.CharField(max_length=120)
    preferred_language = models.CharField(max_length=2, choices=Language, default=Language.BN)
    role = models.CharField(max_length=8, choices=Role, default=Role.CITIZEN)
    department = models.ForeignKey(
        "directory.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="staff",
        db_index=False,  # covered by user_department_role_idx
    )
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    # Bumped on deactivation, role change and password change; access tokens carry it, so
    # those changes take effect within seconds instead of at token expiry.
    token_version = models.PositiveIntegerField(default=0)
    totp_secret_encrypted = models.CharField(max_length=255, null=True, blank=True)
    totp_enabled_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = created_at_field()
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "app_user"  # "user" is a reserved word in SQL
        constraints = [
            models.CheckConstraint(
                condition=Q(phone__regex=PHONE_E164_REGEX), name="user_phone_e164"
            ),
            in_choices("role", Role, "user"),
            in_choices("preferred_language", Language, "user"),
            models.CheckConstraint(
                condition=~Q(role=Role.OFFICER) | Q(department__isnull=False),
                name="user_officer_has_department",
            ),
            # An administrator cannot be active without two-factor login.
            models.CheckConstraint(
                condition=~Q(role=Role.ADMIN)
                | Q(totp_enabled_at__isnull=False)
                | Q(is_active=False),
                name="user_active_admin_has_totp",
            ),
            models.UniqueConstraint(Lower("email"), name="user_email_lower_unique"),
        ]
        indexes = [
            models.Index(fields=["department", "role"], name="user_department_role_idx"),
        ]

    def __str__(self):
        return f"{self.role}:{self.public_id}"


class OtpPurpose(models.TextChoices):
    VERIFY_PHONE = "VERIFY_PHONE"
    RESET_PASSWORD = "RESET_PASSWORD"  # noqa: S105 - a label, not a password
    CHANGE_PHONE = "CHANGE_PHONE"
    CONFIRM_OWNER = "CONFIRM_OWNER"


class OtpChallenge(models.Model):
    """A one-time code. Stored as an HMAC, never in plain text; purged a day after expiry."""

    phone = models.CharField(max_length=16)
    purpose = models.CharField(max_length=16, choices=OtpPurpose)
    code_hmac = models.CharField(max_length=64)
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = created_at_field()

    class Meta:
        db_table = "otp_challenge"
        constraints = [
            in_choices("purpose", OtpPurpose, "otp_challenge"),
            models.CheckConstraint(condition=Q(attempts__lte=5), name="otp_challenge_attempts_max"),
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("created_at")),
                name="otp_challenge_expiry_after_creation",
            ),
        ]
        indexes = [
            models.Index(fields=["phone", "purpose", "-created_at"], name="otp_phone_purpose_idx"),
            models.Index(fields=["expires_at"], name="otp_expires_idx"),  # purge job
        ]


class TrustMode(models.TextChoices):
    PERSONAL = "PERSONAL"
    SHARED = "SHARED"
    STAFF = "STAFF"


class RefreshSession(models.Model):
    """One refresh token in a rotation family. Only hashes are stored."""

    public_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="sessions")
    family_id = models.UUIDField()
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="+", db_index=False
    )
    device_id = models.CharField(max_length=64, null=True, blank=True)
    trust_mode = models.CharField(max_length=8, choices=TrustMode)
    token_hash = models.CharField(max_length=64, unique=True)
    user_agent = models.CharField(max_length=255, blank=True, default="")
    rotated_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    idle_expires_at = models.DateTimeField()
    absolute_expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=32, blank=True, default="")
    created_at = created_at_field()

    class Meta:
        db_table = "refresh_session"
        constraints = [
            in_choices("trust_mode", TrustMode, "refresh_session"),
            models.CheckConstraint(
                condition=Q(idle_expires_at__lte=F("absolute_expires_at")),
                name="refresh_session_idle_within_absolute",
            ),
        ]
        indexes = [
            models.Index(fields=["family_id"], name="refresh_family_idx"),
            models.Index(fields=["absolute_expires_at"], name="refresh_expiry_idx"),  # purge job
        ]


class LoginThrottle(models.Model):
    """Failed-login state per (account, device). In PostgreSQL so it survives a Redis outage."""

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+", db_index=False)
    device_key = models.CharField(max_length=64)  # a device id, or "unknown"
    failures = models.PositiveSmallIntegerField(default=0)
    next_allowed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "login_throttle"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "device_key"], name="login_throttle_user_device"
            ),
        ]


class RecoveryCode(models.Model):
    """Admin two-factor recovery: ten single-use codes issued at enrolment, stored hashed."""

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="recovery_codes")
    code_hash = models.CharField(max_length=128)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = created_at_field()

    class Meta:
        db_table = "recovery_code"
