from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import Role
from apps.common.fields import TextField

from .models import MAX_ATTACHMENT_BYTES, Attachment, Comment
from .scanning import ALLOWED_TYPES


class CommentIn(serializers.Serializer):
    body = TextField(max_length=5000, multiline=True)
    internal = serializers.BooleanField(
        default=False, help_text="Staff only: never shown to the citizen."
    )
    respond = serializers.BooleanField(
        default=True,
        help_text="Citizens: while the office waits on you, your comment is your answer and "
        "resumes the request. Send false to add a note without resuming.",
    )


class _Author(serializers.Serializer):
    role = serializers.CharField()
    department = serializers.CharField(allow_null=True)
    name = serializers.CharField(required=False)


class CommentOut(serializers.ModelSerializer):
    """Citizens see who wrote a staff comment as a role and office, never a name (design §7.5)."""

    id = serializers.UUIDField(source="public_id")
    internal = serializers.BooleanField(source="is_internal")
    author = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ["id", "body", "internal", "author", "created_at"]

    @extend_schema_field(_Author)
    def get_author(self, comment):
        author = comment.author
        department = author.department.code if author.department_id else None
        shown = {"role": author.role, "department": department}
        viewer = self.context["viewer"]
        if viewer.role != Role.CITIZEN or author.pk == viewer.pk:
            shown["name"] = author.full_name
        return shown


class AttachmentIn(serializers.Serializer):
    file_name = TextField(max_length=255)
    content_type = serializers.ChoiceField(
        ALLOWED_TYPES, error_messages={"invalid_choice": _("Upload a PDF, JPEG or PNG file.")}
    )
    size = serializers.IntegerField(
        min_value=1,
        max_value=MAX_ATTACHMENT_BYTES,
        help_text="Exact size in bytes; at most 10 MB.",
        error_messages={"max_value": _("Files can be at most 10 MB.")},
    )


class AttachmentOut(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id")
    name = serializers.CharField(source="original_name")
    content_type = serializers.CharField(source="declared_content_type")
    size = serializers.IntegerField(source="declared_size")

    class Meta:
        model = Attachment
        fields = [
            "id",
            "name",
            "content_type",
            "size",
            "status",
            "rejection_reason",
            "sha256",
            "created_at",
            "verified_at",
        ]


class UploadOut(serializers.Serializer):
    method = serializers.CharField()
    url = serializers.URLField()
    headers = serializers.DictField(child=serializers.CharField())
    expires_at = serializers.DateTimeField()


class AttachmentCreatedOut(AttachmentOut):
    upload = serializers.SerializerMethodField()

    class Meta(AttachmentOut.Meta):
        fields = [*AttachmentOut.Meta.fields, "upload"]

    @extend_schema_field(UploadOut)
    def get_upload(self, attachment):
        return self.context["upload"]


class DownloadOut(serializers.Serializer):
    url = serializers.URLField()
    expires_at = serializers.DateTimeField()
