"""
Manpower status classification, recommendation and explanation.

Rule precedence (first match wins):
  1. Current FTE = 0                                    -> Less Manpower
  2. Current FTE < Required FTE                         -> Less Manpower
  3. MC sufficiency probability < 80%  (only if MC ran) -> Less Manpower
  4. Utilization < 70%                                  -> Higher Manpower
  5. Otherwise                                          -> Sufficient Manpower
     (+ High Utilization Risk flag when utilization > 90%)

When Monte Carlo is switched off, `sufficiency_probability` is None and rule 3 is skipped.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings

from .calculations import ceil_decimal, q, to_decimal

HIGH_UTILIZATION_WARNING = (
    "Current manpower may be sufficient under normal conditions, but the process has a high utilization risk."
)
MC_NOT_RUN_NOTE = (
    "Monte Carlo simulation was not run, so this status is based on the deterministic calculation only."
)


def _thresholds():
    cfg = getattr(settings, "FORECASTING", {})
    return (Decimal(str(cfg.get("SUFFICIENCY_THRESHOLD", 80))),
            Decimal(str(cfg.get("UTILIZATION_LOWER", 70))),
            Decimal(str(cfg.get("UTILIZATION_UPPER", 90))))


@dataclass
class StatusResult:
    status: str
    high_utilization_risk: bool
    recommendation: str
    explanation: str
    warning: str = ""


def classify_status(current_fte, required_fte, utilization, sufficiency_probability=None,
                    p90_fte=None) -> StatusResult:
    threshold, util_lower, util_upper = _thresholds()
    current, required = to_decimal(current_fte), to_decimal(required_fte)
    mc_ran = sufficiency_probability is not None
    prob = to_decimal(sufficiency_probability) if mc_ran else None
    operational = ceil_decimal(required)
    p90_ceiling = ceil_decimal(p90_fte) if (mc_ran and p90_fte is not None) else None
    util_text = f"{q(utilization)}%" if utilization is not None else "not applicable"
    mc_suffix = "" if mc_ran else f" {MC_NOT_RUN_NOTE}"

    if current == 0:
        target = (f"deploy at least {operational} FTE (risk-adjusted P90 requirement: {p90_ceiling} FTE)."
                  if mc_ran else f"deploy at least {operational} FTE.")
        return StatusResult(
            "LESS", False,
            f"Additional manpower is required to manage the forecasted workload. No FTE is currently allocated; {target}",
            f"Current FTE is 0 while the workload requires {q(required)} FTE, so no capacity is available "
            f"and utilization cannot be calculated.{mc_suffix}",
        )

    if current < required:
        if mc_ran:
            rec_tail = f"; plan for {p90_ceiling} FTE in total to cover 90% of simulated workload scenarios."
            exp_tail = (f" Utilization is {util_text}, and the Monte Carlo simulation shows only {q(prob)}% "
                        "probability that current manpower can handle the workload.")
        else:
            rec_tail = f" (operational requirement: {operational} FTE)."
            exp_tail = f" Utilization is {util_text}.{mc_suffix}"
        return StatusResult(
            "LESS", False,
            "Additional manpower is required to manage the forecasted workload. "
            f"Add {q(required - current)} FTE to meet the calculated requirement{rec_tail}",
            f"Current FTE ({q(current)}) is lower than the calculated required FTE ({q(required)}).{exp_tail}",
        )

    if mc_ran and prob < threshold:
        warning = HIGH_UTILIZATION_WARNING if utilization is not None and utilization > util_upper else ""
        return StatusResult(
            "LESS", bool(warning),
            "Additional manpower is required to manage the forecasted workload. Although current FTE covers "
            f"the average workload, increase staffing to {p90_ceiling} FTE (P90 risk-adjusted) to absorb "
            "volume and processing-time variability.",
            f"Current FTE ({q(current)}) covers the calculated requirement ({q(required)}) under average "
            f"conditions, but the Monte Carlo sufficiency probability is {q(prob)}%, below the {q(threshold)}% "
            f"threshold. Utilization is {util_text}.",
            warning,
        )

    if utilization is not None and utilization < util_lower:
        p90_text = f"; the risk-adjusted P90 requirement is {p90_ceiling} FTE" if mc_ran else ""
        prob_text = f" Sufficiency probability is {q(prob)}%." if mc_ran else mc_suffix
        return StatusResult(
            "HIGHER", False,
            "Current manpower is higher than the forecasted requirement. Consider reallocating available capacity. "
            f"Approximately {q(current - required)} FTE is unutilized{p90_text}.",
            f"Current FTE ({q(current)}) exceeds the required FTE ({q(required)}) and utilization is {util_text}, "
            f"below the {q(util_lower)}% lower bound.{prob_text}",
        )

    high_risk = utilization is not None and utilization > util_upper
    band = (f" (above the {q(util_upper)}% upper bound)" if high_risk
            else f" (within the {q(util_lower)}%-{q(util_upper)}% target band)")
    prob_text = (f", and the Monte Carlo sufficiency probability is {q(prob)}% (at or above the "
                 f"{q(threshold)}% threshold)." if mc_ran else f".{mc_suffix}")
    return StatusResult(
        "SUFFICIENT", high_risk,
        "Current manpower is sufficient for the expected workload."
        + (" Monitor closely because utilization is above the target band." if high_risk else ""),
        f"Current FTE ({q(current)}) is equal to or higher than the required FTE ({q(required)}), utilization is "
        f"{util_text}{band}{prob_text}",
        HIGH_UTILIZATION_WARNING if high_risk else "",
    )
