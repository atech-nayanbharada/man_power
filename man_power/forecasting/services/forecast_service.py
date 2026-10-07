"""
Orchestration: deterministic calculation + optional Monte Carlo + status classification
+ optional growth projection (volume and/or AHT), persisted with a simulation summary and an audit log.
"""
import secrets
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.forms.models import model_to_dict
from django.utils import timezone

from ..models import ApprovalStatus, ForecastAuditLog, ForecastSimulationSummary, ManpowerForecast
from .calculations import DeterministicResult, ForecastInput, calculate_deterministic, q
from .monte_carlo import MonteCarloResult, run_monte_carlo
from .projection import ProjectionResult, run_projection
from .status import StatusResult, classify_status

INPUT_FIELDS = (
    "frequency", "volume", "current_fte", "avg_processing_time", "time_unit", "working_hours_per_day",
    "working_days_per_week", "working_days_per_month", "contingency_percentage", "run_monte_carlo",
    "volume_variation_percentage", "time_variation_percentage", "simulation_count", "simulation_seed",
    "growth_rate_percentage", "growth_period", "forecast_horizon_months",
    "aht_change_percentage", "aht_change_period",
)
RESULT_FIELDS = (
    "daily_volume", "processing_time_minutes", "productive_minutes_per_fte", "workload_minutes",
    "workload_hours", "available_capacity_minutes", "required_fte", "recommended_operational_fte",
    "fte_gap", "operational_fte_gap", "utilization_percentage", "unused_capacity_percentage",
)


@dataclass
class ForecastComputation:
    inputs: ForecastInput
    deterministic: DeterministicResult
    monte_carlo: Optional[MonteCarloResult]
    status: StatusResult


def build_input(data) -> ForecastInput:
    if isinstance(data, dict):
        return ForecastInput(**{k: data.get(k) for k in INPUT_FIELDS})
    return ForecastInput(**{k: getattr(data, k) for k in INPUT_FIELDS})


def with_effective_seed(inp: ForecastInput) -> ForecastInput:
    """
    Use one seed for the current result and every projected month so the projection curve is
    consistent with today's result. A random seed is drawn when the user did not set one.
    """
    if not inp.run_monte_carlo or inp.simulation_seed is not None:
        return inp
    return replace(inp, simulation_seed=secrets.randbelow(2 ** 32))


def compute_forecast(inp: ForecastInput) -> ForecastComputation:
    det = calculate_deterministic(inp)
    mc = None
    if inp.run_monte_carlo:
        mc = run_monte_carlo(
            daily_volume=det.daily_volume,
            processing_time_minutes=det.processing_time_minutes,
            productive_minutes_per_fte=det.productive_minutes_per_fte,
            current_fte=inp.current_fte,
            volume_variation_pct=inp.volume_variation_percentage,
            time_variation_pct=inp.time_variation_percentage,
            simulation_count=inp.simulation_count,
            seed=inp.simulation_seed,
        )
    status = classify_status(
        inp.current_fte, det.required_fte, det.utilization_percentage,
        sufficiency_probability=mc.sufficiency_probability if mc else None,
        p90_fte=Decimal(str(mc.p90_required_fte)) if mc else None,
    )
    return ForecastComputation(inp, det, mc, status)


def compute_projection(inp: ForecastInput, start_date=None) -> Optional[ProjectionResult]:
    """Projection, or None when neither volume growth nor AHT change is entered."""
    if not inp.has_growth:
        return None
    return run_projection(inp, compute_forecast, start_date or timezone.localdate())


def serialize_forecast(instance):
    if instance is None or instance.pk is None:
        return None
    data = model_to_dict(instance, exclude=["projection_data"])
    return {k: (v if v is None or isinstance(v, (bool, int, str)) else str(v)) for k, v in data.items()}


def _apply_results(forecast, comp):
    det, st = comp.deterministic, comp.status
    for attr in RESULT_FIELDS:
        setattr(forecast, attr, getattr(det, attr))
    forecast.status = st.status
    forecast.high_utilization_risk = st.high_utilization_risk
    forecast.recommendation = st.recommendation
    forecast.status_explanation = st.explanation + (f" Warning: {st.warning}" if st.warning else "")


def _apply_projection(forecast, proj: Optional[ProjectionResult]):
    if proj is None:
        forecast.projection_data = {}
        forecast.projected_shortfall_month = None
        forecast.projected_horizon_required_fte = None
        forecast.projected_horizon_fte_needed = None
        forecast.projected_horizon_status = ""
        forecast.projection_summary = ""
        return
    forecast.projection_data = proj.as_json()
    forecast.projected_shortfall_month = proj.shortfall_month
    forecast.projected_horizon_required_fte = proj.horizon_required_fte
    forecast.projected_horizon_fte_needed = proj.horizon_fte_needed
    forecast.projected_horizon_status = proj.horizon_status
    forecast.projection_summary = proj.summary


def _save_summary(forecast, mc):
    def d(value, places="0.0001"):
        return q(Decimal(str(value)), places)

    return ForecastSimulationSummary.objects.create(
        forecast=forecast,
        average_required_fte=d(mc.average_required_fte),
        minimum_required_fte=d(mc.minimum_required_fte),
        maximum_required_fte=d(mc.maximum_required_fte),
        standard_deviation=d(mc.standard_deviation),
        p50_required_fte=d(mc.p50_required_fte),
        p80_required_fte=d(mc.p80_required_fte),
        p90_required_fte=d(mc.p90_required_fte),
        p95_required_fte=d(mc.p95_required_fte),
        p99_required_fte=d(mc.p99_required_fte),
        risk_adjusted_recommended_fte=Decimal(mc.risk_adjusted_recommended_fte),
        sufficiency_probability=d(mc.sufficiency_probability, "0.01"),
        failure_probability=d(mc.failure_probability, "0.01"),
        simulation_count=mc.simulation_count,
        histogram_data=mc.histogram,
    )


@transaction.atomic
def save_forecast(forecast: ManpowerForecast, user, action=ForecastAuditLog.Action.CREATE) -> ManpowerForecast:
    """Compute and persist. Any change resets approval to Pending so maker-checker restarts."""
    old_data = serialize_forecast(ManpowerForecast.objects.get(pk=forecast.pk)) if forecast.pk else None
    inp = with_effective_seed(build_input(forecast))
    comp = compute_forecast(inp)
    _apply_results(forecast, comp)
    start = timezone.localdate(forecast.created_at) if forecast.created_at else timezone.localdate()
    _apply_projection(forecast, compute_projection(inp, start))
    if not forecast.pk:
        forecast.created_by = user
    forecast.approval_status = ApprovalStatus.PENDING
    forecast.approved_by = None
    forecast.approved_at = None
    forecast.approval_comments = ""
    forecast.save()
    if comp.monte_carlo is not None:
        _save_summary(forecast, comp.monte_carlo)
    ForecastAuditLog.objects.create(forecast=forecast, action=action, old_data=old_data,
                                    new_data=serialize_forecast(forecast), performed_by=user)
    return forecast


def log_action(forecast, action, user, old_data=None, new_data=None):
    ForecastAuditLog.objects.create(forecast=forecast, action=action, old_data=old_data,
                                    new_data=new_data, performed_by=user)
