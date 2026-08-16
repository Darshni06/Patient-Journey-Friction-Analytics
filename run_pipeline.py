#!/usr/bin/env python3
"""
End-to-end pipeline entry point.

Usage:
    python run_pipeline.py --input Hospital_log.xes

Follows the execution sequence: validate -> ingest -> clean -> features
(waiting, rework) -> process discovery -> conformance/deviation ->
normalization -> friction score -> required correlation diagnostic ->
Parquet -> Neo4j. Each stage fails loudly on error (per the locked "no
fake data / no silent failures" requirement) rather than proceeding with
partial or fabricated results.
"""

from __future__ import annotations

import argparse
import itertools
import sys
import time
import yaml

from src.cleaning.clean_events import classify_and_drop_exact_duplicates, clean_events
from src.features.normalization import clip_and_normalize
from src.features.rework import compute_rework_for_all_cases
from src.features.waiting import Event, compute_waiting_for_all_cases
from src.friction.friction_score import (
    FrictionComponents,
    compute_component_correlation_diagnostic,
    compute_friction_for_all_cases,
)
from src.process_mining.discovery import apply_department_collapse, compute_department_collapse
from src.storage.parquet_io import write_case_level_table
from src.utils.xes_parser import parse_xes_to_flat_events
from src.validation.inspect_log import print_validation_report, validate_dataset


def load_config(path: str = "configs/config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def stage(name: str):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            print(f"\n{'=' * 70}\nSTAGE: {name}\n{'=' * 70}")
            start = time.time()
            result = fn(*args, **kwargs)
            print(f"[{name}] completed in {time.time() - start:.2f}s")
            return result

        return wrapper

    return decorator


@stage("Phase 1 - Validate raw XES file")
def phase_1_validate(xes_path: str):
    report = validate_dataset(xes_path)
    print_validation_report(report)
    return report


@stage("Phase 2 - Ingest and clean")
def phase_2_ingest_and_clean(xes_path: str, cfg: dict):
    flat_events, parse_report = parse_xes_to_flat_events(xes_path)
    print(f"Parsed {parse_report['event_count']:,} events across {parse_report['trace_count']:,} cases")

    cleaned, clean_report = clean_events(
        flat_events,
        section_corrections=cfg["cleaning"]["section_value_corrections"],
        required_non_null_keys=tuple(cfg["cleaning"]["drop_rows_missing_keys"]),
    )
    print(
        f"Cleaning: {clean_report.total_rows_in:,} in -> {clean_report.total_rows_out:,} out "
        f"({clean_report.rows_dropped_missing_required} dropped, "
        f"{clean_report.section_values_corrected} Section values corrected)"
    )
    return cleaned, clean_report


@stage("Phase 2b - Duplicate detection and exact-duplicate removal")
def phase_2b_deduplicate(cleaned_events: list[dict], cfg: dict):
    deduped, dup_report = classify_and_drop_exact_duplicates(cleaned_events)
    print(
        f"Duplicate groups (same case_id + activity + timestamp): "
        f"{dup_report.total_coarse_duplicate_groups:,}\n"
        f"  -> FULL exact duplicates (dropped, kept 1 each): "
        f"{dup_report.full_exact_duplicate_groups:,} groups, "
        f"{dup_report.rows_dropped_as_exact_duplicates:,} rows removed\n"
        f"  -> PARTIAL duplicates (retained - differ in >=1 other field): "
        f"{dup_report.partial_duplicate_groups:,} groups"
    )
    if dup_report.total_coarse_duplicate_groups > 0:
        print(
            "  NOTE: this default (drop full, keep partial) is provisional. "
            "Run scripts/inspect_duplicates.py against this file and review "
            "the examples before treating Rework results as final - see "
            "DEVIATIONS_FROM_PROMPT.md."
        )
    return deduped, dup_report


def _group_events_by_case(cleaned_events: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for e in cleaned_events:
        grouped.setdefault(e["case_id"], []).append(e)
    return grouped


@stage("Phase 4/5 - Compute Waiting and Rework features")
def phase_4_5_features(cleaned_events: list[dict], cfg: dict):
    by_case = _group_events_by_case(cleaned_events)

    waiting_events_by_case = {}
    activities_by_case = {}
    for case_id, events in by_case.items():
        waiting_events_by_case[case_id] = [
            Event(activity=e["concept:name"], timestamp=e["_timestamp_parsed"])
            for e in events
            if e.get("_timestamp_parsed") is not None
        ]
        activities_by_case[case_id] = [e["concept:name"] for e in events]

    waiting_results = compute_waiting_for_all_cases(
        waiting_events_by_case,
        admin_keywords=tuple(cfg["waiting"]["administrative_activity_keywords"]),
    )
    rework_results = compute_rework_for_all_cases(
        activities_by_case,
        use_log_dampening=cfg["rework"]["use_log_dampening"],
    )

    n_anomalies = sum(len(r.anomalies) for r in waiting_results.values())
    print(f"Computed Waiting for {len(waiting_results)} cases ({n_anomalies} timestamp anomalies reported)")
    print(f"Computed Rework for {len(rework_results)} cases")

    return waiting_results, rework_results


@stage("Phase 6 - Process discovery alphabet (department collapsing)")
def phase_6_discovery_alphabet(cleaned_events: list[dict], cfg: dict):
    from collections import Counter

    org_counts = Counter(e["org:group"] for e in cleaned_events)
    collapse = compute_department_collapse(
        dict(org_counts), coverage_threshold=cfg["process_discovery"]["cumulative_coverage_threshold"]
    )
    print(
        f"Kept {len(collapse.kept_departments)} departments individually "
        f"(cumulative coverage {collapse.cumulative_coverage_at_cutoff:.1%}); "
        f"collapsed {len(collapse.collapsed_departments)} into 'Other department'"
    )
    print(f"Kept: {sorted(collapse.kept_departments)}")
    return collapse


@stage("Phase 8/9 - Normalize components and compute Friction Score")
def phase_8_9_friction(waiting_results, rework_results, deviation_by_case: dict[str, float], cfg: dict):
    raw_waiting = {cid: r.total_wait_seconds for cid, r in waiting_results.items()}
    raw_rework = {cid: r.rework_score for cid, r in rework_results.items()}

    common_ids = sorted(set(raw_waiting) & set(raw_rework) & set(deviation_by_case))
    if len(common_ids) < len(raw_waiting):
        missing = len(raw_waiting) - len(common_ids)
        print(f"WARNING: {missing} case(s) missing a deviation value and were excluded from scoring.")

    raw_waiting = {k: raw_waiting[k] for k in common_ids}
    raw_rework = {k: raw_rework[k] for k in common_ids}
    raw_deviation = {k: deviation_by_case[k] for k in common_ids}

    norm_cfg = cfg["normalization"]
    norm_w = clip_and_normalize(raw_waiting, norm_cfg["lower_percentile"], norm_cfg["upper_percentile"])
    norm_r = clip_and_normalize(raw_rework, norm_cfg["lower_percentile"], norm_cfg["upper_percentile"])
    norm_d = clip_and_normalize(raw_deviation, norm_cfg["lower_percentile"], norm_cfg["upper_percentile"])

    if cfg["friction_score"]["require_component_correlation_check"]:
        diag = compute_component_correlation_diagnostic(raw_waiting, raw_rework, raw_deviation)
        print(
            f"\nREQUIRED VALIDITY CHECK - raw component correlations:\n"
            f"  corr(W,R) = {diag.corr_waiting_rework:.3f}\n"
            f"  corr(W,D) = {diag.corr_waiting_deviation:.3f}\n"
            f"  corr(R,D) = {diag.corr_rework_deviation:.3f}"
        )
        if diag.warning:
            print(f"  WARNING: {diag.warning}")

    weights = (
        cfg["friction_score"]["weight_waiting"],
        cfg["friction_score"]["weight_rework"],
        cfg["friction_score"]["weight_deviation"],
    )
    components = {
        cid: FrictionComponents(
            case_id=cid,
            waiting_norm=norm_w.normalized[cid],
            rework_norm=norm_r.normalized[cid],
            deviation_norm=norm_d.normalized[cid],
        )
        for cid in common_ids
    }
    friction_results = compute_friction_for_all_cases(components, weights)

    scores = [r.friction_score for r in friction_results.values()]
    print(f"\nFriction Score computed for {len(scores)} cases. "
          f"Range: [{min(scores):.3f}, {max(scores):.3f}], mean {sum(scores)/len(scores):.3f}")

    return friction_results


@stage("Phase 7 - pm4py process discovery over collapsed departments")
def phase_7_discover_model(cleaned_events: list[dict], collapse, cfg: dict):
    import pandas as pd

    from src.process_mining.discovery import discover_process_model, ensure_pm4py_timestamp_dtype

    rows = []
    n_skipped_null_timestamp = 0
    for e in cleaned_events:
        ts = e.get("_timestamp_parsed")
        if ts is None:
            n_skipped_null_timestamp += 1
            continue
        rows.append(
            {
                "case:concept:name": e["case_id"],
                "concept:name": apply_department_collapse(
                    e["org:group"], collapse, cfg["process_discovery"]["other_department_label"]
                ),
                "time:timestamp": ts,
            }
        )

    if n_skipped_null_timestamp > 0:
        print(f"NOTE: {n_skipped_null_timestamp} event(s) had no parseable timestamp "
              f"and were excluded from process discovery (they are not silently "
              f"dropped elsewhere - Waiting/Rework already handle them separately).")

    event_log_df = pd.DataFrame(rows)

    # Explicitly coerce 'time:timestamp' to a real pandas datetime64 dtype and
    # validate there are no nulls before handing this off to pm4py. This is
    # done here (not only inside discover_process_model) so any timestamp
    # problem is caught with full context at the point the discovery event
    # log is built, rather than surfacing as a bare exception from inside
    # pm4py's internal dtype check.
    event_log_df = ensure_pm4py_timestamp_dtype(event_log_df, "time:timestamp")
    print(f"Timestamp column dtype after coercion: {event_log_df['time:timestamp'].dtype}")

    print(f"Built discovery event log: {len(event_log_df):,} events over "
          f"{event_log_df['concept:name'].nunique()} collapsed department labels")

    net, im, fm = discover_process_model(
        event_log_df, noise_threshold=cfg["process_discovery"]["inductive_miner_noise_threshold"]
    )
    print(f"Discovered Petri net: {len(net.places)} places, {len(net.transitions)} transitions")
    return event_log_df, net, im, fm


@stage("Phase 7b - Conformance checking (pathway deviation)")
def phase_7b_conformance(event_log_df, net, im, fm, cfg: dict):
    from src.process_mining.conformance import compute_deviation_for_dataset

    pd_cfg = cfg["process_discovery"]
    conformance_method = pd_cfg.get("conformance_method", "auto")
    time_budget = pd_cfg.get("alignment_time_budget_seconds", 300)

    print(
        f"Requested conformance_method='{conformance_method}', "
        f"alignment_time_budget_seconds={time_budget} "
        f"(configs/config.yaml: process_discovery.conformance_method / alignment_time_budget_seconds)"
    )

    raw_deviation, run_report = compute_deviation_for_dataset(
        event_log_df, net, im, fm,
        conformance_method=conformance_method,
        alignment_time_budget_seconds=time_budget,
    )

    # This is the explicit, unambiguous statement of which conformance
    # method was ACTUALLY used, printed regardless of what was requested -
    # required so the final report never leaves this ambiguous.
    print("\n" + "=" * 70)
    print(f"CONFORMANCE METHOD ACTUALLY USED: {run_report.method_used.upper()}")
    print("=" * 70)
    print(f"  Requested method:              {run_report.requested_method}")
    print(f"  Cases scored:                  {run_report.n_cases:,}")
    print(f"  Distinct variants:             {run_report.n_variants:,}")
    print(f"  Variants completed via alignment: {run_report.n_variants_completed_via_alignment:,} / {run_report.n_variants:,}")
    print(f"  Elapsed (alignment attempt):   {run_report.elapsed_seconds:.1f}s")
    if run_report.fallback_triggered:
        print(f"  FALLBACK TRIGGERED: {run_report.fallback_reason}")
        print(f"  -> Every case's Deviation value in this run comes from TOKEN-BASED REPLAY, "
              f"not alignments, to keep D_p comparable across all cases.")
    print("=" * 70)

    return raw_deviation, run_report


@stage("Phase 10 - Write Parquet outputs")
def phase_10_write_parquet(
    cleaned_events: list[dict],
    waiting_results,
    rework_results,
    raw_deviation: dict[str, float],
    friction_results,
    conformance_report=None,
    output_dir: str = "outputs",
):
    import os

    os.makedirs(output_dir, exist_ok=True)

    events_records = [
        {
            "case_id": e["case_id"],
            "concept:name": e["concept:name"],
            "org:group": e["org:group"],
            "Section": e["Section"],
            "_timestamp_iso": e["_timestamp_parsed"].isoformat() if e.get("_timestamp_parsed") else None,
        }
        for e in cleaned_events
    ]
    write_case_level_table(events_records, os.path.join(output_dir, "clean_events.parquet"))

    waiting_records = [
        {
            "case_id": cid,
            "total_wait_seconds": r.total_wait_seconds,
            "anomaly_count": len(r.anomalies),
            "excluded_administrative_events": r.excluded_administrative_events,
        }
        for cid, r in waiting_results.items()
    ]
    write_case_level_table(waiting_records, os.path.join(output_dir, "patient_waiting.parquet"))

    rework_records = [
        {"case_id": cid, "rework_score": r.rework_score, "total_events": r.total_events}
        for cid, r in rework_results.items()
    ]
    write_case_level_table(rework_records, os.path.join(output_dir, "patient_rework.parquet"))

    deviation_method = conformance_report.method_used if conformance_report is not None else "unknown"
    deviation_records = [
        {"case_id": cid, "raw_deviation_cost": v, "deviation_method": deviation_method}
        for cid, v in raw_deviation.items()
    ]
    write_case_level_table(deviation_records, os.path.join(output_dir, "patient_deviation.parquet"))

    friction_records = [
        {
            "case_id": cid,
            "waiting_norm": r.waiting_norm,
            "rework_norm": r.rework_norm,
            "deviation_norm": r.deviation_norm,
            "friction_score": r.friction_score,
            "dominant_component": r.dominant_component,
            "deviation_method": deviation_method,
        }
        for cid, r in friction_results.items()
    ]
    write_case_level_table(friction_records, os.path.join(output_dir, "friction_scores.parquet"))

    print(f"Wrote 5 Parquet tables to {output_dir}/ (deviation_method='{deviation_method}' recorded on every row)")


def main():
    parser = argparse.ArgumentParser(description="Patient Journey Friction Analytics pipeline")
    parser.add_argument("--input", required=True, help="Path to the BPIC 2011 Hospital_log.xes file")
    parser.add_argument("--config", default="configs/config.yaml")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument(
        "--conformance-method",
        choices=["alignments", "token_based_replay", "auto"],
        default=None,
        help="Override configs/config.yaml's process_discovery.conformance_method for this run. "
             "'token_based_replay' is the fastest/safest option on constrained hardware.",
    )
    parser.add_argument(
        "--skip-process-mining",
        action="store_true",
        help="Skip pm4py discovery/conformance (requires pm4py installed); "
             "useful for validating the rest of the pipeline without that dependency. "
             "No Friction Scores are produced with this flag set.",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.conformance_method is not None:
        cfg["process_discovery"]["conformance_method"] = args.conformance_method

    phase_1_validate(args.input)
    cleaned_events, clean_report = phase_2_ingest_and_clean(args.input, cfg)
    cleaned_events, dup_report = phase_2b_deduplicate(cleaned_events, cfg)
    waiting_results, rework_results = phase_4_5_features(cleaned_events, cfg)
    collapse = phase_6_discovery_alphabet(cleaned_events, cfg)

    if args.skip_process_mining:
        print(
            "\n--skip-process-mining set: Deviation component and Friction "
            "Scores not computed. Re-run without this flag to produce them."
        )
        sys.exit(0)

    event_log_df, net, im, fm = phase_7_discover_model(cleaned_events, collapse, cfg)
    raw_deviation, conformance_report = phase_7b_conformance(event_log_df, net, im, fm, cfg)
    friction_results = phase_8_9_friction(waiting_results, rework_results, raw_deviation, cfg)
    phase_10_write_parquet(
        cleaned_events, waiting_results, rework_results, raw_deviation, friction_results,
        conformance_report=conformance_report, output_dir=args.output_dir,
    )

    print(f"\nPipeline complete. Deviation computed via: {conformance_report.method_used.upper()}. "
          f"Run: streamlit run dashboard/app.py")



if __name__ == "__main__":
    main()