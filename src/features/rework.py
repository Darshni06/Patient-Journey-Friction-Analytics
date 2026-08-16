"""
Rework / Loop Burden calculation.

Locked methodology (see DEVIATIONS_FROM_PROMPT.md):

    Rework_p = sum over activities a of log(1 + max(0, Count_p,a - 1))

This is a LOG-DAMPENED version of the originally specified linear formula
(max(0, Count_p,a - 1), summed). The dampening was added during the
methodology review: BPIC 2011 contains serial lab monitoring (e.g. repeated
potassium/sodium/hemoglobin/creatinine draws) that can repeat dozens of
times for long-treatment patients. Under a linear count, one hyper-repeated
routine activity dominates Rework_p and drowns out the more intuitive
"rework" pattern of several DIFFERENT activities each repeated a few times
(e.g. Consultation -> Lab -> Consultation). Log-dampening curbs this without
reintroducing any judgment about clinical legitimacy - repetition is still
counted "as observed," just with diminishing marginal weight.

"Number of executions" (a BPIC 2011 event attribute) is deliberately NOT
used as a repeat multiplier anywhere in this module. See waiting.py's
module docstring philosophy and DEVIATIONS_FROM_PROMPT.md for why: full-file
inspection showed this field takes negative and round-number values
inconsistent with a clinical repeat-count interpretation (it behaves like a
billing quantity/credit-adjustment field instead).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class ReworkResult:
    case_id: str
    rework_score: float
    repeated_activities: dict[str, int] = field(default_factory=dict)  # activity -> raw count
    immediate_loops: list[tuple[str, str]] = field(default_factory=list)  # (A, A) adjacent repeats
    total_events: int = 0


def compute_rework_score(activity_counts: Counter, use_log_dampening: bool = True) -> float:
    """
    activity_counts: Counter of activity -> occurrence count for one case.
    """
    total = 0.0
    for _activity, count in activity_counts.items():
        excess = max(0, count - 1)
        total += math.log1p(excess) if use_log_dampening else float(excess)
    return total


def detect_immediate_loops(activities_in_order: list[str]) -> list[tuple[str, str]]:
    """
    Detects back-to-back repeats (A -> A) in the case's chronological
    activity sequence. This is a descriptive/dashboard feature (Rework
    Analysis page), separate from the numeric Rework_p score.
    """
    loops = []
    for i in range(len(activities_in_order) - 1):
        if activities_in_order[i] == activities_in_order[i + 1]:
            loops.append((activities_in_order[i], activities_in_order[i + 1]))
    return loops


def compute_case_rework(
    case_id: str,
    activities_in_order: list[str],
    use_log_dampening: bool = True,
) -> ReworkResult:
    counts = Counter(activities_in_order)
    score = compute_rework_score(counts, use_log_dampening=use_log_dampening)
    repeated = {a: c for a, c in counts.items() if c > 1}
    loops = detect_immediate_loops(activities_in_order)

    return ReworkResult(
        case_id=case_id,
        rework_score=score,
        repeated_activities=repeated,
        immediate_loops=loops,
        total_events=len(activities_in_order),
    )


def compute_rework_for_all_cases(
    activities_by_case: dict[str, list[str]],
    use_log_dampening: bool = True,
) -> dict[str, ReworkResult]:
    return {
        case_id: compute_case_rework(case_id, activities, use_log_dampening)
        for case_id, activities in activities_by_case.items()
    }
