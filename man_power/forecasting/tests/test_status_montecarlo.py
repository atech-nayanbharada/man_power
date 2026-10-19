from decimal import Decimal

from django.test import SimpleTestCase, override_settings

from forecasting.services.calculations import ForecastInput
from forecasting.services.forecast_service import compute_forecast
from forecasting.services.monte_carlo import run_monte_carlo
from forecasting.services.status import HIGH_UTILIZATION_WARNING, MC_NOT_RUN_NOTE, classify_status


class StatusClassificationTests(SimpleTestCase):
    def test_less_whole_people_text(self):
        r = classify_status(Decimal("2"), Decimal("2.45"), Decimal("122.5"), Decimal("5"), Decimal("3.1"))
        self.assertEqual(r.status, "LESS")
        self.assertIn("Add 1 FTE (requirement: 3 FTE)", r.recommendation)
        self.assertIn("Plan for 4 FTE in total", r.recommendation)
        self.assertNotIn(".45", r.recommendation + r.explanation)

    def test_less_when_probability_below_threshold(self):
        r = classify_status(Decimal("3"), Decimal("2.9"), Decimal("96.67"), Decimal("60"), Decimal("3.3"))
        self.assertEqual(r.status, "LESS")
        self.assertTrue(r.high_utilization_risk)
        self.assertEqual(r.warning, HIGH_UTILIZATION_WARNING)

    def test_sufficient(self):
        r = classify_status(Decimal("3"), Decimal("2.45"), Decimal("81.67"), Decimal("95"))
        self.assertEqual(r.status, "SUFFICIENT")
        self.assertIn("covers the required 3 FTE", r.explanation)

    def test_higher_whole_people(self):
        r = classify_status(Decimal("4"), Decimal("2.35"), Decimal("58.75"))
        self.assertEqual(r.status, "HIGHER")
        self.assertIn("About 1 FTE can be reallocated", r.recommendation)
        self.assertIn(MC_NOT_RUN_NOTE, r.explanation)

    def test_zero_fte_is_less(self):
        self.assertEqual(classify_status(Decimal("0"), Decimal("2.45"), None, Decimal("0")).status, "LESS")

    @override_settings(FORECASTING={"SUFFICIENCY_THRESHOLD": 95, "UTILIZATION_LOWER": 70, "UTILIZATION_UPPER": 90})
    def test_thresholds_are_configurable(self):
        self.assertEqual(classify_status(3, 2.45, Decimal("81.67"), Decimal("90"), 3).status, "LESS")

    def test_compute_forecast_skips_simulation(self):
        comp = compute_forecast(ForecastInput(frequency="MONTHLY", volume=2200, current_fte=3,
                                              avg_processing_time=10, run_monte_carlo=False))
        self.assertIsNone(comp.monte_carlo)


class MonteCarloTests(SimpleTestCase):
    def kwargs(self, **kw):
        base = dict(daily_volume=100, processing_time_minutes=10, productive_minutes_per_fte=408, current_fte=3,
                    volume_variation_pct=10, time_variation_pct=15, simulation_count=10000, seed=42)
        base.update(kw)
        return base

    def test_reproducible_and_reasonable(self):
        r = run_monte_carlo(**self.kwargs())
        self.assertEqual(r.as_dict(), run_monte_carlo(**self.kwargs()).as_dict())
        self.assertAlmostEqual(r.p90_required_fte, 3.03, delta=0.05)
        self.assertEqual(r.risk_adjusted_recommended_fte, 4)

    def test_samples_never_negative(self):
        _, s = run_monte_carlo(**self.kwargs(volume_variation_pct=200, time_variation_pct=200), return_samples=True)
        self.assertTrue((s["volume"] >= 0).all())

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            run_monte_carlo(**self.kwargs(simulation_count=0))
