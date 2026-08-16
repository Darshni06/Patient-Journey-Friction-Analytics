"""
Process discovery: reference process model for pathway deviation.

Locked methodology (see DEVIATIONS_FROM_PROMPT.md point 3):
- Grouping field is org:group (NOT Section - rejected: 68% of events sit in
  one Section value, plus a confirmed typo "Sectoin 7").
- 624 raw concept:name activities is too high-cardinality for Inductive
  Miner to produce a readable model. org:group has 42 distinct values, still
  a long tail (~30 departments with <100 events each in the real file).
- Departments are kept individually until they cumulatively cover
  `coverage_threshold` (default 0.95) of all events; the remainder is
  collapsed into "Other department". This is a DERIVED rule, not a
  hard-coded "top 10-12" - the master prompt's literal "top 10-12" was a
  loose estimate from before the coverage math was worked out, and this
  threshold rule supersedes it (it will land near 10-12 in practice, but is
  reproducible rather than eyeballed).

The actual pm4py Inductive Miner call lives in `discover_process_model()`
at the bottom - it requires pm4py + a pandas/Spark event log DataFrame and
is not unit-testable without those dependencies installed, so the
department-collapsing logic above it is deliberately isolated and
dependency-free for direct testing.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


DEFAULT_OTHER_LABEL = "Other department"
DEFAULT_COVERAGE_THRESHOLD = 0.95


@dataclass
class DepartmentCollapseResult:
    kept_departments: set[str]
    collapsed_departments: set[str]
    cumulative_coverage_at_cutoff: float
    total_events: int


def compute_department_collapse(
    org_group_counts: dict[str, int],
    coverage_threshold: float = DEFAULT_COVERAGE_THRESHOLD,
) -> DepartmentCollapseResult:
    """
    org_group_counts: {department_name: event_count} across the WHOLE
    dataset (not per case). Departments are ranked by frequency; the
    smallest set of top departments whose cumulative share reaches
    `coverage_threshold` is kept individually.
    """
    if not org_group_counts:
        raise ValueError("org_group_counts must not be empty")
    if not (0.0 < coverage_threshold <= 1.0):
        raise ValueError("coverage_threshold must be in (0, 1]")

    total = sum(org_group_counts.values())
    ranked = sorted(org_group_counts.items(), key=lambda kv: -kv[1])

    kept: set[str] = set()
    cumulative = 0
    cumulative_fraction = 0.0
    for name, count in ranked:
        kept.add(name)
        cumulative += count
        cumulative_fraction = cumulative / total
        if cumulative_fraction >= coverage_threshold:
            break

    collapsed = set(org_group_counts.keys()) - kept

    return DepartmentCollapseResult(
        kept_departments=kept,
        collapsed_departments=collapsed,
        cumulative_coverage_at_cutoff=cumulative_fraction,
        total_events=total,
    )


def apply_department_collapse(
    org_group_value: str,
    collapse_result: DepartmentCollapseResult,
    other_label: str = DEFAULT_OTHER_LABEL,
) -> str:
    """Maps a raw org:group value to itself (if kept) or the "Other
    department" bucket (if collapsed). Used as a row-level transform before
    process discovery, applied consistently at both training/discovery time
    and at conformance-checking time."""
    return org_group_value if org_group_value in collapse_result.kept_departments else other_label


def build_department_alphabet(activities_with_org_group: list[str]) -> Counter:
    """Simple frequency counter helper, kept trivial and dependency-free so
    it can be unit tested without Spark."""
    return Counter(activities_with_org_group)


# -----------------------------------------------------------------------
# pm4py-dependent discovery call. Requires: pip install pm4py
# Not unit-tested directly (would require pm4py + a real/synthetic event
# log); exercised via an integration test only if pm4py is available.
# -----------------------------------------------------------------------
TIMESTAMP_COLUMN = "time:timestamp"


def ensure_pm4py_timestamp_dtype(event_log_df, timestamp_col: str = TIMESTAMP_COLUMN):
    """
    Guarantees `event_log_df[timestamp_col]` is an actual pandas datetime64
    dtype column before handing the DataFrame to pm4py.

    Why this is needed: constructing a pandas DataFrame directly from a list
    of row-dicts containing Python `datetime.datetime` objects does not
    reliably yield a `datetime64` dtype column - if the objects carry
    (consistent or inconsistent) tzinfo, pandas can leave the column as
    generic `object` dtype instead of inferring `datetime64[ns, tz]`. pm4py's
    `discover_petri_net_inductive` explicitly checks for a real date/datetime
    dtype and raises "the dataframe should (at least) contain a column of
    type date" when it isn't one - this is exactly the error hit when running
    the real pipeline.

    This function is defensive: it explicitly coerces the column via
    `pd.to_datetime(..., errors="coerce")`, normalizes timezone handling so
    every value ends up as a single consistent tz-aware dtype (UTC) rather
    than a column of mixed/uncomparable tz offsets, and validates that no
    values became null (NaT) as a result of coercion - if any did, it raises
    with an exact count and example values rather than silently discovering
    a process model over a partially-corrupted timestamp column.
    """
    import pandas as pd

    if timestamp_col not in event_log_df.columns:
        raise ValueError(f"Expected timestamp column '{timestamp_col}' not found in event log dataframe")

    df = event_log_df.copy()

    original_non_null = df[timestamp_col].notna().sum()

    # utc=True normalizes any mix of naive/tz-aware or differently-offset
    # timestamps onto a single consistent UTC dtype, which is what pm4py's
    # dtype check expects - it does not accept an `object` column even if
    # every element happens to already be a `datetime.datetime`.
    df[timestamp_col] = pd.to_datetime(df[timestamp_col], errors="coerce", utc=True)

    if not pd.api.types.is_datetime64_any_dtype(df[timestamp_col]):
        raise TypeError(
            f"Column '{timestamp_col}' could not be coerced to a pandas datetime64 "
            f"dtype (got {df[timestamp_col].dtype} instead)."
        )

    n_null_after = df[timestamp_col].isna().sum()
    if n_null_after > 0:
        n_became_null = n_null_after - (len(df) - original_non_null)
        example_bad_rows = event_log_df.loc[df[timestamp_col].isna(), timestamp_col].head(5).tolist()
        raise ValueError(
            f"{n_null_after} row(s) have a null/unparseable '{timestamp_col}' after "
            f"coercion to datetime ({n_became_null} became null during coercion, "
            f"the rest were already null). Process discovery requires every row to "
            f"have a valid timestamp. Example offending values: {example_bad_rows}. "
            f"These rows must be filtered out upstream (e.g. during cleaning) rather "
            f"than silently dropped here."
        )

    return df


def discover_process_model(event_log_df, noise_threshold: float = 0.2):
    """
    event_log_df: a pandas DataFrame with at least columns
        ['case:concept:name', 'concept:name', 'time:timestamp']
    where 'concept:name' here is expected to already be the COLLAPSED
    org:group value (i.e. apply_department_collapse has already been run
    upstream), not the raw 624-value activity field.

    The 'time:timestamp' column is explicitly validated/coerced to a real
    pandas datetime64 dtype (see ensure_pm4py_timestamp_dtype) before being
    handed to pm4py, since pm4py requires an actual date/datetime dtype and
    raises otherwise.

    Returns a pm4py Petri net (net, initial_marking, final_marking) discovered
    via the Inductive Miner (infrequent variant, given the noise threshold).
    """
    import pm4py

    event_log_df = ensure_pm4py_timestamp_dtype(event_log_df, TIMESTAMP_COLUMN)

    net, initial_marking, final_marking = pm4py.discover_petri_net_inductive(
        event_log_df, noise_threshold=noise_threshold
    )
    return net, initial_marking, final_marking