from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, override_settings

from forecasting.services.calculations import (ForecastInput, aht_from_total_time, available_time_in_period,
                                               calculate_deterministic, convert_to_daily_volume, productive_capacity)
from forecasting.services.forecast_service import compute_projection
from forecasting.services.monte_carlo import run_monte_carlo
from forecasting.services.projection import growth_factor, periods_elapsed
from forecasting.services.status import classify_status


class CalculationTests(SimpleTestCase):
    def test_frequencies_and_decimal_days(self):
        self.assertEqual(convert_to_daily_volume(2200, "MONTHLY", 5, 22), Decimal("100"))
        self.assertEqual(convert_to_daily_volume(550, "WEEKLY", Decimal("5.5"), 22), Decimal("100"))

    def test_productive_capacity(self):
        self.assertEqual(productive_capacity(8, 15).productive_minutes, Decimal("408"))

    def test_available_time_ignores_contingency(self):
        self.assertEqual(available_time_in_period(3, 8, 15, "MONTHLY", 5, 22), Decimal("528.0000"))
        self.assertEqual(available_time_in_period(3, 8, 40, "MONTHLY", 5, 22), Decimal("528.0000"))
        self.assertEqual(available_time_in_period(Decimal("2.5"), 8, 15, "MONTHLY", 5, 22), Decimal("440.0000"))

    def test_user_example_yearly(self):
        hours = available_time_in_period(180, 8, 15, "YEARLY", 5, 22)
        self.assertEqual(hours, Decimal("380160.0000"))
        self.assertEqual(aht_from_total_time(hours, 6305).quantize(Decimal("0.0001")), Decimal("3617.7002"))

    def test_reference_example(self):
        r = calculate_deterministic(ForecastInput(frequency="MONTHLY", volume=2200, current_fte=3, avg_processing_time=10))
        self.assertEqual(r.required_fte, Decimal("2.45"))
        self.assertEqual(r.utilization_percentage, Decimal("81.70"))
        self.assertEqual(r.breakeven_aht_minutes, Decimal("12.2400"))

    def test_decimal_fte_and_volume(self):
        r = calculate_deterministic(ForecastInput(frequency="DAILY", volume=Decimal("100.5"),
                                                  current_fte=Decimal("2.5"), avg_processing_time=10))
        self.assertEqual(r.required_fte, Decimal("2.46"))
        self.assertEqual(r.utilization_percentage, Decimal("98.53"))


class StatusTests(SimpleTestCase):
    def test_less_with_decimal_fte(self):
        r = classify_status(Decimal("2.5"), Decimal("2.9"), Decimal("116"), Decimal("5"), Decimal("3.4"))
        self.assertEqual(r.status, "LESS")
        self.assertIn("Add 0.5 FTE (requirement: 3 FTE)", r.recommendation)
        self.assertIn("2.5 FTE", r.explanation)

    def test_sufficient(self):
        r = classify_status(Decimal("3"), Decimal("2.45"), Decimal("81.67"), Decimal("95"))
        self.assertEqual(r.status, "SUFFICIENT")

    def test_higher(self):
        r = classify_status(Decimal("4"), Decimal("2.35"), Decimal("58.75"))
        self.assertEqual(r.status, "HIGHER")
        self.assertIn("About 1 FTE can be reallocated", r.recommendation)

    def test_zero_fte(self):
        self.assertEqual(classify_status(Decimal("0"), Decimal("2.45"), None, Decimal("0")).status, "LESS")

    @override_settings(FORECASTING={"SUFFICIENCY_THRESHOLD": 95, "UTILIZATION_LOWER": 70, "UTILIZATION_UPPER": 90})
    def test_thresholds_configurable(self):
        self.assertEqual(classify_status(3, 2.45, Decimal("81.67"), Decimal("90"), 3).status, "LESS")


class MonteCarloAndProjectionTests(SimpleTestCase):
    def test_monte_carlo(self):
        kw = dict(daily_volume=100, processing_time_minutes=10, productive_minutes_per_fte=408, current_fte=3,
                  volume_variation_pct=10, time_variation_pct=15, simulation_count=10000, seed=42)
        r = run_monte_carlo(**kw)
        self.assertEqual(r.as_dict(), run_monte_carlo(**kw).as_dict())
        self.assertEqual(r.risk_adjusted_recommended_fte, 4)

    def test_growth_periods(self):
        self.assertEqual(growth_factor(10, "QUARTERLY", 12), Decimal("1.1") ** 4)
        self.assertEqual(periods_elapsed("WEEKLY", 12, 5, 22), 52)

    def test_projection(self):
        proj = compute_projection(ForecastInput(frequency="MONTHLY", volume=2200, current_fte=3, avg_processing_time=10,
                                                run_monte_carlo=False, growth_rate_percentage=5,
                                                aht_change_percentage=-2), date(2026, 10, 5))
        self.assertEqual(proj.shortfall_month, 8)
        self.assertEqual(proj.points[12]["aht_minutes"], 7.85)
