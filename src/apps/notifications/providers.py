"""Where messages leave the system. Called by the delivery worker only, never in a web request."""

import logging

from django.conf import settings
from django.core.mail import send_mail

from .models import DemoSms

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    pass


def _masked(phone: str) -> str:
    return phone[:6] + "*****" + phone[-2:]


def send_sms(phone: str, body: str) -> str:
    """Returns the provider's message id. Only the fake exists until a gateway is chosen."""
    if settings.SMS_BACKEND != "fake":
        raise ProviderError(f"unknown SMS backend {settings.SMS_BACKEND!r}")
    if not settings.DEMO_MODE:
        # Outside demo mode the fake would keep real people's codes in a table, unsent.
        raise ProviderError("the fake SMS provider runs only in demo mode")
    message = DemoSms.objects.create(phone=phone, body=body)
    logger.info("fake sms stored for %s", _masked(phone))  # never the body: it may hold a code
    return f"fake-{message.pk}"


def send_email(address: str, subject: str, body: str) -> str:
    try:
        send_mail(subject, body, None, [address], fail_silently=False)
    except OSError as exc:  # SMTP errors are OSError subclasses
        raise ProviderError(str(exc)) from exc
    return ""
