"""
Data model for the Manpower Capacity Planning and Monte Carlo Forecasting System.
Business values use DecimalField; design is PostgreSQL-compatible.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower


class Frequency(models.TextChoices):
    DAILY = "DAILY", "Daily"
    WEEKLY = "WEEKLY", "Weekly"
    MONTHLY = "MONTHLY", "Monthly"
    QUARTERLY = "QUARTERLY", "Quarterly"
    HALF_YEARLY = "HALF_YEARLY", "Half-Yearly"
    YEARLY = "YEARLY", "Yearly"


class TimeUnit(models.TextChoices):
    SECONDS = "SECONDS", "Seconds"
    MINUTES = "MINUTES", "Minutes"
    HOURS = "HOURS", "Hours"


class ManpowerStatus(models.TextChoices):
    LESS = "LESS", "Less Manpower"
    SUFFICIENT = "SUFFICIENT", "Sufficient Manpower"
    HIGHER = "HIGHER", "Higher Manpower"


class ApprovalStatus(models.TextChoices):
    PENDING = "PENDING", "Pending Approval"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


STATUS_CSS = {"LESS": "danger", "SUFFICIENT": "success", "HIGHER": "amber"}
PERIOD_WORDS = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month", "QUARTERLY": "quarter",
                "HALF_YEARLY": "half-year", "YEARLY": "year"}


def pct_text(value) -> str:
    """Signed percentage without trailing zeros: +5, -2.5."""
    d = Decimal(str(value)).normalize()
    text = f"{d:f}"
    return f"+{text}" if d > 0 else text


def default_run_monte_carlo():
    return getattr(settings, "FORECASTING", {}).get("MONTE_CARLO_DEFAULT", True)


def default_horizon_months():
    return getattr(settings, "FORECASTING", {}).get("HORIZON_DEFAULT", 12)


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class FunctionMaster(TimeStampedModel):
    function_name = models.CharField(max_length=150)
    function_owner = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="functions_created"
    )

    class Meta:
        ordering = ["function_name"]
        verbose_name = "Function"
        verbose_name_plural = "Function Master"
        constraints = [
            models.UniqueConstraint(
                Lower("function_name"), name="uniq_function_name_ci",
                violation_error_message="A function with this name already exists.",
            ),
        ]

    def __str__(self):
        return self.function_name


class ProcessMaster(TimeStampedModel):
    function = models.ForeignKey(FunctionMaster, on_delete=models.PROTECT, related_name="processes")
    process_name = models.CharField(max_length=200)
    process_owner = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    default_frequency = models.CharField(max_length=20, choices=Frequency.choices, default=Frequency.DAILY)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="processes_created"
    )

    class Meta:
        ordering = ["function__function_name", "process_name"]
        verbose_name = "Process"
        verbose_name_plural = "Process Master"
        constraints = [
            models.UniqueConstraint(
                "function", Lower("process_name"), name="uniq_process_per_function_ci",
                violation_error_message="This process already exists under the selected function.",
            ),
        ]

    def __str__(self):
        return f"{self.process_name} ({self.function.function_name})"


class ManpowerForecast(TimeStampedModel):
    # ---------- Inputs ----------
    function = models.ForeignKey(FunctionMaster, on_delete=models.PROTECT, related_name="forecasts")
    process = models.ForeignKey(ProcessMaster, on_delete=models.PROTECT, related_name="forecasts")
    frequency = models.CharField(max_length=20, choices=Frequency.choices)
    volume = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    current_fte = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    avg_processing_time = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    time_unit = models.CharField(max_length=10, choices=TimeUnit.choices, default=TimeUnit.MINUTES)
    working_hours_per_day = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("8"),
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("24"))],
    )
    working_days_per_week = models.PositiveSmallIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(7)]
    )
    working_days_per_month = models.PositiveSmallIntegerField(
        default=22, validators=[MinValueValidator(1), MaxValueValidator(31)]
    )
    contingency_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("15"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("99.99"))],
    )
    run_monte_carlo = models.BooleanField(
        "Run Monte Carlo simulation", default=default_run_monte_carlo,
        help_text="Switch off to classify manpower using the deterministic calculation only.",
    )
    volume_variation_percentage = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("10"), validators=[MinValueValidator(Decimal("0"))]
    )
    time_variation_percentage = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("15"), validators=[MinValueValidator(Decimal("0"))]
    )
    simulation_count = models.PositiveIntegerField(
        default=10000, validators=[MinValueValidator(1000), MaxValueValidator(100000)]
    )
    simulation_seed = models.PositiveIntegerField(null=True, blank=True)
    growth_rate_percentage = models.DecimalField(
        "Growth %", max_digits=7, decimal_places=2, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("-99.99")), MaxValueValidator(Decimal("1000"))],
        help_text="Expected volume change per growth period (negative = decline, 0 = no projection).",
    )
    growth_period = models.CharField(max_length=20, choices=Frequency.choices, default=Frequency.MONTHLY)
    forecast_horizon_months = models.PositiveSmallIntegerField(
        default=default_horizon_months, validators=[MinValueValidator(1), MaxValueValidator(60)]
    )
    aht_change_percentage = models.DecimalField(
        "AHT change %", max_digits=7, decimal_places=2, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("-99.99")), MaxValueValidator(Decimal("1000"))],
        help_text="Expected change in average handling time per AHT period (negative = faster, 0 = no change).",
    )
    aht_change_period = models.CharField(max_length=20, choices=Frequency.choices, default=Frequency.MONTHLY)
    remarks = models.TextField(blank=True)

    # ---------- Deterministic outputs ----------
    daily_volume = models.DecimalField(max_digits=16, decimal_places=4, default=0)
    processing_time_minutes = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    productive_minutes_per_fte = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    workload_minutes = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    workload_hours = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    available_capacity_minutes = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    required_fte = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    recommended_operational_fte = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fte_gap = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    operational_fte_gap = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    utilization_percentage = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Empty when Current FTE is zero (utilization undefined).",
    )
    unused_capacity_percentage = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=ManpowerStatus.choices, db_index=True)
    high_utilization_risk = models.BooleanField(default=False)
    recommendation = models.TextField(blank=True)
    status_explanation = models.TextField(blank=True)

    # ---------- Growth projection outputs ----------
    projection_data = models.JSONField(default=dict, blank=True)
    projected_shortfall_month = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="First projected month with Less Manpower (0 = already short today).",
    )
    projected_horizon_required_fte = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    projected_horizon_fte_needed = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    projected_horizon_status = models.CharField(max_length=20, choices=ManpowerStatus.choices, blank=True)
    projection_summary = models.TextField(blank=True)

    # ---------- Maker-checker ----------
    approval_status = models.CharField(
        max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING, db_index=True
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="forecasts_reviewed"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_comments = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="forecasts_created"
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["created_at"]), models.Index(fields=["function", "process"])]

    def __str__(self):
        return f"#{self.pk} {self.process.process_name} - {self.get_status_display()}"

    @property
    def latest_summary(self):
        """Latest Monte Carlo summary, or None when Monte Carlo is switched off for this forecast."""
        if not getattr(self, "run_monte_carlo", True):
            return None
        cache = getattr(self, "_prefetched_objects_cache", {})
        if "simulation_summaries" in cache:
            items = list(self.simulation_summaries.all())
            return max(items, key=lambda s: (s.created_at, s.pk)) if items else None
        return self.simulation_summaries.order_by("-created_at", "-pk").first()

    @property
    def risk_adjusted_fte(self):
        """ceil(P90) when Monte Carlo ran, otherwise the operational (deterministic) FTE."""
        summary = self.latest_summary
        return summary.risk_adjusted_recommended_fte if summary else self.recommended_operational_fte

    @property
    def available_capacity_hours(self):
        return (self.available_capacity_minutes or Decimal("0")) / Decimal("60")

    @property
    def status_css(self):
        return STATUS_CSS.get(self.status, "secondary")

    @property
    def approval_css(self):
        return {"APPROVED": "success", "REJECTED": "danger", "PENDING": "info"}.get(self.approval_status, "secondary")

    # ---------- Growth projection helpers ----------
    @property
    def has_volume_growth(self):
        return bool(getattr(self, "growth_rate_percentage", 0))

    @property
    def has_aht_change(self):
        return bool(getattr(self, "aht_change_percentage", 0))

    @property
    def growth_drivers(self):
        """Human-readable list of the projection drivers, e.g. ['+5% volume per month', '-2% AHT per quarter']."""
        drivers = []
        if self.has_volume_growth:
            drivers.append(f"{pct_text(self.growth_rate_percentage)}% volume per "
                           f"{PERIOD_WORDS.get(self.growth_period, self.growth_period)}")
        if self.has_aht_change:
            drivers.append(f"{pct_text(self.aht_change_percentage)}% AHT per "
                           f"{PERIOD_WORDS.get(self.aht_change_period, self.aht_change_period)}")
        return drivers

    @property
    def growth_drivers_text(self):
        return " and ".join(self.growth_drivers)

    @property
    def projection_points(self):
        data = getattr(self, "projection_data", None) or {}
        return data.get("points", []) if isinstance(data, dict) else []

    @property
    def hiring_plan(self):
        data = getattr(self, "projection_data", None) or {}
        return data.get("hiring_plan", []) if isinstance(data, dict) else []

    @property
    def has_projection(self):
        return bool(self.projection_points)

    @property
    def projection_end_label(self):
        points = self.projection_points
        return points[-1]["label"] if points else ""

    @property
    def projection_end_aht(self):
        points = self.projection_points
        return points[-1].get("aht_minutes") if points else None

    @property
    def shortfall_label(self):
        month = getattr(self, "projected_shortfall_month", None)
        points = self.projection_points
        if month is None or month >= len(points):
            return ""
        return points[month]["label"]

    @property
    def sufficient_until_label(self):
        month = getattr(self, "projected_shortfall_month", None)
        points = self.projection_points
        if not points:
            return ""
        if month is None:
            return points[-1]["label"]
        if month == 0:
            return ""
        return points[month - 1]["label"]

    @property
    def outlook(self):
        """Short code for templates: none / short_now / short_future / ok."""
        if not self.has_projection:
            return "none"
        month = self.projected_shortfall_month
        if month is None:
            return "ok"
        return "short_now" if month == 0 else "short_future"

    @property
    def horizon_status_css(self):
        return STATUS_CSS.get(getattr(self, "projected_horizon_status", ""), "secondary")

    @property
    def horizon_additional_fte(self):
        needed = getattr(self, "projected_horizon_fte_needed", None)
        if needed is None:
            return None
        return max(Decimal("0"), needed - self.current_fte)


class ForecastSimulationSummary(models.Model):
    forecast = models.ForeignKey(ManpowerForecast, on_delete=models.CASCADE, related_name="simulation_summaries")
    average_required_fte = models.DecimalField(max_digits=10, decimal_places=4)
    minimum_required_fte = models.DecimalField(max_digits=10, decimal_places=4)
    maximum_required_fte = models.DecimalField(max_digits=10, decimal_places=4)
    standard_deviation = models.DecimalField(max_digits=10, decimal_places=4)
    p50_required_fte = models.DecimalField(max_digits=10, decimal_places=4)
    p80_required_fte = models.DecimalField(max_digits=10, decimal_places=4)
    p90_required_fte = models.DecimalField(max_digits=10, decimal_places=4)
    p95_required_fte = models.DecimalField(max_digits=10, decimal_places=4)
    p99_required_fte = models.DecimalField(max_digits=10, decimal_places=4)
    risk_adjusted_recommended_fte = models.DecimalField(max_digits=10, decimal_places=2)
    sufficiency_probability = models.DecimalField(max_digits=6, decimal_places=2)
    failure_probability = models.DecimalField(max_digits=6, decimal_places=2)
    simulation_count = models.PositiveIntegerField()
    histogram_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Forecast Simulation Summary"
        verbose_name_plural = "Forecast Simulation Summaries"

    def __str__(self):
        return f"Simulation for forecast #{self.forecast_id} ({self.simulation_count} runs)"


class ForecastAuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "CREATE", "Created"
        UPDATE = "UPDATE", "Updated"
        DELETE = "DELETE", "Deleted"
        SIMULATE = "SIMULATE", "Simulation Re-run"
        APPROVE = "APPROVE", "Approved"
        REJECT = "REJECT", "Rejected"
        UPLOAD = "UPLOAD", "Bulk Uploaded"

    forecast = models.ForeignKey(
        ManpowerForecast, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs"
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    old_data = models.JSONField(null=True, blank=True)
    new_data = models.JSONField(null=True, blank=True)
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    performed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-performed_at", "-id"]

    def __str__(self):
        return f"{self.get_action_display()} - forecast #{self.forecast_id}"
