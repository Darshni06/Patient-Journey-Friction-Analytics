"""
BPIC 2011 XES Follow-up Inspection
-----------------------------------
Answers three specific open questions left after the first inspection pass:

1. Does "Number of executions" ever exceed 1? (affects the rework formula)
2. How many distinct values does org:group / Section take? (affects choice
   of discovery alphabet for the reference process model)
3. How clustered are events on the same calendar day per case? (quantifies
   the day-only timestamp granularity issue)

Stdlib only, streams the file the same way as inspect_xes.py.

Usage (PowerShell):
    python inspect_xes_followup.py "Hospital_log.xes"
"""

import sys
from collections import Counter

ATTR_TAGS = {"string", "date", "int", "float", "boolean", "id", "list"}


def strip_ns(tag):
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def followup_inspect(path):
    import xml.etree.ElementTree as ET

    execution_counts = Counter()      # "Number of executions" raw values
    section_values = Counter()
    org_group_values = Counter()
    specialism_event_values = Counter()

    total_events = 0
    non_midnight_timestamp_count = 0
    distinct_case_day_pairs = set()

    stack = []
    current_case_id = None
    current_event_attrs = {}

    context = ET.iterparse(path, events=("start", "end"))
    for event_type, elem in context:
        tag = strip_ns(elem.tag)

        if event_type == "start":
            stack.append(tag)
            if tag == "trace":
                current_case_id = None
            elif tag == "event":
                current_event_attrs = {}
            continue

        if tag in ATTR_TAGS:
            key = elem.get("key")
            value = elem.get("value")
            parent = stack[-2] if len(stack) >= 2 else None
            if parent == "trace" and key == "concept:name":
                current_case_id = value
            elif parent == "event":
                current_event_attrs[key] = value

        elif tag == "event":
            total_events += 1

            exec_count = current_event_attrs.get("Number of executions")
            if exec_count is not None:
                execution_counts[exec_count] += 1

            section = current_event_attrs.get("Section")
            if section is not None:
                section_values[section] += 1

            org_group = current_event_attrs.get("org:group")
            if org_group is not None:
                org_group_values[org_group] += 1

            spec = current_event_attrs.get("Specialism code")
            if spec is not None:
                specialism_event_values[spec] += 1

            ts_raw = current_event_attrs.get("time:timestamp")
            if ts_raw:
                # crude check: does the string contain a non-"00:00:00" time?
                if "T00:00:00" not in ts_raw:
                    non_midnight_timestamp_count += 1
                date_part = ts_raw.split("T")[0]
                if current_case_id is not None:
                    distinct_case_day_pairs.add((current_case_id, date_part))

            elem.clear()

        elif tag == "trace":
            elem.clear()

        stack.pop()

    return {
        "total_events": total_events,
        "execution_counts": execution_counts,
        "section_values": section_values,
        "org_group_values": org_group_values,
        "specialism_event_values": specialism_event_values,
        "non_midnight_timestamp_count": non_midnight_timestamp_count,
        "distinct_case_day_pairs": len(distinct_case_day_pairs),
    }


def print_report(r):
    print("=" * 70)
    print("BPIC 2011 XES FOLLOW-UP REPORT")
    print("=" * 70)

    print(f"\nTotal events: {r['total_events']:,}")

    print("\n--- Number of executions (raw values) ---")
    for val, count in sorted(r["execution_counts"].items(), key=lambda kv: -kv[1]):
        print(f"  value='{val}'  count={count:,}")
    non_one = sum(c for v, c in r["execution_counts"].items() if v != "1")
    print(f"\n  Events where Number of executions != '1': {non_one:,} "
          f"({100 * non_one / r['total_events']:.4f}% of all events)")

    print(f"\n--- Section: {len(r['section_values'])} distinct values ---")
    for val, count in r["section_values"].most_common():
        print(f"  {count:>8,}  {val}")

    print(f"\n--- org:group: {len(r['org_group_values'])} distinct values ---")
    for val, count in r["org_group_values"].most_common():
        print(f"  {count:>8,}  {val}")

    print(f"\n--- Specialism code (event-level): {len(r['specialism_event_values'])} distinct values ---")
    for val, count in r["specialism_event_values"].most_common(15):
        print(f"  {count:>8,}  {val}")

    print("\n--- Timestamp clustering ---")
    print(f"Events with a non-midnight time component: {r['non_midnight_timestamp_count']:,} "
          f"({100 * r['non_midnight_timestamp_count'] / r['total_events']:.4f}% of all events)")
    print(f"Distinct (case, calendar-day) pairs: {r['distinct_case_day_pairs']:,}")
    print(f"Average events per (case, day): {r['total_events'] / r['distinct_case_day_pairs']:.2f}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inspect_xes_followup.py <path_to_xes_file>")
        sys.exit(1)

    path = sys.argv[1]
    print(f"Inspecting {path} ...\n")
    result = followup_inspect(path)
    print_report(result)