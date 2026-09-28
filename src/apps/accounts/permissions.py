"""Who may call a view. Every view names one of these explicitly (checked by a meta-test)."""

from rest_framework.permissions import BasePermission

from .models import Role


class _HasRole(BasePermission):
    roles: tuple[str, ...] = ()

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.role in self.roles):
            return False
        # An administrator's token is worth nothing without the second step, on every route.
        return user.role != Role.ADMIN or bool(request.auth and request.auth.get("mfa"))


class IsAnyUser(_HasRole):
    roles = (Role.CITIZEN, Role.OFFICER, Role.ADMIN)


class IsCitizen(_HasRole):
    roles = (Role.CITIZEN,)


class IsStaff(_HasRole):
    roles = (Role.OFFICER, Role.ADMIN)


class IsOfficer(_HasRole):
    roles = (Role.OFFICER,)


class IsAdmin(_HasRole):
    """Administrators (with a two-step session, like every admin route)."""

    roles = (Role.ADMIN,)


class IsPublic(BasePermission):
    """No login needed. Named, rather than DRF's AllowAny, so that opening a view is a visible,
    searchable decision."""

    def has_permission(self, request, view):
        return True
