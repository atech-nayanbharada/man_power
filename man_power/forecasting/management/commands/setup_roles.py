"""Create the four application roles (Django groups) and assign model permissions."""
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from forecasting.permissions import ROLE_ADMIN, ROLE_ANALYST, ROLE_APPROVER, ROLE_VIEWER

APP_MODELS = ["functionmaster", "processmaster", "manpowerforecast", "forecastsimulationsummary", "forecastauditlog"]

ROLE_PERMISSIONS = {
    ROLE_ADMIN: {"forecasting": [f"{a}_{m}" for m in APP_MODELS for a in ("add", "change", "delete", "view")],
                 "auth": [f"{a}_{m}" for m in ("user", "group") for a in ("add", "change", "delete", "view")]},
    ROLE_ANALYST: {"forecasting": ["add_manpowerforecast", "change_manpowerforecast", "view_manpowerforecast",
                                   "view_functionmaster", "view_processmaster",
                                   "view_forecastsimulationsummary"]},
    ROLE_APPROVER: {"forecasting": ["view_manpowerforecast", "change_manpowerforecast", "view_functionmaster",
                                    "view_processmaster", "view_forecastsimulationsummary",
                                    "view_forecastauditlog"]},
    ROLE_VIEWER: {"forecasting": ["view_manpowerforecast", "view_forecastsimulationsummary"]},
}


class Command(BaseCommand):
    help = "Create Admin, Analyst, Viewer and Approver groups with permissions."

    def handle(self, *args, **options):
        for role, app_perms in ROLE_PERMISSIONS.items():
            group, created = Group.objects.get_or_create(name=role)
            perms = []
            for app_label, codenames in app_perms.items():
                perms.extend(Permission.objects.filter(content_type__app_label=app_label, codename__in=codenames))
            group.permissions.set(perms)
            self.stdout.write(self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} role '{role}' with {len(perms)} permissions."))
