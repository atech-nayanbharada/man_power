"""
Growth projection: how manpower sufficiency changes month by month when VOLUME and/or
AVERAGE HANDLING TIME (AHT) change in the future.

Each driver is compounded per its own period and applied in steps:
  Daily       -> once per working day     (month m = m x working days per month periods)
  Weekly      -> once per completed week  (floor(m x days per month / days per week))
  Monthly     -> once per month           (m)
  Quarterly   -> once every 3 months      (floor(m / 3))
  Half-Yearly -> once every 6 months      (floor(m / 6))
  Yearly      -> once every 12 months     (floor(m / 12))

  Volume(m) = Volume x (1 + volume growth% / 100) ^ periods_elapsed(volume period, m)
  AHT(m)    = AHT    x (1 + AHT change%    / 100) ^ periods_elapsed(AHT period, m)
  Workload(m) = Volume(m) x AHT(m)      ->  workload factor = volume factor x AHT factor

For every month 0..horizon the full forecast (deterministic + optional Monte Carlo + status)
is recalculated with the projected volume and AHT while current FTE stays fixed.
"""
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Callable, Optional

from django.conf import settings

from .calculations import ForecastInput, fmt, q, to_decimal

MONTHS_PER_PERIOD = {"MONTHLY": 1, "QUARTERLY": 3, "HALF_YEARLY": 6, "YEARLY": 12}
PERIOD_LABELS = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month", "QUARTERLY": "quarter",
                 "HALF_YEARLY": "half-year", "YEARLY": "year"}
STATUS_LABELS = {"LESS": "Less Manpower", "SUFFICIENT": "Sufficient Manpower", "HIGHER": "Higher Manpower"}
STATUS_CSS = {"LESS": "danger", "SUFFICIENT": "success", "HIGHER": "amber"}


def max_growth_factor() -> Decimal:
    return Decimal(str(getattr(settings, "FORECASTING", {}).get("GROWTH_MAX_FACTOR", 1000)))


def periods_elapsed(growth_period: str, month: int, working_days_per_week: int, working_days_per_month: int) -> int:
    if growth_period == "DAILY":
        return month * int(working_days_per_month)
    if growth_period == "WEEKLY":
        return (month * int(working_days_per_month)) // int(working_days_per_week)
    if growth_period not in MONTHS_PER_PERIOD:
        raise ValueError(f"Unsupported growth period: {growth_period}")
    return month // MONTHS_PER_PERIOD[growth_period]


def growth_factor(growth_rate_pct, growth_period, month, working_days_per_week=5, working_days_per_month=22) -> Decimal:
    rate = Decimal("1") + to_decimal(growth_rate_pct) / Decimal("100")
    return rate ** periods_elapsed(growth_period or "MONTHLY", month, working_days_per_week, working_days_per_month)


def workload_factors(inp_or_values, month):
    """Return (volume_factor, aht_factor, workload_factor) for a month."""
    g = inp_or_values
    vf = growth_factor(g.growth_rate_percentage, g.growth_period, month, g.working_days_per_week,
                       g.working_days_per_month)
    af = growth_factor(g.aht_change_percentage, g.aht_change_period, month, g.working_days_per_week,
                       g.working_days_per_month)
    return vf, af, vf * af


def add_months(start: date, months: int) -> date:
    years, month_index = divmod(start.month - 1 + months, 12)
    return date(start.year + years, month_index + 1, 1)


def month_label(start: date, months: int) -> str:
    return add_months(start, months).strftime("%b %Y")


@dataclass
class ProjectionResult:
    points: list
    shortfall_month: Optional[int]
    horizon_required_fte: Decimal
    horizon_fte_needed: Decimal
    horizon_status: str
    hiring_plan: list = field(default_factory=list)
    summary: str = ""

    def as_json(self):
        return {"points": self.points, "hiring_plan": self.hiring_plan}


def run_projection(inp: ForecastInput, compute_fn: Callable, start_date: date) -> ProjectionResult:
    """compute_fn(ForecastInput) -> ForecastComputation (deterministic, monte_carlo, status)."""
    current = inp.current_fte
    points = []
    for m in range(inp.forecast_horizon_months + 1):
        vf, af, wf = workload_factors(inp, m)
        projected = replace(inp, volume=inp.volume * vf, avg_processing_time=inp.avg_processing_time * af)
        comp = compute_fn(projected)
        det, mc, st = comp.deterministic, comp.monte_carlo, comp.status
        needed = Decimal(mc.risk_adjusted_recommended_fte) if mc else det.recommended_operational_fte
        points.append({
            "month": m,
            "label": month_label(start_date, m),
            "growth_factor": float(q(vf, "0.0001")),
            "aht_factor": float(q(af, "0.0001")),
            "workload_factor": float(q(wf, "0.0001")),
            "volume": float(q(projected.volume)),
            "daily_volume": float(q(det.daily_volume)),
            "aht": float(q(projected.avg_processing_time)),
            "aht_minutes": float(q(det.processing_time_minutes)),
            "required_fte": float(det.required_fte),
            "operational_fte": float(det.recommended_operational_fte),
            "p90_fte": round(mc.p90_required_fte, 2) if mc else None,
            "fte_needed": float(needed),
            "utilization": float(det.utilization_percentage) if det.utilization_percentage is not None else None,
            "sufficiency": mc.sufficiency_probability if mc else None,
            "status": st.status,
            "status_label": STATUS_LABELS[st.status],
            "status_css": STATUS_CSS[st.status],
            "high_risk": st.high_utilization_risk,
            "fte_gap": float(det.fte_gap),
            "additional_fte": float(max(Decimal("0"), needed - current)),
        })

    shortfall = next((p["month"] for p in points if p["status"] == "LESS"), None)
    hiring_plan = build_hiring_plan(points, current)
    last = points[-1]
    return ProjectionResult(
        points=points,
        shortfall_month=shortfall,
        horizon_required_fte=q(Decimal(str(last["required_fte"]))),
        horizon_fte_needed=q(Decimal(str(last["fte_needed"]))),
        horizon_status=last["status"],
        hiring_plan=hiring_plan,
        summary=build_summary(points, shortfall, current, inp),
    )


def build_hiring_plan(points, current_fte) -> list:
    """Each step where the headcount needed rises above both today's FTE and the previous step."""
    plan, previous = [], to_decimal(current_fte)
    for p in points:
        needed = Decimal(str(p["fte_needed"]))
        if needed > previous and needed > current_fte:
            plan.append({"month": p["month"], "label": p["label"], "fte_needed": float(needed),
                         "additional_fte": float(needed - current_fte)})
            previous = needed
    return plan


def drivers_text(inp: ForecastInput) -> str:
    drivers = []
    if inp.has_volume_growth:
        word = "growth" if inp.growth_rate_percentage > 0 else "decline"
        drivers.append(f"{fmt(abs(inp.growth_rate_percentage))}% volume {word} per "
                       f"{PERIOD_LABELS.get(inp.growth_period, inp.growth_period.lower())}")
    if inp.has_aht_change:
        word = "increase" if inp.aht_change_percentage > 0 else "reduction"
        drivers.append(f"{fmt(abs(inp.aht_change_percentage))}% AHT {word} per "
                       f"{PERIOD_LABELS.get(inp.aht_change_period, inp.aht_change_period.lower())}")
    return " and ".join(drivers)


def build_summary(points, shortfall, current_fte, inp: ForecastInput) -> str:
    basis = "risk-adjusted P90" if inp.run_monte_carlo else "operational"
    first, last = points[0], points[-1]
    end = f"{last['label']} (month {last['month']})"
    changes = []
    if inp.has_volume_growth:
        changes.append(f"volume moves from {fmt(first['volume'])} to {fmt(last['volume'])}")
    if inp.has_aht_change:
        changes.append(f"AHT moves from {fmt(first['aht_minutes'])} to {fmt(last['aht_minutes'])} minutes")
    head = (f"With {drivers_text(inp)}, {' and '.join(changes)} by {end}, and required FTE moves from "
            f"{fmt(first['required_fte'])} to {fmt(last['required_fte'])}. ")
    extra = max(Decimal("0"), Decimal(str(last["fte_needed"])) - current_fte)

    if shortfall is None:
        text = (f"Current {fmt(current_fte)} FTE remains sufficient for the full {inp.forecast_horizon_months}-month "
                f"horizon up to {end}.")
        if last["status"] == "HIGHER":
            text += " Capacity is still higher than needed at the end of the horizon."
        return head + text

    if shortfall == 0:
        recovered = next((p for p in points if p["status"] != "LESS"), None)
        text = "Manpower is already insufficient today."
        if recovered:
            text += (f" As the workload falls, current manpower becomes sufficient from {recovered['label']} "
                     f"(month {recovered['month']}).")
        elif extra > 0:
            text += (f" By {end} the process needs {fmt(last['fte_needed'])} FTE ({basis}), "
                     f"{fmt(extra)} more than today.")
        return head + text

    prev, short = points[shortfall - 1], points[shortfall]
    text = (f"Current {fmt(current_fte)} FTE remains sufficient until {prev['label']} (month {prev['month']}). "
            f"From {short['label']} (month {short['month']}) additional manpower is required.")
    if extra > 0:
        text += f" By {end} the process needs {fmt(last['fte_needed'])} FTE ({basis}), {fmt(extra)} more than today."
    return head + text
