"""Current FTE and Volume accept decimals."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from forecasting.forms import ManpowerForecastForm, ScenarioForm
from forecasting.services.explain import calculation_steps

from .helpers import PASSWORD, form_data, make_forecast, make_masters, make_user


class DecimalFteTests(TestCase):
    def setUp(self):
        self.user = make_user("analyst", "Analyst")
        self.function, self.process = make_masters()

    def test_form_accepts_decimals(self):
        form = ManpowerForecastForm(data=form_data(self.function, self.process, current_fte="2.5", volume="6305.5"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["current_fte"], Decimal("2.5"))
        self.assertEqual(form.cleaned_data["volume"], Decimal("6305.5"))

    def test_negative_fte_rejected(self):
        self.assertIn("current_fte", ManpowerForecastForm(data=form_data(self.function, self.process,
                                                                         current_fte="-0.5")).errors)

    def test_calculation_with_decimal_fte(self):
        f = make_forecast(self.user, self.function, self.process, current_fte=Decimal("2.5"), run_monte_carlo=False)
        self.assertEqual(f.required_people, 3)                 # 2.45 rounded up
        self.assertEqual(f.people_gap, Decimal("-0.50"))
        self.assertEqual(f.utilization_percentage, Decimal("98.04"))  # 2.45 / 2.5
        self.assertIn("2.5 FTE", f.status_explanation)
        steps = {s["label"]: s for s in calculation_steps(f)}
        self.assertEqual(steps["Current FTE"]["result"], "2.5 FTE")
        self.assertEqual(steps["Gap"]["result"], "-0.5 FTE")

    def test_calculate_aht_with_decimal_fte(self):
        form = ManpowerForecastForm(data=form_data(self.function, self.process, current_fte="2.5",
                                                   avg_processing_time=""))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["avg_processing_time"], Decimal("12.0000"))  # 2.5 x 8 x 22 x 60 / 2200

    def test_pages_show_decimal(self):
        f = make_forecast(self.user, self.function, self.process, current_fte=Decimal("2.5"), run_monte_carlo=False)
        self.client.login(username="analyst", password=PASSWORD)
        self.assertContains(self.client.get(reverse("forecasting:forecast_result", args=[f.pk])), "2.5")
        self.assertContains(self.client.get(reverse("forecasting:forecast_update", args=[f.pk])), 'value="2.5"')
        self.assertEqual(self.client.get(reverse("forecasting:forecast_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("forecasting:dashboard")).status_code, 200)

    def test_scenario_proposed_fte_decimal(self):
        form = ScenarioForm(data={"current_fte": "3.5"})
        self.assertTrue(form.is_valid(), form.errors)
