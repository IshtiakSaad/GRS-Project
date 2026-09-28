from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.accounts.models import Role, User
from apps.common.fields import PhoneField, TextField
from apps.directory.models import Category, Department, Holiday, SlaSuspension
from apps.service_requests.models import Review, ReviewReason, ReviewStatus

CODE = r"^[A-Z][A-Z0-9_]{1,29}$"
CODE_HELP = "Upper-case letters, digits and _, starting with a letter. Never changes."


# --- departments and categories ---------------------------------------------------------------


class DepartmentIn(serializers.Serializer):
    code = serializers.RegexField(CODE, max_length=20, help_text=CODE_HELP)
    name_bn = TextField(max_length=120)
    name_en = TextField(max_length=120)


class DepartmentPatchIn(serializers.Serializer):
    name_bn = TextField(max_length=120, required=False)
    name_en = TextField(max_length=120, required=False)
    is_active = serializers.BooleanField(required=False)


class DepartmentOut(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["code", "name_bn", "name_en", "is_active", "created_at"]


class CategoryIn(serializers.Serializer):
    department = serializers.CharField(max_length=20, help_text="Department code. Permanent.")
    code = serializers.RegexField(CODE, max_length=30, help_text=CODE_HELP)
    name_bn = TextField(max_length=120)
    name_en = TextField(max_length=120)
    target_working_days = serializers.IntegerField(min_value=1, max_value=365)


class CategoryPatchIn(serializers.Serializer):
    """No `department`: requests keep a copy of it, so a category never moves. To move a
    service, deactivate this category and create a new one."""

    name_bn = TextField(max_length=120, required=False)
    name_en = TextField(max_length=120, required=False)
    target_working_days = serializers.IntegerField(
        min_value=1,
        max_value=365,
        required=False,
        help_text="Changing it recomputes the deadlines of this category's open requests.",
    )
    is_active = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if "department" in self.initial_data:
            raise serializers.ValidationError(
                {"department": [_("A category's department never changes.")]}
            )
        return attrs


class CategoryAdminOut(serializers.ModelSerializer):
    department = serializers.CharField(source="department.code")

    class Meta:
        model = Category
        fields = [
            "code",
            "department",
            "name_bn",
            "name_en",
            "target_working_days",
            "is_active",
            "created_at",
        ]


# --- holidays and suspensions -----------------------------------------------------------------


class HolidayIn(serializers.Serializer):
    date = serializers.DateField()
    name_bn = TextField(max_length=120)
    name_en = TextField(max_length=120)


class HolidayOut(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = ["date", "name_bn", "name_en", "created_at"]


class SuspensionIn(serializers.Serializer):
    department = serializers.CharField(
        max_length=20, required=False, allow_null=True, help_text="Empty: the whole country."
    )
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    reason = TextField(max_length=500)

    def validate(self, attrs):
        if attrs["ends_on"] < attrs["starts_on"]:
            raise serializers.ValidationError({"ends_on": [_("Must not be before starts_on.")]})
        if (attrs["ends_on"] - attrs["starts_on"]).days > 365:
            raise serializers.ValidationError({"ends_on": [_("A suspension is at most a year.")]})
        return attrs


class SuspensionOut(serializers.ModelSerializer):
    department = serializers.CharField(source="scope_department.code", allow_null=True)

    class Meta:
        model = SlaSuspension
        fields = ["id", "department", "starts_on", "ends_on", "reason", "created_at"]


# --- users ------------------------------------------------------------------------------------


class NewOfficerIn(serializers.Serializer):
    phone = PhoneField(help_text="The officer's own phone: the password-setup code goes there.")
    full_name = TextField(max_length=120)
    department = serializers.CharField(max_length=20)


class UserPatchIn(serializers.Serializer):
    full_name = TextField(max_length=120, required=False)
    department = serializers.CharField(max_length=20, required=False, help_text="Officers only.")
    is_active = serializers.BooleanField(
        required=False, help_text="false ends every session of the account at once."
    )


class UserOut(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id")
    department = serializers.SlugRelatedField(slug_field="code", read_only=True)
    phone_verified = serializers.SerializerMethodField()
    two_step_login = serializers.SerializerMethodField()
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "phone",
            "full_name",
            "role",
            "department",
            "is_active",
            "phone_verified",
            "two_step_login",
            "has_password",
            "last_login",
            "created_at",
        ]

    def get_phone_verified(self, user) -> bool:
        return user.phone_verified_at is not None

    def get_two_step_login(self, user) -> bool:
        return user.totp_enabled_at is not None

    def get_has_password(self, user) -> bool:
        return user.has_usable_password()


class UserFilterIn(serializers.Serializer):
    role = serializers.ChoiceField(Role.choices, required=False)
    department = serializers.CharField(max_length=20, required=False)
    is_active = serializers.BooleanField(required=False, allow_null=True, default=None)
    phone = PhoneField(required=False)


# --- statistics -------------------------------------------------------------------------------


class StatsIn(serializers.Serializer):
    by = serializers.ChoiceField(["department", "category", "officer"], default="department")
    date_from = serializers.DateField(required=False, help_text="Default: 30 days ago.")
    date_to = serializers.DateField(required=False, help_text="Inclusive. Default: today.")

    def validate(self, attrs):
        first, last = attrs.get("date_from"), attrs.get("date_to")
        if first and last and last < first:
            raise serializers.ValidationError({"date_to": [_("Must not be before date_from.")]})
        if first and last and (last - first).days > 400:
            raise serializers.ValidationError({"date_to": [_("At most 400 days at a time.")]})
        return attrs


class _Group(serializers.Serializer):
    code = serializers.CharField(allow_null=True)
    name = serializers.CharField(allow_null=True)


class _Counts(serializers.Serializer):
    submitted = serializers.IntegerField()
    open = serializers.IntegerField()
    overdue = serializers.IntegerField()
    resolved = serializers.IntegerField()
    rejected = serializers.IntegerField()
    withdrawn = serializers.IntegerField()


class _Primary(serializers.Serializer):
    on_time_resolution_rate = serializers.FloatField(allow_null=True)
    median_days_to_resolve = serializers.FloatField(allow_null=True)
    resolution_rate = serializers.FloatField(allow_null=True)
    resolved = serializers.IntegerField()


class _Counter(serializers.Serializer):
    info_request_rate = serializers.FloatField(allow_null=True)
    median_days_paused = serializers.FloatField(allow_null=True)
    rejection_rate = serializers.FloatField(allow_null=True)
    late_rejections = serializers.IntegerField()
    reopen_rate_after_resolution = serializers.FloatField(allow_null=True)
    reopen_rate_after_rejection = serializers.FloatField(allow_null=True)
    reassignment_rate = serializers.FloatField(allow_null=True)
    withdrawn_after_deadline = serializers.IntegerField()


class _Metrics(serializers.Serializer):
    counts = _Counts()
    primary = _Primary()
    counter = _Counter(help_text="The numbers that would show the primary ones being gamed.")


class _GroupMetrics(_Metrics):
    group = _Group()


class StatsOut(serializers.Serializer):
    by = serializers.CharField()
    date_from = serializers.DateField(source="from")
    date_to = serializers.DateField(source="to")
    totals = _Metrics()
    groups = _GroupMetrics(many=True)


# --- review queue -----------------------------------------------------------------------------


class ReviewFilterIn(serializers.Serializer):
    status = serializers.ChoiceField(ReviewStatus.choices, required=False)
    reason = serializers.ChoiceField(ReviewReason.choices, required=False)
    department = serializers.CharField(max_length=20, required=False)


class ReviewRequestOut(serializers.Serializer):
    id = serializers.UUIDField(source="public_id")
    tracking_no = serializers.CharField()
    status = serializers.CharField()
    department = serializers.CharField(source="department.code")
    category = serializers.CharField(source="category.code")
    resolution_note = serializers.CharField(allow_null=True)
    rejection_reason_code = serializers.CharField(allow_null=True)
    rejection_note = serializers.CharField(allow_null=True)


class ReviewPersonOut(serializers.Serializer):
    id = serializers.UUIDField(source="public_id")
    full_name = serializers.CharField()


class ReviewOut(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id")
    request = ReviewRequestOut()
    officer = ReviewPersonOut()
    reviewer = ReviewPersonOut(allow_null=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "request",
            "reason",
            "decided_status",
            "officer",
            "status",
            "reviewer",
            "note",
            "reviewed_at",
            "created_at",
        ]


class ReviewDecisionIn(serializers.Serializer):
    decision = serializers.ChoiceField(["UPHOLD", "OVERTURN"])
    note = TextField(multiline=True, max_length=2000, required=False, allow_blank=True)

    def validate(self, data):
        if data["decision"] == "OVERTURN" and len((data.get("note") or "").strip()) < 10:
            raise serializers.ValidationError(
                {"note": _("Say why the decision is overturned (at least 10 characters).")}
            )
        return data
