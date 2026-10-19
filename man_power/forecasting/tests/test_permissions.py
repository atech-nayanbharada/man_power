from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from forecasting.models import ApprovalStatus, ManpowerForecast

from .helpers import PASSWORD, form_data, make_forecast, make_masters, make_user


class PermissionAndPageTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", "Admin")
        self.analyst = make_user("analyst", "Analyst")
        self.viewer = make_user("viewer", "Viewer")
        self.approver = make_user("approver", "Approver")
        self.norole = make_user("norole")
        self.function, self.process = make_masters()
        self.forecast = make_forecast(self.analyst, self.function, self.process)

    def login(self, user):
        self.client.login(username=user.username, password=PASSWORD)

    def test_all_pages_render_for_admin(self):
        det = make_forecast(self.analyst, self.function, self.process, run_monte_carlo=False,
                            growth_rate_percentage=Decimal("5"), aht_change_percentage=Decimal("-2"),
                            working_days_per_week=Decimal("5.5"))
        self.login(self.admin)
        for pk in (self.forecast.pk, det.pk):
            for name, args in [("dashboard", []), ("executive", []), ("executive_export", []),
                               ("forecast_list", []), ("forecast_create", []),
                               ("forecast_detail", [pk]), ("forecast_result", [pk]), ("forecast_update", [pk]),
                               ("function_list", []), ("process_list", []), ("scenario", []),
                               ("bulk_upload", []), ("reports", []), ("upload_template", []),
                               ("report_export", []), ("forecast_export", [pk])]:
                with self.subTest(page=name, pk=pk):
                    self.assertEqual(self.client.get(reverse(f"forecasting:{name}", args=args)).status_code, 200)
        r = self.client.get(reverse("forecasting:forecast_result", args=[det.pk]))
        for text in ("How the numbers are calculated", "AHT (calculated)", "366.67 hours x 60", "5.5 days x 8.00 hours",
                     "Required FTE (whole people)", "Future Manpower Forecast"):
            self.assertContains(r, text)
        form_page = self.client.get(reverse("forecasting:forecast_create"))
        self.assertContains(form_page, "id_total_time_spent_hours")
        self.assertNotContains(form_page, "id_avg_processing_time")
        self.assertContains(form_page, "data-aht-preview")

    def test_create_via_web_calculates_aht(self):
        self.login(self.analyst)
        response = self.client.post(reverse("forecasting:forecast_create"),
                                    form_data(self.function, self.process, total_time_spent_hours="300",
                                              working_days_per_week="5.5", working_days_per_month="23.83",
                                              run_monte_carlo=None))
        new = ManpowerForecast.objects.exclude(pk=self.forecast.pk).get()
        self.assertRedirects(response, reverse("forecasting:forecast_result", args=[new.pk]))
        self.assertEqual(new.avg_processing_time, Decimal("8.1818"))
        self.assertEqual(new.working_days_per_week, Decimal("5.50"))

    def test_edit_form_shows_whole_fte(self):
        self.login(self.analyst)
        r = self.client.get(reverse("forecasting:forecast_update", args=[self.forecast.pk]))
        self.assertContains(r, 'name="current_fte" value="3"')

    def test_role_restrictions(self):
        self.login(self.norole)
        self.assertEqual(self.client.get(reverse("forecasting:dashboard")).status_code, 403)
        self.client.logout()
        self.login(self.viewer)
        self.assertEqual(self.client.get(reverse("forecasting:forecast_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("forecasting:forecast_detail", args=[self.forecast.pk])).status_code, 403)
        ManpowerForecast.objects.filter(pk=self.forecast.pk).update(approval_status=ApprovalStatus.APPROVED)
        self.assertEqual(self.client.get(reverse("forecasting:forecast_detail", args=[self.forecast.pk])).status_code, 200)

    def test_rerun_keeps_aht(self):
        self.login(self.analyst)
        self.client.post(reverse("forecasting:forecast_rerun", args=[self.forecast.pk]) + "?monte_carlo=off")
        self.forecast.refresh_from_db()
        self.assertFalse(self.forecast.run_monte_carlo)
        self.assertEqual(self.forecast.avg_processing_time, Decimal("10.0000"))

    def test_scenario_post(self):
        self.login(self.approver)
        base = {"base_forecast": self.forecast.pk, "simulation_seed": 42, "run_monte_carlo": "on",
                "sc-TOTAL_FORMS": 1, "sc-INITIAL_FORMS": 0, "sc-MIN_NUM_FORMS": 0, "sc-MAX_NUM_FORMS": 4,
                "sc-0-name": "Proposed", "sc-0-current_fte": 4}
        r = self.client.post(reverse("forecasting:scenario"), base)
        self.assertContains(r, "Risk-Adjusted P90 FTE")

    def test_maker_checker(self):
        self.login(self.approver)
        self.client.post(reverse("forecasting:forecast_approve", args=[self.forecast.pk]),
                         {"decision": "APPROVE", "comments": "ok"})
        self.forecast.refresh_from_db()
        self.assertEqual(self.forecast.approval_status, ApprovalStatus.APPROVED)
        own = make_forecast(self.admin, self.function, self.process)
        self.client.logout()
        self.login(self.admin)
        self.client.post(reverse("forecasting:forecast_approve", args=[own.pk]), {"decision": "APPROVE"})
        own.refresh_from_db()
        self.assertEqual(own.approval_status, ApprovalStatus.PENDING)
