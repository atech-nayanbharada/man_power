"""
Executive (CEO-level) analytics.

Built on the latest forecast per process. Converts process-level results into organisation-level
answers:
  * How healthy is our capacity overall?           -> Capacity Health Score (0-100)
  * How many people do we need now / in N months?  -> hiring need, net of redeployment
  * What does it cost?                             -> hiring budget and idle-capacity cost
  * Where are the risks and what should we do?     -> top risks, redeployment moves, insights
  * How does the requirement evolve?               -> headcount trajectory and quarterly hiring plan
    (projections include both volume growth and AHT change)

Capacity Health Score = 40% Coverage + 30% Efficiency + 30% Resilience
  Coverage    = % of processes that are not short of manpower today
  Efficiency  = 100 - 2 x |organisation utilization - target utilization|   (floored at 0)
  Resilience  = average Monte Carlo sufficiency probability (processes with Monte Carlo);
                if no process has Monte Carlo: % of processes neither short nor at high-utilization risk
"""
import math
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_FLOOR, Decimal

from django.conf import settings

from .calculations import fmt, q
from .dashboard_service import latest_per_process
from .projection import month_label

ZERO = Decimal("0")
WEIGHTS = {"coverage": Decimal("0.4"), "efficiency": Decimal("0.3"), "resilience": Decimal("0.3")}


def exec_config():
    cfg = getattr(settings, "FORECASTING", {})
    return {
        "cost_per_fte": Decimal(str(cfg.get("EXEC_COST_PER_FTE", 600000))),
        "currency": cfg.get("EXEC_CURRENCY", "₹"),
        "horizon": int(cfg.get("EXEC_HORIZON_MONTHS", 12)),
        "target_utilization": Decimal(str(cfg.get("EXEC_TARGET_UTILIZATION", 80))),
        "util_upper": Decimal(str(cfg.get("UTILIZATION_UPPER", 90))),
        "util_lower": Decimal(str(cfg.get("UTILIZATION_LOWER", 70))),
    }


def floor_int(value) -> int:
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_FLOOR))


def rag_for_score(score) -> str:
    if score >= 75:
        return "success"
    if score >= 50:
        return "amber"
    return "danger"


def money(value, currency) -> str:
    """Compact money: ₹1.2 Cr / ₹45.0 L for INR; 1.2M / 45.0K otherwise."""
    value = Decimal(value)
    sign = "-" if value < 0 else ""
    v = abs(value)
    if currency == "₹":
        if v >= 10_000_000:
            return f"{sign}₹{v / 10_000_000:.2f} Cr"
        if v >= 100_000:
            return f"{sign}₹{v / 100_000:.1f} L"
        return f"{sign}₹{v:,.0f}"
    if v >= 1_000_000:
        return f"{sign}{currency}{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{sign}{currency}{v / 1_000:.1f}K"
    return f"{sign}{currency}{v:,.0f}"


@dataclass
class ProcessView:
    """One process reduced to the numbers an executive needs."""
    forecast: object
    function: str
    process: str
    status: str
    current: Decimal
    required: Decimal
    needed_today: Decimal          # whole FTE: ceil(P90) or ceil(required)
    utilization: Decimal = None
    sufficiency: Decimal = None
    high_risk: bool = False
    shortfall_month: int = None    # within exec horizon; 0 = short today
    needed_series: list = field(default_factory=list)
    required_series: list = field(default_factory=list)

    @property
    def hire_now(self) -> Decimal:
        return max(ZERO, self.needed_today - self.current)

    @property
    def redeployable(self) -> int:
        """Whole people that can move out without dropping below today's need."""
        if self.status != "HIGHER":
            return 0
        return max(0, floor_int(self.current - self.needed_today))

    @property
    def idle_fte(self) -> Decimal:
        """Capacity above the risk-safe staffing level (not just above the average requirement)."""
        return max(ZERO, self.current - self.needed_today)

    @property
    def needed_at_horizon(self) -> Decimal:
        return self.needed_series[-1]

    @property
    def hire_at_horizon(self) -> Decimal:
        return max(ZERO, self.needed_at_horizon - self.current)

    @property
    def short_now(self) -> bool:
        return self.status == "LESS"

    @property
    def short_future(self) -> bool:
        return not self.short_now and self.shortfall_month is not None


def _series_value(points, key, month, fallback):
    if not points:
        return fallback
    idx = min(month, len(points) - 1)
    return Decimal(str(points[idx][key]))


def to_process_view(f, horizon: int) -> ProcessView:
    s = f.latest_summary
    needed_today = Decimal(f.risk_adjusted_fte)
    points = f.projection_points
    needed_series = [_series_value(points, "fte_needed", m, needed_today) for m in range(horizon + 1)]
    required_series = [_series_value(points, "required_fte", m, f.required_fte) for m in range(horizon + 1)]
    shortfall = None
    if f.status == "LESS":
        shortfall = 0
    elif points:
        shortfall = next((p["month"] for p in points[: horizon + 1] if p["status"] == "LESS"), None)
    return ProcessView(
        forecast=f, function=f.function.function_name, process=f.process.process_name, status=f.status,
        current=f.current_fte, required=f.required_fte, needed_today=needed_today,
        utilization=f.utilization_percentage, sufficiency=s.sufficiency_probability if s else None,
        high_risk=f.high_utilization_risk, shortfall_month=shortfall,
        needed_series=needed_series, required_series=required_series,
    )


# ---------------------------------------------------------------- scoring
def health_score(views, org_utilization, cfg):
    total = len(views)
    if not total:
        return {"score": 0, "rag": "secondary", "coverage": 0, "efficiency": 0, "resilience": 0,
                "resilience_basis": "No data"}
    coverage = Decimal(sum(1 for v in views if not v.short_now)) * 100 / total
    if org_utilization is None:
        efficiency = ZERO
    else:
        efficiency = max(ZERO, Decimal("100") - 2 * abs(org_utilization - cfg["target_utilization"]))
    mc = [v.sufficiency for v in views if v.sufficiency is not None]
    if mc:
        resilience = sum(mc) / len(mc)
        basis = f"Average Monte Carlo sufficiency across {len(mc)} process(es)"
    else:
        resilience = Decimal(sum(1 for v in views if not v.short_now and not v.high_risk)) * 100 / total
        basis = "Share of processes neither short nor at high-utilization risk (no Monte Carlo data)"
    score = (WEIGHTS["coverage"] * coverage + WEIGHTS["efficiency"] * efficiency
             + WEIGHTS["resilience"] * resilience)
    score = int(q(score, "1"))
    return {"score": score, "rag": rag_for_score(score), "coverage": float(q(coverage, "0.1")),
            "efficiency": float(q(efficiency, "0.1")), "resilience": float(q(resilience, "0.1")),
            "resilience_basis": basis}


# ---------------------------------------------------------------- redeployment
def redeployment_moves(views):
    """
    Greedy matching of surplus people (Higher Manpower processes) to shortages (Less Manpower today).
    Same-function moves are preferred, then cross-function moves. Whole people only.
    """
    donors = [[v, v.redeployable] for v in views if v.redeployable > 0]
    receivers = [[v, int(math.ceil(v.hire_now))] for v in views if v.short_now and v.hire_now > 0]
    moves = []
    for same_function in (True, False):
        for rec in receivers:
            for don in donors:
                if rec[1] <= 0:
                    break
                if don[1] <= 0 or (don[0].function == rec[0].function) != same_function:
                    continue
                qty = min(rec[1], don[1])
                moves.append({"from_process": don[0].process, "from_function": don[0].function,
                              "to_process": rec[0].process, "to_function": rec[0].function, "fte": qty,
                              "same_function": same_function})
                rec[1] -= qty
                don[1] -= qty
    return moves


# ---------------------------------------------------------------- hiring plan
def quarterly_hiring_plan(views, horizon, start_date, cost_per_fte, redeployable_pool):
    """
    Cumulative hires needed per quarter-end (whole people), net of the redeployable pool,
    with the incremental hires and budget for each quarter.
    """
    def gross_hires(month):
        return sum((max(ZERO, v.needed_series[month] - v.current) for v in views), ZERO)

    plan, previous = [], 0
    checkpoints = list(range(0, horizon + 1, 3))
    if checkpoints[-1] != horizon:
        checkpoints.append(horizon)
    for m in checkpoints:
        cumulative = max(0, int(math.ceil(gross_hires(m))) - redeployable_pool)
        new = max(0, cumulative - previous)
        plan.append({"month": m, "label": "Now" if m == 0 else month_label(start_date, m),
                     "cumulative_hires": cumulative, "new_hires": new,
                     "budget": cost_per_fte * new, "cumulative_budget": cost_per_fte * cumulative})
        previous = max(previous, cumulative)
    return plan


# ---------------------------------------------------------------- risks and insights
def top_risks(views, start_date, limit=7):
    risks = []
    for v in views:
        if v.short_now:
            gap = v.hire_now
            risks.append({"severity": "danger", "rank": (0, -float(gap)), "process": v.process,
                          "function": v.function, "when": "Now",
                          "issue": f"Short today: needs {fmt(v.needed_today)} FTE, has {fmt(v.current)}"
                                   + (f" (utilization {fmt(v.utilization)}%)" if v.utilization is not None else ""),
                          "action": f"Add {fmt(gap)} FTE or redeploy surplus capacity",
                          "forecast_id": v.forecast.pk})
        elif v.short_future:
            when = month_label(start_date, v.shortfall_month)
            drivers = v.forecast.growth_drivers_text or "projected workload growth"
            risks.append({"severity": "orange", "rank": (1, v.shortfall_month), "process": v.process,
                          "function": v.function, "when": when,
                          "issue": f"Sufficient today, short from {when} ({drivers})",
                          "action": f"Plan {fmt(v.hire_at_horizon)} FTE before {when}",
                          "forecast_id": v.forecast.pk})
        elif v.high_risk:
            risks.append({"severity": "amber", "rank": (2, -float(v.utilization or 0)), "process": v.process,
                          "function": v.function, "when": "Now",
                          "issue": f"High utilization ({fmt(v.utilization)}%): no buffer for peaks or absence",
                          "action": "Monitor weekly; cross-train backup staff",
                          "forecast_id": v.forecast.pk})
    risks.sort(key=lambda r: r["rank"])
    for r in risks:
        r.pop("rank")
    return risks[:limit]


def build_insights(k, scorecard, moves, plan, cfg, horizon_label):
    cur = cfg["currency"]
    insights = []
    if k["process_count"] == 0:
        return insights
    if k["short_now_count"]:
        insights.append({"tone": "danger", "icon": "bi-exclamation-octagon",
                         "text": f"{k['short_now_count']} of {k['process_count']} processes are short of manpower "
                                 f"today. {fmt(k['hire_now'])} FTE are needed to close the gap."})
    else:
        insights.append({"tone": "success", "icon": "bi-check-circle",
                         "text": f"All {k['process_count']} processes have enough manpower today."})
    if k["redeployable"]:
        covered = min(k["redeployable"], int(math.ceil(k["hire_now"])))
        text = f"{k['redeployable']} FTE sit in over-staffed processes and can be redeployed"
        text += (f"; this covers {covered} of today's {int(math.ceil(k['hire_now']))} FTE need and avoids about "
                 f"{money(k['redeploy_savings'], cur)} in annual hiring cost." if covered else ".")
        insights.append({"tone": "info", "icon": "bi-arrow-left-right", "text": text})
    if k["short_future_count"]:
        first = min((r for r in plan if r["new_hires"] > 0 and r["month"] > 0), key=lambda r: r["month"],
                    default=None)
        text = (f"{k['short_future_count']} process(es) are fine today but will need more people by {horizon_label} "
                f"because of projected volume and AHT changes.")
        if first:
            text += f" The first new hiring wave is due by {first['label']} ({first['new_hires']} FTE)."
        insights.append({"tone": "orange", "icon": "bi-graph-up-arrow", "text": text})
    if k["aht_change_count"]:
        insights.append({"tone": "primary", "icon": "bi-stopwatch",
                         "text": f"{k['aht_change_count']} process(es) include a projected AHT change "
                                 "(for example automation savings or added complexity) in their forecast."})
    if k["net_hire_horizon"]:
        insights.append({"tone": "primary", "icon": "bi-cash-coin",
                         "text": f"Net hiring need by {horizon_label}: {k['net_hire_horizon']} FTE "
                                 f"(about {money(k['budget_horizon'], cur)} per year at "
                                 f"{money(cfg['cost_per_fte'], cur)} per FTE)."})
    if k["idle_fte"] >= 1:
        insights.append({"tone": "amber", "icon": "bi-hourglass-split",
                         "text": f"About {fmt(k['idle_fte'])} FTE sit above the safe staffing level, "
                                 f"worth roughly {money(k['idle_cost'], cur)} per year."})
    if k["org_utilization"] is not None:
        u, t = k["org_utilization"], cfg["target_utilization"]
        if u > cfg["util_upper"]:
            insights.append({"tone": "danger", "icon": "bi-speedometer",
                             "text": f"Organisation utilization is {fmt(u)}%, above the {fmt(cfg['util_upper'])}% "
                                     "safe limit. Teams have little buffer for peaks or leave."})
        elif u < cfg["util_lower"]:
            insights.append({"tone": "amber", "icon": "bi-speedometer",
                             "text": f"Organisation utilization is {fmt(u)}%, below the {fmt(cfg['util_lower'])}% "
                                     "lower bound. There is room to absorb growth without hiring."})
        else:
            insights.append({"tone": "success", "icon": "bi-speedometer",
                             "text": f"Organisation utilization is {fmt(u)}%, close to the {fmt(t)}% target."})
    worst = max(scorecard, key=lambda r: r["hire_now"], default=None)
    if worst and worst["hire_now"] > 0:
        insights.append({"tone": "danger", "icon": "bi-diagram-3",
                         "text": f"{worst['function']} needs the most people today: {fmt(worst['hire_now'])} FTE "
                                 f"across {worst['short_now']} short process(es)."})
    return insights


# ---------------------------------------------------------------- main entry
def build_executive(queryset, start_date: date, cost_per_fte=None, horizon=None):
    cfg = exec_config()
    if cost_per_fte is not None:
        cfg["cost_per_fte"] = Decimal(str(cost_per_fte))
    if horizon is not None:
        cfg["horizon"] = int(horizon)
    horizon = cfg["horizon"]
    cost = cfg["cost_per_fte"]
    horizon_label = month_label(start_date, horizon)

    forecasts = list(latest_per_process(queryset))
    views = [to_process_view(f, horizon) for f in forecasts]

    total_current = sum((v.current for v in views), ZERO)
    total_required = sum((v.required for v in views), ZERO)
    total_needed = sum((v.needed_today for v in views), ZERO)
    org_util = q(total_required * 100 / total_current) if total_current else None
    hire_now = sum((v.hire_now for v in views), ZERO)
    redeployable = sum(v.redeployable for v in views)
    hire_horizon = sum((v.hire_at_horizon for v in views), ZERO)
    net_hire_now = max(0, int(math.ceil(hire_now)) - redeployable)
    net_hire_horizon = max(0, int(math.ceil(hire_horizon)) - redeployable)
    idle_fte = sum((v.idle_fte for v in views), ZERO)
    redeploy_used = min(redeployable, int(math.ceil(hire_now)))

    kpis = {
        "process_count": len(views),
        "function_count": len({v.function for v in views}),
        "total_current": total_current,
        "total_required": total_required,
        "total_needed": total_needed,
        "total_needed_horizon": sum((v.needed_at_horizon for v in views), ZERO),
        "org_utilization": org_util,
        "net_gap": total_current - total_required,
        "hire_now": hire_now,
        "redeployable": redeployable,
        "net_hire_now": net_hire_now,
        "hire_horizon": hire_horizon,
        "net_hire_horizon": net_hire_horizon,
        "idle_fte": idle_fte,
        "idle_cost": idle_fte * cost,
        "budget_now": cost * net_hire_now,
        "budget_horizon": cost * net_hire_horizon,
        "redeploy_savings": cost * redeploy_used,
        "short_now_count": sum(1 for v in views if v.short_now),
        "short_future_count": sum(1 for v in views if v.short_future),
        "high_risk_count": sum(1 for v in views if v.high_risk and not v.short_now),
        "higher_count": sum(1 for v in views if v.status == "HIGHER"),
        "sufficient_count": sum(1 for v in views if v.status == "SUFFICIENT"),
        "projection_count": sum(1 for f in forecasts if f.has_projection),
        "aht_change_count": sum(1 for f in forecasts if f.has_aht_change),
        "mc_count": sum(1 for v in views if v.sufficiency is not None),
        "pending_count": sum(1 for f in forecasts if f.approval_status != "APPROVED"),
    }
    score = health_score(views, org_util, cfg)

    # Function scorecard
    groups = OrderedDict()
    for v in sorted(views, key=lambda x: x.function):
        groups.setdefault(v.function, []).append(v)
    scorecard = []
    for name, items in groups.items():
        cur = sum((i.current for i in items), ZERO)
        req = sum((i.required for i in items), ZERO)
        util = q(req * 100 / cur) if cur else None
        short_now = sum(1 for i in items if i.short_now)
        short_future = sum(1 for i in items if i.short_future)
        if short_now:
            rag, rag_label = "danger", "Action needed"
        elif short_future or any(i.high_risk for i in items):
            rag, rag_label = "amber", "Watch"
        elif util is not None and util < cfg["util_lower"]:
            rag, rag_label = "info", "Surplus"
        else:
            rag, rag_label = "success", "Healthy"
        scorecard.append({
            "function": name, "processes": len(items), "current": cur, "required": req,
            "needed_horizon": sum((i.needed_at_horizon for i in items), ZERO),
            "utilization": util, "net_gap": cur - req,
            "hire_now": sum((i.hire_now for i in items), ZERO),
            "redeployable": sum(i.redeployable for i in items),
            "hire_horizon": sum((i.hire_at_horizon for i in items), ZERO),
            "short_now": short_now, "short_future": short_future,
            "higher": sum(1 for i in items if i.status == "HIGHER"),
            "rag": rag, "rag_label": rag_label,
        })

    moves = redeployment_moves(views)
    plan = quarterly_hiring_plan(views, horizon, start_date, cost, redeployable)
    risks = top_risks(views, start_date)
    insights = build_insights(kpis, scorecard, moves, plan, cfg, horizon_label)

    labels = [month_label(start_date, m) for m in range(horizon + 1)]
    fte_by_status = defaultdict(lambda: ZERO)
    for v in views:
        fte_by_status[v.status] += v.current
    bubbles = []
    for v in views:
        runway = v.shortfall_month if v.shortfall_month is not None else horizon + 1
        bubbles.append({"x": float(min(v.utilization, Decimal("200"))) if v.utilization is not None else 200.0,
                        "y": runway, "r": max(4.0, min(22.0, float(v.current) * 3)),
                        "label": f"{v.process} ({v.function})", "status": v.status,
                        "fte": float(v.current)})
    chart = {
        "health": {"score": score["score"], "rag": score["rag"]},
        "trajectory": {
            "labels": labels,
            "current": [float(total_current)] * len(labels),
            "required": [float(sum((v.required_series[m] for v in views), ZERO)) for m in range(horizon + 1)],
            "needed": [float(sum((v.needed_series[m] for v in views), ZERO)) for m in range(horizon + 1)],
        },
        "functions": {
            "labels": [r["function"] for r in scorecard],
            "current": [float(r["current"]) for r in scorecard],
            "required": [float(r["required"]) for r in scorecard],
            "needed_horizon": [float(r["needed_horizon"]) for r in scorecard],
        },
        "fte_status": {"labels": ["Less Manpower", "Sufficient Manpower", "Higher Manpower"],
                       "values": [float(fte_by_status[s]) for s in ("LESS", "SUFFICIENT", "HIGHER")]},
        "risk_matrix": {"points": bubbles, "horizon": horizon,
                        "util_lower": float(cfg["util_lower"]), "util_upper": float(cfg["util_upper"])},
        "hiring_plan": {"labels": [p["label"] for p in plan],
                        "new_hires": [p["new_hires"] for p in plan],
                        "cumulative": [p["cumulative_hires"] for p in plan]},
    }
    return {
        "kpis": kpis, "score": score, "scorecard": scorecard, "moves": moves, "hiring_plan": plan,
        "risks": risks, "insights": insights, "chart_data": chart, "config": cfg,
        "horizon_label": horizon_label, "views": views,
        "money": {
            "idle_cost": money(kpis["idle_cost"], cfg["currency"]),
            "budget_now": money(kpis["budget_now"], cfg["currency"]),
            "budget_horizon": money(kpis["budget_horizon"], cfg["currency"]),
            "redeploy_savings": money(kpis["redeploy_savings"], cfg["currency"]),
            "cost_per_fte": money(cfg["cost_per_fte"], cfg["currency"]),
        },
    }
