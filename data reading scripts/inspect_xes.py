"""
BPIC 2011 XES Inspection Script
--------------------------------
Reads only schema-level, aggregate, and sample information from an XES event log
WITHOUT loading the entire file into memory and WITHOUT any external dependencies
(pm4py, pandas, etc. are not required). Uses xml.etree.ElementTree.iterparse to
stream the file and clears each <trace>/<event> element after processing.

This is safe to run against a file "too large to upload" since nothing leaves
your machine and memory use stays roughly constant regardless of file size.

Usage (PowerShell):
    python inspect_xes.py "Hospital_log.xes"

Optional second argument sets the JSON summary output path (defaults to
bpic2011_inspection_summary.json in the current directory):
    python inspect_xes.py "Hospital_log.xes" summary.json
"""

import sys
import os
import json
import re
from collections import Counter
from datetime import datetime

ATTR_TAGS = {"string", "date", "int", "float", "boolean", "id", "list"}
SAMPLE_TRACE_LIMIT = 2
SAMPLE_EVENTS_PER_TRACE = 3
TOP_N_ACTIVITIES = 20


def parse_xes_timestamp(raw):
    if raw is None:
        return None
    # Try native ISO parsing first (handles offsets like +01:00 on Python 3.11+)
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
    # Fallback: strip milliseconds and try common XES formats
    cleaned = re.sub(r"\.\d+", "", raw)
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def inspect_xes(path):
    import xml.etree.ElementTree as ET

    file_size_bytes = os.path.getsize(path)

    trace_count = 0
    event_count = 0
    trace_attr_keys = Counter()
    event_attr_keys = Counter()          # fill-count per event-level key
    activity_values = Counter()          # concept:name on events
    activity_code_values = Counter()     # alternate 'Activity code' field, if present
    timestamp_min = None
    timestamp_max = None
    timestamp_unparseable = 0
    timestamp_present = 0

    sample_traces = []
    current_sample_trace = None

    stack = []
    current_trace_attrs = {}
    current_event_attrs = {}
    trace_event_counter = 0

    context = ET.iterparse(path, events=("start", "end"))
    for event_type, elem in context:
        # XES files typically declare a default namespace
        # (xmlns="http://www.xes-standard.org"), which makes ElementTree
        # report tags as "{http://www.xes-standard.org}trace" instead of
        # "trace". Strip the namespace so plain tag comparisons work.
        raw_tag = elem.tag
        tag = raw_tag.split("}", 1)[1] if raw_tag.startswith("{") else raw_tag

        if event_type == "start":
            stack.append(tag)
            if tag == "trace":
                current_trace_attrs = {}
                trace_event_counter = 0
                if len(sample_traces) < SAMPLE_TRACE_LIMIT:
                    current_sample_trace = {"trace_attrs": {}, "events": []}
            elif tag == "event":
                current_event_attrs = {}
            continue

        # --- end-tag handling ---
        if tag in ATTR_TAGS:
            key = elem.get("key")
            value = elem.get("value")
            parent = stack[-2] if len(stack) >= 2 else None
            if parent == "event":
                current_event_attrs[key] = value
            elif parent == "trace":
                current_trace_attrs[key] = value

        elif tag == "event":
            event_count += 1
            trace_event_counter += 1
            for k in current_event_attrs:
                event_attr_keys[k] += 1

            act = current_event_attrs.get("concept:name")
            if act:
                activity_values[act] += 1
            act_code = current_event_attrs.get("Activity code")
            if act_code:
                activity_code_values[act_code] += 1

            ts_raw = current_event_attrs.get("time:timestamp")
            if ts_raw:
                timestamp_present += 1
                ts = parse_xes_timestamp(ts_raw)
                if ts is None:
                    timestamp_unparseable += 1
                else:
                    if timestamp_min is None or ts < timestamp_min:
                        timestamp_min = ts
                    if timestamp_max is None or ts > timestamp_max:
                        timestamp_max = ts

            if current_sample_trace is not None and len(current_sample_trace["events"]) < SAMPLE_EVENTS_PER_TRACE:
                current_sample_trace["events"].append(dict(current_event_attrs))

            elem.clear()

        elif tag == "trace":
            trace_count += 1
            for k in current_trace_attrs:
                trace_attr_keys[k] += 1
            if current_sample_trace is not None:
                current_sample_trace["trace_attrs"] = dict(current_trace_attrs)
                current_sample_trace["total_events_in_trace"] = trace_event_counter
                sample_traces.append(current_sample_trace)
                current_sample_trace = None
            elem.clear()

        stack.pop()

    missing_stats = {
        k: {
            "present_count": count,
            "missing_count": event_count - count,
            "fill_rate_pct": round(100 * count / event_count, 2) if event_count else None,
        }
        for k, count in event_attr_keys.items()
    }

    summary = {
        "file": {
            "path": os.path.abspath(path),
            "size_bytes": file_size_bytes,
            "size_mb": round(file_size_bytes / (1024 * 1024), 2),
        },
        "row_counts": {
            "trace_count_patients": trace_count,
            "event_count_total": event_count,
            "avg_events_per_trace": round(event_count / trace_count, 2) if trace_count else None,
        },
        "schema": {
            "trace_level_keys": sorted(trace_attr_keys.keys()),
            "event_level_keys": sorted(event_attr_keys.keys()),
        },
        "activity_field": {
            "concept:name": {
                "unique_count": len(activity_values),
                "top_20": activity_values.most_common(TOP_N_ACTIVITIES),
            },
            "Activity code (if present)": {
                "unique_count": len(activity_code_values),
                "top_20": activity_code_values.most_common(TOP_N_ACTIVITIES),
            },
        },
        "timestamp_field_time:timestamp": {
            "present_count": timestamp_present,
            "missing_count": event_count - timestamp_present,
            "unparseable_count": timestamp_unparseable,
            "min_timestamp": timestamp_min.isoformat() if timestamp_min else None,
            "max_timestamp": timestamp_max.isoformat() if timestamp_max else None,
        },
        "missing_value_stats_per_event_key": missing_stats,
        "sample": sample_traces,
    }
    return summary


def print_report(summary):
    f = summary["file"]
    rc = summary["row_counts"]
    print("=" * 70)
    print("BPIC 2011 XES INSPECTION REPORT")
    print("=" * 70)
    print(f"\nFile: {f['path']}")
    print(f"Size: {f['size_mb']} MB ({f['size_bytes']:,} bytes)")

    print(f"\nCases (traces/patients): {rc['trace_count_patients']:,}")
    print(f"Events (rows) total:     {rc['event_count_total']:,}")
    print(f"Avg events per case:     {rc['avg_events_per_trace']}")

    print("\n--- Schema ---")
    print(f"Trace-level attribute keys ({len(summary['schema']['trace_level_keys'])}):")
    print("  " + ", ".join(summary["schema"]["trace_level_keys"]))
    print(f"Event-level attribute keys ({len(summary['schema']['event_level_keys'])}):")
    print("  " + ", ".join(summary["schema"]["event_level_keys"]))

    print("\n--- Activity field: concept:name ---")
    cn = summary["activity_field"]["concept:name"]
    print(f"Unique activity values: {cn['unique_count']}")
    print("Top 20 by frequency:")
    for name, count in cn["top_20"]:
        print(f"  {count:>8,}  {name}")

    ac = summary["activity_field"]["Activity code (if present)"]
    if ac["unique_count"]:
        print("\n--- Alternate field: Activity code ---")
        print(f"Unique values: {ac['unique_count']}")
        for name, count in ac["top_20"][:10]:
            print(f"  {count:>8,}  {name}")

    print("\n--- Timestamp field: time:timestamp ---")
    ts = summary["timestamp_field_time:timestamp"]
    print(f"Present: {ts['present_count']:,}  Missing: {ts['missing_count']:,}  Unparseable: {ts['unparseable_count']:,}")
    print(f"Range:   {ts['min_timestamp']}  ->  {ts['max_timestamp']}")

    print("\n--- Missing-value stats (event-level keys) ---")
    print(f"{'key':<30}{'present':>10}{'missing':>10}{'fill %':>10}")
    for k, v in sorted(summary["missing_value_stats_per_event_key"].items(), key=lambda kv: kv[1]["fill_rate_pct"]):
        print(f"{k:<30}{v['present_count']:>10,}{v['missing_count']:>10,}{v['fill_rate_pct']:>9}%")

    print("\n--- Sample (first traces) ---")
    for i, tr in enumerate(summary["sample"], start=1):
        print(f"\nTrace {i}: {tr['trace_attrs']}  (total_events_in_trace={tr['total_events_in_trace']})")
        for j, ev in enumerate(tr["events"], start=1):
            print(f"  event {j}: {ev}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inspect_xes.py <path_to_xes_file> [output_json]")
        sys.exit(1)

    xes_path = sys.argv[1]
    output_json = sys.argv[2] if len(sys.argv) > 2 else "bpic2011_inspection_summary.json"

    print(f"Inspecting {xes_path} ...\n")
    summary = inspect_xes(xes_path)
    print_report(summary)

    with open(output_json, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
    print(f"\nFull summary also written to: {output_json}")