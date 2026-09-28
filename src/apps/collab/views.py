"""HTTP for comments and attachments. Thin: validate, call a service, shape the answer."""

from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAnyUser
from apps.common import idempotency
from apps.common.pagination import OldestFirstPagination
from apps.common.schema import errors

from . import serializers, services, storage

TAG = ["comments and files"]
IDEMPOTENCY_KEY = OpenApiParameter(
    "Idempotency-Key",
    str,
    OpenApiParameter.HEADER,
    required=True,
    description="8 to 64 letters, digits, - or _. Reuse it on retries.",
)


def _input(serializer_class, request):
    s = serializer_class(data=request.data)
    s.is_valid(raise_exception=True)
    return s.validated_data


class CommentsView(APIView):
    permission_classes = [IsAnyUser]

    @extend_schema(
        tags=TAG,
        responses={200: serializers.CommentOut(many=True), **errors(e404=["NOT_FOUND"])},
        description="Oldest first. Citizens do not see internal comments.",
    )
    def get(self, request, request_id):
        req = services.visible_request(request.user, request_id)
        paginator = OldestFirstPagination()
        page = paginator.paginate_queryset(services.comments_for(request.user, req), request)
        data = serializers.CommentOut(page, many=True, context={"viewer": request.user}).data
        return paginator.get_paginated_response(data)

    @extend_schema(
        tags=TAG,
        request=serializers.CommentIn,
        responses={
            201: serializers.CommentOut,
            **errors(
                e400=["VALIDATION_ERROR"],
                e403=["NOT_ALLOWED"],
                e404=["NOT_FOUND"],
                e409=["NOT_SUBMITTED"],
            ),
        },
        description="A citizen's comment while the office waits on them resumes the request "
        "(unless `respond` is false). A public staff comment sends the citizen an SMS.",
    )
    def post(self, request, request_id):
        data = _input(serializers.CommentIn, request)
        comment, _req = services.add_comment(
            request.user,
            request_id,
            data["body"],
            internal=data["internal"],
            respond=data["respond"],
            http_request=request,
        )
        body = serializers.CommentOut(comment, context={"viewer": request.user}).data
        return Response(body, status=status.HTTP_201_CREATED)


class AttachmentsView(APIView):
    permission_classes = [IsAnyUser]

    @extend_schema(
        tags=TAG,
        responses={200: serializers.AttachmentOut(many=True), **errors(e404=["NOT_FOUND"])},
    )
    def get(self, request, request_id):
        req = services.visible_request(request.user, request_id)
        rows = req.attachments.order_by("created_at", "id")
        return Response(serializers.AttachmentOut(rows, many=True).data)

    @extend_schema(
        tags=TAG,
        parameters=[IDEMPOTENCY_KEY],
        request=serializers.AttachmentIn,
        responses={
            201: serializers.AttachmentCreatedOut,
            **errors(
                e400=["VALIDATION_ERROR", "IDEMPOTENCY_KEY_REQUIRED"],
                e404=["NOT_FOUND"],
                e409=["REQUEST_CLOSED", "TOO_MANY_ATTACHMENTS"],
                e422=["IDEMPOTENCY_KEY_REUSED"],
            ),
        },
        description="Step 1 of 3. Returns an upload URL: PUT the file there with exactly the "
        "headers given (the size is part of the signature). Step 2: POST "
        "/attachments/{id}/confirm. Step 3: the file is checked (type, size, SHA-256, virus "
        "scan) and becomes READY or REJECTED. PDF, JPEG or PNG, at most 10 MB.",
    )
    def post(self, request, request_id):
        data = _input(serializers.AttachmentIn, request)
        key = idempotency.read_key(request)
        fp = idempotency.fingerprint(request.method, request.path, data)

        def create():
            attachment = services.start_upload(request.user, request_id, data, request)
            upload = {
                "method": "PUT",
                "url": storage.upload_url(
                    attachment.storage_key, data["content_type"], data["size"]
                ),
                "headers": {
                    "Content-Type": data["content_type"],
                    "Content-Length": str(data["size"]),
                },
                "expires_at": timezone.now() + storage.UPLOAD_TTL,
            }
            out = serializers.AttachmentCreatedOut(attachment, context={"upload": upload})
            return status.HTTP_201_CREATED, out.data

        code, body, replayed = idempotency.once(request.user, key, fp, create)
        headers = {"Idempotent-Replayed": "true"} if replayed else {}
        return Response(body, status=code, headers=headers)


class AttachmentView(APIView):
    permission_classes = [IsAnyUser]

    @extend_schema(
        tags=TAG, responses={200: serializers.AttachmentOut, **errors(e404=["NOT_FOUND"])}
    )
    def get(self, request, attachment_id):
        attachment = services.visible_attachment(request.user, attachment_id)
        return Response(serializers.AttachmentOut(attachment).data)


class AttachmentConfirmView(APIView):
    permission_classes = [IsAnyUser]

    @extend_schema(
        tags=TAG,
        request=None,
        responses={
            202: serializers.AttachmentOut,
            **errors(e404=["NOT_FOUND"], e409=["ATTACHMENT_REJECTED"]),
        },
        description="The uploader says the file is uploaded; checks start. Safe to repeat.",
    )
    def post(self, request, attachment_id):
        attachment = services.confirm_upload(request.user, attachment_id, request)
        return Response(serializers.AttachmentOut(attachment).data, status=status.HTTP_202_ACCEPTED)


class AttachmentDownloadView(APIView):
    permission_classes = [IsAnyUser]

    @extend_schema(
        tags=TAG,
        responses={
            200: serializers.DownloadOut,
            **errors(e404=["NOT_FOUND"], e409=["ATTACHMENT_NOT_READY"]),
        },
        description="A download URL valid for 5 minutes, only for a file that passed its checks.",
    )
    def get(self, request, attachment_id):
        attachment = services.visible_attachment(request.user, attachment_id)
        url = services.download(request.user, attachment)
        return Response({"url": url, "expires_at": timezone.now() + storage.DOWNLOAD_TTL})
