"""Request payloads. Three views of a request: the owner's, staff's, and the short list rows
staff see (tracking number, category, status, priority, due date, initials)."""

from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import Role
from apps.common.fields import TextField
from apps.directory.models import Category

from .models import PauseReason, Priority, RejectionReason, Relation, ServiceRequest, Status


class PriorityField(serializers.ChoiceField):
    """Priority by name (LOW, NORMAL, HIGH, URGENT); stored as a number so it sorts."""

    def __init__(self, **kwargs):
        super().__init__(Priority.names, **kwargs)

    def to_internal_value(self, data):
        return Priority[super().to_internal_value(data)].value

    def to_representation(self, value):
        return Priority(value).name


class CategoryOut(serializers.ModelSerializer):
    department = serializers.CharField(source="department.code")

    class Meta:
        model = Category
        fields = ["code", "name_bn", "name_en", "department", "target_working_days"]


class BeneficiaryIn(serializers.Serializer):
    name = TextField(max_length=120)
    relation = serializers.ChoiceField(Relation.choices)


class DraftIn(serializers.Serializer):
    category = serializers.CharField(max_length=30, help_text="A code from GET /categories.")
    title = TextField(max_length=200)
    description = TextField(max_length=5000, multiline=True)
    beneficiary = BeneficiaryIn(
        required=False,
        allow_null=True,
        help_text="The person the request is for, if not the account owner.",
    )
    citizen_urgent = serializers.BooleanField(default=False)
    urgency_reason = TextField(max_length=500, required=False, allow_null=True)

    def validate(self, attrs):
        # Priority is the office's call. Saying so beats silently dropping the field.
        if "priority" in self.initial_data:
            raise serializers.ValidationError(
                {"priority": _("The office sets priority. Mark the request urgent instead.")}
            )
        return attrs


class ListFilterIn(serializers.Serializer):
    status = serializers.ChoiceField(Status.choices, required=False)
    category = serializers.CharField(max_length=30, required=False, help_text="Category code.")
    department = serializers.CharField(max_length=20, required=False, help_text="Department code.")
    officer = serializers.UUIDField(required=False, help_text="Assigned officer's id.")
    overdue = serializers.BooleanField(
        required=False, help_text="true: open requests past their deadline."
    )


# --- action inputs ----------------------------------------------------------------------------


class SubmitIn(serializers.Serializer):
    confirm_duplicate = serializers.BooleanField(
        default=False, help_text="Send true after a POSSIBLE_DUPLICATE answer to submit anyway."
    )


class OfficerIn(serializers.Serializer):
    officer = serializers.UUIDField()


class ReassignIn(OfficerIn):
    reason = TextField(max_length=500)


class RequestInfoIn(serializers.Serializer):
    reason_code = serializers.ChoiceField(PauseReason.choices)
    message = TextField(max_length=2000, multiline=True)


class MessageIn(serializers.Serializer):
    message = TextField(max_length=2000, multiline=True)


class ReasonIn(serializers.Serializer):
    reason = TextField(max_length=500)


class OptionalReasonIn(serializers.Serializer):
    reason = TextField(max_length=500, required=False, allow_blank=True)


class ResolveIn(serializers.Serializer):
    note = TextField(max_length=5000, multiline=True)


class RejectIn(serializers.Serializer):
    reason_code = serializers.ChoiceField(RejectionReason.choices)
    note = TextField(max_length=5000, multiline=True)


class PriorityIn(serializers.Serializer):
    priority = PriorityField()


class EmptyIn(serializers.Serializer):
    pass


ACTION_INPUTS = {
    "submit": SubmitIn,
    "assign": OfficerIn,
    "reassign": ReassignIn,
    "start": EmptyIn,
    "request_info": RequestInfoIn,
    "respond": MessageIn,
    "resume": ReasonIn,
    "resolve": ResolveIn,
    "reject": RejectIn,
    "withdraw": OptionalReasonIn,
    "reopen": ReasonIn,
}


# --- outputs ----------------------------------------------------------------------------------


class _Category(serializers.Serializer):
    code = serializers.CharField()
    name_bn = serializers.CharField()
    name_en = serializers.CharField()


class _Beneficiary(serializers.Serializer):
    name = serializers.CharField(source="beneficiary_name")
    relation = serializers.CharField(source="beneficiary_relation")


class _Party(serializers.Serializer):
    id = serializers.UUIDField(source="public_id")
    name = serializers.CharField(source="full_name")
    phone = serializers.CharField()


class _Department(serializers.Serializer):
    code = serializers.CharField()
    name_bn = serializers.CharField()
    name_en = serializers.CharField()


class _HandledBy(serializers.Serializer):
    role = serializers.CharField()
    department = _Department()


class _Officer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class RequestOut(serializers.ModelSerializer):
    """The owner's view. The handling officer is shown as a role and office, never a name:
    decisions are the office's, and officers are not exposed to pressure."""

    id = serializers.UUIDField(source="public_id")
    category = _Category()
    beneficiary = serializers.SerializerMethodField()
    priority = PriorityField()
    handled_by = serializers.SerializerMethodField()

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "tracking_no",
            "status",
            "category",
            "title",
            "description",
            "beneficiary",
            "citizen_urgent",
            "urgency_reason",
            "priority",
            "handled_by",
            "submitted_at",
            "due_at",
            "resolved_at",
            "closed_at",
            "reopen_deadline",
            "resolution_note",
            "rejection_reason_code",
            "rejection_note",
            "info_request_count",
            "reopen_count",
            "version",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(_Beneficiary(allow_null=True))
    def get_beneficiary(self, obj):
        return _Beneficiary(obj).data if obj.beneficiary_name else None

    @extend_schema_field(_HandledBy(allow_null=True))
    def get_handled_by(self, obj):
        if obj.assigned_officer_id is None:
            return None
        return {"role": Role.OFFICER, "department": _Department(obj.department).data}


class StaffRequestOut(RequestOut):
    """Staff open a request to work on it, so they see who it belongs to and who holds it."""

    owner = _Party()
    assigned_officer = serializers.SerializerMethodField()

    class Meta(RequestOut.Meta):
        fields = [*RequestOut.Meta.fields, "owner", "assigned_officer", "reassignment_count"]

    @extend_schema_field(_Officer(allow_null=True))
    def get_assigned_officer(self, obj):
        officer = obj.assigned_officer
        return {"id": officer.public_id, "name": officer.full_name} if officer else None


class RequestRowOut(serializers.ModelSerializer):
    """A row of the citizen's own list."""

    id = serializers.UUIDField(source="public_id")
    category = serializers.CharField(source="category.code")

    class Meta:
        model = ServiceRequest
        fields = ["id", "tracking_no", "status", "title", "category", "submitted_at", "due_at"]


class StaffRowOut(serializers.ModelSerializer):
    """A row of a staff list: enough to choose what to open, nothing personal."""

    id = serializers.UUIDField(source="public_id")
    category = serializers.CharField(source="category.code")
    priority = PriorityField()
    owner_initials = serializers.SerializerMethodField()

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "tracking_no",
            "category",
            "status",
            "priority",
            "citizen_urgent",
            "due_at",
            "submitted_at",
            "owner_initials",
        ]

    def get_owner_initials(self, obj) -> str:
        return "".join(f"{word[0]}." for word in obj.owner.full_name.split()[:3])


class EventOut(serializers.Serializer):
    type = serializers.CharField(source="event_type")
    from_status = serializers.CharField()
    to_status = serializers.CharField()
    actor_role = serializers.CharField()
    data = serializers.JSONField()
    at = serializers.DateTimeField(source="created_at")


class StaffEventOut(EventOut):
    actor = serializers.UUIDField(source="actor.public_id", allow_null=True)
    is_public = serializers.BooleanField()


class QueueOut(serializers.Serializer):
    waiting = serializers.IntegerField()
    requests = StaffRowOut(many=True)
