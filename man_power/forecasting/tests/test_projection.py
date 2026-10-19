from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from forecasting.services.calculations import ForecastInput
from forecasting.services.forecast_service import compute_projection, save_forecast
from forecasting.services.projection import growth_factor, periods_elapsed

from .helpers import make_forecast, make_masters, make_user

START = date(2026, 10, 5)


def invoice_input(**kw):
    data = dict(frequency="MONTHLY", volume=Decimal("2200"), current_fte=Decimal("3"),
                avg_processing_time=Decimal("10"), run_monte_carlo=False,
                growth_rate_percentage=Decimal("5"), growth_period="MONTHLY", forecast_horizon_months=12)
    data.update(kw)
    return ForecastInput(**data)


class GrowthFactorTests(SimpleTestCase):
    def test_periods(self):
        self.assertEqual(growth_factor(10, "QUARTERLY", 12), Decimal("1.1") ** 4)
        self.assertEqual(periods_elapsed("DAILY", 1, 5, 22), 22)
        self.assertEqual(periods_elapsed("WEEKLY", 12, 5, 22), 52)

    def test_decimal_days(self):
        self.assertEqual(periods_elapsed("DAILY", 1, Decimal("5.5"), Decimal("23.83")), 23)
        self.assertEqual(periods_elapsed("WEEKLY", 12, Decimal("5.5"), Decimal("23.83")), 51)


class ProjectionTests(SimpleTestCase):
    def test_volume_only(self):
        proj = compute_projection(invoice_input(), START)
        self.assertEqual(proj.shortfall_month, 5)
        self.assertEqual(proj.horizon_fte_needed, Decimal("5.00"))
        self.assertEqual(proj.points[12]["required_people"], 5)
        self.assertIn("required FTE moves from 3 to 5", proj.summary)

    def test_volume_growth_with_aht_reduction(self):
        proj = compute_projection(invoice_input(aht_change_percentage=Decimal("-2")), START)
        self.assertEqual(proj.shortfall_month, 8)
        self.assertEqual(proj.points[12]["aht_minutes"], 7.85)

    def test_no_growth(self):
        self.assertIsNone(compute_projection(invoice_input(growth_rate_percentage=0), START))


class ProjectionPersistenceTests(TestCase):
    def setUp(self):
        self.user = make_user("analyst", "Analyst")
        self.function, self.process = make_masters()

    def test_saved(self):
        f = make_forecast(self.user, self.function, self.process, run_monte_carlo=False,
                          growth_rate_percentage=Decimal("5"), aht_change_percentage=Decimal("-2"))
        self.assertEqual(f.projected_shortfall_month, 8)
        self.assertEqual(f.growth_drivers_text, "+5% volume per month and -2% AHT per month")

    def test_growth_removed_clears_projection(self):
        f = make_forecast(self.user, self.function, self.process, growth_rate_percentage=Decimal("5"))
        f.growth_rate_percentage = Decimal("0")
        save_forecast(f, self.user)
        self.assertFalse(f.has_projection)
