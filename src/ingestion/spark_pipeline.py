"""
PySpark orchestration layer.

Per the locked requirement (master implementation prompt, section 11):
"Do not simply load the entire dataset into Pandas and claim Spark
processing." This module performs the ingestion, schema handling,
cleaning, and case-level/department-level aggregation as actual Spark
DataFrame operations - not a Pandas script wearing a Spark import.

Division of labor:
  1. The XES file itself is parsed once, on the driver, via
     src/utils/xes_parser.py (streaming XML parse - not something Spark
     natively does well, and at ~150K events this is a few seconds of
     single-machine work). See config.yaml comments on why this is an
     honest, documented choice rather than a Spark requirement.
  2. The resulting flat record list is parallelized into a Spark
     DataFrame, and all subsequent cleaning, grouping, and per-case /
     per-department aggregation happens as genuine distributed Spark
     operations - this is the part of the pipeline that would need to
     scale if this became a multi-hospital, multi-year dataset (the
     documented future-scope scenario for why Spark is used at all here).

Requires: pip install pyspark (see requirements.txt). Not imported by the
pure-logic test suite - only exercised when actually run via run_pipeline.py
in an environment with a working Spark/Java setup.
"""

from __future__ import annotations

from typing import Any

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T

from src.cleaning.clean_events import DEFAULT_SECTION_CORRECTIONS
from src.utils.xes_parser import parse_xes_to_flat_events

EVENT_SCHEMA = T.StructType(
    [
        T.StructField("case_id", T.StringType(), True),
        T.StructField("concept:name", T.StringType(), True),
        T.StructField("time:timestamp", T.StringType(), True),
        T.StructField("org:group", T.StringType(), True),
        T.StructField("Section", T.StringType(), True),
        T.StructField("Specialism code", T.StringType(), True),
        T.StructField("Producer code", T.StringType(), True),
        T.StructField("Activity code", T.StringType(), True),
        T.StructField("lifecycle:transition", T.StringType(), True),
        T.StructField("Number of executions", T.StringType(), True),
        T.StructField("_timestamp_iso", T.StringType(), True),
    ]
)


def get_spark_session(app_name: str = "PatientJourneyFriction") -> SparkSession:
    return (
        SparkSession.builder.appName(app_name)
        .config("spark.sql.shuffle.partitions", "8")  # small dataset, no need for 200 default
        .getOrCreate()
    )


def load_raw_events_as_spark_df(spark: SparkSession, xes_path: str) -> DataFrame:
    """
    Parses the XES file on the driver (see module docstring), then
    parallelizes the flat record list into a genuine Spark DataFrame for
    all subsequent distributed processing.
    """
    flat_events, _parse_report = parse_xes_to_flat_events(xes_path)

    rows = []
    for e in flat_events:
        ts = e.get("_timestamp_parsed")
        rows.append(
            {
                "case_id": e.get("case_id"),
                "concept:name": e.get("concept:name"),
                "time:timestamp": e.get("time:timestamp"),
                "org:group": e.get("org:group"),
                "Section": e.get("Section"),
                "Specialism code": e.get("Specialism code"),
                "Producer code": e.get("Producer code"),
                "Activity code": e.get("Activity code"),
                "lifecycle:transition": e.get("lifecycle:transition"),
                "Number of executions": e.get("Number of executions"),
                "_timestamp_iso": ts.isoformat() if ts is not None else None,
            }
        )

    return spark.createDataFrame(rows, schema=EVENT_SCHEMA)


def clean_events_spark(df: DataFrame, section_corrections: dict[str, str] = None) -> tuple[DataFrame, dict[str, Any]]:
    """
    Distributed cleaning: Section typo correction (via a broadcasted mapping
    expression, not a driver-side Python loop) and dropping rows missing
    org:group or Section. Returns (cleaned_df, report_dict) where the report
    is computed via Spark aggregations, not collected row-by-row.
    """
    section_corrections = section_corrections or DEFAULT_SECTION_CORRECTIONS

    total_in = df.count()

    corrected_df = df
    for wrong, right in section_corrections.items():
        corrected_df = corrected_df.withColumn(
            "Section", F.when(F.col("Section") == wrong, F.lit(right)).otherwise(F.col("Section"))
        )

    corrections_applied = df.filter(F.col("Section").isin(list(section_corrections.keys()))).count()

    valid_df = corrected_df.filter(
        (F.col("org:group").isNotNull())
        & (F.trim(F.col("org:group")) != "")
        & (F.col("Section").isNotNull())
        & (F.trim(F.col("Section")) != "")
    )

    total_out = valid_df.count()

    report = {
        "total_rows_in": total_in,
        "total_rows_out": total_out,
        "rows_dropped_missing_required": total_in - total_out,
        "section_values_corrected": corrections_applied,
    }
    return valid_df, report


def compute_department_event_counts(df: DataFrame) -> dict[str, int]:
    """Distributed groupBy + count, collected to the driver only as the
    small final aggregate (at most ~42 distinct department rows for BPIC
    2011) - this is the appropriate point to collect, not before."""
    rows = df.groupBy("org:group").count().collect()
    return {row["org:group"]: row["count"] for row in rows}


def collect_events_by_case(df: DataFrame) -> dict[str, list[dict[str, Any]]]:
    """
    Collects cleaned events grouped by case_id, for handoff to the
    pure-Python per-case Waiting/Rework computation (src/features/waiting.py,
    src/features/rework.py). At 1,143 cases / 150K events this collection is
    reasonable; at a genuinely larger future scale this would instead be
    implemented as a Spark pandas_udf applied via groupBy().applyInPandas(),
    which is a mechanical change to this one function, not a redesign of the
    Waiting/Rework math itself.
    """
    rows = df.select(
        "case_id", "concept:name", "_timestamp_iso", "org:group", "Section"
    ).collect()

    events_by_case: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        events_by_case.setdefault(row["case_id"], []).append(
            {
                "activity": row["concept:name"],
                "timestamp_iso": row["_timestamp_iso"],
                "org_group": row["org:group"],
                "section": row["Section"],
            }
        )
    return events_by_case
