import math
from collections import Counter

from src.features.rework import (
    compute_case_rework,
    compute_rework_score,
    detect_immediate_loops,
)


def test_no_repeats_gives_zero_rework():
    counts = Counter({"A": 1, "B": 1, "C": 1})
    assert compute_rework_score(counts) == 0.0


def test_single_repeat_gives_log1p_one():
    counts = Counter({"A": 2})
    assert math.isclose(compute_rework_score(counts), math.log1p(1))


def test_log_dampening_reduces_dominance_of_hyper_repeated_activity():
    # One activity repeated 30 times vs three activities each repeated 3 times
    hyper = Counter({"Lab test": 30})
    spread = Counter({"Consultation": 3, "Laboratory": 3, "Registration": 3})

    hyper_score = compute_rework_score(hyper, use_log_dampening=True)
    spread_score = compute_rework_score(spread, use_log_dampening=True)

    hyper_linear = compute_rework_score(hyper, use_log_dampening=False)
    spread_linear = compute_rework_score(spread, use_log_dampening=False)

    # Under linear scoring, the hyper-repeated case dominates heavily (29 vs 6)
    assert hyper_linear > spread_linear * 4

    # Under log dampening, the gap should shrink substantially relative to linear
    linear_ratio = hyper_linear / spread_linear
    log_ratio = hyper_score / spread_score
    assert log_ratio < linear_ratio


def test_immediate_loop_detection():
    sequence = ["Registration", "Consultation", "Consultation", "Laboratory", "Laboratory", "Discharge"]
    loops = detect_immediate_loops(sequence)
    assert loops == [("Consultation", "Consultation"), ("Laboratory", "Laboratory")]


def test_no_immediate_loops_in_linear_sequence():
    sequence = ["Registration", "Consultation", "Laboratory", "Discharge"]
    assert detect_immediate_loops(sequence) == []


def test_compute_case_rework_full_result():
    sequence = ["Registration", "Consultation", "Laboratory", "Consultation", "Registration", "Discharge"]
    result = compute_case_rework("case_1", sequence)
    assert result.total_events == 6
    assert result.repeated_activities == {"Consultation": 2, "Registration": 2}
    assert result.rework_score == math.log1p(1) * 2  # two activities each repeated once
    assert result.immediate_loops == []  # no back-to-back repeats here


def test_empty_sequence_gives_zero_rework():
    result = compute_case_rework("case_1", [])
    assert result.rework_score == 0.0
    assert result.repeated_activities == {}
    assert result.total_events == 0


def test_number_of_executions_field_is_never_referenced_in_code():
    # Structural guard: rework module must not use "Number of executions" as
    # an actual dict/field access anywhere - it's only allowed to appear in
    # comments/docstrings explaining why it's excluded, per the locked
    # decision that it behaves like a billing quantity field, not a
    # repeat-count.
    import inspect
    import src.features.rework as rework_module

    source = inspect.getsource(rework_module)
    forbidden_patterns = ['["Number of executions"]', "['Number of executions']", '.get("Number of executions"', ".get('Number of executions'"]
    for pattern in forbidden_patterns:
        assert pattern not in source, f"rework.py must not access the 'Number of executions' field ({pattern} found)"
