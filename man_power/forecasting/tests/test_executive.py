import io
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from forecasting.models import FunctionMaster, ManpowerForecast, ProcessMaster
from forecasting.services.executive_service import build_executive

from .helpers import PASSWORD, make_forecast, make_user


class ExecutiveTests(TestCase):
    def setUp(self):
        self.user = make_user("analyst", "Analyst")
        self.admin = make_user("boss", "Admin")
        fin = FunctionMaster.objects.create(function_name="Finance")
        hr = FunctionMaster.objects.create(function_name="HR")
        mk = lambda fn, name: ProcessMaster.objects.create(function=fn, process_name=name)  # noqa: E731
        common = dict(run_monte_carlo=False, simulation_seed=None)
        make_forecast(self.user, fin, mk(fin, "Bank Rec"), frequency="DAILY", volume=Decimal("150"),
                      current_fte=Decimal("2"), avg_processing_time=Decimal("6"), **common)
        make_forecast(self.user, fin, mk(fin, "Vendor Pay"), frequency="WEEKLY", volume=Decimal("400"),
                      current_fte=Decimal("4"), avg_processing_time=Decimal("12"), **common)
        make_forecast(self.user, fin, mk(fin, "Invoices"), growth_rate_percentage=Decimal("5"), **common)
        make_forecast(self.user, hr, mk(hr, "Leave"), frequency="DAILY", volume=Decimal("300"),
                      current_fte=Decimal("2"), avg_processing_time=Decimal("6"), **common)

    def test_kpis(self):
        d = build_executive(ManpowerForecast.objects.all(), date(2026, 10, 5), cost_per_fte=600000, horizon=12)
        k = d["kpis"]
        self.assertEqual(k["net_hire_now"], 3)
        self.assertEqual(k["net_hire_horizon"], 5)
        self.assertEqual(k["total_required_people"], 14)
        self.assertEqual(d["score"]["score"], 51)

    def test_page_and_export(self):
        self.client.login(username=self.admin.username, password=PASSWORD)
        r = self.client.get(reverse("forecasting:executive"))
        self.assertContains(r, "Capacity Health Score")
        wb = load_workbook(io.BytesIO(self.client.get(reverse("forecasting:executive_export")).content))
        self.assertEqual(wb["Executive Summary"]["B5"].value, 51)
