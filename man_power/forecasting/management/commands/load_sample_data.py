"""
Load sample masters, demo users and forecasts. Most samples have a measured AHT; two leave AHT blank so it is
calculated from team working hours (Calculate AHT). Some samples use decimal FTE and volume.

Demo users (password: Demo@12345): admin_user, analyst_user, analyst2_user, approver_user, viewer_user
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
USERS = [("admin_user", "Admin", True), ("analyst_user", "Analyst", False), ("analyst2_user", "Analyst", False),
         ("approver_user", "Approver", False), ("viewer_user", "Viewer", False)]
MASTERS = {
    ("Finance", "Rahul Mehta", "Finance and accounting operations"): [
        ("Invoice Processing", "MONTHLY"), ("Vendor Payments", "WEEKLY"),
        ("Bank Reconciliation", "DAILY"), ("GST Return Filing", "MONTHLY")],
    ("HR -TA", "Priya Shah", "Talent acquisition"): [("Offer Rollout", "YEARLY")],
    ("Human Resources", "Priya Shah", "Employee lifecycle operations"): [
        ("Employee Onboarding", "MONTHLY"), ("Payroll Processing", "MONTHLY"), ("Leave Management", "DAILY")],
    ("Procurement", "Amit Patel", "Purchase and sourcing"): [
        ("Purchase Order Creation", "DAILY"), ("Vendor Registration", "WEEKLY")],
    ("Customer Service", "Neha Desai", "Customer support operations"): [
        ("Email Ticket Resolution", "DAILY"), ("Complaint Handling", "WEEKLY")],
}
# (process, frequency, volume, fte, AHT minutes (None = Calculate AHT), days/wk, days/mo, contingency, run_mc,
#  approve, growth %, growth period, AHT change %, AHT period, horizon)
FORECASTS = [
    ("Invoice Processing", "MONTHLY", "2200", "3", "10", 5, 22, 15, True, True, 3, "MONTHLY", -2, "QUARTERLY", 12),
    ("Vendor Payments", "WEEKLY", "400", "4", "12", 5.5, 23.83, 15, True, True, 10, "QUARTERLY", 0, "MONTHLY", 24),
    ("Bank Reconciliation", "DAILY", "150", "2", "6", 5, 22, 15, True, True, 0, "MONTHLY", -5, "QUARTERLY", 12),
    ("GST Return Filing", "MONTHLY", "300", "1", "60", 5, 22, 15, False, False, 0, "MONTHLY", 0, "MONTHLY", 12),
    ("Offer Rollout", "YEARLY", "6305", "180", "120", 5, 22, 15, False, False, 0, "MONTHLY", 0, "MONTHLY", 12),
    ("Employee Onboarding", "MONTHLY", "120", "2", "120", 5, 22, 15, True, True, 15, "YEARLY", 0, "MONTHLY", 36),
    ("Payroll Processing", "MONTHLY", "5000", "1.5", "1.5", 5, 22, 15, False, True, 8, "HALF_YEARLY", 0, "MONTHLY", 36),
    ("Leave Management", "DAILY", "300", "1", None, 5, 22, 15, False, False, -2, "MONTHLY", 0, "MONTHLY", 12),
    ("Purchase Order Creation", "DAILY", "180.5", "4.5", "8", 5.5, 23.83, 15, True, True, 2, "MONTHLY", 0, "MONTHLY", 18),
    ("Vendor Registration", "WEEKLY", "60", "1", None, 5, 22, 15, False, False, 0, "MONTHLY", 10, "YEARLY", 24),
    ("Email Ticket Resolution", "DAILY", "600", "8", "4", 5.5, 23.83, 15, True, True, 0.5, "WEEKLY", 0, "MONTHLY", 12),
    ("Complaint Handling", "WEEKLY", "900", "3", "15", 5, 22, 20, True, False, 5, "QUARTERLY", 3, "HALF_YEARLY", 12),
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
        processes = {}
        for (fname, owner, desc), plist in MASTERS.items():
            function, _ = FunctionMaster.objects.get_or_create(
                function_name=fname, defaults={"function_owner": owner, "description": desc,
                                               "created_by": users["admin_user"]})
            for pname, freq in plist:
                processes[pname], _ = ProcessMaster.objects.get_or_create(
                    function=function, process_name=pname,
                    defaults={"default_frequency": freq, "process_owner": owner, "created_by": users["admin_user"]})
        makers = [users["analyst_user"], users["analyst2_user"]]
        for i, row in enumerate(FORECASTS):
            (pname, freq, vol, fte, aht, wk, mo, cont, run_mc, approve, growth, gperiod, ahtc, aperiod, horizon) = row
            process = processes[pname]
            forecast = ManpowerForecast(
                function=process.function, process=process, frequency=freq, volume=Decimal(vol),
                current_fte=Decimal(fte), avg_processing_time=Decimal(aht) if aht else Decimal("0"),
                working_days_per_week=Decimal(str(wk)), working_days_per_month=Decimal(str(mo)),
                contingency_percentage=Decimal(cont), run_monte_carlo=run_mc,
                simulation_count=10000, simulation_seed=42 if run_mc else None,
                growth_rate_percentage=Decimal(str(growth)), growth_period=gperiod,
                aht_change_percentage=Decimal(str(ahtc)), aht_change_period=aperiod, forecast_horizon_months=horizon,
                remarks="Sample data" + (" (AHT calculated)" if aht is None else ""),
            )
            save_forecast(forecast, makers[i % 2])
            if approve:
                forecast.approval_status = ApprovalStatus.APPROVED
                forecast.approved_by = users["approver_user"]
                forecast.approved_at = timezone.now()
                forecast.approval_comments = "Reviewed - sample approval."
                forecast.save()
            src = "calc" if forecast.aht_is_calculated else "entered"
            self.stdout.write(f"  {pname:<26} AHT {forecast.avg_processing_time:>8.2f} ({src:<7}) FTE {forecast.current_fte:>6} "
                              f"| {forecast.get_status_display():<20} Req {forecast.required_people} "
                              f"| Util {forecast.utilization_percentage}%")
        self.stdout.write(self.style.SUCCESS(
            f"Loaded {len(processes)} processes and {len(FORECASTS)} forecasts. Demo password: {DEMO_PASSWORD}"))
