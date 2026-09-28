"""One error shape for every failure: {"error": {"code", "message", "fields", "request_id"}}.

Clients branch on `code`, which never changes; `message` is for people and is localised.
"""

import logging

from django.http import JsonResponse
from django.utils.translation import gettext as _
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .request_id import get_request_id

logger = logging.getLogger(__name__)


class AppError(exceptions.APIException):
    """A domain error with a stable code, e.g. AppError("INVALID_TRANSITION", "...", 409)."""

    def __init__(self, code: str, message: str, status_code: int = 400, fields=None, wait=None):
        super().__init__(detail=message, code=code)
        self.status_code = status_code
        self.error_code = code
        self.fields = fields or {}
        self.wait = wait  # seconds; DRF sends it as Retry-After


# DRF's built-in exceptions, renamed to the codes this API documents.
_CODES = {
    "not_authenticated": "NOT_AUTHENTICATED",
    "authentication_failed": "AUTHENTICATION_FAILED",
    "permission_denied": "PERMISSION_DENIED",
    "not_found": "NOT_FOUND",
    "method_not_allowed": "METHOD_NOT_ALLOWED",
    "not_acceptable": "NOT_ACCEPTABLE",
    "unsupported_media_type": "UNSUPPORTED_MEDIA_TYPE",
    "parse_error": "MALFORMED_REQUEST",
    "throttled": "RATE_LIMITED",
}


def envelope(code: str, message: str, fields: dict | None = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "fields": fields or {},
            "request_id": get_request_id(),
        }
    }


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None  # unhandled: Django logs it and handler500 answers

    if isinstance(exc, AppError):
        body = envelope(exc.error_code, str(exc.detail), exc.fields)
    elif isinstance(exc, exceptions.ValidationError):
        detail = exc.detail
        fields = detail if isinstance(detail, dict) else {"non_field_errors": detail}
        body = envelope("VALIDATION_ERROR", _("Some fields are invalid."), fields)
    else:
        code = _CODES.get(getattr(exc, "default_code", ""), "ERROR")
        body = envelope(code, str(getattr(exc, "detail", exc)))

    response.data = body
    return response


def not_found(request, exception=None):
    return JsonResponse(envelope("NOT_FOUND", _("Not found.")), status=status.HTTP_404_NOT_FOUND)


def server_error(request):
    return JsonResponse(
        envelope("INTERNAL_ERROR", _("Something went wrong. Please try again.")),
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def error_response(code: str, message: str, status_code: int, headers=None) -> Response:
    return Response(envelope(code, message), status=status_code, headers=headers)
