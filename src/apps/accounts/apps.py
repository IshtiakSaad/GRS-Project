from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"

    def ready(self):
        check_keys()
        from . import schema  # noqa: F401 - registers the Bearer scheme with the API docs


def check_keys() -> None:
    """Refuse to start with keys that would make tokens forgeable or secrets unreadable."""
    from cryptography.fernet import Fernet
    from django.conf import settings

    keys = settings.JWT_SIGNING_KEYS
    if settings.JWT_ACTIVE_KID not in keys:
        raise ImproperlyConfigured("JWT_ACTIVE_KID must name one of JWT_SIGNING_KEYS")
    for kid, secret in keys.items():
        if len(secret.encode()) < 32:  # RFC 7518 §3.2: HS256 keys of at least 256 bits
            raise ImproperlyConfigured(f"JWT signing key {kid!r} is shorter than 32 bytes")
    if not settings.FIELD_ENCRYPTION_KEYS:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS is empty")
    for key in settings.FIELD_ENCRYPTION_KEYS:
        try:
            Fernet(key)
        except ValueError as exc:
            raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS holds an invalid key") from exc
