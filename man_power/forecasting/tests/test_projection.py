"""Future projection: volume growth and AHT change compounding, shortfall detection, hiring plan and summary."""
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from forecasting.services.calculations import ForecastInput
from forecasting.services.forecast_service import compute_forecast, compute_projection, save_forecast
from forecasting.services.projection import (add_months, growth_factor, month_label, periods_elapsed,
                                             workload_factors)

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

    def test_zero_rate_is_neutral(self):
        self.assertEqual(growth_factor(0, "DAILY", 12), Decimal("1"))

    def test_workload_factor_combines_volume_and_aht(self):
        inp = invoice_input(growth_rate_percentage=10, growth_period="MONTHLY",
                            aht_change_percentage=-10, aht_change_period="QUARTERLY")
        vf, af, wf = workload_factors(inp, 3)
        self.assertEqual(vf, Decimal("1.1") ** 3)
        self.assertEqual(af, Decimal("0.9"))
        self.assertEqual(wf, vf * af)

    def test_month_labels(self):
        self.assertEqual(add_months(START, 3), date(2027, 1, 1))
        self.assertEqual(month_label(START, 0), "Oct 2026")
        self.assertEqual(month_label(START, 14), "Dec 2027")


class ProjectionDeterministicTests(SimpleTestCase):
    def test_no_growth_returns_none(self):
        self.assertIsNone(compute_projection(invoice_input(growth_rate_percentage=0), START))

    def test_volume_growth_shortfall_and_horizon(self):
        proj = compute_projection(invoice_input(), START)
        self.assertEqual(len(proj.points), 13)
        self.assertEqual(proj.points[0]["required_fte"], 2.45)
        self.assertEqual(proj.points[4]["status"], "SUFFICIENT")
        self.assertTrue(proj.points[4]["high_risk"])
        self.assertEqual(proj.points[5]["status"], "LESS")
        self.assertEqual(proj.shortfall_month, 5)
        self.assertEqual(proj.horizon_required_fte, Decimal("4.40"))
        self.assertEqual(proj.horizon_fte_needed, Decimal("5.00"))
        self.assertEqual(proj.points[12]["aht_minutes"], 10.0)        # AHT unchanged
        self.assertIn("5% volume growth per month", proj.summary)
        self.assertNotIn("AHT", proj.summary)
        self.assertIn("remains sufficient until Feb 2027 (month 4)", proj.summary)
        self.assertIn("From Mar 2027 (month 5) additional manpower is required", proj.summary)
        self.assertIn("2 more than today", proj.summary)

    def test_aht_only_increase_matches_equivalent_volume_growth(self):
        # +5% AHT per month has exactly the same workload effect as +5% volume per month
        proj = compute_projection(invoice_input(growth_rate_percentage=0, aht_change_percentage=5,
                                                aht_change_period="MONTHLY"), START)
        self.assertEqual(proj.shortfall_month, 5)
        self.assertEqual(proj.horizon_required_fte, Decimal("4.40"))
        self.assertEqual(proj.points[12]["volume"], 2200.0)            # volume unchanged
        self.assertEqual(proj.points[12]["aht_minutes"], 17.96)        # 10 x 1.05^12
        self.assertIn("5% AHT increase per month", proj.summary)
        self.assertIn("AHT moves from 10 to 17.96 minutes", proj.summary)

    def test_aht_reduction_offsets_volume_growth(self):
        # +5% volume and -5% AHT per month -> workload x0.9975^m -> stays sufficient
        proj = compute_projection(invoice_input(aht_change_percentage=-5, aht_change_period="MONTHLY"), START)
        self.assertIsNone(proj.shortfall_month)
        self.assertEqual(proj.horizon_required_fte, Decimal("2.38"))
        self.assertIn("5% volume growth per month and 5% AHT reduction per month", proj.summary)
        self.assertIn("remains sufficient for the full 12-month horizon", proj.summary)

    def test_aht_increase_brings_shortfall_forward(self):
        # +5% volume and +5% AHT per month -> workload x1.1025^m -> short from month 3
        proj = compute_projection(invoice_input(aht_change_percentage=5, aht_change_period="MONTHLY"), START)
        self.assertEqual(proj.shortfall_month, 3)
        self.assertEqual(proj.points[2]["status"], "SUFFICIENT")

    def test_quarterly_aht_steps(self):
        proj = compute_projection(invoice_input(growth_rate_percentage=0, aht_change_percentage=-10,
                                                aht_change_period="QUARTERLY"), START)
        self.assertEqual(proj.points[2]["aht_minutes"], 10.0)
        self.assertEqual(proj.points[3]["aht_minutes"], 9.0)
        self.assertEqual(proj.points[6]["aht_minutes"], 8.1)
        self.assertEqual(proj.points[3]["aht_factor"], 0.9)

    def test_aht_in_seconds_converted(self):
        proj = compute_projection(invoice_input(growth_rate_percentage=0, avg_processing_time=Decimal("600"),
                                                time_unit="SECONDS", aht_change_percentage=10,
                                                aht_change_period="YEARLY"), START)
        self.assertEqual(proj.points[0]["aht_minutes"], 10.0)
        self.assertEqual(proj.points[12]["aht_minutes"], 11.0)
        self.assertEqual(proj.points[12]["aht"], 660.0)               # stored in the entered unit

    def test_hiring_plan_steps(self):
        proj = compute_projection(invoice_input(), START)
        self.assertEqual([(s["month"], s["fte_needed"], s["additional_fte"]) for s in proj.hiring_plan],
                         [(5, 4.0, 1.0), (11, 5.0, 2.0)])

    def test_sufficient_through_horizon(self):
        proj = compute_projection(invoice_input(growth_rate_percentage=1), START)
        self.assertIsNone(proj.shortfall_month)
        self.assertEqual(proj.hiring_plan, [])

    def test_already_short_and_recovers_with_aht_reduction(self):
        # 150/day x 6 min = 2.21 FTE vs 2 FTE; -5% AHT per month -> 1.99 at month 2
        proj = compute_projection(ForecastInput(frequency="DAILY", volume=150, current_fte=2, avg_processing_time=6,
                                                run_monte_carlo=False, aht_change_percentage=-5,
                                                forecast_horizon_months=6), START)
        self.assertEqual(proj.shortfall_month, 0)
        self.assertEqual(proj.points[2]["status"], "SUFFICIENT")
        self.assertIn("becomes sufficient from Dec 2026 (month 2)", proj.summary)

    def test_month_zero_matches_current_result(self):
        inp = invoice_input(aht_change_percentage=3)
        today = compute_forecast(inp)
        proj = compute_projection(inp, START)
        self.assertEqual(Decimal(str(proj.points[0]["required_fte"])), today.deterministic.required_fte)
        self.assertEqual(proj.points[0]["status"], today.status.status)

    def test_projection_with_monte_carlo(self):
        inp = invoice_input(run_monte_carlo=True, simulation_count=2000, simulation_seed=7,
                            aht_change_percentage=-2, aht_change_period="QUARTERLY")
        proj = compute_projection(inp, START)
        self.assertIsNotNone(proj.points[0]["p90_fte"])
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
        self.assertEqual(f.horizon_additional_fte, Decimal("2.00"))
        self.assertEqual(f.growth_drivers, ["+5% volume per month"])
        self.assertEqual(f.status, "SUFFICIENT")

    def test_aht_only_forecast_saved(self):
        f = make_forecast(self.user, self.function, self.process, run_monte_carlo=False,
                          aht_change_percentage=Decimal("-2.5"), aht_change_period="QUARTERLY")
        f.refresh_from_db()
        self.assertTrue(f.has_projection)
        self.assertTrue(f.has_aht_change)
        self.assertFalse(f.has_volume_growth)
        self.assertEqual(f.growth_drivers_text, "-2.5% AHT per quarter")
        self.assertEqual(f.projection_end_aht, 9.04)               # 10 x 0.975^4
        self.assertEqual(f.outlook, "ok")

    def test_both_drivers_text(self):
        f = make_forecast(self.user, self.function, self.process, run_monte_carlo=False,
                          growth_rate_percentage=Decimal("10"), growth_period="YEARLY",
                          aht_change_percentage=Decimal("3"), aht_change_period="HALF_YEARLY")
        self.assertEqual(f.growth_drivers_text, "+10% volume per year and +3% AHT per half-year")

    def test_removing_both_drivers_clears_projection(self):
        f = make_forecast(self.user, self.function, self.process, growth_rate_percentage=Decimal("5"),
                          aht_change_percentage=Decimal("2"))
        f.growth_rate_percentage = Decimal("0")
        f.aht_change_percentage = Decimal("0")
        save_forecast(f, self.user)
        f.refresh_from_db()
        self.assertFalse(f.has_projection)
        self.assertEqual(f.outlook, "none")

    def test_random_seed_keeps_month_zero_consistent(self):
        f = make_forecast(self.user, self.function, self.process, simulation_seed=None,
                          aht_change_percentage=Decimal("3"))
        self.assertEqual(f.projection_points[0]["sufficiency"], float(f.latest_summary.sufficiency_probability))
        self.assertEqual(f.projection_points[0]["status"], f.status)
