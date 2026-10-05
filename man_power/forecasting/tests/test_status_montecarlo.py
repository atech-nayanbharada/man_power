from decimal import Decimal

from django.test import SimpleTestCase, override_settings

from forecasting.services.calculations import ForecastInput
from forecasting.services.forecast_service import compute_forecast
from forecasting.services.monte_carlo import run_monte_carlo
from forecasting.services.status import HIGH_UTILIZATION_WARNING, MC_NOT_RUN_NOTE, classify_status


class StatusClassificationTests(SimpleTestCase):
    def test_less_when_current_below_required(self):
        r = classify_status(Decimal("2"), Decimal("2.45"), Decimal("122.5"), Decimal("5"))
        self.assertEqual(r.status, "LESS")
        self.assertIn("Additional manpower", r.recommendation)

    def test_less_when_probability_below_threshold(self):
        r = classify_status(Decimal("3"), Decimal("2.9"), Decimal("96.67"), Decimal("60"))
        self.assertEqual(r.status, "LESS")
        self.assertTrue(r.high_utilization_risk)
        self.assertEqual(r.warning, HIGH_UTILIZATION_WARNING)

    def test_sufficient_in_band(self):
        r = classify_status(Decimal("3"), Decimal("2.45"), Decimal("81.67"), Decimal("95"))
        self.assertEqual(r.status, "SUFFICIENT")
        self.assertEqual(r.recommendation, "Current manpower is sufficient for the expected workload.")

    def test_sufficient_with_high_utilization_risk(self):
        r = classify_status(Decimal("10"), Decimal("9.2"), Decimal("92"), Decimal("85"))
        self.assertEqual(r.status, "SUFFICIENT")
        self.assertTrue(r.high_utilization_risk)

    def test_higher_when_utilization_below_70(self):
        r = classify_status(Decimal("4"), Decimal("2"), Decimal("50"), Decimal("100"))
        self.assertEqual(r.status, "HIGHER")

    def test_zero_fte_is_less(self):
        r = classify_status(Decimal("0"), Decimal("2.45"), None, Decimal("0"))
        self.assertEqual(r.status, "LESS")
        self.assertIn("utilization cannot be calculated", r.explanation)

    def test_boundaries(self):
        self.assertEqual(classify_status(10, 7, Decimal("70"), 100).status, "SUFFICIENT")
        r = classify_status(10, 9, Decimal("90"), 90)
        self.assertEqual(r.status, "SUFFICIENT")
        self.assertFalse(r.high_utilization_risk)
        self.assertEqual(classify_status(3, 2.4, Decimal("80"), Decimal("80")).status, "SUFFICIENT")

    @override_settings(FORECASTING={"SUFFICIENCY_THRESHOLD": 95, "UTILIZATION_LOWER": 70, "UTILIZATION_UPPER": 90})
    def test_thresholds_are_configurable(self):
        self.assertEqual(classify_status(3, 2.45, Decimal("81.67"), Decimal("90")).status, "LESS")


class StatusWithoutMonteCarloTests(SimpleTestCase):
    def test_less_when_short(self):
        r = classify_status(Decimal("2"), Decimal("5.88"), Decimal("294.12"))
        self.assertEqual(r.status, "LESS")
        self.assertIn(MC_NOT_RUN_NOTE, r.explanation)
        self.assertIn("operational requirement: 6 FTE", r.recommendation)

    def test_sufficient_in_band(self):
        r = classify_status(Decimal("3"), Decimal("2.45"), Decimal("81.67"))
        self.assertEqual(r.status, "SUFFICIENT")
        self.assertIn(MC_NOT_RUN_NOTE, r.explanation)

    def test_high_utilization_is_sufficient_with_risk(self):
        r = classify_status(Decimal("1"), Decimal("0.92"), Decimal("91.91"))
        self.assertEqual(r.status, "SUFFICIENT")
        self.assertTrue(r.high_utilization_risk)

    def test_higher(self):
        r = classify_status(Decimal("4"), Decimal("2.35"), Decimal("58.75"))
        self.assertEqual(r.status, "HIGHER")
        self.assertNotIn("P90", r.recommendation)

    def test_compute_forecast_skips_simulation(self):
        comp = compute_forecast(ForecastInput(frequency="MONTHLY", volume=2200, current_fte=3,
                                              avg_processing_time=10, run_monte_carlo=False))
        self.assertIsNone(comp.monte_carlo)
        self.assertEqual(comp.status.status, "SUFFICIENT")


class MonteCarloTests(SimpleTestCase):
    def kwargs(self, **kw):
        base = dict(daily_volume=100, processing_time_minutes=10, productive_minutes_per_fte=408, current_fte=3,
                    volume_variation_pct=10, time_variation_pct=15, simulation_count=10000, seed=42)
        base.update(kw)
        return base

    def test_reproducible_with_seed(self):
        self.assertEqual(run_monte_carlo(**self.kwargs()).as_dict(), run_monte_carlo(**self.kwargs()).as_dict())

    def test_percentiles_ordered_and_reasonable(self):
        r = run_monte_carlo(**self.kwargs())
        self.assertLessEqual(r.minimum_required_fte, r.p50_required_fte)
        self.assertLess(r.p50_required_fte, r.p80_required_fte)
        self.assertLess(r.p80_required_fte, r.p90_required_fte)
        self.assertLess(r.p90_required_fte, r.p95_required_fte)
        self.assertLess(r.p95_required_fte, r.p99_required_fte)
        self.assertLessEqual(r.p99_required_fte, r.maximum_required_fte)
        self.assertAlmostEqual(r.average_required_fte, 2.45, delta=0.05)
        self.assertAlmostEqual(r.p90_required_fte, 3.03, delta=0.05)
        self.assertEqual(r.risk_adjusted_recommended_fte, 4)
        self.assertAlmostEqual(r.sufficiency_probability + r.failure_probability, 100.0, places=2)
        self.assertEqual(sum(r.histogram["counts"]), 10000)

    def test_zero_variation_is_deterministic(self):
        r = run_monte_carlo(**self.kwargs(volume_variation_pct=0, time_variation_pct=0))
        self.assertAlmostEqual(r.p90_required_fte, 1000 / 408, places=6)
        self.assertAlmostEqual(r.standard_deviation, 0.0, places=9)
        self.assertEqual(r.sufficiency_probability, 100.0)

    def test_samples_never_negative(self):
        _, s = run_monte_carlo(**self.kwargs(volume_variation_pct=200, time_variation_pct=200), return_samples=True)
        self.assertTrue((s["volume"] >= 0).all())
        self.assertTrue((s["processing_time"] >= 0).all())

    def test_zero_fte_gives_zero_sufficiency(self):
        r = run_monte_carlo(**self.kwargs(current_fte=0))
        self.assertEqual(r.sufficiency_probability, 0.0)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            run_monte_carlo(**self.kwargs(simulation_count=0))
        with self.assertRaises(ValueError):
            run_monte_carlo(**self.kwargs(productive_minutes_per_fte=0))
