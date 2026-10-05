from decimal import Decimal

from django.test import SimpleTestCase

from forecasting.services.calculations import (ForecastInput, calculate_deterministic, convert_time_to_minutes,
                                               convert_to_daily_volume, fmt, productive_capacity, safe_divide)


class FrequencyConversionTests(SimpleTestCase):
    def test_all_frequencies(self):
        cases = [
            ("DAILY", 100, Decimal("100")),
            ("WEEKLY", 500, Decimal("100")),          # 500 / 5
            ("MONTHLY", 2200, Decimal("100")),        # 2200 / 22
            ("QUARTERLY", 6600, Decimal("100")),      # 6600 / 66
            ("HALF_YEARLY", 13200, Decimal("100")),   # 13200 / 132
            ("YEARLY", 26400, Decimal("100")),        # 26400 / 264
        ]
        for freq, volume, expected in cases:
            with self.subTest(freq=freq):
                self.assertEqual(convert_to_daily_volume(volume, freq, 5, 22), expected)

    def test_configurable_working_days(self):
        self.assertEqual(convert_to_daily_volume(600, "WEEKLY", 6, 22), Decimal("100"))
        self.assertEqual(convert_to_daily_volume(2600, "MONTHLY", 5, 26), Decimal("100"))

    def test_invalid_frequency(self):
        with self.assertRaises(ValueError):
            convert_to_daily_volume(100, "HOURLY", 5, 22)


class TimeConversionTests(SimpleTestCase):
    def test_units(self):
        self.assertEqual(convert_time_to_minutes(90, "SECONDS"), Decimal("1.5"))
        self.assertEqual(convert_time_to_minutes(10, "MINUTES"), Decimal("10"))
        self.assertEqual(convert_time_to_minutes(2, "HOURS"), Decimal("120"))

    def test_invalid_unit(self):
        with self.assertRaises(ValueError):
            convert_time_to_minutes(1, "DAYS")


class ProductiveCapacityTests(SimpleTestCase):
    def test_default_8_hours_15_percent(self):
        cap = productive_capacity(8, 15)
        self.assertEqual(cap.total_available_minutes, Decimal("480"))
        self.assertEqual(cap.contingency_minutes, Decimal("72"))
        self.assertEqual(cap.productive_minutes, Decimal("408"))
        self.assertEqual(cap.productive_hours, Decimal("6.8"))

    def test_custom_values(self):
        self.assertEqual(productive_capacity(9, 20).productive_minutes, Decimal("432"))


class DeterministicCalculationTests(SimpleTestCase):
    def test_reference_example(self):
        r = calculate_deterministic(ForecastInput(frequency="MONTHLY", volume=2200, current_fte=3,
                                                  avg_processing_time=10))
        self.assertEqual(r.daily_volume, Decimal("100.0000"))
        self.assertEqual(r.workload_minutes, Decimal("1000.00"))
        self.assertEqual(r.workload_hours, Decimal("16.67"))
        self.assertEqual(r.productive_minutes_per_fte, Decimal("408.00"))
        self.assertEqual(r.available_capacity_minutes, Decimal("1224.00"))
        self.assertEqual(r.required_fte, Decimal("2.45"))
        self.assertEqual(r.recommended_operational_fte, Decimal("3"))
        self.assertEqual(r.fte_gap, Decimal("0.55"))
        self.assertEqual(r.operational_fte_gap, Decimal("0.00"))
        self.assertEqual(r.utilization_percentage, Decimal("81.70"))
        self.assertEqual(r.unused_capacity_percentage, Decimal("18.30"))

    def test_vendor_payments_example(self):
        r = calculate_deterministic(ForecastInput(frequency="DAILY", volume=20, current_fte=2,
                                                  avg_processing_time=2, time_unit="HOURS"))
        self.assertEqual(r.required_fte, Decimal("5.88"))
        self.assertEqual(r.recommended_operational_fte, Decimal("6"))
        self.assertEqual(r.utilization_percentage, Decimal("294.12"))

    def test_exact_integer_requirement_not_rounded_up(self):
        r = calculate_deterministic(ForecastInput(frequency="DAILY", volume=408, current_fte=1,
                                                  avg_processing_time=1))
        self.assertEqual(r.required_fte, Decimal("1.00"))
        self.assertEqual(r.recommended_operational_fte, Decimal("1"))

    def test_zero_fte_safe(self):
        r = calculate_deterministic(ForecastInput(frequency="MONTHLY", volume=2200, current_fte=0,
                                                  avg_processing_time=10))
        self.assertIsNone(r.utilization_percentage)
        self.assertIsNone(r.unused_capacity_percentage)
        self.assertEqual(r.fte_gap, Decimal("-2.45"))

    def test_safe_divide(self):
        self.assertEqual(safe_divide(10, 0), Decimal("0"))
        self.assertIsNone(safe_divide(10, 0, default=None))

    def test_input_defaults(self):
        inp = ForecastInput(frequency="DAILY", volume=1, current_fte=1, avg_processing_time=1,
                            run_monte_carlo=False, volume_variation_percentage=None, time_variation_percentage=None,
                            simulation_count=None, growth_rate_percentage=None, growth_period=None,
                            forecast_horizon_months=None)
        self.assertEqual(inp.volume_variation_percentage, Decimal("10"))
        self.assertEqual(inp.simulation_count, 10000)
        self.assertEqual(inp.growth_rate_percentage, Decimal("0"))
        self.assertEqual(inp.growth_period, "MONTHLY")
        self.assertEqual(inp.forecast_horizon_months, 12)
        self.assertFalse(inp.has_growth)

    def test_fmt(self):
        self.assertEqual(fmt(Decimal("3.00")), "3")
        self.assertEqual(fmt(2.45), "2.45")
        self.assertEqual(fmt(10), "10")
