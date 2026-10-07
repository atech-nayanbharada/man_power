"""What-if scenario comparison. Runs in memory; nothing is saved. Monte Carlo and growth are optional."""
from dataclasses import replace
from decimal import Decimal

from django.utils import timezone

from .calculations import ForecastInput, q
from .forecast_service import compute_forecast, compute_projection, with_effective_seed
from .projection import STATUS_CSS, STATUS_LABELS


def _filled(value):
    return value not in (None, "")


def apply_adjustments(base: ForecastInput, adj: dict) -> ForecastInput:
    """
    adj keys (all optional):
      volume_growth_pct      -> volume x (1 + x/100)       (one-off change to today's volume)
      time_change_pct        -> avg time x (1 + x/100)     (one-off change to today's AHT)
      contingency_percentage -> override
      current_fte            -> override (proposed FTE)
      growth_rate_percentage -> override the ongoing volume growth % per period
      aht_change_percentage  -> override the ongoing AHT change % per period
    """
    changes = {}
    if _filled(adj.get("volume_growth_pct")):
        changes["volume"] = base.volume * (1 + Decimal(str(adj["volume_growth_pct"])) / 100)
    if _filled(adj.get("time_change_pct")):
        changes["avg_processing_time"] = base.avg_processing_time * (1 + Decimal(str(adj["time_change_pct"])) / 100)
    if _filled(adj.get("contingency_percentage")):
        changes["contingency_percentage"] = Decimal(str(adj["contingency_percentage"]))
    if _filled(adj.get("current_fte")):
        changes["current_fte"] = Decimal(str(adj["current_fte"]))
    if _filled(adj.get("growth_rate_percentage")):
        changes["growth_rate_percentage"] = Decimal(str(adj["growth_rate_percentage"]))
    if _filled(adj.get("aht_change_percentage")):
        changes["aht_change_percentage"] = Decimal(str(adj["aht_change_percentage"]))
    return replace(base, **changes)


def compare_scenarios(base: ForecastInput, scenarios: list, start_date=None) -> list:
    base = with_effective_seed(base)
    start_date = start_date or timezone.localdate()
    rows = []
    for case in [{"name": "Base Case"}] + list(scenarios):
        inp = apply_adjustments(base, case)
        comp = compute_forecast(inp)
        det, mc, st = comp.deterministic, comp.monte_carlo, comp.status
        proj = compute_projection(inp, start_date)
        shortfall_label = ""
        if proj:
            if proj.shortfall_month is None:
                shortfall_label = "Not within horizon"
            else:
                shortfall_label = "Already short" if proj.shortfall_month == 0 else proj.points[proj.shortfall_month]["label"]
        rows.append({
            "name": case.get("name") or "Scenario",
            "volume": q(inp.volume),
            "current_fte": q(inp.current_fte),
            "avg_processing_time": q(inp.avg_processing_time),
            "contingency_percentage": q(inp.contingency_percentage),
            "growth_rate_percentage": q(inp.growth_rate_percentage),
            "aht_change_percentage": q(inp.aht_change_percentage),
            "required_fte": det.required_fte,
            "operational_fte": det.recommended_operational_fte,
            "monte_carlo": mc is not None,
            "p90_fte": q(Decimal(str(mc.p90_required_fte))) if mc else None,
            "risk_adjusted_fte": mc.risk_adjusted_recommended_fte if mc else None,
            "utilization": det.utilization_percentage,
            "sufficiency_probability": q(Decimal(str(mc.sufficiency_probability))) if mc else None,
            "status": st.status,
            "status_label": STATUS_LABELS[st.status],
            "status_css": STATUS_CSS[st.status],
            "high_risk": st.high_utilization_risk,
            "fte_gap": det.fte_gap,
            "has_projection": proj is not None,
            "horizon_label": proj.points[-1]["label"] if proj else "",
            "horizon_aht": proj.points[-1]["aht_minutes"] if proj else None,
            "horizon_required_fte": proj.horizon_required_fte if proj else None,
            "horizon_fte_needed": proj.horizon_fte_needed if proj else None,
            "horizon_status_label": STATUS_LABELS[proj.horizon_status] if proj else "",
            "horizon_status_css": STATUS_CSS[proj.horizon_status] if proj else "secondary",
            "shortfall_label": shortfall_label,
        })
    return rows
