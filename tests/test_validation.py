from pathlib import Path

import pytest

from src.validation.inspect_log import validate_dataset

FIXTURE = Path(__file__).parent / "fixtures" / "sample_log.xes"


def test_validate_dataset_computes_stats_dynamically_not_hardcoded():
    report = validate_dataset(str(FIXTURE))
    assert report.trace_count == 2
    assert report.event_count == 5
    assert report.file_size_bytes > 0


def test_validate_dataset_detects_section_typo():
    report = validate_dataset(str(FIXTURE))
    assert report.section_values_needing_correction == 1
    assert any("typo" in w.lower() for w in report.warnings)


def test_validate_dataset_missing_file_raises_clear_error():
    with pytest.raises(FileNotFoundError):
        validate_dataset("/nonexistent/path/does_not_exist.xes")


def test_validate_dataset_no_duplicates_in_fixture():
    report = validate_dataset(str(FIXTURE))
    assert report.duplicate_event_count == 0


def test_validate_dataset_timestamp_range_present():
    report = validate_dataset(str(FIXTURE))
    assert report.timestamp_min is not None
    assert report.timestamp_max is not None
    assert report.timestamp_min < report.timestamp_max
