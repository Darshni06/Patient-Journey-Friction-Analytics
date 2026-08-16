import time

import pandas as pd
import pytest

from src.process_mining import conformance as conf


def test_build_case_activity_sequences_orders_chronologically():
    df = pd.DataFrame(
        [
            {"case:concept:name": "p1", "concept:name": "B", "time:timestamp": pd.Timestamp("2005-01-02")},
            {"case:concept:name": "p1", "concept:name": "A", "time:timestamp": pd.Timestamp("2005-01-01")},
            {"case:concept:name": "p2", "concept:name": "X", "time:timestamp": pd.Timestamp("2005-01-01")},
        ]
    )
    seqs = conf.build_case_activity_sequences(df)
    assert seqs["p1"] == ["A", "B"]
    assert seqs["p2"] == ["X"]


def test_compute_case_variants_and_grouping():
    seqs = {"p1": ["A", "B"], "p2": ["A", "B"], "p3": ["A", "C"]}
    variants = conf.compute_case_variants(seqs)
    groups = conf.group_cases_by_variant(variants)
    assert sorted(groups[("A", "B")]) == ["p1", "p2"]
    assert groups[("A", "C")] == ["p3"]
    assert len(groups) == 2


def test_extract_deviation_from_alignments_basic():
    results = [{"cost": 3}, {"cost": 0}]
    out = conf.extract_deviation_from_alignments(results, ["p1", "p2"])
    assert out["p1"].raw_deviation_cost == 3.0
    assert out["p2"].method == "alignments"


def test_extract_deviation_from_alignments_length_mismatch_raises():
    with pytest.raises(ValueError):
        conf.extract_deviation_from_alignments([{"cost": 1}], ["p1", "p2"])


def test_extract_deviation_from_alignments_missing_cost_raises():
    with pytest.raises(ValueError):
        conf.extract_deviation_from_alignments([{}], ["p1"])


def test_extract_deviation_from_token_replay_basic():
    results = [{"missing_tokens": 2, "remaining_tokens": 1}]
    out = conf.extract_deviation_from_token_replay(results, ["p1"])
    assert out["p1"].raw_deviation_cost == 3.0
    assert out["p1"].method == "token_based_replay"


def _sample_event_log_df():
    # p1 and p2 share the exact variant (A, B); p3 has a different variant
    # (A, C) - so 3 cases, only 2 distinct variants.
    return pd.DataFrame(
        [
            {"case:concept:name": "p1", "concept:name": "A", "time:timestamp": pd.Timestamp("2005-01-01")},
            {"case:concept:name": "p1", "concept:name": "B", "time:timestamp": pd.Timestamp("2005-01-02")},
            {"case:concept:name": "p2", "concept:name": "A", "time:timestamp": pd.Timestamp("2005-01-01")},
            {"case:concept:name": "p2", "concept:name": "B", "time:timestamp": pd.Timestamp("2005-01-02")},
            {"case:concept:name": "p3", "concept:name": "A", "time:timestamp": pd.Timestamp("2005-01-01")},
            {"case:concept:name": "p3", "concept:name": "C", "time:timestamp": pd.Timestamp("2005-01-02")},
        ]
    )


def test_variant_level_caching_avoids_redundant_alignment_calls():
    """The core efficiency fix: p1 and p2 share a variant, so alignment
    should be invoked once per DISTINCT variant (2), not once per case (3)."""
    df = _sample_event_log_df()
    call_count = {"n": 0}

    def fake_align(variant, net, im, fm):
        call_count["n"] += 1
        return float(len(variant))

    original = conf._align_single_variant
    conf._align_single_variant = fake_align
    try:
        raw_dev, report = conf.compute_deviation_for_dataset(
            df, net=None, initial_marking=None, final_marking=None,
            conformance_method="alignments", alignment_time_budget_seconds=100,
        )
    finally:
        conf._align_single_variant = original

    assert call_count["n"] == 2  # not 3 - variant caching worked
    assert raw_dev["p1"] == raw_dev["p2"]  # same variant -> identical cost
    assert report.method_used == "alignments"
    assert report.n_variants == 2
    assert report.n_cases == 3
    assert report.fallback_triggered is False


def test_auto_mode_falls_back_to_token_replay_when_budget_exceeded():
    df = _sample_event_log_df()

    def slow_align(variant, net, im, fm):
        time.sleep(0.05)
        return 1.0

    fallback_calls = {"n": 0}

    def fake_token_replay(event_log_df, net, im, fm):
        fallback_calls["n"] += 1
        return {cid: 42.0 for cid in ["p1", "p2", "p3"]}

    original_align = conf._align_single_variant
    original_replay = conf._compute_deviation_token_replay_all_cases
    conf._align_single_variant = slow_align
    conf._compute_deviation_token_replay_all_cases = fake_token_replay
    try:
        raw_dev, report = conf.compute_deviation_for_dataset(
            df, net=None, initial_marking=None, final_marking=None,
            conformance_method="auto", alignment_time_budget_seconds=0.01,
        )
    finally:
        conf._align_single_variant = original_align
        conf._compute_deviation_token_replay_all_cases = original_replay

    assert report.method_used == "token_based_replay"
    assert report.fallback_triggered is True
    assert report.fallback_reason is not None
    assert fallback_calls["n"] == 1  # whole-dataset recompute, called exactly once
    assert raw_dev == {"p1": 42.0, "p2": 42.0, "p3": 42.0}


def test_alignments_only_mode_raises_timeout_instead_of_falling_back():
    df = _sample_event_log_df()

    def slow_align(variant, net, im, fm):
        time.sleep(0.05)
        return 1.0

    original_align = conf._align_single_variant
    conf._align_single_variant = slow_align
    try:
        with pytest.raises(TimeoutError):
            conf.compute_deviation_for_dataset(
                df, net=None, initial_marking=None, final_marking=None,
                conformance_method="alignments", alignment_time_budget_seconds=0.01,
            )
    finally:
        conf._align_single_variant = original_align


def test_token_based_replay_mode_skips_alignment_entirely():
    df = pd.DataFrame(
        [{"case:concept:name": "p1", "concept:name": "A", "time:timestamp": pd.Timestamp("2005-01-01")}]
    )

    align_calls = {"n": 0}

    def fake_align(variant, net, im, fm):
        align_calls["n"] += 1
        return 1.0

    def fake_token_replay(event_log_df, net, im, fm):
        return {"p1": 7.0}

    original_align = conf._align_single_variant
    original_replay = conf._compute_deviation_token_replay_all_cases
    conf._align_single_variant = fake_align
    conf._compute_deviation_token_replay_all_cases = fake_token_replay
    try:
        raw_dev, report = conf.compute_deviation_for_dataset(
            df, net=None, initial_marking=None, final_marking=None,
            conformance_method="token_based_replay",
        )
    finally:
        conf._align_single_variant = original_align
        conf._compute_deviation_token_replay_all_cases = original_replay

    assert align_calls["n"] == 0  # alignment never attempted
    assert raw_dev == {"p1": 7.0}
    assert report.method_used == "token_based_replay"
    assert report.fallback_triggered is False
    assert report.requested_method == "token_based_replay"


def test_invalid_conformance_method_raises_value_error():
    df = pd.DataFrame(
        [{"case:concept:name": "p1", "concept:name": "A", "time:timestamp": pd.Timestamp("2005-01-01")}]
    )
    with pytest.raises(ValueError):
        conf.compute_deviation_for_dataset(df, None, None, None, conformance_method="bogus")


def test_all_variants_complete_within_budget_uses_alignments_no_fallback():
    df = _sample_event_log_df()

    def fast_align(variant, net, im, fm):
        return 5.0

    original = conf._align_single_variant
    conf._align_single_variant = fast_align
    try:
        raw_dev, report = conf.compute_deviation_for_dataset(
            df, net=None, initial_marking=None, final_marking=None,
            conformance_method="auto", alignment_time_budget_seconds=100,
        )
    finally:
        conf._align_single_variant = original

    assert report.method_used == "alignments"
    assert report.fallback_triggered is False
    assert report.n_variants_completed_via_alignment == 2
    assert all(v == 5.0 for v in raw_dev.values())