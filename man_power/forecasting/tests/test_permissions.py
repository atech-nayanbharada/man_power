from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from forecasting.models import ApprovalStatus, ForecastAuditLog, ManpowerForecast

from .helpers import PASSWORD, form_data, make_forecast, make_masters, make_user


class PermissionTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", "Admin")
        self.analyst = make_user("analyst", "Analyst")
        self.analyst2 = make_user("analyst2", "Analyst")
        self.viewer = make_user("viewer", "Viewer")
        self.approver = make_user("approver", "Approver")
        self.norole = make_user("norole")
        self.function, self.process = make_masters()
        self.forecast = make_forecast(self.analyst, self.function, self.process)

    def login(self, user):
        self.client.login(username=user.username, password=PASSWORD)

    def test_login_required(self):
        response = self.client.get(reverse("forecasting:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_all_pages_render_for_admin(self):
        det = make_forecast(self.analyst, self.function, self.process, run_monte_carlo=False,
                            growth_rate_percentage=Decimal("5"), aht_change_percentage=Decimal("-2"),
                            aht_change_period="QUARTERLY")
        self.login(self.admin)
        for pk in (self.forecast.pk, det.pk):
            for name, args in [("dashboard", []), ("executive", []), ("executive_export", []),
                               ("forecast_list", []), ("forecast_create", []),
                               ("forecast_detail", [pk]), ("forecast_result", [pk]), ("forecast_update", [pk]),
                               ("function_list", []), ("function_create", []), ("process_list", []),
                               ("process_create", []), ("scenario", []), ("bulk_upload", []), ("reports", []),
                               ("upload_template", []), ("report_export", []), ("forecast_export", [pk])]:
                with self.subTest(page=name, pk=pk):
                    self.assertEqual(self.client.get(reverse(f"forecasting:{name}", args=args)).status_code, 200)
        r = self.client.get(reverse("forecasting:forecast_result", args=[det.pk]))
        self.assertContains(r, "Future Manpower Forecast")
        self.assertContains(r, "-2% AHT per quarter")
        self.assertContains(r, "AHT (min)")
        self.assertContains(self.client.get(reverse("forecasting:forecast_create")), "AHT Change (%)")
        self.assertContains(self.client.get(reverse("forecasting:forecast_result", args=[self.forecast.pk])),
                            "No volume growth or AHT change was entered")

    def test_user_without_role_denied(self):
        self.login(self.norole)
        self.assertEqual(self.client.get(reverse("forecasting:dashboard")).status_code, 403)

    def test_viewer_restrictions(self):
        self.login(self.viewer)
        self.assertEqual(self.client.get(reverse("forecasting:dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("forecasting:executive")).status_code, 200)
        self.assertEqual(self.client.get(reverse("forecasting:forecast_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("forecasting:bulk_upload")).status_code, 403)
        self.assertEqual(self.client.get(reverse("forecasting:forecast_detail", args=[self.forecast.pk])).status_code, 403)
        ManpowerForecast.objects.filter(pk=self.forecast.pk).update(approval_status=ApprovalStatus.APPROVED)
        self.assertEqual(self.client.get(reverse("forecasting:forecast_detail", args=[self.forecast.pk])).status_code, 200)

    def test_analyst_can_create_and_only_edit_own(self):
        self.login(self.analyst2)
        self.assertEqual(self.client.get(reverse("forecasting:forecast_update", args=[self.forecast.pk])).status_code, 403)
        response = self.client.post(reverse("forecasting:forecast_create"),
                                    form_data(self.function, self.process, frequency="DAILY", volume="100",
                                              current_fte="2", avg_processing_time="5", simulation_seed="1"))
        new = ManpowerForecast.objects.exclude(pk=self.forecast.pk).get()
        self.assertRedirects(response, reverse("forecasting:forecast_result", args=[new.pk]))

    def test_create_with_aht_change_via_web(self):
        self.login(self.analyst)
        self.client.post(reverse("forecasting:forecast_create"),
                         form_data(self.function, self.process, run_monte_carlo=None, growth_rate_percentage="10",
                                   growth_period="QUARTERLY", aht_change_percentage="-5",
                                   aht_change_period="HALF_YEARLY", forecast_horizon_months="24"))
        new = ManpowerForecast.objects.exclude(pk=self.forecast.pk).get()
        self.assertEqual(len(new.projection_points), 25)
        self.assertEqual(new.aht_change_period, "HALF_YEARLY")
        self.assertEqual(new.projection_points[6]["aht_minutes"], 9.5)
        # workload factor 1.1^q x 0.95^h: month 9 = 1.331 x 0.95 = 1.264 -> 3.10 FTE > 3
        self.assertEqual(new.projected_shortfall_month, 9)

    def test_create_with_aht_only_via_web(self):
        self.login(self.analyst)
        self.client.post(reverse("forecasting:forecast_create"),
                         form_data(self.function, self.process, run_monte_carlo=None, aht_change_percentage="5"))
        new = ManpowerForecast.objects.exclude(pk=self.forecast.pk).get()
        self.assertTrue(new.has_projection)
        self.assertEqual(new.projected_shortfall_month, 5)

    def test_rerun_toggles_monte_carlo(self):
        self.login(self.analyst)
        url = reverse("forecasting:forecast_rerun", args=[self.forecast.pk])
        self.client.post(url + "?monte_carlo=off")
        self.forecast.refresh_from_db()
        self.assertFalse(self.forecast.run_monte_carlo)
        self.client.post(url + "?monte_carlo=on")
        self.forecast.refresh_from_db()
        self.assertTrue(self.forecast.run_monte_carlo)

    def test_edit_resets_approval(self):
        ManpowerForecast.objects.filter(pk=self.forecast.pk).update(approval_status=ApprovalStatus.APPROVED,
                                                                    approved_by=self.approver)
        self.login(self.analyst)
        self.client.post(reverse("forecasting:forecast_rerun", args=[self.forecast.pk]))
        self.forecast.refresh_from_db()
        self.assertEqual(self.forecast.approval_status, ApprovalStatus.PENDING)

    def test_scenario_post_with_aht(self):
        growth = make_forecast(self.analyst, self.function, self.process, growth_rate_percentage=Decimal("5"))
        self.login(self.approver)
        base = {"base_forecast": growth.pk, "simulation_seed": 42, "sc-TOTAL_FORMS": 1,
                "sc-INITIAL_FORMS": 0, "sc-MIN_NUM_FORMS": 0, "sc-MAX_NUM_FORMS": 4,
                "sc-0-name": "Automation", "sc-0-aht_change_percentage": -3}
        r = self.client.post(reverse("forecasting:scenario"), {**base, "run_monte_carlo": "on"})
        self.assertContains(r, "AHT Change % per Period")
        self.assertContains(r, "AHT at Horizon")
        r = self.client.post(reverse("forecasting:scenario"), base)
        self.assertNotContains(r, "P90 Required FTE")

    def test_approver_cannot_create(self):
        self.login(self.approver)
        self.assertEqual(self.client.get(reverse("forecasting:forecast_create")).status_code, 403)


class MakerCheckerTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", "Admin")
        self.approver = make_user("approver", "Approver")
        self.analyst = make_user("analyst", "Analyst")
        self.function, self.process = make_masters()

    def approve(self, user, forecast, decision="APPROVE", comments="Looks good"):
        self.client.login(username=user.username, password=PASSWORD)
        return self.client.post(reverse("forecasting:forecast_approve", args=[forecast.pk]),
                                {"decision": decision, "comments": comments})

    def test_approver_approves_others_forecast(self):
        f = make_forecast(self.analyst, self.function, self.process, aht_change_percentage=Decimal("2"))
        self.approve(self.approver, f)
        f.refresh_from_db()
        self.assertEqual(f.approval_status, ApprovalStatus.APPROVED)
        self.assertTrue(f.audit_logs.filter(action=ForecastAuditLog.Action.APPROVE).exists())

    def test_maker_cannot_approve_own_forecast_even_as_admin(self):
        f = make_forecast(self.admin, self.function, self.process)
        self.approve(self.admin, f)
        f.refresh_from_db()
        self.assertEqual(f.approval_status, ApprovalStatus.PENDING)

    def test_analyst_cannot_approve(self):
        f = make_forecast(self.admin, self.function, self.process)
        self.assertEqual(self.approve(self.analyst, f).status_code, 403)

    def test_reject_requires_comment(self):
        f = make_forecast(self.analyst, self.function, self.process)
        self.approve(self.approver, f, decision="REJECT", comments="")
        f.refresh_from_db()
        self.assertEqual(f.approval_status, ApprovalStatus.PENDING)
        self.approve(self.approver, f, decision="REJECT", comments="Volume looks wrong")
        f.refresh_from_db()
        self.assertEqual(f.approval_status, ApprovalStatus.REJECTED)

    def test_cannot_approve_twice(self):
        f = make_forecast(self.analyst, self.function, self.process)
        self.approve(self.approver, f)
        self.approve(self.admin, f, decision="REJECT", comments="x")
        f.refresh_from_db()
        self.assertEqual(f.approval_status, ApprovalStatus.APPROVED)
