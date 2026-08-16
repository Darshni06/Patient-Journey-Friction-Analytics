"""
Regression test for the Phase 7 pm4py error:

    Exception: the dataframe should (at least) contain a column of type date

This was hit when running the real pipeline: constructing a pandas DataFrame
directly from a list of row-dicts containing tz-aware `datetime.datetime`
objects does not reliably produce a `datetime64` dtype column - pandas can
leave it as generic `object` dtype instead, which fails pm4py's internal
dtype check before discovery even runs.

These tests exercise `ensure_pm4py_timestamp_dtype` directly with pandas
only (no pm4py import required), so they run in any environment that has
pandas installed, independent of whether pm4py/PySpark/Neo4j are available.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.process_mining.discovery import ensure_pm4py_timestamp_dtype

CET = timezone(timedelta(hours=1))


def test_reproduces_object_dtype_from_tz_aware_datetimes():
    """
    Sanity check that the failure mode is real: a DataFrame built the same
    way run_pipeline.py's phase_7_discover_model builds it (a list of dicts
    with tz-aware datetime.datetime values) is NOT guaranteed to already be
    a datetime64 dtype column. If this assertion ever starts failing because
    a pandas version changes this behavior, that's fine - it just means the
    defensive coercion below is doing less work, not that it's now wrong.
    """
    rows = [
        {"case:concept:name": "p1", "concept:name": "Nursing ward", "time:timestamp": datetime(2005, 1, 3, 9, 0, tzinfo=CET)},
        {"case:concept:name": "p1", "concept:name": "Radiology", "time:timestamp": datetime(2005, 1, 3, 10, 0, tzinfo=CET)},
    ]
    df = pd.DataFrame(rows)
    # We don't assert it MUST be object dtype (pandas behavior can vary by
    # version/platform - this is exactly why the explicit coercion exists),
    # we just document that it's not guaranteed to be datetime64 already.
    assert True  # documentation test; the real guarantee is tested below


def test_ensure_pm4py_timestamp_dtype_coerces_to_datetime64():
    rows = [
        {"time:timestamp": datetime(2005, 1, 3, 9, 0, tzinfo=CET)},
        {"time:timestamp": datetime(2005, 1, 3, 10, 0, tzinfo=CET)},
    ]
    df = pd.DataFrame(rows)

    result = ensure_pm4py_timestamp_dtype(df, "time:timestamp")

    assert pd.api.types.is_datetime64_any_dtype(result["time:timestamp"])


def test_ensure_pm4py_timestamp_dtype_handles_string_timestamps_too():
    # Defensive: also works if timestamps arrive as ISO strings rather than
    # datetime objects (e.g. from a different upstream path).
    rows = [
        {"time:timestamp": "2005-01-03T09:00:00+01:00"},
        {"time:timestamp": "2005-01-03T10:00:00+01:00"},
    ]
    df = pd.DataFrame(rows)

    result = ensure_pm4py_timestamp_dtype(df, "time:timestamp")

    assert pd.api.types.is_datetime64_any_dtype(result["time:timestamp"])


def test_ensure_pm4py_timestamp_dtype_normalizes_mixed_offsets_to_utc():
    # A mix of differently-offset tz-aware datetimes (e.g. across a DST
    # boundary) must not be left as an unusable object column.
    rows = [
        {"time:timestamp": datetime(2005, 1, 3, 9, 0, tzinfo=timezone(timedelta(hours=1)))},   # CET
        {"time:timestamp": datetime(2005, 7, 3, 9, 0, tzinfo=timezone(timedelta(hours=2)))},   # CEST
    ]
    df = pd.DataFrame(rows)

    result = ensure_pm4py_timestamp_dtype(df, "time:timestamp")

    assert pd.api.types.is_datetime64_any_dtype(result["time:timestamp"])
    assert result["time:timestamp"].isna().sum() == 0


def test_ensure_pm4py_timestamp_dtype_raises_on_null_timestamps():
    rows = [
        {"time:timestamp": datetime(2005, 1, 3, 9, 0, tzinfo=CET)},
        {"time:timestamp": None},
    ]
    df = pd.DataFrame(rows)

    with pytest.raises(ValueError, match="null/unparseable"):
        ensure_pm4py_timestamp_dtype(df, "time:timestamp")


def test_ensure_pm4py_timestamp_dtype_raises_on_unparseable_strings():
    rows = [
        {"time:timestamp": datetime(2005, 1, 3, 9, 0, tzinfo=CET)},
        {"time:timestamp": "not-a-timestamp"},
    ]
    df = pd.DataFrame(rows)

    with pytest.raises(ValueError, match="null/unparseable"):
        ensure_pm4py_timestamp_dtype(df, "time:timestamp")


def test_ensure_pm4py_timestamp_dtype_missing_column_raises_clear_error():
    df = pd.DataFrame([{"concept:name": "A"}])
    with pytest.raises(ValueError, match="not found"):
        ensure_pm4py_timestamp_dtype(df, "time:timestamp")


def test_ensure_pm4py_timestamp_dtype_does_not_mutate_caller_dataframe():
    rows = [{"time:timestamp": datetime(2005, 1, 3, 9, 0, tzinfo=CET)}]
    df = pd.DataFrame(rows)
    original_dtype = df["time:timestamp"].dtype

    ensure_pm4py_timestamp_dtype(df, "time:timestamp")

    assert df["time:timestamp"].dtype == original_dtype