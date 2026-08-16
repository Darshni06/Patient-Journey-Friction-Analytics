import pytest

from src.process_mining.discovery import apply_department_collapse, compute_department_collapse


def test_collapse_keeps_top_departments_until_coverage_threshold():
    # Mirrors the real dataset's shape: two dominant departments + long tail
    counts = {
        "General Lab Clinical Chemistry": 632,  # 63.2%
        "Nursing ward": 207,                     # 20.7%
        "Obstetrics & Gynaecology clinic": 71,   # 7.1%
        "Medical Microbiology": 42,               # 4.2%
        "Radiology": 32,                          # 3.2%
        "Tiny dept A": 8,
        "Tiny dept B": 5,
        "Tiny dept C": 3,
    }
    result = compute_department_collapse(counts, coverage_threshold=0.95)

    assert "General Lab Clinical Chemistry" in result.kept_departments
    assert "Nursing ward" in result.kept_departments
    assert result.cumulative_coverage_at_cutoff >= 0.95
    # long-tail tiny departments should be collapsed
    assert "Tiny dept C" in result.collapsed_departments


def test_collapse_with_single_dominant_department():
    counts = {"Dept A": 1000, "Dept B": 1, "Dept C": 1}
    result = compute_department_collapse(counts, coverage_threshold=0.95)
    assert result.kept_departments == {"Dept A"}


def test_collapse_threshold_must_be_valid_fraction():
    with pytest.raises(ValueError):
        compute_department_collapse({"A": 1}, coverage_threshold=0.0)
    with pytest.raises(ValueError):
        compute_department_collapse({"A": 1}, coverage_threshold=1.5)


def test_collapse_empty_counts_raises():
    with pytest.raises(ValueError):
        compute_department_collapse({})


def test_apply_department_collapse_maps_correctly():
    counts = {"Dept A": 100, "Dept B": 5}
    result = compute_department_collapse(counts, coverage_threshold=0.9)
    assert apply_department_collapse("Dept A", result) == "Dept A"
    assert apply_department_collapse("Dept B", result) == "Other department"
    assert apply_department_collapse("Unseen Dept", result) == "Other department"
