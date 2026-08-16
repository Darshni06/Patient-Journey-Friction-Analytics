"""
Parquet storage layer.

Logical tables written (matches the master spec's §33 recommended layout):
  outputs/clean_events.parquet       - cleaned, standardized event log
  outputs/patient_waiting.parquet    - per-case raw + normalized Waiting
  outputs/patient_rework.parquet     - per-case raw + normalized Rework
  outputs/patient_deviation.parquet  - per-case raw + normalized Deviation
  outputs/friction_scores.parquet    - per-case final Friction Score + breakdown
  outputs/department_stats.parquet   - department-level event/waiting stats
  outputs/activity_stats.parquet     - activity-level frequency stats

Uses pandas + pyarrow for writing (lighter weight than round-tripping
through Spark for these already-small, already-aggregated per-case
tables - the case-level tables have exactly one row per patient, ~1,143
rows for BPIC 2011). The large raw/cleaned event table IS written via the
Spark DataFrame writer directly, since that one is genuinely large-ish
(150K rows) and already lives in Spark from the ingestion layer.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd


def write_case_level_table(records: list[dict[str, Any]], output_path: str) -> None:
    if not records:
        raise ValueError(f"Refusing to write an empty table to {output_path}")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df = pd.DataFrame(records)
    df.to_parquet(output_path, index=False, engine="pyarrow")


def write_spark_events_table(spark_df, output_path: str) -> None:
    """spark_df: a pyspark.sql.DataFrame. Writes as a genuine Spark parquet
    write (partitioned output directory, not a single pandas file), since
    this is the one table where that distinction matters at this dataset's
    row count."""
    spark_df.write.mode("overwrite").parquet(output_path)


def read_case_level_table(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Expected Parquet table not found at {path}")
    return pd.read_parquet(path, engine="pyarrow")
