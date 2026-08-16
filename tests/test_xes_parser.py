from pathlib import Path

from src.utils.xes_parser import parse_xes_timestamp, parse_xes_to_flat_events

FIXTURE = Path(__file__).parent / "fixtures" / "sample_log.xes"


def test_parses_correct_trace_and_event_counts():
    events, report = parse_xes_to_flat_events(str(FIXTURE))
    assert report["trace_count"] == 2
    assert report["event_count"] == 5
    assert len(events) == 5


def test_namespaced_xes_is_not_silently_ignored():
    # Regression guard: BPIC 2011 declares xmlns="http://www.xes-standard.org"
    # on <log>. An earlier version of the inspection script matched tags with
    # exact string equality and silently returned zero events on a
    # namespaced file. This must never happen again.
    events, report = parse_xes_to_flat_events(str(FIXTURE))
    assert report["event_count"] > 0
    assert len(events) > 0


def test_case_id_correctly_attached_to_events():
    events, _ = parse_xes_to_flat_events(str(FIXTURE))
    case_ids = {e["case_id"] for e in events}
    assert case_ids == {"patient_001", "patient_002"}


def test_event_level_fields_present():
    events, _ = parse_xes_to_flat_events(str(FIXTURE))
    first = events[0]
    assert first["concept:name"] == "Registration"
    assert first["org:group"] == "Nursing ward"
    assert first["Section"] == "Section 2"
    assert first["_timestamp_parsed"] is not None


def test_section_typo_is_present_in_raw_parse_uncorrected():
    # The parser itself should NOT correct the typo - that's the cleaning
    # layer's job (src/cleaning/clean_events.py). Parsing must be faithful
    # to the raw file.
    events, _ = parse_xes_to_flat_events(str(FIXTURE))
    sections = {e["Section"] for e in events}
    assert "Sectoin 7" in sections


def test_timestamp_parsing_handles_offset_and_milliseconds():
    ts = parse_xes_timestamp("2005-01-03T09:00:00.000+01:00")
    assert ts is not None
    assert ts.year == 2005 and ts.month == 1 and ts.day == 3


def test_timestamp_parsing_returns_none_for_garbage():
    assert parse_xes_timestamp("not-a-timestamp") is None
    assert parse_xes_timestamp(None) is None


def test_administrative_activity_present_in_fixture():
    events, _ = parse_xes_to_flat_events(str(FIXTURE))
    activities = {e["concept:name"] for e in events}
    assert "administratief tarief - eerste pol" in activities
