"""
Traffic pattern analysis: coefficient of variation, daily autocorrelation,
and pattern classification from Prometheus time-series data.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class PatternResult:
    cov: float                    # coefficient of variation (stddev/mean)
    mean: float
    peak: float
    baseline: float
    peak_to_baseline_ratio: float
    daily_pattern: bool           # True if 24h autocorrelation is strong
    classification: str           # steady | moderate_burst | predictable_peak | spike_prone
    scale_event_count: int = 0    # HPA scale events in observation window
    oom_kill_count: int = 0


def coefficient_of_variation(values: Sequence[float]) -> float:
    """Standard deviation / mean. Returns 0.0 for empty or zero-mean series."""
    if not values:
        return 0.0
    n = len(values)
    mean = sum(values) / n
    if mean == 0:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / n
    return math.sqrt(variance) / mean


def daily_autocorrelation(
    values: Sequence[float],
    step_minutes: int = 5,
) -> float:
    """
    Pearson correlation between the series and a 24h-lagged version of itself.
    Returns a value in [-1, 1]. Values > 0.5 suggest a strong daily pattern.
    """
    lag = int(24 * 60 / step_minutes)
    if len(values) <= lag:
        return 0.0

    x = list(values[:-lag])
    y = list(values[lag:])
    n = len(x)
    if n < 2:
        return 0.0

    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    denom_x = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    denom_y = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if denom_x * denom_y == 0:
        return 0.0
    return num / (denom_x * denom_y)


def classify_pattern(
    values: Sequence[float],
    step_minutes: int = 5,
    scale_events: int = 0,
    oom_kills: int = 0,
) -> PatternResult:
    """
    Classify a metric time series into a traffic pattern category.

    Classification rules (from ARCHITECTURE.md):
      CoV < 0.2                          → steady
      CoV 0.2–0.5, strong daily pattern  → predictable_peak
      CoV 0.2–0.5, no daily pattern      → moderate_burst
      CoV > 0.5                          → spike_prone
    """
    if not values:
        return PatternResult(
            cov=0.0, mean=0.0, peak=0.0, baseline=0.0,
            peak_to_baseline_ratio=1.0, daily_pattern=False,
            classification="unknown",
            scale_event_count=scale_events,
            oom_kill_count=oom_kills,
        )

    sorted_vals = sorted(values)
    mean = sum(values) / len(values)
    peak = sorted_vals[int(0.95 * len(sorted_vals))]  # p95 as peak
    baseline = sorted_vals[int(0.05 * len(sorted_vals))]  # p5 as baseline
    cov = coefficient_of_variation(values)
    autocorr = daily_autocorrelation(values, step_minutes)
    strong_daily = autocorr > 0.5

    if cov < 0.2:
        classification = "steady"
    elif cov <= 0.5 and strong_daily:
        classification = "predictable_peak"
    elif cov <= 0.5:
        classification = "moderate_burst"
    else:
        classification = "spike_prone"

    ratio = (peak / baseline) if baseline > 0 else 1.0

    return PatternResult(
        cov=round(cov, 3),
        mean=round(mean, 3),
        peak=round(peak, 3),
        baseline=round(baseline, 3),
        peak_to_baseline_ratio=round(ratio, 2),
        daily_pattern=strong_daily,
        classification=classification,
        scale_event_count=scale_events,
        oom_kill_count=oom_kills,
    )


def parse_prometheus_matrix(result: list[dict]) -> list[float]:
    """
    Flatten a Prometheus range query result (matrix type) into a list of float values.
    Expects result items to have 'values': [[timestamp, value_str], ...].
    """
    out: list[float] = []
    for item in result:
        for _ts, val in item.get("values", []):
            try:
                out.append(float(val))
            except (ValueError, TypeError):
                pass
    return out
