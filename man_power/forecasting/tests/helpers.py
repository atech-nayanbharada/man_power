from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from forecasting.models import FunctionMaster, ManpowerForecast, ProcessMaster
from forecasting.permissions import ALL_ROLES
from forecasting.services.forecast_service import save_forecast

PASSWORD = "Test@12345"


def make_user(username, role=None):
    for r in ALL_ROLES:
        Group.objects.get_or_create(name=r)
    user = get_user_model().objects.create_user(username=username, password=PASSWORD)
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


def make_masters():
    function = FunctionMaster.objects.create(function_name="Finance")
    process = ProcessMaster.objects.create(function=function, process_name="Invoice Processing",
                                           default_frequency="MONTHLY")
    return function, process


def make_forecast(user, function, process, **overrides):
    data = dict(function=function, process=process, frequency="MONTHLY", volume=Decimal("2200"),
                current_fte=Decimal("3"), avg_processing_time=Decimal("10"), time_unit="MINUTES",
                run_monte_carlo=True, simulation_count=2000, simulation_seed=42,
                growth_rate_percentage=Decimal("0"), growth_period="MONTHLY", forecast_horizon_months=12,
                aht_change_percentage=Decimal("0"), aht_change_period="MONTHLY")
    data.update(overrides)
    return save_forecast(ManpowerForecast(**data), user)


def form_data(fn, proc, **kw):
    base = dict(function=fn.pk, process=proc.pk, frequency="MONTHLY", volume="2200",
                current_fte="3", avg_processing_time="10", time_unit="MINUTES", working_hours_per_day="8",
                working_days_per_week="5", working_days_per_month="22", contingency_percentage="15",
                run_monte_carlo="on", volume_variation_percentage="10", time_variation_percentage="15",
                simulation_count="1000", simulation_seed="", growth_rate_percentage="0",
                growth_period="MONTHLY", aht_change_percentage="0", aht_change_period="MONTHLY",
                forecast_horizon_months="12", remarks="")
    base.update(kw)
    return {k: v for k, v in base.items() if v is not None}
