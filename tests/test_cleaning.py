from src.cleaning.clean_events import (
    classify_and_drop_exact_duplicates,
    clean_events,
    is_row_valid,
    normalize_section_value,
)


def test_section_typo_is_corrected():
    assert normalize_section_value("Sectoin 7") == "Section 7"
    assert normalize_section_value("Section 4") == "Section 4"  # untouched
    assert normalize_section_value(None) is None


def test_row_missing_org_group_is_invalid():
    row = {"case_id": "p1", "org:group": None, "Section": "Section 1"}
    assert is_row_valid(row) is False


def test_row_with_blank_string_is_invalid():
    row = {"case_id": "p1", "org:group": "   ", "Section": "Section 1"}
    assert is_row_valid(row) is False


def test_row_with_all_required_fields_is_valid():
    row = {"case_id": "p1", "org:group": "Nursing ward", "Section": "Section 2"}
    assert is_row_valid(row) is True


def test_clean_events_drops_invalid_rows_and_reports_them():
    raw = [
        {"case_id": "p1", "org:group": "Nursing ward", "Section": "Section 2"},
        {"case_id": "p2", "org:group": None, "Section": "Section 1"},  # dropped
        {"case_id": "p3", "org:group": "Radiology", "Section": "Sectoin 7"},  # typo fixed, kept
    ]
    cleaned, report = clean_events(raw)

    assert report.total_rows_in == 3
    assert report.total_rows_out == 2
    assert report.rows_dropped_missing_required == 1
    assert "p2" in report.dropped_row_case_ids
    assert report.section_values_corrected == 1

    corrected_row = next(r for r in cleaned if r["case_id"] == "p3")
    assert corrected_row["Section"] == "Section 7"


def test_clean_events_never_mutates_input_list():
    raw = [{"case_id": "p1", "org:group": "Nursing ward", "Section": "Sectoin 7"}]
    original_copy = dict(raw[0])
    clean_events(raw)
    assert raw[0] == original_copy


def test_empty_input_produces_empty_output():
    cleaned, report = clean_events([])
    assert cleaned == []
    assert report.total_rows_in == 0
    assert report.total_rows_out == 0


def test_full_exact_duplicates_are_dropped():
    row = {
        "case_id": "p1", "concept:name": "kalium potentiometrisch",
        "time:timestamp": "2005-01-05T00:00:00+01:00", "org:group": "General Lab Clinical Chemistry",
        "Section": "Section 7", "Specialism code": "7", "Producer code": "SGEH",
        "Activity code": "370443", "lifecycle:transition": "complete", "Number of executions": "1",
    }
    events = [dict(row), dict(row), dict(row)]  # three byte-identical rows
    kept, report = classify_and_drop_exact_duplicates(events)

    assert len(kept) == 1
    assert report.total_coarse_duplicate_groups == 1
    assert report.full_exact_duplicate_groups == 1
    assert report.partial_duplicate_groups == 0
    assert report.rows_dropped_as_exact_duplicates == 2


def test_partial_duplicates_are_retained_not_dropped():
    base = {
        "case_id": "p1", "concept:name": "kalium potentiometrisch",
        "time:timestamp": "2005-01-05T00:00:00+01:00", "org:group": "General Lab Clinical Chemistry",
        "Section": "Section 7", "Specialism code": "7", "Producer code": "SGEH",
        "lifecycle:transition": "complete", "Number of executions": "1",
    }
    row_a = dict(base, **{"Activity code": "370443"})
    row_b = dict(base, **{"Activity code": "370444"})  # differs in Activity code only

    kept, report = classify_and_drop_exact_duplicates([row_a, row_b])

    assert len(kept) == 2  # both retained
    assert report.total_coarse_duplicate_groups == 1
    assert report.full_exact_duplicate_groups == 0
    assert report.partial_duplicate_groups == 1
    assert report.rows_dropped_as_exact_duplicates == 0


def test_non_duplicate_rows_untouched():
    events = [
        {"case_id": "p1", "concept:name": "Registration", "time:timestamp": "t1"},
        {"case_id": "p1", "concept:name": "Consultation", "time:timestamp": "t2"},
    ]
    kept, report = classify_and_drop_exact_duplicates(events)
    assert len(kept) == 2
    assert report.total_coarse_duplicate_groups == 0


def test_example_keys_are_capped_at_max_examples():
    groups = []
    for i in range(10):
        row = {
            "case_id": f"p{i}", "concept:name": "A", "time:timestamp": "t1",
            "org:group": "X", "Section": "S", "Specialism code": None,
            "Producer code": None, "Activity code": "1", "lifecycle:transition": "complete",
            "Number of executions": "1",
        }
        groups.extend([dict(row), dict(row)])  # each case_id gets its own full-duplicate pair
    kept, report = classify_and_drop_exact_duplicates(groups, max_examples=3)
    assert report.full_exact_duplicate_groups == 10
    assert len(report.example_full_duplicate_keys) == 3
