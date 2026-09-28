"""OpenAPI helpers: the error envelope, and which error codes each endpoint can answer with.

Clients branch on `error.code`, so the docs list the codes per status, not just the status.
"""

from drf_spectacular.utils import OpenApiExample, OpenApiResponse, inline_serializer
from rest_framework import serializers

ErrorOut = inline_serializer(
    "Error",
    {
        "error": inline_serializer(
            "ErrorBody",
            {
                "code": serializers.CharField(help_text="Stable; branch on this."),
                "message": serializers.CharField(help_text="Localised (Accept-Language)."),
                "fields": serializers.DictField(
                    help_text="Per-field messages, or extra data such as `tracking_no`."
                ),
                "request_id": serializers.CharField(help_text="Quote it when reporting."),
            },
        )
    },
)

# Codes every authenticated endpoint can return, whatever it does.
AUTH_CODES = {401: ["NOT_AUTHENTICATED", "AUTHENTICATION_FAILED"], 403: ["PERMISSION_DENIED"]}


def _example(code: str, message: str, fields=None) -> OpenApiExample:
    return OpenApiExample(
        code,
        value={
            "error": {
                "code": code,
                "message": message,
                "fields": fields or {},
                "request_id": "0b6f4c1e9d2a4f7e",
            }
        },
        response_only=True,
    )


EXAMPLES = {
    "VALIDATION_ERROR": _example(
        "VALIDATION_ERROR", "Some fields are invalid.", {"title": ["This field is required."]}
    ),
    "NOT_AUTHENTICATED": _example(
        "NOT_AUTHENTICATED", "Authentication credentials were not provided."
    ),
    "NOT_FOUND": _example("NOT_FOUND", "Not found."),
    "INVALID_TRANSITION": _example(
        "INVALID_TRANSITION", "This cannot be done while the request is in this state."
    ),
    "POSSIBLE_DUPLICATE": _example(
        "POSSIBLE_DUPLICATE",
        "You submitted the same request a few minutes ago.",
        {"tracking_no": "26-0004213-7"},
    ),
    "PRECONDITION_FAILED": _example(
        "PRECONDITION_FAILED", "Someone else changed this request. Reload it and try again."
    ),
    "LOGIN_DELAYED": _example("LOGIN_DELAYED", "Too many failed attempts. Try again in 2 minutes."),
}


def errors(authenticated: bool = True, **by_status: list[str]) -> dict:
    """`errors(e409=["INVALID_TRANSITION"])` → responses for extend_schema.

    Statuses are given as e<status> because keyword names cannot start with a digit."""
    codes: dict[int, list[str]] = {}
    if authenticated:
        for status, names in AUTH_CODES.items():
            codes.setdefault(status, []).extend(names)
    for key, names in by_status.items():
        codes.setdefault(int(key.removeprefix("e")), []).extend(names)
    return {
        status: OpenApiResponse(
            ErrorOut,
            description="Error codes: " + ", ".join(f"`{n}`" for n in names),
            examples=[EXAMPLES[n] for n in names if n in EXAMPLES],
        )
        for status, names in sorted(codes.items())
    }
