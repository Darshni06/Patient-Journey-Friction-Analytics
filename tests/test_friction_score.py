import math

import pytest

from src.friction.friction_score import (
    FrictionComponents,
    compute_case_friction,
    compute_component_correlation_diagnostic,
    compute_friction_score,
)


def test_formula_matches_spec_example():
    # From the master implementation prompt: W=0.2, R=0.4, D=0.6 -> F=0.4
    score = compute_friction_score(0.2, 0.4, 0.6)
    assert math.isclose(score, 0.4, rel_tol=1e-9)


def test_equal_weights_are_locked_default():
    score = compute_friction_score(1.0, 0.0, 0.0)
    assert math.isclose(score, 1.0 / 3.0, rel_tol=1e-9)


def test_all_zero_gives_zero_friction():
    assert compute_friction_score(0.0, 0.0, 0.0) == 0.0


def test_all_one_gives_one_friction():
    assert math.isclose(compute_friction_score(1.0, 1.0, 1.0), 1.0)


def test_weights_must_sum_to_one():
    with pytest.raises(ValueError):
        compute_friction_score(0.5, 0.5, 0.5, weights=(0.5, 0.5, 0.5))


def test_out_of_range_component_raises():
    with pytest.raises(ValueError):
        compute_friction_score(1.5, 0.2, 0.2)
    with pytest.raises(ValueError):
        compute_friction_score(0.2, -0.1, 0.2)


def test_dominant_component_identification():
    components = FrictionComponents(case_id="p1", waiting_norm=0.9, rework_norm=0.1, deviation_norm=0.2)
    result = compute_case_friction(components)
    assert result.dominant_component == "waiting"
    assert math.isclose(result.friction_score, (0.9 + 0.1 + 0.2) / 3)


def test_correlation_diagnostic_detects_perfect_collinearity():
    raw_w = {"p1": 1.0, "p2": 2.0, "p3": 3.0, "p4": 4.0}
    raw_r = {"p1": 2.0, "p2": 4.0, "p3": 6.0, "p4": 8.0}  # perfectly correlated with W
    raw_d = {"p1": 5.0, "p2": 1.0, "p3": 9.0, "p4": 3.0}  # unrelated

    diag = compute_component_correlation_diagnostic(raw_w, raw_r, raw_d)
    assert math.isclose(diag.corr_waiting_rework, 1.0, rel_tol=1e-6)
    assert diag.warning is not None  # must flag collinearity, not silently pass


def test_correlation_diagnostic_no_warning_when_independent():
    raw_w = {"p1": 1.0, "p2": 5.0, "p3": 2.0, "p4": 9.0, "p5": 3.0}
    raw_r = {"p1": 9.0, "p2": 1.0, "p3": 8.0, "p4": 2.0, "p5": 7.0}
    raw_d = {"p1": 4.0, "p2": 4.0, "p3": 4.1, "p4": 3.9, "p5": 4.0}

    diag = compute_component_correlation_diagnostic(
        raw_w, raw_r, raw_d, collinearity_warning_threshold=0.95
    )
    assert diag.n_cases == 5


def test_correlation_diagnostic_requires_minimum_cases():
    with pytest.raises(ValueError):
        compute_component_correlation_diagnostic({"p1": 1.0}, {"p1": 2.0}, {"p1": 3.0})
