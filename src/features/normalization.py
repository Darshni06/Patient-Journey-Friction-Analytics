"""
Normalization: percentile clipping + min-max scaling to [0, 1].

Applied identically to the raw Waiting, Rework, and Deviation values before
they're combined into the Friction Score. This uniformity matters: if only
one component were clipped, the weights (1/3, 1/3, 1/3) would no longer be
comparable in effect across components.

Percentile clipping (default 1st/99th) exists specifically because BPIC 2011
raw distributions are skewed (a small number of patients with very long
multi-year multi-DTC histories will have extreme raw Waiting and Rework
values). Without clipping, min-max would compress the rest of the cohort
into a narrow band near 0, destroying the score's discriminative power.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class NormalizationResult:
    normalized: dict[str, float]
    raw_min_after_clip: float
    raw_max_after_clip: float
    lower_bound: float
    upper_bound: float
    n_clipped_low: int
    n_clipped_high: int
    degenerate: bool  # True if all values were equal after clipping


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile, stdlib-only (no numpy dependency
    required for this module so it stays trivially testable)."""
    if not sorted_values:
        raise ValueError("Cannot compute percentile of an empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]

    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    d0 = sorted_values[int(f)] * (c - k)
    d1 = sorted_values[int(c)] * (k - f)
    return d0 + d1


def clip_and_normalize(
    values: dict[str, float],
    lower_percentile: float = 1.0,
    upper_percentile: float = 99.0,
) -> NormalizationResult:
    """
    values: {case_id: raw_value}
    Returns normalized values in [0, 1] plus diagnostics about how many
    points were clipped, and whether the distribution was degenerate
    (all-equal after clipping, which would otherwise cause a division by
    zero) - documented rather than silently handled.
    """
    if not values:
        raise ValueError("Cannot normalize an empty value set")

    sorted_vals = sorted(values.values())
    lo = _percentile(sorted_vals, lower_percentile)
    hi = _percentile(sorted_vals, upper_percentile)
    if hi < lo:
        # Degenerate percentile ordering can only happen with pathologically
        # small n; fail loudly rather than silently swapping bounds.
        raise ValueError(
            f"Computed lower clip bound ({lo}) exceeds upper clip bound ({hi}); "
            "dataset is too small or degenerate for percentile clipping."
        )

    clipped = {k: min(max(v, lo), hi) for k, v in values.items()}
    n_clipped_low = sum(1 for v in values.values() if v < lo)
    n_clipped_high = sum(1 for v in values.values() if v > hi)

    vmin = min(clipped.values())
    vmax = max(clipped.values())

    if vmax == vmin:
        # Every case has the same value after clipping - min-max is
        # undefined. Document this explicitly and return 0.0 for all
        # cases (no discriminative information available) rather than
        # dividing by zero or fabricating spread.
        return NormalizationResult(
            normalized={k: 0.0 for k in clipped},
            raw_min_after_clip=vmin,
            raw_max_after_clip=vmax,
            lower_bound=lo,
            upper_bound=hi,
            n_clipped_low=n_clipped_low,
            n_clipped_high=n_clipped_high,
            degenerate=True,
        )

    normalized = {k: (v - vmin) / (vmax - vmin) for k, v in clipped.items()}

    return NormalizationResult(
        normalized=normalized,
        raw_min_after_clip=vmin,
        raw_max_after_clip=vmax,
        lower_bound=lo,
        upper_bound=hi,
        n_clipped_low=n_clipped_low,
        n_clipped_high=n_clipped_high,
        degenerate=False,
    )
