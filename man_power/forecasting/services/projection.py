"""
Growth projection: how manpower sufficiency changes month by month when volume grows (or declines).

Volume growth is compounded per growth period and applied in steps:
  Daily       -> once per working day     (month m = m x working days per month periods)
  Weekly      -> once per completed week  (floor(m x days per month / days per week))
  Monthly     -> once per month           (m)
  Quarterly   -> once every 3 months      (floor(m / 3))
  Half-Yearly -> once every 6 months      (floor(m / 6))
  Yearly      -> once every 12 months     (floor(m / 12))

  Projected volume(m) = Current volume x (1 + growth% / 100) ^ periods_elapsed(m)

For every month 0..horizon the full forecast (deterministic + optional Monte Carlo + status)
is recalculated with the projected volume while current FTE stays fixed.
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
    return rate ** periods_elapsed(growth_period, month, working_days_per_week, working_days_per_month)


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
        factor = growth_factor(inp.growth_rate_percentage, inp.growth_period, m,
                               inp.working_days_per_week, inp.working_days_per_month)
        projected_volume = inp.volume * factor
        comp = compute_fn(replace(inp, volume=projected_volume))
        det, mc, st = comp.deterministic, comp.monte_carlo, comp.status
        needed = Decimal(mc.risk_adjusted_recommended_fte) if mc else det.recommended_operational_fte
        points.append({
            "month": m,
            "label": month_label(start_date, m),
            "growth_factor": float(q(factor, "0.0001")),
            "volume": float(q(projected_volume)),
            "daily_volume": float(q(det.daily_volume)),
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


def build_summary(points, shortfall, current_fte, inp: ForecastInput) -> str:
    basis = "risk-adjusted P90" if inp.run_monte_carlo else "operational"
    period = PERIOD_LABELS.get(inp.growth_period, inp.growth_period.lower())
    direction = "growth" if inp.growth_rate_percentage > 0 else "decline"
    first, last = points[0], points[-1]
    end = f"{last['label']} (month {last['month']})"
    head = (f"With {fmt(abs(inp.growth_rate_percentage))}% volume {direction} per {period}, volume moves from "
            f"{fmt(first['volume'])} to {fmt(last['volume'])} by {end}, and required FTE from "
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
            text += f" With the projected decline, current manpower becomes sufficient from {recovered['label']} (month {recovered['month']})."
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
