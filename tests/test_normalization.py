import pytest

from src.features.normalization import clip_and_normalize


def test_basic_minmax_no_clipping_needed():
    values = {"a": 0.0, "b": 5.0, "c": 10.0}
    result = clip_and_normalize(values, lower_percentile=0, upper_percentile=100)
    assert result.normalized["a"] == 0.0
    assert result.normalized["c"] == 1.0
    assert result.normalized["b"] == pytest.approx(0.5)
    assert result.degenerate is False


def test_all_equal_values_returns_zero_not_division_error():
    values = {"a": 5.0, "b": 5.0, "c": 5.0}
    result = clip_and_normalize(values)
    assert result.degenerate is True
    assert all(v == 0.0 for v in result.normalized.values())


def test_outlier_is_clipped_not_dropped():
    values = {f"case_{i}": 1.0 for i in range(98)}
    values["outlier_low"] = -1000.0
    values["outlier_high"] = 1000.0

    result = clip_and_normalize(values, lower_percentile=1, upper_percentile=99)

    # every case_id must still be present in the output (never dropped)
    assert set(result.normalized.keys()) == set(values.keys())
    assert result.n_clipped_low >= 1
    assert result.n_clipped_high >= 1


def test_single_value_dataset_does_not_crash():
    result = clip_and_normalize({"only_case": 42.0})
    assert result.degenerate is True
    assert result.normalized["only_case"] == 0.0


def test_empty_input_raises_value_error():
    with pytest.raises(ValueError):
        clip_and_normalize({})


def test_output_always_within_zero_one_bounds():
    values = {"a": -5.0, "b": 0.0, "c": 3.0, "d": 3.0, "e": 3.0, "f": 100.0}
    result = clip_and_normalize(values, lower_percentile=5, upper_percentile=95)
    for v in result.normalized.values():
        assert 0.0 <= v <= 1.0
