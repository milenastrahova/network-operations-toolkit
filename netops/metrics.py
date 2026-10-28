"""Explicitly scoped measurement metrics (do not conflate TCP connect with RTT)."""
from __future__ import annotations
import math
from statistics import mean


def percentile(values: list[float], percentage: float) -> float | None:
    """Nearest rank for percentiles: ceil(p*N/100), with p=0 choosing first."""
    if not values:
        return None
    if not 0 <= percentage <= 100:
        raise ValueError("percentage must be in [0,100]")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentage / 100 * len(ordered)))
    return ordered[rank-1]


def summary(values: list[float]) -> dict:
    """Values must already have the intended unit; empty values return null metrics."""
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("measurements must be finite and nonnegative")
    return {"count": len(values), "min": min(values) if values else None,
            "mean": mean(values) if values else None,
            "p50": percentile(values, 50), "p95": percentile(values, 95),
            "p99": percentile(values, 99), "max": max(values) if values else None}


def variation(values: list[float]) -> dict:
    """Absolute consecutive-difference proxy; not RFC 3550 interarrival jitter."""
    diffs = [abs(b-a) for a, b in zip(values, values[1:])]
    return {"definition": "absolute_consecutive_difference", **summary(diffs)}
