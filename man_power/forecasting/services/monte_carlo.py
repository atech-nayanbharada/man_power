"""
Monte Carlo simulation of daily FTE requirement (optional step).

Per simulation i:
    volume_i     = max(0, Normal(daily_volume, daily_volume * volume_var%))
    time_i       = max(0, Normal(time_min,     time_min * time_var%))
    workload_i   = volume_i * time_i
    fte_i        = workload_i / productive_minutes_per_fte
    sufficient_i = fte_i <= current_fte
"""
from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np

PERCENTILES = (50, 80, 90, 95, 99)


@dataclass
class MonteCarloResult:
    simulation_count: int
    average_required_fte: float
    minimum_required_fte: float
    maximum_required_fte: float
    standard_deviation: float
    p50_required_fte: float
    p80_required_fte: float
    p90_required_fte: float
    p95_required_fte: float
    p99_required_fte: float
    risk_adjusted_recommended_fte: int
    sufficiency_probability: float
    failure_probability: float
    histogram: dict

    def as_dict(self):
        return asdict(self)


def run_monte_carlo(daily_volume, processing_time_minutes, productive_minutes_per_fte, current_fte,
                    volume_variation_pct, time_variation_pct, simulation_count=10000,
                    seed: Optional[int] = None, histogram_bins=20, return_samples=False):
    daily_volume = float(daily_volume)
    processing_time_minutes = float(processing_time_minutes)
    productive = float(productive_minutes_per_fte)
    current_fte = float(current_fte)
    simulation_count = int(simulation_count)
    if simulation_count <= 0:
        raise ValueError("simulation_count must be positive")
    if productive <= 0:
        raise ValueError("productive_minutes_per_fte must be positive")

    rng = np.random.default_rng(seed)
    volume_sd = daily_volume * float(volume_variation_pct) / 100.0
    time_sd = processing_time_minutes * float(time_variation_pct) / 100.0

    sim_volume = np.clip(rng.normal(daily_volume, volume_sd, simulation_count), 0, None)
    sim_time = np.clip(rng.normal(processing_time_minutes, time_sd, simulation_count), 0, None)
    sim_workload = sim_volume * sim_time
    sim_fte = sim_workload / productive
    sufficient = sim_fte <= current_fte

    pct = np.percentile(sim_fte, PERCENTILES)
    sufficiency = float(sufficient.mean() * 100.0)
    counts, edges = np.histogram(sim_fte, bins=histogram_bins)
    histogram = {
        "labels": [f"{edges[i]:.2f}-{edges[i + 1]:.2f}" for i in range(len(counts))],
        "counts": counts.tolist(),
    }
    result = MonteCarloResult(
        simulation_count=simulation_count,
        average_required_fte=float(sim_fte.mean()),
        minimum_required_fte=float(sim_fte.min()),
        maximum_required_fte=float(sim_fte.max()),
        standard_deviation=float(sim_fte.std(ddof=1)) if simulation_count > 1 else 0.0,
        p50_required_fte=float(pct[0]),
        p80_required_fte=float(pct[1]),
        p90_required_fte=float(pct[2]),
        p95_required_fte=float(pct[3]),
        p99_required_fte=float(pct[4]),
        risk_adjusted_recommended_fte=int(np.ceil(round(float(pct[2]), 6))),
        sufficiency_probability=round(sufficiency, 2),
        failure_probability=round(100.0 - sufficiency, 2),
        histogram=histogram,
    )
    if return_samples:
        return result, {
            "volume": sim_volume, "processing_time": sim_time, "workload_minutes": sim_workload,
            "required_fte": sim_fte, "is_sufficient": sufficient,
        }
    return result
