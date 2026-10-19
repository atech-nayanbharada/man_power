from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from forecasting.models import ApprovalStatus, ManpowerForecast
from forecasting.services.executive_service import build_executive

from .helpers import PASSWORD, make_forecast, make_masters, make_user


class PageTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", "Admin")
        self.analyst = make_user("analyst", "Analyst")
        self.viewer = make_user("viewer", "Viewer")
        self.approver = make_user("approver", "Approver")
        self.norole = make_user("norole")
        self.function, self.process = make_masters()
        self.forecast = make_forecast(self.analyst, self.function, self.process, growth_rate_percentage=Decimal("5"),
                                      current_fte=Decimal("2.5"))
        self.auto = make_forecast(self.analyst, self.function, self.process, avg_processing_time=None,
                                  run_monte_carlo=False)

    def test_all_pages_admin(self):
        self.client.login(username="admin", password=PASSWORD)
        for pk in (self.forecast.pk, self.auto.pk):
            for name, args in [("dashboard", []), ("executive", []), ("executive_export", []), ("forecast_list", []),
                               ("forecast_create", []), ("forecast_detail", [pk]), ("forecast_result", [pk]),
                               ("forecast_update", [pk]), ("function_list", []), ("process_list", []),
                               ("scenario", []), ("bulk_upload", []), ("reports", []), ("upload_template", []),
                               ("report_export", []), ("forecast_export", [pk])]:
                with self.subTest(page=name, pk=pk):
                    self.assertEqual(self.client.get(reverse(f"forecasting:{name}", args=args)).status_code, 200)
        self.assertContains(self.client.get(reverse("forecasting:dashboard")), "Calculated AHT")
        self.assertEqual(self.client.get(reverse("forecasting:scenario") + f"?base={self.forecast.pk}").status_code, 200)

    def test_roles(self):
        self.client.login(username="norole", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("forecasting:dashboard")).status_code, 403)
        self.client.logout()
        self.client.login(username="viewer", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("forecasting:forecast_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("forecasting:forecast_detail", args=[self.forecast.pk])).status_code, 403)

    def test_maker_checker(self):
        self.client.login(username="approver", password=PASSWORD)
        self.client.post(reverse("forecasting:forecast_approve", args=[self.forecast.pk]), {"decision": "APPROVE"})
        self.forecast.refresh_from_db()
        self.assertEqual(self.forecast.approval_status, ApprovalStatus.APPROVED)
        own = make_forecast(self.admin, self.function, self.process)
        self.client.logout()
        self.client.login(username="admin", password=PASSWORD)
        self.client.post(reverse("forecasting:forecast_approve", args=[own.pk]), {"decision": "APPROVE"})
        own.refresh_from_db()
        self.assertEqual(own.approval_status, ApprovalStatus.PENDING)

    def test_scenario_post(self):
        self.client.login(username="approver", password=PASSWORD)
        r = self.client.post(reverse("forecasting:scenario"), {
            "base_forecast": self.forecast.pk, "simulation_seed": 42, "run_monte_carlo": "on",
            "sc-TOTAL_FORMS": 1, "sc-INITIAL_FORMS": 0, "sc-MIN_NUM_FORMS": 0, "sc-MAX_NUM_FORMS": 4,
            "sc-0-name": "Proposed", "sc-0-current_fte": "3.5"})
        self.assertContains(r, "Risk-Adjusted P90 FTE")
        self.assertContains(r, "3.5")

    def test_executive(self):
        d = build_executive(ManpowerForecast.objects.all(), date(2026, 10, 5))
        self.assertEqual(d["kpis"]["calculated_aht_count"], 1)
        self.assertTrue(any("Calculate AHT" in i["text"] for i in d["insights"]))
