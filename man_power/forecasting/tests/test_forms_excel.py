import io
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook, load_workbook

from forecasting.forms import FunctionMasterForm, ManpowerForecastForm, ProcessMasterForm
from forecasting.models import FunctionMaster, ManpowerForecast, ProcessMaster
from forecasting.services import excel_service
from forecasting.services.dashboard_service import build_dashboard
from forecasting.services.forecast_service import build_input, save_forecast
from forecasting.services.scenario_service import compare_scenarios

from .helpers import form_data, make_forecast, make_masters, make_user


class ForecastFormValidationTests(TestCase):
    def setUp(self):
        self.function, self.process = make_masters()

    def data(self, **kw):
        return form_data(self.function, self.process, **kw)

    def test_valid(self):
        form = ManpowerForecastForm(data=self.data())
        self.assertTrue(form.is_valid(), form.errors)

    def test_zero_fte_allowed(self):
        self.assertTrue(ManpowerForecastForm(data=self.data(current_fte="0")).is_valid())

    def test_negative_and_out_of_range_values(self):
        cases = {
            "volume": "0", "current_fte": "-1", "avg_processing_time": "0", "working_hours_per_day": "25",
            "working_days_per_week": "8", "working_days_per_month": "32", "contingency_percentage": "100",
            "volume_variation_percentage": "-5", "time_variation_percentage": "-1", "simulation_count": "500",
            "growth_rate_percentage": "-100", "forecast_horizon_months": "61",
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                form = ManpowerForecastForm(data=self.data(**{field: value}))
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)
                self.assertEqual(len(form.errors[field]), 1)

    def test_monte_carlo_fields_required_when_on(self):
        form = ManpowerForecastForm(data=self.data(simulation_count="", volume_variation_percentage=""))
        self.assertFalse(form.is_valid())
        self.assertIn("simulation_count", form.errors)

    def test_monte_carlo_off_ignores_monte_carlo_fields(self):
        form = ManpowerForecastForm(data=self.data(run_monte_carlo=None, volume_variation_percentage="-5",
                                                   time_variation_percentage="", simulation_count="500",
                                                   simulation_seed="abc"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["simulation_count"], 10000)
        self.assertIsNone(form.cleaned_data["simulation_seed"])

    def test_growth_fields_optional(self):
        form = ManpowerForecastForm(data=self.data(growth_rate_percentage="", growth_period="",
                                                   forecast_horizon_months=""))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["growth_rate_percentage"], Decimal("0"))
        self.assertEqual(form.cleaned_data["growth_period"], "MONTHLY")
        self.assertEqual(form.cleaned_data["forecast_horizon_months"], 12)

    def test_growth_valid_values(self):
        for rate, period in (("5", "MONTHLY"), ("10", "QUARTERLY"), ("-3", "YEARLY"), ("0.5", "DAILY")):
            with self.subTest(rate=rate, period=period):
                form = ManpowerForecastForm(data=self.data(growth_rate_percentage=rate, growth_period=period))
                self.assertTrue(form.is_valid(), form.errors)

    def test_growth_too_high_blocked(self):
        form = ManpowerForecastForm(data=self.data(growth_rate_percentage="50", growth_period="DAILY"))
        self.assertFalse(form.is_valid())
        self.assertIn("multiplies volume", form.errors["growth_rate_percentage"][0])

    def test_process_must_belong_to_function(self):
        other = FunctionMaster.objects.create(function_name="HR")
        form = ManpowerForecastForm(data=self.data(function=other.pk))
        self.assertFalse(form.is_valid())
        self.assertIn("process", form.errors)


class MasterValidationTests(TestCase):
    def setUp(self):
        self.function, self.process = make_masters()

    def test_duplicate_function_case_insensitive(self):
        form = FunctionMasterForm(data={"function_name": "  finance ", "is_active": True})
        self.assertFalse(form.is_valid())

    def test_duplicate_process_in_same_function(self):
        form = ProcessMasterForm(data={"function": self.function.pk, "process_name": "INVOICE PROCESSING",
                                       "default_frequency": "DAILY", "is_active": True})
        self.assertFalse(form.is_valid())

    def test_same_process_name_in_other_function_allowed(self):
        other = FunctionMaster.objects.create(function_name="Procurement")
        form = ProcessMasterForm(data={"function": other.pk, "process_name": "Invoice Processing",
                                       "default_frequency": "DAILY", "is_active": True})
        self.assertTrue(form.is_valid(), form.errors)


class ForecastServiceTests(TestCase):
    def setUp(self):
        self.user = make_user("analyst", "Analyst")
        self.function, self.process = make_masters()

    def test_save_forecast_with_monte_carlo(self):
        f = make_forecast(self.user, self.function, self.process)
        self.assertEqual(f.required_fte, Decimal("2.45"))
        self.assertEqual(f.status, "SUFFICIENT")
        self.assertEqual(f.simulation_summaries.count(), 1)
        self.assertEqual(f.risk_adjusted_fte, Decimal("4"))
        self.assertFalse(f.has_projection)

    def test_save_forecast_without_monte_carlo(self):
        f = make_forecast(self.user, self.function, self.process, run_monte_carlo=False)
        self.assertEqual(f.simulation_summaries.count(), 0)
        self.assertEqual(f.risk_adjusted_fte, Decimal("3"))

    def test_switching_monte_carlo_off_hides_old_summary(self):
        f = make_forecast(self.user, self.function, self.process)
        f.run_monte_carlo = False
        save_forecast(f, self.user)
        self.assertIsNone(f.latest_summary)
        self.assertEqual(f.simulation_summaries.count(), 1)

    def test_scenarios_with_monte_carlo(self):
        f = make_forecast(self.user, self.function, self.process)
        rows = compare_scenarios(build_input(f), [
            {"name": "Growth", "volume_growth_pct": 10},
            {"name": "Contingency 20", "contingency_percentage": 20},
            {"name": "Proposed 4", "current_fte": 4},
            {"name": "Slower", "time_change_pct": 20},
        ])
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[1]["required_fte"], Decimal("2.70"))
        self.assertEqual(rows[2]["required_fte"], Decimal("2.60"))
        self.assertEqual(rows[3]["status"], "HIGHER")
        self.assertEqual(rows[4]["required_fte"], Decimal("2.94"))

    def test_scenarios_with_growth(self):
        f = make_forecast(self.user, self.function, self.process, run_monte_carlo=False,
                          growth_rate_percentage=Decimal("5"))
        rows = compare_scenarios(build_input(f), [{"name": "Faster growth", "growth_rate_percentage": 8},
                                                  {"name": "Proposed 5", "current_fte": 5}])
        self.assertTrue(all(r["has_projection"] for r in rows))
        self.assertEqual(rows[0]["horizon_required_fte"], Decimal("4.40"))
        self.assertGreater(rows[1]["horizon_required_fte"], rows[0]["horizon_required_fte"])
        self.assertEqual(rows[2]["shortfall_label"], "Not within horizon")

    def test_dashboard_mixed_methods_and_outlook(self):
        other = ProcessMaster.objects.create(function=self.function, process_name="Vendor Payments")
        make_forecast(self.user, self.function, self.process, run_monte_carlo=False,
                      growth_rate_percentage=Decimal("5"))
        make_forecast(self.user, self.function, other)
        data = build_dashboard(ManpowerForecast.objects.all())
        cards = data["cards"]
        self.assertEqual(cards["monte_carlo_count"], 1)
        self.assertEqual(cards["projection_count"], 1)
        self.assertEqual(cards["future_shortage_count"], 1)
        self.assertEqual(cards["horizon_additional_fte"], Decimal("2.00"))


def build_upload(rows, headers=None):
    wb = Workbook()
    ws = wb.active
    ws.append(headers or [h for h, _ in excel_service.UPLOAD_COLUMNS])
    for r in rows:
        ws.append(r)
    bio = io.BytesIO()
    wb.save(bio)
    return SimpleUploadedFile("upload.xlsx", bio.getvalue())


def row(function="Finance", process="Invoice Processing", frequency="Monthly", volume=2200, fte=3, time=10,
        unit="Minutes", run_mc="Yes", vol_var=10, time_var=15, sims=2000, growth=0, period="Monthly",
        horizon=12, remarks=""):
    return [function, process, frequency, volume, fte, time, unit, 8, 5, 22, 15, run_mc, vol_var, time_var, sims,
            growth, period, horizon, remarks]


class ExcelUploadTests(TestCase):
    def setUp(self):
        self.user = make_user("analyst", "Analyst")
        self.function, self.process = make_masters()
        self.vendor = ProcessMaster.objects.create(function=self.function, process_name="Vendor Payments")

    def test_mixed_valid_and_invalid_rows(self):
        upload = build_upload([
            row(remarks="ok"),
            row(process="Vendor Payments", frequency="weekly", volume=-5),
            row(function="Unknown", process="Something"),
            row(process="Vendor Payments", frequency="Fortnightly"),
            [*row(process="Vendor Payments", frequency="Weekly", volume=400, fte=4, time=12)[:6],
             None, None, None, None, None, None, None, None, None, None, None, None, ""],
        ])
        result = excel_service.process_upload(upload, self.user)
        self.assertEqual(result.total_rows, 5)
        self.assertEqual(result.success_count, 2)
        self.assertEqual(result.error_count, 3)
        rows = {e["row_number"]: e["errors"] for e in result.errors}
        self.assertIn("Volume must be greater than zero", rows[3])
        self.assertIn("does not exist", rows[4])
        self.assertIn("Invalid frequency", rows[5])
        defaulted = ManpowerForecast.objects.get(process=self.vendor)
        self.assertTrue(defaulted.run_monte_carlo)
        self.assertEqual(defaulted.growth_rate_percentage, Decimal("0.00"))

    def test_growth_columns(self):
        upload = build_upload([
            row(run_mc="No", growth=5, period="Monthly", horizon=12),
            row(process="Vendor Payments", growth=10, period="Fortnightly"),
            row(process="Vendor Payments", growth=50, period="Daily", horizon=12),
        ])
        result = excel_service.process_upload(upload, self.user)
        self.assertEqual(result.success_count, 1)
        errors = {e["row_number"]: e["errors"] for e in result.errors}
        self.assertIn("Growth Period: Invalid growth period", errors[3])
        self.assertIn("multiplies volume", errors[4])
        f = ManpowerForecast.objects.get(process=self.process)
        self.assertEqual(f.projected_shortfall_month, 5)

    def test_run_monte_carlo_no(self):
        upload = build_upload([row(run_mc="No", vol_var=-5, time_var=None, sims=50),
                               row(process="Vendor Payments", run_mc="Maybe")])
        result = excel_service.process_upload(upload, self.user)
        self.assertEqual(result.success_count, 1)
        self.assertIn("Run Monte Carlo: Invalid value", result.errors[0]["errors"])
        self.assertFalse(ManpowerForecast.objects.get(process=self.process).run_monte_carlo)

    def test_old_template_without_new_columns(self):
        headers = [h for h, _ in excel_service.UPLOAD_COLUMNS
                   if h not in ("Run Monte Carlo", "Growth Percentage", "Growth Period", "Forecast Horizon Months")]
        upload = build_upload([["Finance", "Invoice Processing", "Monthly", 2200, 3, 10, "Minutes", 8, 5, 22, 15,
                                10, 15, 2000, ""]], headers=headers)
        result = excel_service.process_upload(upload, self.user)
        self.assertEqual(result.success_count, 1)
        self.assertFalse(ManpowerForecast.objects.get().has_projection)

    def test_duplicate_rows_in_file(self):
        result = excel_service.process_upload(build_upload([row(), row()]), self.user)
        self.assertEqual(result.success_count, 1)
        self.assertIn("Duplicate", result.errors[0]["errors"])

    def test_process_from_other_function(self):
        FunctionMaster.objects.create(function_name="HR")
        result = excel_service.process_upload(build_upload([row(function="HR")]), self.user)
        self.assertIn("does not belong", result.errors[0]["errors"])

    def test_missing_columns(self):
        with self.assertRaises(excel_service.UploadFormatError):
            excel_service.process_upload(build_upload([["Finance"]], headers=["Function Name"]), self.user)

    def test_template_and_reports(self):
        wb = load_workbook(io.BytesIO(excel_service.generate_upload_template()))
        self.assertEqual(wb.sheetnames, ["Forecast Upload", "Instructions", "Valid Masters"])
        make_forecast(self.user, self.function, self.process, growth_rate_percentage=Decimal("5"))
        make_forecast(self.user, self.function, self.vendor, run_monte_carlo=False)
        report = load_workbook(io.BytesIO(excel_service.export_forecasts(ManpowerForecast.objects.all())))
        self.assertEqual(report.sheetnames, ["Summary", "Forecast Report", "Growth Projection"])
        ws = report["Forecast Report"]
        labels = [c.value for c in ws[2]]
        by_process = {ws.cell(row=r, column=labels.index("Process") + 1).value: r for r in (3, 4)}
        self.assertEqual(ws.cell(row=by_process["Vendor Payments"], column=labels.index("P90 FTE") + 1).value,
                         "Not run")
        self.assertEqual(report["Growth Projection"].max_row, 14)
        detail = load_workbook(io.BytesIO(excel_service.export_forecast_detail(
            ManpowerForecast.objects.get(process=self.process))))
        self.assertIn("Month-by-Month Projection", detail.sheetnames)
