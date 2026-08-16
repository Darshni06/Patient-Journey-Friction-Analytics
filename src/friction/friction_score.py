"""
Friction Score engine.

    F_p = w_W * W_p + w_R * R_p + w_D * D_p,   w_W = w_R = w_D = 1/3

W_p, R_p, D_p are the already-normalized (percentile-clipped, min-max
scaled to [0,1]) Waiting, Rework, and Deviation components for case p.
This module does not compute the raw components - see features/waiting.py,
features/rework.py, and process_mining/conformance.py for those. It only
combines already-normalized inputs and runs the required diagnostic checks.

REQUIRED V1 VALIDITY CHECK (elevated from an optional Phase-2 experiment
during the methodology review, see DEVIATIONS_FROM_PROMPT.md point 8):
before any composite-score interpretation is reported, the pairwise Pearson
correlation between the RAW (pre-normalization) W, R, D values must be
computed and reported. If the three components are strongly collinear, the
central research claim - that the composite reveals more than any single
dimension - is weaker than presented, and this must be stated honestly
rather than glossed over.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


DEFAULT_WEIGHTS = (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)


@dataclass
class FrictionComponents:
    case_id: str
    waiting_norm: float
    rework_norm: float
    deviation_norm: float


@dataclass
class FrictionResult:
    case_id: str
    waiting_norm: float
    rework_norm: float
    deviation_norm: float
    friction_score: float
    dominant_component: str  # "waiting" | "rework" | "deviation"


def compute_friction_score(
    waiting_norm: float,
    rework_norm: float,
    deviation_norm: float,
    weights: tuple[float, float, float] = DEFAULT_WEIGHTS,
) -> float:
    for name, v in (("waiting_norm", waiting_norm), ("rework_norm", rework_norm), ("deviation_norm", deviation_norm)):
        if not (0.0 <= v <= 1.0 + 1e-9):
            raise ValueError(f"{name}={v} is outside the expected [0, 1] normalized range")

    w_w, w_r, w_d = weights
    if not math.isclose(w_w + w_r + w_d, 1.0, rel_tol=1e-9):
        raise ValueError(f"Weights must sum to 1.0, got {w_w + w_r + w_d}")

    return w_w * waiting_norm + w_r * rework_norm + w_d * deviation_norm


def compute_case_friction(
    components: FrictionComponents,
    weights: tuple[float, float, float] = DEFAULT_WEIGHTS,
) -> FrictionResult:
    score = compute_friction_score(
        components.waiting_norm, components.rework_norm, components.deviation_norm, weights
    )
    contributions = {
        "waiting": components.waiting_norm,
        "rework": components.rework_norm,
        "deviation": components.deviation_norm,
    }
    dominant = max(contributions, key=contributions.get)

    return FrictionResult(
        case_id=components.case_id,
        waiting_norm=components.waiting_norm,
        rework_norm=components.rework_norm,
        deviation_norm=components.deviation_norm,
        friction_score=score,
        dominant_component=dominant,
    )


def compute_friction_for_all_cases(
    components_by_case: dict[str, FrictionComponents],
    weights: tuple[float, float, float] = DEFAULT_WEIGHTS,
) -> dict[str, FrictionResult]:
    return {cid: compute_case_friction(c, weights) for cid, c in components_by_case.items()}


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _pearson_correlation(xs: list[float], ys: list[float]) -> float:
    """Stdlib-only Pearson correlation coefficient, kept dependency-free so
    this diagnostic can run even before numpy/pandas are available."""
    if len(xs) != len(ys):
        raise ValueError("xs and ys must be the same length")
    n = len(xs)
    if n < 2:
        raise ValueError("Need at least 2 data points to compute correlation")

    mx, my = _mean(xs), _mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    var_x = sum((x - mx) ** 2 for x in xs)
    var_y = sum((y - my) ** 2 for y in ys)

    denom = math.sqrt(var_x * var_y)
    if denom == 0:
        # No variance in one of the series - correlation is undefined, not 0.
        return float("nan")
    return cov / denom


@dataclass
class CorrelationDiagnostic:
    corr_waiting_rework: float
    corr_waiting_deviation: float
    corr_rework_deviation: float
    n_cases: int
    warning: str | None = None


def compute_component_correlation_diagnostic(
    raw_waiting: dict[str, float],
    raw_rework: dict[str, float],
    raw_deviation: dict[str, float],
    collinearity_warning_threshold: float = 0.7,
) -> CorrelationDiagnostic:
    """
    Computes pairwise correlation between the RAW (pre-normalization) W, R, D
    values across all cases. This is the required V1 validity check - it
    must be run and its result included in the report BEFORE presenting any
    "the composite reveals more than waiting alone" claim.
    """
    common_ids = sorted(set(raw_waiting) & set(raw_rework) & set(raw_deviation))
    if len(common_ids) < 2:
        raise ValueError("Need at least 2 cases with all three components present")

    w = [raw_waiting[cid] for cid in common_ids]
    r = [raw_rework[cid] for cid in common_ids]
    d = [raw_deviation[cid] for cid in common_ids]

    corr_wr = _pearson_correlation(w, r)
    corr_wd = _pearson_correlation(w, d)
    corr_rd = _pearson_correlation(r, d)

    max_abs_corr = max(
        abs(c) for c in (corr_wr, corr_wd, corr_rd) if not math.isnan(c)
    ) if any(not math.isnan(c) for c in (corr_wr, corr_wd, corr_rd)) else 0.0

    warning = None
    if max_abs_corr >= collinearity_warning_threshold:
        warning = (
            f"At least one pairwise correlation reaches {max_abs_corr:.2f}, "
            f">= threshold {collinearity_warning_threshold}. The three "
            "components may be substantially driven by a common latent "
            "factor (e.g. overall journey size/length) rather than being "
            "independent dimensions of friction. This weakens - but does "
            "not by itself invalidate - the claim that the composite score "
            "adds information beyond any single component. Report this "
            "explicitly rather than omitting it."
        )

    return CorrelationDiagnostic(
        corr_waiting_rework=corr_wr,
        corr_waiting_deviation=corr_wd,
        corr_rework_deviation=corr_rd,
        n_cases=len(common_ids),
        warning=warning,
    )
