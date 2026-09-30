"""The API reference page: Scalar, reading the OpenAPI schema at /api/schema/.

Scalar's script is served by our own Nginx (built into its image from a checksum-pinned npm
release, see web/Dockerfile), never from a CDN. The page's Content-Security-Policy allows
nothing from another origin, so fonts, a request proxy or anything else Scalar might reach for
stays off even if a setting below is missed.
"""

import json

from django.http import HttpResponse
from django.utils.html import escape
from django.views.decorators.http import require_GET

SCRIPT = "/vendor/scalar/standalone.js"

CONFIG = {
    "url": "/api/schema/",
    "theme": "default",
    "layout": "modern",
    "withDefaultFonts": False,  # would load fonts from fonts.scalar.com
    "hideClientButton": True,  # would send the schema to Scalar's hosted client
    "showToolbar": "never",  # Scalar's own share and deploy menus
    "showDeveloperTools": "never",
    "persistAuth": True,  # a pasted token survives reloading the page
    "defaultOpenAllTags": False,
    "showSidebar": True,
    "hideDownloadButton": False,
    "documentDownloadType": "json",
    "defaultHttpClient": {"targetKey": "shell", "clientKey": "curl"},
    "authentication": {"preferredSecurityScheme": "bearerAuth"},
    "agent": {"disabled": True},
    "mcp": {"disabled": True},
    "telemetry": False,
}

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",  # Scalar sets styles at run time
        "img-src 'self' data:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
)

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Government Service Request API</title>
<style>body{{margin:0}}</style>
</head>
<body>
<script id="api-reference" data-url="/api/schema/" data-configuration="{config}"></script>
<script src="{script}"></script>
</body>
</html>
"""


@require_GET
def api_docs(request):
    body = PAGE.format(config=escape(json.dumps(CONFIG)), script=SCRIPT)
    response = HttpResponse(body, content_type="text/html; charset=utf-8")
    response["Content-Security-Policy"] = CSP
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "same-origin"
    return response
