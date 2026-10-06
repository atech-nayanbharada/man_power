"""Growth projection: compounding rules, shortfall detection, hiring plan and summary."""
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from forecasting.services.calculations import ForecastInput
from forecasting.services.forecast_service import compute_forecast, compute_projection, save_forecast
from forecasting.services.projection import add_months, growth_factor, month_label, periods_elapsed

from .helpers import make_forecast, make_masters, make_user

START = date(2026, 10, 5)


def invoice_input(**kw):
    """2,200 invoices/month, 10 min each, 3 FTE -> 2.45 FTE today."""
    data = dict(frequency="MONTHLY", volume=Decimal("2200"), current_fte=Decimal("3"),
                avg_processing_time=Decimal("10"), run_monte_carlo=False,
                growth_rate_percentage=Decimal("5"), growth_period="MONTHLY", forecast_horizon_months=12)
    data.update(kw)
    return ForecastInput(**data)


class GrowthFactorTests(SimpleTestCase):
    def test_monthly_compounds_every_month(self):
        self.assertEqual(growth_factor(5, "MONTHLY", 0), Decimal("1"))
        self.assertEqual(growth_factor(5, "MONTHLY", 1), Decimal("1.05"))
        self.assertEqual(growth_factor(5, "MONTHLY", 12), Decimal("1.05") ** 12)

    def test_quarterly_steps_every_three_months(self):
        self.assertEqual(growth_factor(10, "QUARTERLY", 2), Decimal("1"))
        self.assertEqual(growth_factor(10, "QUARTERLY", 3), Decimal("1.1"))
        self.assertEqual(growth_factor(10, "QUARTERLY", 12), Decimal("1.1") ** 4)

    def test_half_yearly_and_yearly(self):
        self.assertEqual(growth_factor(8, "HALF_YEARLY", 5), Decimal("1"))
        self.assertEqual(growth_factor(8, "HALF_YEARLY", 6), Decimal("1.08"))
        self.assertEqual(growth_factor(15, "YEARLY", 11), Decimal("1"))
        self.assertEqual(growth_factor(15, "YEARLY", 24), Decimal("1.15") ** 2)

    def test_daily_uses_working_days(self):
        self.assertEqual(periods_elapsed("DAILY", 1, 5, 22), 22)
        self.assertEqual(growth_factor(1, "DAILY", 1, 5, 22), Decimal("1.01") ** 22)

    def test_weekly_counts_completed_weeks(self):
        self.assertEqual(periods_elapsed("WEEKLY", 1, 5, 22), 4)
        self.assertEqual(periods_elapsed("WEEKLY", 12, 5, 22), 52)

    def test_negative_growth(self):
        self.assertEqual(growth_factor(-5, "MONTHLY", 2), Decimal("0.95") ** 2)

    def test_month_labels(self):
        self.assertEqual(add_months(START, 3), date(2027, 1, 1))
        self.assertEqual(month_label(START, 0), "Oct 2026")
        self.assertEqual(month_label(START, 14), "Dec 2027")


class ProjectionDeterministicTests(SimpleTestCase):
    def test_no_growth_returns_none(self):
        self.assertIsNone(compute_projection(invoice_input(growth_rate_percentage=0), START))

    def test_shortfall_month_and_horizon(self):
        proj = compute_projection(invoice_input(), START)
        self.assertEqual(len(proj.points), 13)
        self.assertEqual(proj.points[0]["required_fte"], 2.45)
        self.assertEqual(proj.points[4]["status"], "SUFFICIENT")
        self.assertTrue(proj.points[4]["high_risk"])
        self.assertEqual(proj.points[5]["status"], "LESS")
        self.assertEqual(proj.shortfall_month, 5)
        self.assertEqual(proj.horizon_required_fte, Decimal("4.40"))
        self.assertEqual(proj.horizon_fte_needed, Decimal("5.00"))
        self.assertEqual(proj.horizon_status, "LESS")
        self.assertIn("remains sufficient until Feb 2027 (month 4)", proj.summary)
        self.assertIn("From Mar 2027 (month 5) additional manpower is required", proj.summary)
        self.assertIn("2 more than today", proj.summary)

    def test_hiring_plan_steps(self):
        proj = compute_projection(invoice_input(), START)
        self.assertEqual([(s["month"], s["fte_needed"], s["additional_fte"]) for s in proj.hiring_plan],
                         [(5, 4.0, 1.0), (11, 5.0, 2.0)])

    def test_sufficient_through_horizon(self):
        proj = compute_projection(invoice_input(growth_rate_percentage=1), START)
        self.assertIsNone(proj.shortfall_month)
        self.assertEqual(proj.hiring_plan, [])
        self.assertIn("remains sufficient for the full 12-month horizon", proj.summary)

    def test_already_short_and_recovers_with_decline(self):
        proj = compute_projection(ForecastInput(frequency="DAILY", volume=150, current_fte=2, avg_processing_time=6,
                                                run_monte_carlo=False, growth_rate_percentage=-5,
                                                forecast_horizon_months=6), START)
        self.assertEqual(proj.shortfall_month, 0)
        self.assertEqual(proj.points[2]["status"], "SUFFICIENT")
        self.assertIn("becomes sufficient from Dec 2026 (month 2)", proj.summary)

    def test_month_zero_matches_current_result(self):
        inp = invoice_input()
        today = compute_forecast(inp)
        proj = compute_projection(inp, START)
        self.assertEqual(Decimal(str(proj.points[0]["required_fte"])), today.deterministic.required_fte)
        self.assertEqual(proj.points[0]["status"], today.status.status)

    def test_projection_with_monte_carlo(self):
        inp = invoice_input(run_monte_carlo=True, simulation_count=2000, simulation_seed=7)
        proj = compute_projection(inp, START)
        self.assertIsNotNone(proj.points[0]["p90_fte"])
        self.assertLessEqual(proj.shortfall_month, 5)
        self.assertGreaterEqual(proj.horizon_fte_needed, Decimal("5"))
        self.assertIn("risk-adjusted P90", proj.summary)
        self.assertEqual(proj.points, compute_projection(inp, START).points)


class ProjectionPersistenceTests(TestCase):
    def setUp(self):
        self.user = make_user("analyst", "Analyst")
        self.function, self.process = make_masters()

    def test_saved_forecast_fields(self):
        f = make_forecast(self.user, self.function, self.process, run_monte_carlo=False,
                          growth_rate_percentage=Decimal("5"))
        f.refresh_from_db()
        self.assertTrue(f.has_projection)
        self.assertEqual(f.projected_shortfall_month, 5)
        self.assertEqual(f.outlook, "short_future")
        self.assertEqual(f.projected_horizon_required_fte, Decimal("4.40"))
        self.assertEqual(f.horizon_additional_fte, Decimal("2.00"))
        self.assertEqual(f.shortfall_label, f.projection_points[5]["label"])
        self.assertEqual(f.sufficient_until_label, f.projection_points[4]["label"])
        self.assertEqual(f.status, "SUFFICIENT")

    def test_growth_removed_clears_projection(self):
        f = make_forecast(self.user, self.function, self.process, growth_rate_percentage=Decimal("5"))
        f.growth_rate_percentage = Decimal("0")
        save_forecast(f, self.user)
        f.refresh_from_db()
        self.assertFalse(f.has_projection)
        self.assertEqual(f.outlook, "none")

    def test_random_seed_keeps_month_zero_consistent(self):
        f = make_forecast(self.user, self.function, self.process, simulation_seed=None,
                          growth_rate_percentage=Decimal("3"))
        self.assertEqual(f.projection_points[0]["sufficiency"], float(f.latest_summary.sufficiency_probability))
        self.assertEqual(f.projection_points[0]["status"], f.status)
