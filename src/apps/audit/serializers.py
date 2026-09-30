from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.common.fields import TextField

from .models import AccessEvent, BreakGlassReason


class _Office(serializers.Serializer):
    code = serializers.CharField()
    name_bn = serializers.CharField()
    name_en = serializers.CharField()


class _Actor(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class AccessOut(serializers.ModelSerializer):
    """The citizen's view: which office looked, in which role, when. Never a name:
    decisions are the office's, and officers are not exposed to pressure."""

    at = serializers.DateTimeField(source="created_at")
    role = serializers.CharField(source="actor_role")
    office = serializers.SerializerMethodField()
    break_glass = serializers.SerializerMethodField()

    class Meta:
        model = AccessEvent
        fields = ["kind", "at", "role", "office", "break_glass"]

    @extend_schema_field(_Office(allow_null=True))
    def get_office(self, event):
        dept = self.context["departments"].get(event.actor_department_id)
        return (
            {"code": dept.code, "name_bn": dept.name_bn, "name_en": dept.name_en} if dept else None
        )

    def get_break_glass(self, event) -> bool:
        return event.break_glass_reason is not None


class AuditorAccessOut(AccessOut):
    """Administrators and auditors see who, and why when it was outside their scope."""

    actor = serializers.SerializerMethodField()

    class Meta(AccessOut.Meta):
        fields = [*AccessOut.Meta.fields, "actor", "break_glass_reason", "break_glass_note"]

    @extend_schema_field(_Actor(allow_null=True))
    def get_actor(self, event):
        user = self.context["users"].get(event.actor_id)
        return {"id": user.public_id, "name": user.full_name} if user else None


class _RequestRef(serializers.Serializer):
    id = serializers.UUIDField()
    tracking_no = serializers.CharField()


class BreakGlassReportOut(AuditorAccessOut):
    request = serializers.SerializerMethodField()

    class Meta(AuditorAccessOut.Meta):
        fields = [*AuditorAccessOut.Meta.fields, "request"]

    @extend_schema_field(_RequestRef(allow_null=True))
    def get_request(self, event):
        req = self.context["requests"].get(event.request_id)
        return {"id": req.public_id, "tracking_no": req.tracking_no} if req else None


class BreakGlassIn(serializers.Serializer):
    tracking_no = serializers.CharField(max_length=32, help_text="As the citizen reads it out.")
    reason = serializers.ChoiceField(BreakGlassReason.choices)
    note = TextField(max_length=500, required=False, allow_blank=True, multiline=True)

    def validate(self, attrs):
        if attrs["reason"] == BreakGlassReason.OTHER and len(attrs.get("note") or "") < 20:
            raise serializers.ValidationError(
                {"note": [_("Explain the reason in at least 20 characters.")]}
            )
        return attrs
