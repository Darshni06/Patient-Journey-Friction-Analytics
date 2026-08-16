"""
Streaming XES parser (stdlib-only), producing a flat list of event dicts.

This reuses the same namespace-stripping streaming approach validated
during the dataset inspection phase (inspect_xes.py / inspect_xes_followup.py)
- BPIC 2011 declares a default XML namespace
(xmlns="http://www.xes-standard.org"), so tags must have their namespace
prefix stripped before comparison, or trace/event elements silently fail to
match (this was an actual bug hit and fixed during inspection).

The PySpark ingestion layer (src/ingestion/spark_pipeline.py) calls
`parse_xes_to_flat_events()` on the driver (single-machine XML parse - the
XES file itself, at ~81MB / 150K events, is well within what a single
process can stream-parse in seconds; see DEVIATIONS_FROM_PROMPT.md /
config.yaml comments on why Spark's role here is architectural, not a
strict necessity at this file size) and then parallelizes the resulting
flat record list into a Spark DataFrame for the actual cleaning/feature
computation, which IS where the distributed processing work happens.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

ATTR_TAGS = {"string", "date", "int", "float", "boolean", "id", "list"}


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def parse_xes_timestamp(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
    cleaned = re.sub(r"\.\d+", "", raw)
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def parse_xes_to_flat_events(path: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Streams the XES file and returns:
      (flat_events, parse_report)

    flat_events: list of dicts, one per <event>, each carrying:
      - "case_id": the trace's concept:name
      - all event-level string/date/int/etc attributes, keyed by their raw
        XES key (e.g. "concept:name", "time:timestamp", "org:group", ...)
      - "_timestamp_parsed": the parsed datetime (or None if unparseable)

    parse_report: counts of traces, events, unparseable timestamps, so the
    pipeline can log this rather than silently proceeding.
    """
    trace_count = 0
    event_count = 0
    unparseable_timestamps = 0

    flat_events: list[dict[str, Any]] = []

    stack: list[str] = []
    current_case_id: str | None = None
    current_event_attrs: dict[str, Any] = {}

    context = ET.iterparse(path, events=("start", "end"))
    for event_type, elem in context:
        tag = _strip_ns(elem.tag)

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
            event_count += 1
            row = dict(current_event_attrs)
            row["case_id"] = current_case_id
            ts_raw = current_event_attrs.get("time:timestamp")
            parsed_ts = parse_xes_timestamp(ts_raw)
            if ts_raw is not None and parsed_ts is None:
                unparseable_timestamps += 1
            row["_timestamp_parsed"] = parsed_ts
            flat_events.append(row)
            elem.clear()

        elif tag == "trace":
            trace_count += 1
            elem.clear()

        stack.pop()

    report = {
        "trace_count": trace_count,
        "event_count": event_count,
        "unparseable_timestamps": unparseable_timestamps,
    }
    return flat_events, report
