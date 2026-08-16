"""
Conformance checking: raw Pathway Deviation (D_p, pre-normalization).

Locked methodology (unchanged): alignment-based conformance checking against
the Inductive-Miner-discovered department-level process model, "with
token-based replay as the documented fallback if alignments are too slow at
full scale" - that exact contingency is what this module now implements
concretely, because it was hit on real hardware (12/914 variants completed
in ~30 minutes on a laptop, which overheated). This is the fallback the
methodology already anticipated, not a new methodology.

Two efficiency changes were made, neither of which changes what Deviation
*means* for any given case - a case's D_p is still "the conformance cost of
its exact department-level activity sequence against the discovered model":

1. VARIANT-LEVEL CACHING: two cases with the exact same department-level
   activity sequence (the same "variant") necessarily get the exact same
   alignment cost - alignment only depends on the sequence, not on which
   case it came from. So each distinct variant is aligned ONCE and the cost
   is reused for every case sharing it, instead of recomputing identical
   work per case. (In the real dataset this alone only saves ~20% of the
   work - 1,143 cases across 914 variants - so it is necessary but not
   sufficient on its own; see point 2.)

2. TIME-BUDGETED FALLBACK, applied to the WHOLE dataset at once: alignment
   is attempted variant-by-variant with a running wall-clock budget
   (`alignment_time_budget_seconds`, configurable). If the budget is
   exhausted before every distinct variant has been aligned, ALL partial
   alignment results are discarded and Deviation is recomputed for EVERY
   case using token-based replay instead. This "all-or-nothing" switch is
   deliberate: mixing alignment costs and token-replay costs within the
   same normalized D_p column would make the two cost scales
   non-comparable across cases, which would silently corrupt the min-max
   normalization in src/features/normalization.py. Every case in a given
   run always gets its D_p from the SAME method, and which method that was
   is always reported (see ConformanceRunReport / run_pipeline.py Phase 7b).

Configuration (configs/config.yaml, process_discovery section):
  conformance_method: "alignments" | "token_based_replay" | "auto" (default)
  alignment_time_budget_seconds: wall-clock budget for the "auto"/"alignments"
    attempt before falling back (or raising, for "alignments").

This module is a thin wrapper around pm4py's conformance functions. The
interesting engineering logic (variant grouping, budget tracking, turning
alignment/replay results into a clean {case_id: raw_deviation_cost}
mapping) is kept here and is unit-testable given fake pm4py-shaped result
objects / a synthetic pandas DataFrame, without requiring pm4py itself to
be installed for that part of the test suite.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class DeviationResult:
    case_id: str
    raw_deviation_cost: float
    method: str  # "alignments" | "token_based_replay"


@dataclass
class ConformanceRunReport:
    """What the pipeline prints/records so the final report can state,
    unambiguously, which conformance method was actually used - this is
    exactly what's needed to satisfy "the final report must clearly state
    which conformance method was actually used and whether alignment or
    the documented fallback was used"."""

    method_used: str  # "alignments" | "token_based_replay"
    requested_method: str  # what config.yaml asked for
    n_cases: int
    n_variants: int
    n_variants_completed_via_alignment: int
    elapsed_seconds: float
    fallback_triggered: bool
    fallback_reason: str | None = None


def extract_deviation_from_alignments(alignment_results: list[dict], case_ids: list[str]) -> dict[str, DeviationResult]:
    """
    alignment_results: pm4py's `pm4py.conformance_diagnostics_alignments()`
    output - a list of per-trace dicts, each containing (among other keys)
    'cost' (an integer alignment cost) in the same order as case_ids.
    """
    if len(alignment_results) != len(case_ids):
        raise ValueError("alignment_results and case_ids must be the same length and order")

    out = {}
    for cid, result in zip(case_ids, alignment_results):
        cost = result.get("cost")
        if cost is None:
            raise ValueError(f"Alignment result for case {cid} is missing a 'cost' field")
        out[cid] = DeviationResult(case_id=cid, raw_deviation_cost=float(cost), method="alignments")
    return out


def extract_deviation_from_token_replay(replay_results: list[dict], case_ids: list[str]) -> dict[str, DeviationResult]:
    """
    replay_results: pm4py's token-based-replay output - a list of per-trace
    dicts containing 'missing_tokens' and 'remaining_tokens' (among others).
    Used as the deviation proxy: missing_tokens + remaining_tokens, a
    standard token-replay-based nonconformance measure.
    """
    if len(replay_results) != len(case_ids):
        raise ValueError("replay_results and case_ids must be the same length and order")

    out = {}
    for cid, result in zip(case_ids, replay_results):
        missing = result.get("missing_tokens")
        remaining = result.get("remaining_tokens")
        if missing is None or remaining is None:
            raise ValueError(f"Replay result for case {cid} is missing token count fields")
        out[cid] = DeviationResult(
            case_id=cid, raw_deviation_cost=float(missing + remaining), method="token_based_replay"
        )
    return out


# -----------------------------------------------------------------------
# Pure-logic variant computation (pandas only, no pm4py) - unit-testable
# without pm4py installed.
# -----------------------------------------------------------------------
def build_case_activity_sequences(event_log_df) -> dict[str, list[str]]:
    """
    Groups the (already department-collapsed) event log dataframe by case
    and returns each case's activity sequence in chronological order, using
    the 'case:concept:name' / 'concept:name' / 'time:timestamp' columns as
    produced by discovery.discover_process_model's input contract.

    Pure pandas, no pm4py dependency - this is what makes variant grouping
    unit-testable without pm4py installed.
    """
    df = event_log_df.sort_values("time:timestamp")
    sequences: dict[str, list[str]] = {}
    for case_id, group in df.groupby("case:concept:name"):
        sequences[case_id] = list(group["concept:name"])
    return sequences


def compute_case_variants(case_activity_sequences: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
    """Each case's variant is just its activity sequence as a hashable tuple."""
    return {cid: tuple(seq) for cid, seq in case_activity_sequences.items()}


def group_cases_by_variant(case_variants: dict[str, tuple[str, ...]]) -> dict[tuple[str, ...], list[str]]:
    groups: dict[tuple[str, ...], list[str]] = {}
    for cid, variant in case_variants.items():
        groups.setdefault(variant, []).append(cid)
    return groups


# -----------------------------------------------------------------------
# pm4py-dependent conformance calls. Requires: pip install pm4py
# -----------------------------------------------------------------------
def run_alignment_conformance(event_log_df, net, initial_marking, final_marking):
    """event_log_df must use the department-collapsed activity labels, same
    as discovery.discover_process_model's input contract."""
    import pm4py

    return pm4py.conformance_diagnostics_alignments(event_log_df, net, initial_marking, final_marking)


def run_token_replay_conformance(event_log_df, net, initial_marking, final_marking):
    import pm4py

    return pm4py.conformance_diagnostics_token_based_replay(event_log_df, net, initial_marking, final_marking)


def _align_single_variant(variant: tuple[str, ...], net, initial_marking, final_marking) -> float:
    """
    Builds a minimal single-trace event log representing one distinct
    variant and returns its alignment cost. Timestamps here are synthetic
    (evenly spaced, arbitrary start) - alignment cost depends only on the
    activity SEQUENCE, never on wall-clock timestamp values, so this does
    not change what is being measured; it only avoids re-deriving a
    variant's real timestamps, which are irrelevant to this computation and
    differ per case anyway (that's exactly why many cases share one
    variant).
    """
    import pandas as pd
    import pm4py

    from src.process_mining.discovery import ensure_pm4py_timestamp_dtype

    rows = [
        {
            "case:concept:name": "variant",
            "concept:name": activity,
            "time:timestamp": pd.Timestamp("2000-01-01") + pd.Timedelta(seconds=i),
        }
        for i, activity in enumerate(variant)
    ]
    df = pd.DataFrame(rows)
    df = ensure_pm4py_timestamp_dtype(df, "time:timestamp")

    results = pm4py.conformance_diagnostics_alignments(df, net, initial_marking, final_marking)
    if not results:
        raise ValueError(f"Alignment returned no result for variant of length {len(variant)}")
    cost = results[0].get("cost")
    if cost is None:
        raise ValueError(f"Alignment result missing 'cost' field for variant of length {len(variant)}")
    return float(cost)


def _compute_deviation_token_replay_all_cases(event_log_df, net, initial_marking, final_marking) -> dict[str, float]:
    import pm4py

    log = pm4py.convert_to_event_log(event_log_df)
    case_ids = [trace.attributes["concept:name"] for trace in log]

    replay_results = run_token_replay_conformance(log, net, initial_marking, final_marking)
    deviation_results = extract_deviation_from_token_replay(replay_results, case_ids)
    return {cid: r.raw_deviation_cost for cid, r in deviation_results.items()}


def compute_deviation_for_dataset(
    event_log_df,
    net,
    initial_marking,
    final_marking,
    conformance_method: str = "auto",
    alignment_time_budget_seconds: float = 300.0,
) -> tuple[dict[str, float], ConformanceRunReport]:
    """
    Computes raw Pathway Deviation cost per case for the WHOLE dataset.

    conformance_method:
      "alignments"         - alignment-based only, with variant-level
                              caching. If the time budget is exceeded before
                              every distinct variant is processed, raises
                              TimeoutError rather than silently switching
                              method - use "auto" to allow the documented
                              fallback.
      "token_based_replay"  - skip alignments entirely; every case's D_p
                              comes from token-based replay. Fast and safe
                              on constrained hardware; use this directly if
                              you already know alignments won't finish.
      "auto" (default)      - attempt alignment-based conformance with
                              variant-level caching, budget-limited. If the
                              budget runs out before finishing every
                              variant, ALL partial alignment results are
                              discarded and the ENTIRE dataset is instead
                              scored with token-based replay, so every
                              case's D_p always comes from the same method.

    Returns (raw_deviation_by_case, ConformanceRunReport). The report is
    exactly what the pipeline prints/records to state which method was
    ACTUALLY used - see run_pipeline.py Phase 7b.
    """
    if conformance_method not in ("alignments", "token_based_replay", "auto"):
        raise ValueError(
            f"Unknown conformance_method '{conformance_method}'; expected "
            f"'alignments', 'token_based_replay', or 'auto'"
        )

    case_activity_sequences = build_case_activity_sequences(event_log_df)
    n_cases = len(case_activity_sequences)
    variants = group_cases_by_variant(compute_case_variants(case_activity_sequences))
    n_variants = len(variants)

    if conformance_method == "token_based_replay":
        raw_deviation = _compute_deviation_token_replay_all_cases(event_log_df, net, initial_marking, final_marking)
        return raw_deviation, ConformanceRunReport(
            method_used="token_based_replay",
            requested_method=conformance_method,
            n_cases=n_cases,
            n_variants=n_variants,
            n_variants_completed_via_alignment=0,
            elapsed_seconds=0.0,
            fallback_triggered=False,
        )

    # "alignments" or "auto": attempt variant-level alignment within budget.
    variant_costs: dict[tuple[str, ...], float] = {}
    start = time.monotonic()
    n_completed = 0
    budget_exceeded = False

    for variant in variants:
        if (time.monotonic() - start) >= alignment_time_budget_seconds:
            budget_exceeded = True
            break
        variant_costs[variant] = _align_single_variant(variant, net, initial_marking, final_marking)
        n_completed += 1

    elapsed_total = time.monotonic() - start

    if budget_exceeded or n_completed < n_variants:
        reason = (
            f"Alignment-based conformance exceeded the {alignment_time_budget_seconds:.0f}s time "
            f"budget after completing {n_completed}/{n_variants} distinct variants "
            f"({elapsed_total:.1f}s elapsed)."
        )
        if conformance_method == "alignments":
            raise TimeoutError(
                reason + " conformance_method='alignments' does not allow a fallback - set "
                "process_discovery.conformance_method to 'auto' (recommended) or "
                "'token_based_replay' in config.yaml to complete on this hardware."
            )
        # auto: discard partial alignment results, recompute the WHOLE
        # dataset with token-based replay for consistency.
        raw_deviation = _compute_deviation_token_replay_all_cases(event_log_df, net, initial_marking, final_marking)
        return raw_deviation, ConformanceRunReport(
            method_used="token_based_replay",
            requested_method=conformance_method,
            n_cases=n_cases,
            n_variants=n_variants,
            n_variants_completed_via_alignment=n_completed,
            elapsed_seconds=elapsed_total,
            fallback_triggered=True,
            fallback_reason=reason,
        )

    # All variants aligned within budget - expand back out to every case.
    raw_deviation = {
        cid: variant_costs[variant] for variant, case_ids in variants.items() for cid in case_ids
    }
    return raw_deviation, ConformanceRunReport(
        method_used="alignments",
        requested_method=conformance_method,
        n_cases=n_cases,
        n_variants=n_variants,
        n_variants_completed_via_alignment=n_completed,
        elapsed_seconds=elapsed_total,
        fallback_triggered=False,
    )