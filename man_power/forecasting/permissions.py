"""
Role-based access control and maker-checker rules.
Roles are Django Groups: Admin, Analyst, Viewer, Approver. Superusers are treated as Admin.
"""
from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied

from .models import ApprovalStatus

ROLE_ADMIN = "Admin"
ROLE_ANALYST = "Analyst"
ROLE_VIEWER = "Viewer"
ROLE_APPROVER = "Approver"
ALL_ROLES = (ROLE_ADMIN, ROLE_ANALYST, ROLE_VIEWER, ROLE_APPROVER)


def get_roles(user):
    if not user or not user.is_authenticated:
        return set()
    if not hasattr(user, "_forecast_roles_cache"):
        roles = set(user.groups.filter(name__in=ALL_ROLES).values_list("name", flat=True))
        if user.is_superuser:
            roles.add(ROLE_ADMIN)
        user._forecast_roles_cache = roles
    return user._forecast_roles_cache


def has_any_role(user, *roles):
    return bool(get_roles(user) & set(roles))


def is_admin(user):
    return has_any_role(user, ROLE_ADMIN)


def can_manage_masters(user):
    return is_admin(user)


def can_create_forecast(user):
    return has_any_role(user, ROLE_ADMIN, ROLE_ANALYST)


def can_upload(user):
    return has_any_role(user, ROLE_ADMIN, ROLE_ANALYST)


def can_export(user):
    return has_any_role(user, *ALL_ROLES)


def can_compare_scenarios(user):
    return has_any_role(user, ROLE_ADMIN, ROLE_ANALYST, ROLE_APPROVER)


def can_review(user):
    return has_any_role(user, ROLE_ADMIN, ROLE_APPROVER)


def only_approved_visible(user):
    """Users whose only role is Viewer see approved forecasts only."""
    roles = get_roles(user)
    return not roles or roles == {ROLE_VIEWER}


def visible_forecasts(user, queryset):
    if only_approved_visible(user):
        return queryset.filter(approval_status=ApprovalStatus.APPROVED)
    return queryset


def can_view_forecast(user, forecast):
    if not get_roles(user):
        return False
    if only_approved_visible(user):
        return forecast.approval_status == ApprovalStatus.APPROVED
    return True


def can_edit_forecast(user, forecast):
    if is_admin(user):
        return True
    return has_any_role(user, ROLE_ANALYST) and forecast.created_by_id == user.id


def can_delete_forecast(user, forecast):
    if is_admin(user):
        return True
    return (has_any_role(user, ROLE_ANALYST) and forecast.created_by_id == user.id
            and forecast.approval_status != ApprovalStatus.APPROVED)


def can_approve_forecast(user, forecast):
    """Maker-checker: reviewer role required, and a maker can never approve their own forecast."""
    return (can_review(user)
            and forecast.created_by_id != user.id
            and forecast.approval_status == ApprovalStatus.PENDING)


class RoleRequiredMixin(AccessMixin):
    """Restrict a class-based view to users holding at least one of `allowed_roles`."""

    allowed_roles = ALL_ROLES

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not has_any_role(request.user, *self.allowed_roles):
            raise PermissionDenied("You do not have permission to access this page.")
        return super().dispatch(request, *args, **kwargs)
