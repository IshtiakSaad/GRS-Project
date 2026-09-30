"""Production profile: behind Nginx with TLS."""

from django.core.exceptions import ImproperlyConfigured

from .base import *

# The placeholder secrets in .env.example and the test settings are public; production must
# never start with them. (The last marker is the base64 of the example Fernet key.)
_PLACEHOLDERS = ("local-dev-only", "test-only", "bG9jYWwtZGV2LW9ubHkt", "grs-local")
_secrets = [SECRET_KEY, *JWT_SIGNING_KEYS.values(), *FIELD_ENCRYPTION_KEYS, S3_SECRET_KEY]
if any(marker in value for marker in _PLACEHOLDERS for value in _secrets):
    raise ImproperlyConfigured("placeholder secrets in production settings")

# Links in emails and the sender address follow the domain unless set outright. A link to
# localhost in a real inbox opens nothing, and Mailpit delivers nothing: refuse both.
GRS_DOMAIN = env("GRS_DOMAIN")
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default=f"https://{GRS_DOMAIN}")
# A display name: a bare no-reply address is one more thing spam filters count against a mail.
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL", default=f"Grievance & Service Requests <no-reply@{GRS_DOMAIN}>"
)
if not PUBLIC_BASE_URL.startswith("https://") or "localhost" in PUBLIC_BASE_URL:
    raise ImproperlyConfigured(f"PUBLIC_BASE_URL must be the public https URL: {PUBLIC_BASE_URL}")
if (
    EMAIL_HOST == "mailpit"
    or "example." in DEFAULT_FROM_EMAIL
    or (EMAIL_HOST_USER and not EMAIL_HOST_PASSWORD)
):
    raise ImproperlyConfigured("production email needs a real SMTP relay and sender (EMAIL_HOST)")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = False
SECURE_SSL_REDIRECT = False  # Nginx redirects; the health check reaches the app over plain HTTP
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
