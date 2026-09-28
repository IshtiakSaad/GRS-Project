from django.db.models import Exists, OuterRef
from django.utils.translation import gettext as _
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from . import tokens
from .models import RefreshSession, User


class JWTAuthentication(BaseAuthentication):
    """Bearer access tokens, checked against the account on every request.

    One indexed query per request confirms the account is active, its token_version matches
    (deactivation, role or password change take effect at once) and the login session was not
    ended. That read is cheap next to the certainty it buys over a cache.
    """

    def authenticate(self, request):
        header = get_authorization_header(request).split()
        if not header or header[0].lower() != b"bearer":
            return None
        failed = exceptions.AuthenticationFailed(
            _("Your session has expired. Please log in again.")
        )
        if len(header) != 2:
            raise failed
        try:
            claims = tokens.read_access(header[1].decode("ascii"))
        except (tokens.TokenError, UnicodeDecodeError) as exc:
            raise failed from exc

        ended = RefreshSession.objects.filter(
            family_id=claims["sid"], user=OuterRef("pk"), revoked_at__isnull=False
        )
        user = (
            User.objects.select_related("department")
            .annotate(session_ended=Exists(ended))
            .filter(public_id=claims["sub"])
            .first()
        )
        if (
            user is None
            or not user.is_active
            or user.token_version != claims["ver"]
            or user.session_ended
        ):
            raise failed
        return user, claims

    def authenticate_header(self, request):
        return 'Bearer realm="api"'
