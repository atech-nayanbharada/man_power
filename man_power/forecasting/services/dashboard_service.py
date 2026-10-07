"""
Dashboard KPIs and chart datasets. Uses the latest forecast per process to avoid double counting.
Forecasts without Monte Carlo contribute their operational FTE to the risk-adjusted total and appear
as gaps (null) in Monte Carlo-only charts. Forecasts without a projection use today's requirement as the
horizon requirement.
"""
from collections import OrderedDict, defaultdict
from decimal import Decimal

from django.db.models import Max

from ..models import ManpowerForecast


def latest_per_process(queryset):
    ids = list(queryset.order_by().values("process_id").annotate(latest=Max("id")).values_list("latest", flat=True))
    return (ManpowerForecast.objects.filter(id__in=ids)
            .select_related("function", "process", "created_by")
            .prefetch_related("simulation_summaries")
            .order_by("function__function_name", "process__process_name"))


def _f(value):
    return float(value) if value is not None else 0.0


def build_dashboard(queryset):
    forecasts = list(latest_per_process(queryset))
    zero = Decimal("0")
    status_counts = OrderedDict([("LESS", 0), ("SUFFICIENT", 0), ("HIGHER", 0)])
    total_current = total_required = total_risk = shortage = excess = zero
    horizon_additional = zero
    mc_count = projection_count = future_shortage = 0
    function_gap = defaultdict(lambda: Decimal("0"))
    chart = {k: [] for k in ("labels", "current", "required", "required_horizon", "p50", "p80", "p90", "p95",
                             "utilization", "sufficiency")}

    for f in forecasts:
        s = f.latest_summary
        if s:
            mc_count += 1
        status_counts[f.status] = status_counts.get(f.status, 0) + 1
        total_current += f.current_fte
        total_required += f.required_fte
        total_risk += f.risk_adjusted_fte
        gap = f.current_fte - f.required_fte
        if gap < 0:
            shortage += -gap
        else:
            excess += gap
        function_gap[f.function.function_name] += gap

        if f.has_projection:
            projection_count += 1
            if f.status != "LESS" and f.projected_shortfall_month is not None:
                future_shortage += 1
            horizon_additional += f.horizon_additional_fte or zero
            chart["required_horizon"].append(_f(f.projected_horizon_required_fte))
        else:
            chart["required_horizon"].append(_f(f.required_fte))

        chart["labels"].append(f.process.process_name)
        chart["current"].append(_f(f.current_fte))
        chart["required"].append(_f(f.required_fte))
        chart["utilization"].append(_f(f.utilization_percentage))
        for key in ("p50", "p80", "p90", "p95"):
            chart[key].append(round(_f(getattr(s, f"{key}_required_fte")), 2) if s else None)
        chart["sufficiency"].append(_f(s.sufficiency_probability) if s else None)

    chart["status"] = {"labels": ["Less Manpower", "Sufficient Manpower", "Higher Manpower"],
                       "values": list(status_counts.values())}
    chart["function_gap"] = {"labels": list(function_gap.keys()),
                             "values": [round(_f(v), 2) for v in function_gap.values()]}
    chart["has_monte_carlo"] = mc_count > 0
    chart["has_projection"] = projection_count > 0
    cards = {
        "total_functions": len({f.function_id for f in forecasts}),
        "total_processes": len(forecasts),
        "total_current_fte": total_current,
        "total_required_fte": total_required,
        "total_risk_adjusted_fte": total_risk,
        "less_count": status_counts["LESS"],
        "sufficient_count": status_counts["SUFFICIENT"],
        "higher_count": status_counts["HIGHER"],
        "total_shortage": shortage,
        "total_excess": excess,
        "monte_carlo_count": mc_count,
        "deterministic_only_count": len(forecasts) - mc_count,
        "projection_count": projection_count,
        "future_shortage_count": future_shortage,
        "horizon_additional_fte": horizon_additional,
    }
    return {"cards": cards, "chart_data": chart, "latest_forecasts": forecasts}
