"""Serializer fields that normalise what people type before any rule sees it."""

from django.conf import settings
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .phone import normalise_phone
from .text import clean_text


class PhoneField(serializers.CharField):
    default_error_messages = {
        "invalid_phone": _("Enter a Bangladeshi mobile number, for example 01712345678."),
    }

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 32)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        phone = normalise_phone(super().to_internal_value(data))
        if phone is None:
            self.fail("invalid_phone")
        return phone


class TextField(serializers.CharField):
    """NFC-normalised, trimmed, control characters removed; length counted after cleaning."""

    def __init__(self, multiline: bool = False, **kwargs):
        self.multiline = multiline
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        value = super().to_internal_value(clean_text(data, self.multiline))
        if value == "" and not self.allow_blank:
            self.fail("blank")  # only invisible characters were typed
        return value


class PasswordField(serializers.CharField):
    """Never trimmed or normalised: the password is exactly what was typed."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", settings.PASSWORD_MAX_LENGTH)
        kwargs.update(trim_whitespace=False, write_only=True, style={"input_type": "password"})
        super().__init__(**kwargs)
