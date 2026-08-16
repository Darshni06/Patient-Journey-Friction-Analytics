"""
Pipeline-integrated dataset validation (Phase 1 of the required development
sequence). This is the pipeline's own version of the standalone
scripts/inspect_xes.py used earlier to validate the methodology - it runs
automatically as the first stage of run_pipeline.py so every pipeline
execution is checked against a fresh read of the actual file, and nothing
about the dataset's shape is ever hard-coded.

Reports (never hard-coded, always computed from the current file):
- file size, case/event counts
- distinct activities, departments, sections
- timestamp range and unparseable timestamp count
- missing-value stats per event-level key
- duplicate events (identical case_id + activity + timestamp)
- basic anomaly flags (e.g. Section typos still present, non-'1' Number of
  executions values) - informational, does not alter behavior, cleaning.py
  is the layer that actually acts on these.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from src.utils.xes_parser import parse_xes_to_flat_events


@dataclass
class ValidationReport:
    file_path: str
    file_size_bytes: int
    trace_count: int
    event_count: int
    unparseable_timestamps: int
    distinct_activities: int
    distinct_org_groups: int
    distinct_sections: int
    timestamp_min: str | None
    timestamp_max: str | None
    missing_value_counts: dict[str, int] = field(default_factory=dict)
    duplicate_event_count: int = 0
    section_values_needing_correction: int = 0
    number_of_executions_non_one_count: int = 0
    warnings: list[str] = field(default_factory=list)


REQUIRED_EVENT_KEYS = (
    "concept:name",
    "time:timestamp",
    "org:group",
    "Section",
    "lifecycle:transition",
)

KNOWN_SECTION_TYPOS = {"Sectoin 7"}


def validate_dataset(path: str) -> ValidationReport:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Input XES file not found at '{path}'. The pipeline requires the "
            "actual BPIC 2011 file to be present locally; it is never bundled "
            "with the source distribution."
        )

    file_size = os.path.getsize(path)
    events, parse_report = parse_xes_to_flat_events(path)

    activities = Counter(e.get("concept:name") for e in events)
    org_groups = Counter(e.get("org:group") for e in events)
    sections = Counter(e.get("Section") for e in events)

    missing_counts: dict[str, int] = {}
    for key in REQUIRED_EVENT_KEYS:
        missing = sum(1 for e in events if not e.get(key))
        missing_counts[key] = missing

    timestamps = [e["_timestamp_parsed"] for e in events if e.get("_timestamp_parsed") is not None]
    ts_min = min(timestamps).isoformat() if timestamps else None
    ts_max = max(timestamps).isoformat() if timestamps else None

    seen = set()
    duplicates = 0
    for e in events:
        key = (e.get("case_id"), e.get("concept:name"), str(e.get("time:timestamp")))
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)

    section_typo_count = sum(1 for e in events if e.get("Section") in KNOWN_SECTION_TYPOS)

    non_one_exec = sum(
        1 for e in events if e.get("Number of executions") not in (None, "1")
    )

    warnings: list[str] = []
    if parse_report["unparseable_timestamps"] > 0:
        warnings.append(
            f"{parse_report['unparseable_timestamps']} event(s) have an unparseable time:timestamp value."
        )
    if section_typo_count > 0:
        warnings.append(
            f"{section_typo_count} event(s) have a known Section typo value "
            f"({KNOWN_SECTION_TYPOS}); the cleaning layer will correct these."
        )
    if duplicates > 0:
        warnings.append(f"{duplicates} duplicate (case_id, activity, timestamp) event(s) detected.")
    for key, count in missing_counts.items():
        if count > 0:
            warnings.append(f"{count} event(s) missing required field '{key}'.")

    return ValidationReport(
        file_path=os.path.abspath(path),
        file_size_bytes=file_size,
        trace_count=parse_report["trace_count"],
        event_count=parse_report["event_count"],
        unparseable_timestamps=parse_report["unparseable_timestamps"],
        distinct_activities=len(activities),
        distinct_org_groups=len(org_groups),
        distinct_sections=len(sections),
        timestamp_min=ts_min,
        timestamp_max=ts_max,
        missing_value_counts=missing_counts,
        duplicate_event_count=duplicates,
        section_values_needing_correction=section_typo_count,
        number_of_executions_non_one_count=non_one_exec,
        warnings=warnings,
    )


def print_validation_report(report: ValidationReport) -> None:
    print("=" * 70)
    print("DATASET VALIDATION REPORT (computed fresh from the current file)")
    print("=" * 70)
    print(f"File: {report.file_path}")
    print(f"Size: {report.file_size_bytes / (1024*1024):.2f} MB")
    print(f"Cases: {report.trace_count:,}  Events: {report.event_count:,}")
    print(f"Distinct activities: {report.distinct_activities}")
    print(f"Distinct org:group values: {report.distinct_org_groups}")
    print(f"Distinct Section values: {report.distinct_sections}")
    print(f"Timestamp range: {report.timestamp_min} -> {report.timestamp_max}")
    print(f"Duplicate events: {report.duplicate_event_count}")
    print(f"Section typo occurrences: {report.section_values_needing_correction}")
    print(f"'Number of executions' != 1 occurrences: {report.number_of_executions_non_one_count}")
    if report.warnings:
        print("\nWarnings:")
        for w in report.warnings:
            print(f"  - {w}")
    print("=" * 70)
