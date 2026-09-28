"""Production profile: behind Nginx with TLS."""

from django.core.exceptions import ImproperlyConfigured

from .base import *

# The placeholder secrets in .env.example and the test settings are public; production must
# never start with them. (The last marker is the base64 of the example Fernet key.)
_PLACEHOLDERS = ("local-dev-only", "test-only", "bG9jYWwtZGV2LW9ubHkt")
_secrets = [SECRET_KEY, *JWT_SIGNING_KEYS.values(), *FIELD_ENCRYPTION_KEYS]
if any(marker in value for marker in _PLACEHOLDERS for value in _secrets):
    raise ImproperlyConfigured("placeholder secrets in production settings")

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
