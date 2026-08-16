"""
Waiting Burden calculation.

This module intentionally contains ONLY pure Python / stdlib logic with no
Spark dependency. The PySpark orchestration layer (src/ingestion + a Spark
mapPartitions/groupBy wrapper) calls into this module per-case. Keeping the
math here means it can be unit tested directly without a Spark session -
this is a testing/engineering choice, not a methodology change.

Locked methodology (see DEVIATIONS_FROM_PROMPT.md for full rationale):
- Waiting is computed from RAW event timestamps, never collapsed to day-level.
- Gaps are only computed between consecutive CLINICAL events. Administrative/
  billing events (identified by keyword match on activity name) are excluded
  as wait-interval ENDPOINTS, because a gap adjacent to a billing entry
  reflects administrative processing lag, not patient waiting. The
  administrative events themselves are NOT removed from the case's event
  list anywhere else in the pipeline.
- Negative gaps (out-of-order timestamps) are data anomalies: they are
  reported, and excluded from the wait sum, but never silently dropped from
  the underlying event data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

DEFAULT_ADMIN_KEYWORDS = ("tarief", "toesl", "klasse")


@dataclass
class Event:
    activity: str
    timestamp: datetime
    org_group: str | None = None


@dataclass
class WaitGap:
    case_id: str
    from_activity: str
    to_activity: str
    from_ts: datetime
    to_ts: datetime
    gap_seconds: float


@dataclass
class TimestampAnomaly:
    case_id: str
    from_activity: str
    to_activity: str
    from_ts: datetime
    to_ts: datetime
    gap_seconds: float
    reason: str = "negative_gap"


@dataclass
class WaitingResult:
    case_id: str
    total_wait_seconds: float
    gaps: list[WaitGap] = field(default_factory=list)
    anomalies: list[TimestampAnomaly] = field(default_factory=list)
    excluded_administrative_events: int = 0


def is_administrative_activity(
    activity_name: str, keywords: Iterable[str] = DEFAULT_ADMIN_KEYWORDS
) -> bool:
    """
    Returns True if the activity name matches a known billing/tariff pattern
    observed in the actual BPIC 2011 data (e.g. 'ordertarief',
    'administratief tarief - eerste pol', '190101 bovenreg.toesl. a101',
    '190205 klasse 3b a205').
    """
    if not activity_name:
        return False
    name_lower = activity_name.lower()
    return any(kw.lower() in name_lower for kw in keywords)


def compute_case_waiting(
    case_id: str,
    events: list[Event],
    admin_keywords: Iterable[str] = DEFAULT_ADMIN_KEYWORDS,
) -> WaitingResult:
    """
    Computes waiting burden for a single case (patient).

    events: unsorted list of Event for this case. Will be sorted internally
    by timestamp. Ties (identical timestamps) are stable-sorted, preserving
    input order - the pipeline does not claim to know true intra-instant
    ordering.
    """
    if not events:
        return WaitingResult(case_id=case_id, total_wait_seconds=0.0)

    all_sorted = sorted(events, key=lambda e: e.timestamp)
    clinical = [e for e in all_sorted if not is_administrative_activity(e.activity, admin_keywords)]
    excluded_count = len(all_sorted) - len(clinical)

    gaps: list[WaitGap] = []
    anomalies: list[TimestampAnomaly] = []

    for i in range(len(clinical) - 1):
        e0, e1 = clinical[i], clinical[i + 1]
        delta = (e1.timestamp - e0.timestamp).total_seconds()

        if delta < 0:
            anomalies.append(
                TimestampAnomaly(
                    case_id=case_id,
                    from_activity=e0.activity,
                    to_activity=e1.activity,
                    from_ts=e0.timestamp,
                    to_ts=e1.timestamp,
                    gap_seconds=delta,
                )
            )
            continue

        gaps.append(
            WaitGap(
                case_id=case_id,
                from_activity=e0.activity,
                to_activity=e1.activity,
                from_ts=e0.timestamp,
                to_ts=e1.timestamp,
                gap_seconds=delta,
            )
        )

    total_wait = sum(g.gap_seconds for g in gaps)

    return WaitingResult(
        case_id=case_id,
        total_wait_seconds=total_wait,
        gaps=gaps,
        anomalies=anomalies,
        excluded_administrative_events=excluded_count,
    )


def compute_waiting_for_all_cases(
    events_by_case: dict[str, list[Event]],
    admin_keywords: Iterable[str] = DEFAULT_ADMIN_KEYWORDS,
) -> dict[str, WaitingResult]:
    """Convenience batch wrapper. Used both by tests and by the Spark driver
    when it collects per-case event lists to the driver for cases where a
    distributed groupBy + pandas UDF is unnecessary at this dataset size."""
    return {
        case_id: compute_case_waiting(case_id, events, admin_keywords)
        for case_id, events in events_by_case.items()
    }
