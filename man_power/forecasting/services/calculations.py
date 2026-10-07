"""
Deterministic manpower capacity calculations.
Pure functions (no database access) so they are reusable and unit-testable.
"""
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Optional

MINUTES_PER_HOUR = Decimal("60")
HUNDRED = Decimal("100")

# Working days in each frequency period (configurable week/month working days)
FREQUENCY_WORKING_DAYS = {
    "DAILY": lambda wk, mo: Decimal("1"),
    "WEEKLY": lambda wk, mo: Decimal(wk),
    "MONTHLY": lambda wk, mo: Decimal(mo),
    "QUARTERLY": lambda wk, mo: Decimal(mo) * 3,
    "HALF_YEARLY": lambda wk, mo: Decimal(mo) * 6,
    "YEARLY": lambda wk, mo: Decimal(mo) * 12,
}


def to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def q(value, places: str = "0.01") -> Decimal:
    """Round half-up to the given precision."""
    return to_decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def ceil_decimal(value) -> Decimal:
    return to_decimal(value).quantize(Decimal("1"), rounding=ROUND_CEILING)


def fmt(value) -> str:
    """Human-friendly number: 3 instead of 3.00, 2.45 stays 2.45."""
    d = q(value)
    return f"{d:f}".rstrip("0").rstrip(".") if "." in f"{d:f}" else f"{d:f}"


def safe_divide(numerator, denominator, default: Optional[Decimal] = Decimal("0")) -> Optional[Decimal]:
    numerator, denominator = to_decimal(numerator), to_decimal(denominator)
    if denominator == 0:
        return default
    return numerator / denominator


def convert_to_daily_volume(volume, frequency, working_days_per_week, working_days_per_month) -> Decimal:
    if frequency not in FREQUENCY_WORKING_DAYS:
        raise ValueError(f"Unsupported frequency: {frequency}")
    days = FREQUENCY_WORKING_DAYS[frequency](int(working_days_per_week), int(working_days_per_month))
    return safe_divide(volume, days)


def convert_time_to_minutes(avg_time, time_unit) -> Decimal:
    value = to_decimal(avg_time)
    if time_unit == "SECONDS":
        return value / MINUTES_PER_HOUR
    if time_unit == "MINUTES":
        return value
    if time_unit == "HOURS":
        return value * MINUTES_PER_HOUR
    raise ValueError(f"Unsupported time unit: {time_unit}")


@dataclass
class ProductiveCapacity:
    total_available_minutes: Decimal
    contingency_minutes: Decimal
    productive_minutes: Decimal

    @property
    def productive_hours(self) -> Decimal:
        return self.productive_minutes / MINUTES_PER_HOUR


def productive_capacity(working_hours_per_day, contingency_percentage) -> ProductiveCapacity:
    total = to_decimal(working_hours_per_day) * MINUTES_PER_HOUR
    contingency = total * to_decimal(contingency_percentage) / HUNDRED
    return ProductiveCapacity(total, contingency, total - contingency)


@dataclass
class ForecastInput:
    frequency: str
    volume: Decimal
    current_fte: Decimal
    avg_processing_time: Decimal
    time_unit: str = "MINUTES"
    working_hours_per_day: Decimal = Decimal("8")
    working_days_per_week: int = 5
    working_days_per_month: int = 22
    contingency_percentage: Decimal = Decimal("15")
    run_monte_carlo: bool = True
    volume_variation_percentage: Decimal = Decimal("10")
    time_variation_percentage: Decimal = Decimal("15")
    simulation_count: int = 10000
    simulation_seed: Optional[int] = None
    growth_rate_percentage: Decimal = Decimal("0")
    growth_period: str = "MONTHLY"
    forecast_horizon_months: int = 12
    aht_change_percentage: Decimal = Decimal("0")
    aht_change_period: str = "MONTHLY"

    def __post_init__(self):
        defaults = {"volume_variation_percentage": Decimal("10"), "time_variation_percentage": Decimal("15"),
                    "growth_rate_percentage": Decimal("0"), "aht_change_percentage": Decimal("0")}
        for name in ("volume", "current_fte", "avg_processing_time", "working_hours_per_day",
                     "contingency_percentage", "volume_variation_percentage", "time_variation_percentage",
                     "growth_rate_percentage", "aht_change_percentage"):
            value = getattr(self, name)
            if value in (None, "") and name in defaults:
                value = defaults[name]
            setattr(self, name, to_decimal(value))
        self.working_days_per_week = int(self.working_days_per_week)
        self.working_days_per_month = int(self.working_days_per_month)
        self.run_monte_carlo = bool(self.run_monte_carlo) if self.run_monte_carlo is not None else True
        self.simulation_count = int(self.simulation_count) if self.simulation_count not in (None, "") else 10000
        self.simulation_seed = int(self.simulation_seed) if self.simulation_seed not in (None, "") else None
        self.growth_period = self.growth_period or "MONTHLY"
        self.aht_change_period = self.aht_change_period or "MONTHLY"
        self.forecast_horizon_months = (int(self.forecast_horizon_months)
                                        if self.forecast_horizon_months not in (None, "") else 12)

    @property
    def has_volume_growth(self) -> bool:
        return self.growth_rate_percentage != 0

    @property
    def has_aht_change(self) -> bool:
        return self.aht_change_percentage != 0

    @property
    def has_growth(self) -> bool:
        """True when a future projection is needed (volume growth and/or AHT change)."""
        return self.has_volume_growth or self.has_aht_change


@dataclass
class DeterministicResult:
    daily_volume: Decimal
    processing_time_minutes: Decimal
    total_available_minutes: Decimal
    contingency_minutes: Decimal
    productive_minutes_per_fte: Decimal
    workload_minutes: Decimal
    workload_hours: Decimal
    available_capacity_minutes: Decimal
    required_fte: Decimal
    recommended_operational_fte: Decimal
    fte_gap: Decimal
    operational_fte_gap: Decimal
    utilization_percentage: Optional[Decimal]
    unused_capacity_percentage: Optional[Decimal]
    extra: dict = field(default_factory=dict)


def calculate_deterministic(inp: ForecastInput) -> DeterministicResult:
    daily_volume = convert_to_daily_volume(inp.volume, inp.frequency, inp.working_days_per_week,
                                           inp.working_days_per_month)
    time_minutes = convert_time_to_minutes(inp.avg_processing_time, inp.time_unit)
    capacity = productive_capacity(inp.working_hours_per_day, inp.contingency_percentage)

    workload_minutes = daily_volume * time_minutes
    workload_hours = workload_minutes / MINUTES_PER_HOUR
    available_capacity = inp.current_fte * capacity.productive_minutes
    required_fte = safe_divide(workload_minutes, capacity.productive_minutes)
    recommended = ceil_decimal(required_fte)
    utilization = safe_divide(required_fte * HUNDRED, inp.current_fte, default=None)
    unused = (HUNDRED - utilization) if utilization is not None else None

    return DeterministicResult(
        daily_volume=q(daily_volume, "0.0001"),
        processing_time_minutes=q(time_minutes, "0.0001"),
        total_available_minutes=q(capacity.total_available_minutes),
        contingency_minutes=q(capacity.contingency_minutes),
        productive_minutes_per_fte=q(capacity.productive_minutes),
        workload_minutes=q(workload_minutes),
        workload_hours=q(workload_hours),
        available_capacity_minutes=q(available_capacity),
        required_fte=q(required_fte),
        recommended_operational_fte=recommended,
        fte_gap=q(inp.current_fte - required_fte),
        operational_fte_gap=q(inp.current_fte - recommended),
        utilization_percentage=q(utilization) if utilization is not None else None,
        unused_capacity_percentage=q(unused) if unused is not None else None,
        extra={"required_fte_raw": required_fte},
    )
