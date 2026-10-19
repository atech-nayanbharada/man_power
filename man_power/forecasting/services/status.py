"""
Manpower status classification, recommendation and explanation.

Rule precedence (first match wins):
  1. Current FTE = 0                                    -> Less Manpower
  2. Current FTE < Required FTE (exact workload)        -> Less Manpower
  3. MC sufficiency probability < 80%  (only if MC ran) -> Less Manpower
  4. Utilization < 70%                                  -> Higher Manpower
  5. Otherwise                                          -> Sufficient Manpower (+ High Utilization Risk > 90%)

Current FTE is shown as entered (e.g. 2.5 FTE); required headcount is shown in whole people (rounded up).
"""
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings

from .calculations import ceil_decimal, fmt, q, to_decimal

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


def people(value) -> str:
    return f"{int(ceil_decimal(value))} FTE"


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
    needed = ceil_decimal(required)
    p90_ceiling = ceil_decimal(p90_fte) if (mc_ran and p90_fte is not None) else None
    current_txt = f"{fmt(current)} FTE"
    util_text = f"{q(utilization)}%" if utilization is not None else "not applicable"
    mc_suffix = "" if mc_ran else f" {MC_NOT_RUN_NOTE}"

    if current == 0:
        target = (f"deploy at least {people(needed)} ({people(p90_ceiling)} to cover 90% of simulated days)."
                  if mc_ran else f"deploy at least {people(needed)}.")
        return StatusResult(
            "LESS", False,
            f"Additional manpower is required to manage the forecasted workload. No FTE is currently allocated; {target}",
            f"Current FTE is 0 while the workload requires {people(needed)}, so no capacity is available "
            f"and utilization cannot be calculated.{mc_suffix}",
        )

    if current < required:
        add = needed - current
        if mc_ran:
            rec_tail = f" Plan for {people(p90_ceiling)} in total to cover 90% of simulated workload scenarios."
            exp_tail = (f" Utilization is {util_text}, and the Monte Carlo simulation shows only {q(prob)}% "
                        "probability that current manpower can handle the workload.")
        else:
            rec_tail = ""
            exp_tail = f" Utilization is {util_text}.{mc_suffix}"
        return StatusResult(
            "LESS", False,
            f"Additional manpower is required to manage the forecasted workload. Add {fmt(add)} FTE "
            f"(requirement: {people(needed)}).{rec_tail}",
            f"Current FTE ({current_txt}) is lower than the workload of {fmt(required)} FTE "
            f"({people(needed)} rounded up).{exp_tail}",
        )

    if mc_ran and prob < threshold:
        warning = HIGH_UTILIZATION_WARNING if utilization is not None and utilization > util_upper else ""
        return StatusResult(
            "LESS", bool(warning),
            "Additional manpower is required to manage the forecasted workload. Although current FTE covers "
            f"the average workload, increase staffing to {people(p90_ceiling)} (P90 risk-adjusted) to absorb "
            "volume and AHT variability.",
            f"Current FTE ({current_txt}) covers the average workload of {fmt(required)} FTE, but the Monte Carlo "
            f"sufficiency probability is {q(prob)}%, below the {q(threshold)}% threshold. Utilization is {util_text}.",
            warning,
        )

    if utilization is not None and utilization < util_lower:
        spare = current - needed
        spare_text = (f"About {fmt(spare)} FTE can be reallocated" if spare >= 1
                      else f"About {fmt(current - required)} FTE of capacity is unused")
        p90_text = f"; the risk-adjusted P90 requirement is {people(p90_ceiling)}" if mc_ran else ""
        prob_text = f" Sufficiency probability is {q(prob)}%." if mc_ran else mc_suffix
        return StatusResult(
            "HIGHER", False,
            "Current manpower is higher than the forecasted requirement. Consider reallocating available capacity. "
            f"{spare_text}{p90_text}.",
            f"Current FTE ({current_txt}) exceeds the workload of {fmt(required)} FTE and utilization is {util_text}, "
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
        f"Current FTE ({current_txt}) covers the workload of {fmt(required)} FTE, utilization is "
        f"{util_text}{band}{prob_text}",
        HIGH_UTILIZATION_WARNING if high_risk else "",
    )
