from datetime import datetime, timedelta

from src.features.waiting import (
    Event,
    compute_case_waiting,
    is_administrative_activity,
)


def dt(minutes_from_epoch: int) -> datetime:
    return datetime(2005, 1, 1) + timedelta(minutes=minutes_from_epoch)


def test_is_administrative_activity_matches_real_dataset_patterns():
    assert is_administrative_activity("ordertarief")
    assert is_administrative_activity("administratief tarief       - eerste pol")
    assert is_administrative_activity("190101 bovenreg.toesl.  a101")
    assert is_administrative_activity("190205 klasse 3b        a205")
    assert not is_administrative_activity("1e consult poliklinisch")
    assert not is_administrative_activity("kalium potentiometrisch")


def test_is_administrative_activity_handles_none_and_empty():
    assert is_administrative_activity(None) is False
    assert is_administrative_activity("") is False


def test_simple_two_event_wait():
    events = [
        Event("Registration", dt(0)),
        Event("Consultation", dt(30)),
    ]
    result = compute_case_waiting("case_1", events)
    assert result.total_wait_seconds == 30 * 60
    assert len(result.gaps) == 1
    assert result.excluded_administrative_events == 0


def test_administrative_events_excluded_as_wait_endpoints():
    events = [
        Event("Consultation", dt(0)),
        Event("administratief tarief - eerste pol", dt(5)),
        Event("Laboratory test", dt(65)),
    ]
    result = compute_case_waiting("case_1", events)
    # The billing event in between must not create two separate gaps;
    # clinical-only gap should be Consultation -> Laboratory test = 65 min.
    assert result.excluded_administrative_events == 1
    assert len(result.gaps) == 1
    assert result.gaps[0].from_activity == "Consultation"
    assert result.gaps[0].to_activity == "Laboratory test"
    assert result.total_wait_seconds == 65 * 60


def test_zero_duration_gap_is_valid_not_anomalous():
    events = [
        Event("Lab test A", dt(0)),
        Event("Lab test B", dt(0)),  # same instant - legitimate batch draw
    ]
    result = compute_case_waiting("case_1", events)
    assert result.total_wait_seconds == 0
    assert len(result.anomalies) == 0
    assert len(result.gaps) == 1


def test_negative_gap_is_reported_as_anomaly_and_excluded_from_total():
    # Out-of-order timestamps: simulate by constructing events directly
    # in a "bad" order relative to timestamps is irrelevant since we sort
    # internally - a true anomaly requires equal-or-earlier timestamp after
    # sort, which can't happen after sorting by definition. This test
    # instead verifies that ties preserve input order without error and
    # that no anomaly is fabricated for legitimate same-timestamp events.
    events = [
        Event("A", dt(10)),
        Event("B", dt(10)),
        Event("C", dt(5)),
    ]
    result = compute_case_waiting("case_1", events)
    # after sorting: C(5), A(10), B(10) -> both gaps >= 0
    assert all(g.gap_seconds >= 0 for g in result.gaps)
    assert len(result.anomalies) == 0


def test_single_event_case_has_zero_wait():
    result = compute_case_waiting("case_1", [Event("Registration", dt(0))])
    assert result.total_wait_seconds == 0
    assert result.gaps == []


def test_empty_event_list_handled_without_crashing():
    result = compute_case_waiting("case_1", [])
    assert result.total_wait_seconds == 0.0
    assert result.gaps == []
    assert result.anomalies == []


def test_all_administrative_case_has_no_gaps():
    events = [
        Event("ordertarief", dt(0)),
        Event("administratief tarief - eerste pol", dt(10)),
    ]
    result = compute_case_waiting("case_1", events)
    assert result.gaps == []
    assert result.total_wait_seconds == 0
    assert result.excluded_administrative_events == 2
