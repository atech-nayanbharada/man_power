"""
Load sample functions, processes, role users and forecasts covering every status,
with and without Monte Carlo, and with different growth projections.

Demo users (password: Demo@12345):
  admin_user (Admin), analyst_user (Analyst), analyst2_user (Analyst),
  approver_user (Approver), viewer_user (Viewer)
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from forecasting.models import ApprovalStatus, FunctionMaster, ManpowerForecast, ProcessMaster
from forecasting.services.forecast_service import save_forecast

DEMO_PASSWORD = "Demo@12345"

USERS = [
    ("admin_user", "Admin", True),
    ("analyst_user", "Analyst", False),
    ("analyst2_user", "Analyst", False),
    ("approver_user", "Approver", False),
    ("viewer_user", "Viewer", False),
]

MASTERS = {
    ("Finance", "Rahul Mehta", "Finance and accounting operations"): [
        ("Invoice Processing", "MONTHLY"), ("Vendor Payments", "WEEKLY"),
        ("Bank Reconciliation", "DAILY"), ("GST Return Filing", "MONTHLY"),
    ],
    ("Human Resources", "Priya Shah", "Employee lifecycle operations"): [
        ("Employee Onboarding", "MONTHLY"), ("Payroll Processing", "MONTHLY"),
        ("Leave Management", "DAILY"),
    ],
    ("Procurement", "Amit Patel", "Purchase and sourcing"): [
        ("Purchase Order Creation", "DAILY"), ("Vendor Registration", "WEEKLY"),
    ],
    ("Customer Service", "Neha Desai", "Customer support operations"): [
        ("Email Ticket Resolution", "DAILY"), ("Complaint Handling", "WEEKLY"),
    ],
}

# (process, frequency, volume, current_fte, avg_time, unit, contingency, run_mc, approve,
#  growth %, growth period, horizon months)
FORECASTS = [
    ("Invoice Processing", "MONTHLY", 2200, 3, 10, "MINUTES", 15, True, True, 3, "MONTHLY", 12),
    ("Vendor Payments", "WEEKLY", 400, 4, 12, "MINUTES", 15, True, True, 10, "QUARTERLY", 24),
    ("Bank Reconciliation", "DAILY", 150, 2, 6, "MINUTES", 15, True, True, 0, "MONTHLY", 12),
    ("GST Return Filing", "MONTHLY", 300, 1, 1, "HOURS", 15, False, False, 0, "MONTHLY", 12),
    ("Employee Onboarding", "MONTHLY", 120, 2, 2, "HOURS", 15, True, True, 15, "YEARLY", 36),
    ("Payroll Processing", "MONTHLY", 5000, 2, 90, "SECONDS", 15, False, True, 8, "HALF_YEARLY", 36),
    ("Leave Management", "DAILY", 300, 1, 75, "SECONDS", 15, False, False, -2, "MONTHLY", 12),
    ("Purchase Order Creation", "DAILY", 180, 5, 8, "MINUTES", 15, True, True, 2, "MONTHLY", 18),
    ("Vendor Registration", "WEEKLY", 60, 1, 25, "MINUTES", 15, True, False, 0, "MONTHLY", 12),
    ("Email Ticket Resolution", "DAILY", 600, 8, 4, "MINUTES", 15, True, True, 0.5, "WEEKLY", 12),
    ("Complaint Handling", "WEEKLY", 900, 3, 15, "MINUTES", 20, True, False, 5, "QUARTERLY", 12),
]


class Command(BaseCommand):
    help = "Load sample masters, demo users and forecasts."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing forecasts and masters first.")

    @transaction.atomic
    def handle(self, *args, **options):
        call_command("setup_roles", stdout=self.stdout)
        if options["reset"]:
            ManpowerForecast.objects.all().delete()
            ProcessMaster.objects.all().delete()
            FunctionMaster.objects.all().delete()
            self.stdout.write(self.style.WARNING("Existing forecasts and masters deleted."))

        User = get_user_model()
        users = {}
        for username, role, staff in USERS:
            user, created = User.objects.get_or_create(username=username, defaults={
                "email": f"{username}@example.com", "first_name": username.split("_")[0].title(),
                "last_name": role, "is_staff": staff})
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
            user.groups.add(Group.objects.get(name=role))
            users[username] = user
        admin = users["admin_user"]

        processes = {}
        for (fname, owner, desc), plist in MASTERS.items():
            function, _ = FunctionMaster.objects.get_or_create(
                function_name=fname, defaults={"function_owner": owner, "description": desc, "created_by": admin})
            for pname, freq in plist:
                process, _ = ProcessMaster.objects.get_or_create(
                    function=function, process_name=pname,
                    defaults={"default_frequency": freq, "process_owner": owner, "created_by": admin})
                processes[pname] = process

        makers = [users["analyst_user"], users["analyst2_user"]]
        for i, row in enumerate(FORECASTS):
            pname, freq, vol, fte, t, unit, cont, run_mc, approve, growth, gperiod, horizon = row
            process = processes[pname]
            forecast = ManpowerForecast(
                function=process.function, process=process, frequency=freq, volume=Decimal(vol),
                current_fte=Decimal(fte), avg_processing_time=Decimal(t), time_unit=unit,
                contingency_percentage=Decimal(cont), run_monte_carlo=run_mc,
                simulation_count=10000, simulation_seed=42 if run_mc else None,
                growth_rate_percentage=Decimal(str(growth)), growth_period=gperiod,
                forecast_horizon_months=horizon,
                remarks="Sample data" + ("" if run_mc else " (deterministic only)"),
            )
            save_forecast(forecast, makers[i % 2])
            if approve:
                forecast.approval_status = ApprovalStatus.APPROVED
                forecast.approved_by = users["approver_user"]
                forecast.approved_at = timezone.now()
                forecast.approval_comments = "Reviewed - sample approval."
                forecast.save()
            outlook = {"none": "no growth", "ok": "OK through horizon", "short_now": "short now",
                       "short_future": f"short from {forecast.shortfall_label}"}[forecast.outlook]
            self.stdout.write(f"  {pname:<26} {'MC ' if run_mc else 'DET'} -> {forecast.get_status_display():<20} "
                              f"Req {forecast.required_fte} / Cur {forecast.current_fte} | {outlook}")
        self.stdout.write(self.style.SUCCESS(
            f"Loaded {len(processes)} processes and {len(FORECASTS)} forecasts. Demo password: {DEMO_PASSWORD}"))
