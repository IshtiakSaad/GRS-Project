"""Tells the OpenAPI schema how to log in, so the API reference offers a Bearer field for tokens.

Loaded from AccountsConfig.ready(): drf-spectacular finds extensions by import.
"""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class JWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.JWTAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "The `access` token from POST /api/v1/auth/login (10 minutes). "
            "Administrators use the one from /auth/2fa/verify.",
        }
