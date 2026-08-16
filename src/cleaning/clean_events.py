"""
Cleaning / validation layer.

Pure-python core logic (row-level transforms + validation predicates),
callable both directly (unit tests) and from a thin PySpark wrapper
(src/ingestion/spark_pipeline.py) via a UDF for large-scale application.

Locked cleaning rules (see DEVIATIONS_FROM_PROMPT.md and configs/config.yaml):
- "Sectoin 7" -> "Section 7" (confirmed typo in the real export, 32 events).
- Rows missing org:group or Section (16 events / 0.01% in the real file) are
  DROPPED, not imputed. Imputing clinical/administrative routing information
  is not defensible.
- No other row is silently discarded. Anomalies are reported, never hidden.

Duplicate handling (added after the real full-file pipeline run surfaced
25,379 events - 16.9% of the log - sharing an identical (case_id, activity,
timestamp) key; see DEVIATIONS_FROM_PROMPT.md for the full investigation):
- FULL exact duplicates (every captured field identical, not just the
  3-key) are dropped - a byte-identical repeated row is almost certainly a
  log-export artifact, not two separate real clinical occurrences.
- PARTIAL duplicates (same case_id/activity/timestamp but differing in at
  least one other field, e.g. a different Activity code or Producer code)
  are RETAINED - they plausibly represent genuinely distinct events that
  only collide on the coarse key because of the dataset's day-level
  timestamp granularity. This default is provisional pending confirmation
  via scripts/inspect_duplicates.py - see DEVIATIONS_FROM_PROMPT.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_SECTION_CORRECTIONS = {"Sectoin 7": "Section 7"}
DEFAULT_REQUIRED_NON_NULL_KEYS = ("org:group", "Section")

FULL_ROW_DEDUPE_FIELDS = (
    "case_id",
    "concept:name",
    "time:timestamp",
    "org:group",
    "Section",
    "Specialism code",
    "Producer code",
    "Activity code",
    "lifecycle:transition",
    "Number of executions",
)


@dataclass
class CleaningReport:
    total_rows_in: int = 0
    total_rows_out: int = 0
    rows_dropped_missing_required: int = 0
    section_values_corrected: int = 0
    dropped_row_case_ids: list[str] = field(default_factory=list)


def normalize_section_value(value: str | None, corrections: dict[str, str] = None) -> str | None:
    corrections = corrections or DEFAULT_SECTION_CORRECTIONS
    if value is None:
        return None
    return corrections.get(value, value)


def is_row_valid(
    row: dict[str, Any],
    required_non_null_keys: tuple[str, ...] = DEFAULT_REQUIRED_NON_NULL_KEYS,
) -> bool:
    for key in required_non_null_keys:
        val = row.get(key)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            return False
    return True


def clean_events(
    raw_events: list[dict[str, Any]],
    section_corrections: dict[str, str] = None,
    required_non_null_keys: tuple[str, ...] = DEFAULT_REQUIRED_NON_NULL_KEYS,
    case_id_key: str = "case_id",
) -> tuple[list[dict[str, Any]], CleaningReport]:
    """
    raw_events: list of flat event dicts (already flattened from XES parsing,
    each expected to carry at least: case_id_key, 'concept:name', 'org:group',
    'Section', 'time:timestamp').

    Returns (cleaned_events, report). Dropped rows are recorded in the report
    (case id) so the pipeline can log exactly what was removed and why -
    never a silent drop.
    """
    section_corrections = section_corrections or DEFAULT_SECTION_CORRECTIONS
    report = CleaningReport(total_rows_in=len(raw_events))

    cleaned: list[dict[str, Any]] = []
    for row in raw_events:
        row = dict(row)  # avoid mutating caller's data

        original_section = row.get("Section")
        corrected_section = normalize_section_value(original_section, section_corrections)
        if corrected_section != original_section:
            report.section_values_corrected += 1
        row["Section"] = corrected_section

        if not is_row_valid(row, required_non_null_keys):
            report.rows_dropped_missing_required += 1
            report.dropped_row_case_ids.append(str(row.get(case_id_key, "UNKNOWN")))
            continue

        cleaned.append(row)

    report.total_rows_out = len(cleaned)
    return cleaned, report


@dataclass
class DuplicateReport:
    total_coarse_duplicate_groups: int = 0       # groups sharing (case_id, activity, timestamp)
    full_exact_duplicate_groups: int = 0          # of those, identical across ALL captured fields
    partial_duplicate_groups: int = 0             # of those, differ in at least one other field
    rows_dropped_as_exact_duplicates: int = 0
    example_full_duplicate_keys: list[tuple] = field(default_factory=list)
    example_partial_duplicate_keys: list[tuple] = field(default_factory=list)


def classify_and_drop_exact_duplicates(
    events: list[dict[str, Any]],
    dedupe_fields: tuple[str, ...] = FULL_ROW_DEDUPE_FIELDS,
    coarse_key_fields: tuple[str, ...] = ("case_id", "concept:name", "time:timestamp"),
    max_examples: int = 5,
) -> tuple[list[dict[str, Any]], DuplicateReport]:
    """
    Two-pass duplicate handling:
      1. Group rows by the COARSE key (case_id, activity, timestamp) purely
         for reporting/classification - this is the key that originally
         flagged 25,379 "duplicate" events in the real BPIC 2011 file.
      2. Within each coarse-duplicate group, check whether rows are FULL
         exact duplicates (identical across every field in `dedupe_fields`)
         or PARTIAL duplicates (differ in at least one other field).

    Only FULL exact duplicates are removed (keeping the first occurrence).
    PARTIAL duplicates are retained untouched - see module docstring for
    why this is the current default, and DEVIATIONS_FROM_PROMPT.md for the
    open investigation into whether this default is correct.
    """
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in events:
        key = tuple(row.get(f) for f in coarse_key_fields)
        groups.setdefault(key, []).append(row)

    report = DuplicateReport()
    kept: list[dict[str, Any]] = []

    for key, rows in groups.items():
        if len(rows) == 1:
            kept.append(rows[0])
            continue

        report.total_coarse_duplicate_groups += 1
        signatures = {tuple(r.get(f) for f in dedupe_fields) for r in rows}

        if len(signatures) == 1:
            # Fully identical across every captured field - drop all but one.
            report.full_exact_duplicate_groups += 1
            report.rows_dropped_as_exact_duplicates += len(rows) - 1
            if len(report.example_full_duplicate_keys) < max_examples:
                report.example_full_duplicate_keys.append(key)
            kept.append(rows[0])
        else:
            # Differ in at least one field - treat as legitimate distinct
            # events, retain all of them.
            report.partial_duplicate_groups += 1
            if len(report.example_partial_duplicate_keys) < max_examples:
                report.example_partial_duplicate_keys.append(key)
            kept.extend(rows)

    return kept, report
