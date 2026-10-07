"""Forms with business validation for forecasts, masters, filters, approvals, scenarios and uploads."""
from decimal import Decimal

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.urls import reverse

from .models import (ApprovalStatus, Frequency, FunctionMaster, ManpowerForecast, ManpowerStatus,
                     ProcessMaster, TimeUnit)
from .services.projection import PERIOD_LABELS, growth_factor, max_growth_factor

CFG = getattr(settings, "FORECASTING", {})
SIM_MIN = CFG.get("SIMULATION_MIN", 1000)
SIM_MAX = CFG.get("SIMULATION_MAX", 100000)
MC_DEFAULT = CFG.get("MONTE_CARLO_DEFAULT", True)
HORIZON_DEFAULT = CFG.get("HORIZON_DEFAULT", 12)
HORIZON_MAX = CFG.get("HORIZON_MAX", 60)

# Monte Carlo-only fields and the defaults stored when Monte Carlo is switched off
MC_FIELDS = ("volume_variation_percentage", "time_variation_percentage", "simulation_count", "simulation_seed")
MC_DEFAULTS = {"volume_variation_percentage": Decimal("10"), "time_variation_percentage": Decimal("15"),
               "simulation_count": 10000, "simulation_seed": None}
GROWTH_FIELDS = ("growth_rate_percentage", "growth_period", "forecast_horizon_months",
                 "aht_change_percentage", "aht_change_period")

MESSAGES = {
    "volume": "Volume must be greater than zero.",
    "current_fte": "Current FTE cannot be negative.",
    "avg_processing_time": "Average processing time must be greater than zero.",
    "working_hours_per_day": "Working hours per day must be greater than 0 and not more than 24.",
    "working_days_per_week": "Working days per week must be between 1 and 7.",
    "working_days_per_month": "Working days per month must be between 1 and 31.",
    "contingency_percentage": "Contingency must be between 0% and less than 100% (100% leaves no productive time).",
    "volume_variation_percentage": "Volume variation percentage cannot be negative.",
    "time_variation_percentage": "Processing time variation percentage cannot be negative.",
    "simulation_count": f"Simulation count must be between {SIM_MIN:,} and {SIM_MAX:,}.",
    "simulation_seed": "Simulation seed must be zero or a positive whole number.",
    "growth_rate_percentage": "Volume growth % must be greater than -100% and not more than 1000%.",
    "aht_change_percentage": "AHT change % must be greater than -100% and not more than 1000%.",
    "forecast_horizon_months": f"Forecast horizon must be between 1 and {HORIZON_MAX} months.",
}
BASE_RULES = [
    ("volume", lambda v: v > 0),
    ("current_fte", lambda v: v >= 0),
    ("avg_processing_time", lambda v: v > 0),
    ("working_hours_per_day", lambda v: 0 < v <= 24),
    ("working_days_per_week", lambda v: 1 <= v <= 7),
    ("working_days_per_month", lambda v: 1 <= v <= 31),
    ("contingency_percentage", lambda v: 0 <= v < 100),
    ("growth_rate_percentage", lambda v: Decimal("-100") < v <= Decimal("1000")),
    ("aht_change_percentage", lambda v: Decimal("-100") < v <= Decimal("1000")),
    ("forecast_horizon_months", lambda v: 1 <= v <= HORIZON_MAX),
]
MC_RULES = [
    ("volume_variation_percentage", lambda v: v >= 0),
    ("time_variation_percentage", lambda v: v >= 0),
    ("simulation_count", lambda v: SIM_MIN <= v <= SIM_MAX),
    ("simulation_seed", lambda v: v >= 0),
]


def validate_forecast_numbers(cleaned, add_error, run_monte_carlo=True):
    """Shared numeric validation. Monte Carlo fields are only validated when Monte Carlo is on."""
    rules = BASE_RULES + (MC_RULES if run_monte_carlo else [])
    for field, rule in rules:
        value = cleaned.get(field)
        if value is not None and not rule(value):
            add_error(field, MESSAGES[field])


def validate_growth_factor(cleaned, add_error, errors):
    """Block volume growth / AHT change settings that compound to an unrealistic workload within the horizon."""
    horizon = cleaned.get("forecast_horizon_months")
    vol_rate = cleaned.get("growth_rate_percentage") or Decimal("0")
    aht_rate = cleaned.get("aht_change_percentage") or Decimal("0")
    if not horizon or (vol_rate == 0 and aht_rate == 0):
        return
    if any(k in errors for k in GROWTH_FIELDS + ("working_days_per_week", "working_days_per_month")):
        return
    wk, mo = cleaned.get("working_days_per_week") or 5, cleaned.get("working_days_per_month") or 22
    vol_period = cleaned.get("growth_period") or "MONTHLY"
    aht_period = cleaned.get("aht_change_period") or "MONTHLY"
    vf = growth_factor(vol_rate, vol_period, horizon, wk, mo)
    af = growth_factor(aht_rate, aht_period, horizon, wk, mo)
    limit = max_growth_factor()
    if vf * af <= limit:
        return
    hint = "Reduce the %, choose a longer period or a shorter horizon."
    if vf > limit:
        add_error("growth_rate_percentage",
                  f"{vol_rate}% growth per {PERIOD_LABELS.get(vol_period, vol_period)} over {horizon} months "
                  f"multiplies volume by more than {limit:,.0f}x. {hint}")
    elif af > limit:
        add_error("aht_change_percentage",
                  f"{aht_rate}% AHT change per {PERIOD_LABELS.get(aht_period, aht_period)} over {horizon} months "
                  f"multiplies AHT by more than {limit:,.0f}x. {hint}")
    else:
        add_error("aht_change_percentage",
                  f"Volume growth and AHT change together multiply workload by more than {limit:,.0f}x "
                  f"over {horizon} months. {hint}")


def apply_monte_carlo_switch(form, cleaned):
    """
    If Monte Carlo is off: drop errors on Monte Carlo fields and store defaults.
    If Monte Carlo is on: variation % and simulation count become mandatory.
    """
    run_mc = bool(cleaned.get("run_monte_carlo"))
    if not run_mc:
        rules = dict(MC_RULES)
        for name in MC_FIELDS:
            if form._errors:
                form._errors.pop(name, None)
            value = cleaned.get(name)
            if value in (None, "") or not rules[name](value):
                cleaned[name] = MC_DEFAULTS[name]
    else:
        for name in ("volume_variation_percentage", "time_variation_percentage", "simulation_count"):
            if name not in form.errors and cleaned.get(name) in (None, ""):
                form.add_error(name, "This field is required when Monte Carlo simulation is switched on.")
    return run_mc


def apply_growth_defaults(cleaned):
    if cleaned.get("growth_rate_percentage") is None:
        cleaned["growth_rate_percentage"] = Decimal("0")
    if not cleaned.get("growth_period"):
        cleaned["growth_period"] = "MONTHLY"
    if cleaned.get("aht_change_percentage") is None:
        cleaned["aht_change_percentage"] = Decimal("0")
    if not cleaned.get("aht_change_period"):
        cleaned["aht_change_period"] = "MONTHLY"
    if cleaned.get("forecast_horizon_months") is None:
        cleaned["forecast_horizon_months"] = HORIZON_DEFAULT


class BootstrapFormMixin:
    def _apply_bootstrap(self):
        for field in self.fields.values():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault("class", "form-check-input")
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs.setdefault("class", "form-select")
            else:
                w.attrs.setdefault("class", "form-control")

    def full_clean(self):
        super().full_clean()
        for name in self.errors:
            if name in self.fields:
                css = self.fields[name].widget.attrs.get("class", "")
                if "is-invalid" not in css:
                    self.fields[name].widget.attrs["class"] = f"{css} is-invalid".strip()


class ManpowerForecastForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ManpowerForecast
        fields = ["function", "process", "frequency", "volume", "current_fte", "avg_processing_time", "time_unit",
                  "working_hours_per_day", "working_days_per_week", "working_days_per_month",
                  "contingency_percentage", "run_monte_carlo", "volume_variation_percentage",
                  "time_variation_percentage", "simulation_count", "simulation_seed",
                  "growth_rate_percentage", "growth_period", "aht_change_percentage", "aht_change_period",
                  "forecast_horizon_months", "remarks"]
        labels = {
            "function": "Function Name",
            "process": "Process Name",
            "current_fte": "Current FTE",
            "avg_processing_time": "Average Time to Complete One Volume",
            "time_unit": "Average Time Unit",
            "working_hours_per_day": "Working Hours Per Day",
            "working_days_per_week": "Working Days Per Week",
            "working_days_per_month": "Working Days Per Month",
            "contingency_percentage": "Contingency (%)",
            "run_monte_carlo": "Run Monte Carlo simulation",
            "volume_variation_percentage": "Volume Variation (%)",
            "time_variation_percentage": "Processing Time Variation (%)",
            "simulation_count": "Number of Monte Carlo Simulations",
            "simulation_seed": "Simulation Seed",
            "growth_rate_percentage": "Volume Growth (%)",
            "growth_period": "Growth Per",
            "aht_change_percentage": "AHT Change (%)",
            "aht_change_period": "AHT Change Per",
            "forecast_horizon_months": "Forecast Horizon (Months)",
        }
        help_texts = {
            "volume": "Total transactions for the selected frequency.",
            "current_fte": "FTE currently allocated (0 allowed).",
            "contingency_percentage": "Non-productive allowance (breaks, meetings, rework).",
            "run_monte_carlo": "Switch off to get the status from the deterministic calculation only.",
            "simulation_seed": "Optional. The same seed reproduces identical results.",
            "growth_rate_percentage": "Expected volume increase per period. Negative = decline. 0 = no volume change.",
            "growth_period": "How often the volume growth % is applied (compounded).",
            "aht_change_percentage": "Expected change in time per volume. Positive = slower (e.g. complexity), "
                                     "negative = faster (e.g. automation, learning). 0 = no AHT change.",
            "aht_change_period": "How often the AHT change % is applied (compounded).",
            "forecast_horizon_months": f"How far ahead to project (1-{HORIZON_MAX} months).",
        }
        widgets = {
            "volume": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "current_fte": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
            "avg_processing_time": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "working_hours_per_day": forms.NumberInput(attrs={"min": "0.25", "max": "24", "step": "0.25"}),
            "working_days_per_week": forms.NumberInput(attrs={"min": "1", "max": "7"}),
            "working_days_per_month": forms.NumberInput(attrs={"min": "1", "max": "31"}),
            "contingency_percentage": forms.NumberInput(attrs={"min": "0", "max": "99.99", "step": "0.01"}),
            "run_monte_carlo": forms.CheckboxInput(attrs={"role": "switch", "data-mc-toggle": "true"}),
            "volume_variation_percentage": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
            "time_variation_percentage": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
            "simulation_count": forms.NumberInput(attrs={"min": SIM_MIN, "max": SIM_MAX, "step": "1000"}),
            "simulation_seed": forms.NumberInput(attrs={"min": "0"}),
            "growth_rate_percentage": forms.NumberInput(attrs={"min": "-99.99", "max": "1000", "step": "0.01"}),
            "aht_change_percentage": forms.NumberInput(attrs={"min": "-99.99", "max": "1000", "step": "0.01"}),
            "forecast_horizon_months": forms.NumberInput(attrs={"min": "1", "max": HORIZON_MAX}),
            "remarks": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in MC_FIELDS + GROWTH_FIELDS:
            self.fields[name].required = False
        functions = FunctionMaster.objects.filter(is_active=True)
        processes = ProcessMaster.objects.filter(is_active=True)
        if self.instance.pk:
            functions = FunctionMaster.objects.filter(Q(is_active=True) | Q(pk=self.instance.function_id))
            processes = ProcessMaster.objects.filter(Q(is_active=True) | Q(pk=self.instance.process_id))
        if self.is_bound:
            function_id = self.data.get(self.add_prefix("function"))
        elif self.instance.pk:
            function_id = self.instance.function_id
        else:
            function_id = self.initial.get("function")
        function_id = str(function_id or "")
        self.fields["function"].queryset = functions
        self.fields["function"].empty_label = "Select function"
        self.fields["process"].queryset = (processes.filter(function_id=int(function_id))
                                           if function_id.isdigit() else processes.none())
        self.fields["process"].empty_label = "Select process"
        self.fields["process"].label_from_instance = lambda obj: obj.process_name
        self.fields["function"].widget.attrs["data-function-select"] = "true"
        self.fields["process"].widget.attrs.update(
            {"data-process-select": "true", "data-url": reverse("forecasting:process_options")})
        self.fields["frequency"].widget.attrs["data-frequency-select"] = "true"
        self._apply_bootstrap()

    def clean(self):
        cleaned = super().clean()
        run_mc = apply_monte_carlo_switch(self, cleaned)
        apply_growth_defaults(cleaned)
        validate_forecast_numbers(cleaned, self.add_error, run_monte_carlo=run_mc)
        validate_growth_factor(cleaned, self.add_error, self.errors)
        function, process = cleaned.get("function"), cleaned.get("process")
        if function and process and process.function_id != function.id:
            self.add_error("process", "The selected process does not belong to the selected function.")
        return cleaned

    def _post_clean(self):
        # Keep one friendly message per field instead of also showing the model validator's message.
        super()._post_clean()
        for field, message in MESSAGES.items():
            errors = self._errors.get(field) if self._errors else None
            if errors and message in errors and len(errors) > 1:
                self._errors[field] = self.error_class([message])


class FunctionMasterForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = FunctionMaster
        fields = ["function_name", "function_owner", "description", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}
        labels = {"is_active": "Active"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()

    def clean_function_name(self):
        name = (self.cleaned_data.get("function_name") or "").strip()
        if not name:
            raise ValidationError("Function name is required.")
        if FunctionMaster.objects.filter(function_name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise ValidationError(f"A function named '{name}' already exists.")
        return name


class ProcessMasterForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ProcessMaster
        fields = ["function", "process_name", "process_owner", "description", "default_frequency", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}
        labels = {"is_active": "Active"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = FunctionMaster.objects.filter(is_active=True)
        if self.instance.pk:
            qs = FunctionMaster.objects.filter(Q(is_active=True) | Q(pk=self.instance.function_id))
        self.fields["function"].queryset = qs
        self._apply_bootstrap()

    def clean(self):
        cleaned = super().clean()
        name = (cleaned.get("process_name") or "").strip()
        function = cleaned.get("function")
        if name and function:
            cleaned["process_name"] = name
            dup = ProcessMaster.objects.filter(function=function, process_name__iexact=name).exclude(
                pk=self.instance.pk)
            if dup.exists():
                self.add_error("process_name", f"Process '{name}' already exists under function '{function}'.")
        return cleaned


NO_PROJECTION_Q = Q(growth_rate_percentage=0) & Q(aht_change_percentage=0)


class ForecastFilterForm(BootstrapFormMixin, forms.Form):
    OUTLOOK_CHOICES = [("", "All outlooks"), ("short_future", "Short in future"), ("short_now", "Short now"),
                       ("ok", "Sufficient through horizon"), ("none", "No future projection")]

    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Search..."}))
    function = forms.ModelChoiceField(queryset=FunctionMaster.objects.all(), required=False,
                                      empty_label="All functions")
    process = forms.ModelChoiceField(queryset=ProcessMaster.objects.all(), required=False,
                                     empty_label="All processes")
    status = forms.ChoiceField(choices=[("", "All statuses")] + list(ManpowerStatus.choices), required=False)
    frequency = forms.ChoiceField(choices=[("", "All frequencies")] + list(Frequency.choices), required=False)
    approval_status = forms.ChoiceField(choices=[("", "All approvals")] + list(ApprovalStatus.choices),
                                        required=False, label="Approval")
    monte_carlo = forms.ChoiceField(choices=[("", "All methods"), ("yes", "With Monte Carlo"),
                                             ("no", "Deterministic only")], required=False, label="Method")
    outlook = forms.ChoiceField(choices=OUTLOOK_CHOICES, required=False, label="Future outlook")
    created_by = forms.ModelChoiceField(queryset=get_user_model().objects.none(), required=False,
                                        empty_label="All users")
    from_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    to_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["created_by"].queryset = (get_user_model().objects.filter(forecasts_created__isnull=False)
                                              .distinct().order_by("username"))
        self.fields["process"].label_from_instance = lambda obj: obj.process_name
        self._apply_bootstrap()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("from_date") and cleaned.get("to_date") and cleaned["from_date"] > cleaned["to_date"]:
            self.add_error("to_date", "To date must be on or after From date.")
        return cleaned

    def apply(self, queryset):
        if not self.is_bound or not self.is_valid():
            return queryset
        d = self.cleaned_data
        if d.get("q"):
            queryset = queryset.filter(Q(process__process_name__icontains=d["q"])
                                       | Q(function__function_name__icontains=d["q"])
                                       | Q(remarks__icontains=d["q"]))
        for key in ("function", "process", "status", "frequency", "approval_status", "created_by"):
            if d.get(key):
                queryset = queryset.filter(**{key: d[key]})
        if d.get("monte_carlo"):
            queryset = queryset.filter(run_monte_carlo=(d["monte_carlo"] == "yes"))
        outlook = d.get("outlook")
        if outlook == "none":
            queryset = queryset.filter(NO_PROJECTION_Q)
        elif outlook == "ok":
            queryset = queryset.exclude(NO_PROJECTION_Q).filter(projected_shortfall_month__isnull=True)
        elif outlook == "short_now":
            queryset = queryset.exclude(NO_PROJECTION_Q).filter(projected_shortfall_month=0)
        elif outlook == "short_future":
            queryset = queryset.exclude(NO_PROJECTION_Q).filter(projected_shortfall_month__gt=0)
        if d.get("from_date"):
            queryset = queryset.filter(created_at__date__gte=d["from_date"])
        if d.get("to_date"):
            queryset = queryset.filter(created_at__date__lte=d["to_date"])
        return queryset


class ExecutiveFilterForm(BootstrapFormMixin, forms.Form):
    """Controls for the executive dashboard (all optional)."""
    HORIZON_CHOICES = [(3, "3 months"), (6, "6 months"), (12, "12 months"), (18, "18 months"), (24, "24 months")]

    function = forms.ModelChoiceField(queryset=FunctionMaster.objects.all(), required=False,
                                      empty_label="All functions")
    horizon = forms.TypedChoiceField(choices=HORIZON_CHOICES, coerce=int, required=False, label="Outlook")
    cost_per_fte = forms.DecimalField(required=False, min_value=Decimal("0"), max_digits=14, decimal_places=2,
                                      label="Annual cost per FTE",
                                      widget=forms.NumberInput(attrs={"step": "10000", "min": "0"}))
    approved_only = forms.BooleanField(required=False, label="Approved forecasts only",
                                       widget=forms.CheckboxInput(attrs={"role": "switch"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()

    def values(self, defaults):
        """Return (function, horizon, cost_per_fte, approved_only) with defaults for blanks or invalid input."""
        d = self.cleaned_data if self.is_bound and self.is_valid() else {}
        return (d.get("function"), d.get("horizon") or defaults["horizon"],
                d.get("cost_per_fte") if d.get("cost_per_fte") is not None else defaults["cost_per_fte"],
                bool(d.get("approved_only")))


class ApprovalForm(BootstrapFormMixin, forms.Form):
    decision = forms.ChoiceField(choices=(("APPROVE", "Approve"), ("REJECT", "Reject")))
    comments = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False, label="Approval comments")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == "REJECT" and not (cleaned.get("comments") or "").strip():
            self.add_error("comments", "Comments are mandatory when rejecting a forecast.")
        return cleaned


class ScenarioBaseForm(BootstrapFormMixin, forms.Form):
    base_forecast = forms.ModelChoiceField(queryset=ManpowerForecast.objects.none(), label="Base forecast",
                                           empty_label="Select a saved forecast")
    run_monte_carlo = forms.BooleanField(required=False, initial=MC_DEFAULT, label="Run Monte Carlo simulation",
                                         widget=forms.CheckboxInput(attrs={"role": "switch", "data-mc-toggle": "true"}))
    simulation_seed = forms.IntegerField(required=False, min_value=0, initial=42,
                                         help_text="The same seed for all scenarios gives a fair comparison.")

    def __init__(self, *args, queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        if queryset is not None:
            self.fields["base_forecast"].queryset = queryset.select_related("process", "function")
        self.fields["base_forecast"].label_from_instance = (
            lambda f: f"#{f.pk} - {f.function.function_name} / {f.process.process_name} "
                      f"({f.created_at:%d-%b-%Y})")
        self.fields["base_forecast"].widget.attrs["data-reload-param"] = "base"
        self._apply_bootstrap()


class ScenarioForm(BootstrapFormMixin, forms.Form):
    name = forms.CharField(max_length=80, required=False, label="Scenario name")
    volume_growth_pct = forms.DecimalField(required=False, min_value=Decimal("-99"), max_digits=6,
                                           decimal_places=2, label="Volume change today %")
    time_change_pct = forms.DecimalField(required=False, min_value=Decimal("-99"), max_digits=6,
                                         decimal_places=2, label="AHT change today %")
    contingency_percentage = forms.DecimalField(required=False, min_value=Decimal("0"),
                                                max_value=Decimal("99.99"), max_digits=5, decimal_places=2,
                                                label="Contingency %")
    current_fte = forms.DecimalField(required=False, min_value=Decimal("0"), max_digits=8, decimal_places=2,
                                     label="Proposed FTE")
    growth_rate_percentage = forms.DecimalField(required=False, min_value=Decimal("-99.99"),
                                                max_value=Decimal("1000"), max_digits=7, decimal_places=2,
                                                label="Ongoing volume growth % per period",
                                                help_text="Overrides the base forecast's volume growth %.")
    aht_change_percentage = forms.DecimalField(required=False, min_value=Decimal("-99.99"),
                                               max_value=Decimal("1000"), max_digits=7, decimal_places=2,
                                               label="Ongoing AHT change % per period",
                                               help_text="Overrides the base forecast's AHT change %.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()

    def has_adjustment(self):
        d = getattr(self, "cleaned_data", None) or {}
        return any(d.get(k) not in (None, "") for k in
                   ("volume_growth_pct", "time_change_pct", "contingency_percentage", "current_fte",
                    "growth_rate_percentage", "aht_change_percentage"))


ScenarioFormSet = forms.formset_factory(ScenarioForm, extra=0, max_num=CFG.get("SCENARIO_MAX", 4),
                                        validate_max=True)

DEFAULT_SCENARIOS = [
    {"name": "10% Volume Growth", "volume_growth_pct": Decimal("10")},
    {"name": "20% Contingency", "contingency_percentage": Decimal("20")},
    {"name": "Proposed FTE", "current_fte": None},
    {"name": "AHT +20%", "time_change_pct": Decimal("20")},
]


class BulkUploadForm(forms.Form):
    file = forms.FileField(label="Excel file (.xlsx)",
                           widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".xlsx"}))

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith(".xlsx"):
            raise ValidationError("Only .xlsx files are supported. Please use the downloadable template.")
        if f.size > 10 * 1024 * 1024:
            raise ValidationError("File size must not exceed 10 MB.")
        return f


def _choice_lookup(choices):
    lookup = {}
    for value, label in choices:
        for key in (value, label, value.replace("_", "-"), value.replace("_", " "), label.replace("-", " ")):
            lookup[key.strip().lower()] = value
    return lookup


FREQUENCY_LOOKUP = _choice_lookup(Frequency.choices)
TIME_UNIT_LOOKUP = _choice_lookup(TimeUnit.choices)
TIME_UNIT_LOOKUP.update({"sec": "SECONDS", "secs": "SECONDS", "second": "SECONDS", "min": "MINUTES",
                         "mins": "MINUTES", "minute": "MINUTES", "hr": "HOURS", "hrs": "HOURS", "hour": "HOURS"})
YES_VALUES = {"yes", "y", "true", "1", "on"}
NO_VALUES = {"no", "n", "false", "0", "off"}
PERIOD_ERROR = "Invalid {}. Use Daily, Weekly, Monthly, Quarterly, Half-Yearly or Yearly."


class ForecastRowForm(forms.Form):
    """Validates one Excel upload row."""
    function_name = forms.CharField(max_length=150)
    process_name = forms.CharField(max_length=200)
    frequency = forms.CharField()
    volume = forms.DecimalField(max_digits=14, decimal_places=2)
    current_fte = forms.DecimalField(max_digits=8, decimal_places=2)
    avg_processing_time = forms.DecimalField(max_digits=10, decimal_places=2)
    time_unit = forms.CharField(required=False)
    working_hours_per_day = forms.DecimalField(max_digits=4, decimal_places=2, required=False)
    working_days_per_week = forms.IntegerField(required=False)
    working_days_per_month = forms.IntegerField(required=False)
    contingency_percentage = forms.DecimalField(max_digits=5, decimal_places=2, required=False)
    run_monte_carlo = forms.CharField(required=False)
    volume_variation_percentage = forms.DecimalField(max_digits=6, decimal_places=2, required=False)
    time_variation_percentage = forms.DecimalField(max_digits=6, decimal_places=2, required=False)
    simulation_count = forms.IntegerField(required=False)
    growth_rate_percentage = forms.DecimalField(max_digits=7, decimal_places=2, required=False)
    growth_period = forms.CharField(required=False)
    aht_change_percentage = forms.DecimalField(max_digits=7, decimal_places=2, required=False)
    aht_change_period = forms.CharField(required=False)
    forecast_horizon_months = forms.IntegerField(required=False)
    remarks = forms.CharField(required=False)

    DEFAULTS = {
        "working_hours_per_day": Decimal("8"), "working_days_per_week": 5, "working_days_per_month": 22,
        "contingency_percentage": Decimal("15"), "volume_variation_percentage": Decimal("10"),
        "time_variation_percentage": Decimal("15"), "simulation_count": 10000,
        "growth_rate_percentage": Decimal("0"), "aht_change_percentage": Decimal("0"),
        "forecast_horizon_months": HORIZON_DEFAULT,
    }

    def clean_frequency(self):
        value = (self.cleaned_data.get("frequency") or "").strip().lower()
        if value not in FREQUENCY_LOOKUP:
            raise ValidationError(PERIOD_ERROR.format("frequency"))
        return FREQUENCY_LOOKUP[value]

    def clean_time_unit(self):
        value = (self.cleaned_data.get("time_unit") or "").strip().lower()
        if not value:
            return "MINUTES"
        if value not in TIME_UNIT_LOOKUP:
            raise ValidationError("Invalid time unit. Use Seconds, Minutes or Hours.")
        return TIME_UNIT_LOOKUP[value]

    def _clean_period(self, name, label):
        value = (self.cleaned_data.get(name) or "").strip().lower()
        if not value:
            return "MONTHLY"
        if value not in FREQUENCY_LOOKUP:
            raise ValidationError(PERIOD_ERROR.format(label))
        return FREQUENCY_LOOKUP[value]

    def clean_growth_period(self):
        return self._clean_period("growth_period", "growth period")

    def clean_aht_change_period(self):
        return self._clean_period("aht_change_period", "AHT change period")

    def clean_run_monte_carlo(self):
        value = (self.cleaned_data.get("run_monte_carlo") or "").strip().lower()
        if not value:
            return MC_DEFAULT
        if value in YES_VALUES:
            return True
        if value in NO_VALUES:
            return False
        raise ValidationError("Invalid value. Use Yes or No.")

    def clean(self):
        cleaned = super().clean()
        run_mc = cleaned.get("run_monte_carlo", MC_DEFAULT)
        if not run_mc:
            for name in ("volume_variation_percentage", "time_variation_percentage", "simulation_count"):
                self._errors.pop(name, None)
        for key, default in self.DEFAULTS.items():
            if key not in self.errors and cleaned.get(key) is None:
                cleaned[key] = default
        if not run_mc:
            rules = dict(MC_RULES)
            for name in ("volume_variation_percentage", "time_variation_percentage", "simulation_count"):
                if not rules[name](cleaned[name]):
                    cleaned[name] = self.DEFAULTS[name]
        validate_forecast_numbers(cleaned, self.add_error, run_monte_carlo=bool(run_mc))
        validate_growth_factor(cleaned, self.add_error, self.errors)
        fname = (cleaned.get("function_name") or "").strip()
        pname = (cleaned.get("process_name") or "").strip()
        if fname:
            function = FunctionMaster.objects.filter(function_name__iexact=fname, is_active=True).first()
            if not function:
                self.add_error("function_name", f"Function '{fname}' does not exist or is inactive.")
            elif pname:
                process = ProcessMaster.objects.filter(process_name__iexact=pname, function=function,
                                                       is_active=True).first()
                if process:
                    cleaned["function"], cleaned["process"] = function, process
                elif ProcessMaster.objects.filter(process_name__iexact=pname).exists():
                    self.add_error("process_name", f"Process '{pname}' does not belong to function '{fname}'.")
                else:
                    self.add_error("process_name", f"Process '{pname}' does not exist or is inactive.")
        return cleaned
