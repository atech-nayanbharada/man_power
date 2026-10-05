from . import permissions as perms


def user_roles(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    return {
        "user_roles": sorted(perms.get_roles(user)),
        "perm_is_admin": perms.is_admin(user),
        "perm_manage_masters": perms.can_manage_masters(user),
        "perm_create": perms.can_create_forecast(user),
        "perm_upload": perms.can_upload(user),
        "perm_export": perms.can_export(user),
        "perm_review": perms.can_review(user),
        "perm_scenario": perms.can_compare_scenarios(user),
    }
