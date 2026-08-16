"""
Duplicate-event investigation script.

Run this against the real Hospital_log.xes to determine whether the 25,379
events flagged as duplicates (same case_id + activity + timestamp) are:

  (a) FULL exact duplicates - identical across every other captured field
      too (org:group, Section, Specialism code, Producer code, Activity
      code, lifecycle:transition, Number of executions). This pattern is
      consistent with a log-export artifact (the same underlying event
      re-emitted as two rows), not two genuinely separate occurrences.

  (b) PARTIAL duplicates - share the coarse key but differ in at least one
      other field. This pattern is consistent with genuinely distinct
      events that only collide on (case_id, activity, timestamp) because
      of the dataset's day-level timestamp granularity (e.g. two separate
      orders of the same lab test recorded on the same day, routed through
      different Activity codes or Producer codes).

The pipeline's current default (src/cleaning/clean_events.py) drops (a) and
keeps (b). This script's output is what confirms or overturns that default.

Usage:
    python scripts/inspect_duplicates.py "Hospital_log.xes"
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.xes_parser import parse_xes_to_flat_events  # noqa: E402

COMPARE_FIELDS = (
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

MAX_EXAMPLES = 6


def main(path: str) -> None:
    print(f"Parsing {path} ...\n")
    events, report = parse_xes_to_flat_events(path)
    print(f"Total events: {report['event_count']:,}\n")

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for e in events:
        key = (e.get("case_id"), e.get("concept:name"), e.get("time:timestamp"))
        groups[key].append(e)

    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}

    full_identical = []
    partial = []

    for key, rows in dup_groups.items():
        signatures = {tuple(r.get(f) for f in COMPARE_FIELDS) for r in rows}
        if len(signatures) == 1:
            full_identical.append((key, rows))
        else:
            partial.append((key, rows))

    total_dup_events = sum(len(v) for v in dup_groups.values())
    full_dup_events = sum(len(rows) for _, rows in full_identical)
    partial_dup_events = sum(len(rows) for _, rows in partial)

    print("=" * 70)
    print("DUPLICATE EVENT CLASSIFICATION")
    print("=" * 70)
    print(f"Duplicate groups (same case_id + activity + timestamp): {len(dup_groups):,}")
    print(f"  -> FULL exact duplicate groups (identical in every field):  {len(full_identical):,}")
    print(f"  -> PARTIAL duplicate groups (differ in >=1 other field):    {len(partial):,}")
    print(f"\nEvents involved: {total_dup_events:,} total")
    print(f"  -> in FULL exact duplicate groups:    {full_dup_events:,}")
    print(f"  -> in PARTIAL duplicate groups:        {partial_dup_events:,}")
    print(f"\nUnder the current pipeline default, {full_dup_events - len(full_identical):,} "
          f"rows would be DROPPED (keeping 1 per full-duplicate group), and "
          f"{partial_dup_events:,} rows would be RETAINED (partial duplicates).")

    print("\n" + "=" * 70)
    print(f"EXAMPLE FULL-IDENTICAL GROUPS (up to {MAX_EXAMPLES})")
    print("=" * 70)
    for key, rows in full_identical[:MAX_EXAMPLES]:
        print(f"\nKey (case_id, activity, timestamp): {key}")
        print(f"  Occurrences: {len(rows)}")
        for r in rows:
            printable = {k: v for k, v in r.items() if k != "_timestamp_parsed"}
            print(f"  {printable}")

    print("\n" + "=" * 70)
    print(f"EXAMPLE PARTIAL-DUPLICATE GROUPS (up to {MAX_EXAMPLES})")
    print("=" * 70)
    for key, rows in partial[:MAX_EXAMPLES]:
        print(f"\nKey (case_id, activity, timestamp): {key}")
        print(f"  Occurrences: {len(rows)}")
        for r in rows:
            printable = {k: v for k, v in r.items() if k != "_timestamp_parsed"}
            print(f"  {printable}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/inspect_duplicates.py <path_to_xes_file>")
        sys.exit(1)
    main(sys.argv[1])
