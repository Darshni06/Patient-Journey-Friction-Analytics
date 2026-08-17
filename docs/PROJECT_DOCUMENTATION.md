# Patient Journey Friction Analytics (PJFA) — Complete Project Documentation

**Status of this document:** every claim below is either (a) something actually
implemented and present in the codebase, (b) something actually run and observed in
this project's real execution logs, or (c) explicitly labeled as planned/future and
kept separate from the V1 description. Where a result was not directly observed in
the provided logs, this document says so rather than inferring or estimating a
number. Sections describing V2/future ideas or novelty directions are clearly
separated from the V1 description and must not be read as claims about what V1
currently does.

---

## 1. Project Title and One-Line Objective

**Patient Journey Friction Analytics (PJFA)** — a batch research analytics pipeline
that transforms the BPIC 2011 hospital event log into an explainable, patient-level
Friction Score combining waiting burden, rework, and pathway deviation.

---

## 2. Problem Statement

Traditional healthcare process mining reports aggregate, activity-level statistics —
which activities are bottlenecks, what the average waiting time is, which process
variants are most common. These describe the *process*, not any individual patient's
journey. There is no standard, reproducible way to summarize a single patient's
observable process burden and complexity as one interpretable number.

**Research question:** Can a composite patient-level Friction Score, combining
waiting burden, rework, and pathway deviation, provide a more informative
representation of healthcare journey complexity than waiting time alone, when
derived from hospital event logs?

---

## 3. Motivation

Two patients can have very different journeys that traditional bottleneck analysis
treats as similar (or vice versa). A patient who waits a long time but follows a
simple linear path is operationally different from a patient with short waits but
substantial repetition and an unusual pathway. Waiting-time analysis alone does not
distinguish these. A composite, explainable, patient-level metric makes this
difference visible and comparable across a cohort.

---

## 4. What Existing Hospital Process-Mining Systems Typically Do

Based on standard process-mining practice (process discovery tools, conformance
checking, and dashboarding as used across the process-mining literature and common
commercial/open-source tooling such as pm4py, Disco, Celonis):

- Discover an aggregate process model from the full event log.
- Report bottleneck activities/transitions by average or median waiting time.
- Report the most frequent process variants.
- Run conformance checking to report *aggregate* deviation statistics (e.g., overall
  fitness score, most common deviations across the whole log).
- Dashboard these as process-level KPIs.

What is typically **absent**: a single combined, explainable, per-patient score that
fuses temporal, repetition, and structural-deviation burden into one interpretable
number with a documented formula and explicit component breakdown per case.

---

## 5. What V1 Does Differently

- Combines three separately-computed, normalized components (Waiting, Rework,
  Deviation) into one explainable per-case Friction Score, `F_p = (W_p + R_p + D_p)/3`.
- Requires (not just permits) an explicit correlation check between the three raw
  components before any interpretation is drawn, specifically to test whether the
  composite genuinely adds information beyond waiting time alone.
- Documents every data-cleaning and definitional decision with evidence from the
  actual dataset (not assumed defaults) — e.g., the exact administrative-keyword
  exclusion list for Waiting, the log-dampened Rework formula, the derived
  department-collapsing threshold.
- Provides a per-case explainability view (Patient Journey Explorer) showing exactly
  which component drives a given patient's score.
- Explicitly documents which conformance method (alignment-based vs. token-based
  replay) was used for a given run, since this affects how Deviation was computed.

---

## 6. Exact Scope and Non-Scope

**In scope (V1):**
- Batch analysis of a single historical XES event log (BPIC 2011).
- Waiting, Rework, Deviation computation and combination into a Friction Score.
- Process discovery and conformance checking over a department-collapsed alphabet.
- Parquet output tables and a Streamlit dashboard reading from them.

**Explicitly out of scope (V1) — not implemented, not planned for V1:**
- Live hospital data, real-time monitoring, Kafka/streaming ingestion.
- Multiple hospitals or datasets.
- Clinical decision support of any kind.
- Patient-satisfaction prediction or any claim that Friction correlates with
  satisfaction, distress, or care quality.
- Machine-learning prediction, learned/optimized component weights.
- External validation against real patient complaints/surveys.

---

## 7. Dataset: BPIC 2011 — Actual Measured Statistics

All figures below are from actual inspection/validation runs against the real
`Hospital_log.xes` file (not assumed or estimated), computed dynamically by the
pipeline's validation stage on every run — never hard-coded.

| Metric | Value |
|---|---|
| File size | 81.41 MB |
| Cases (patients/traces) | 1,143 |
| Events (total) | 150,291 |
| Average events per case | 131.49 |
| Distinct activities (`concept:name`) | 624 |
| Distinct `Activity code` values | 675 |
| Distinct `org:group` (department) values | 43 (per full-file validation run) / 42 (per an earlier follow-up inspection pass) — both counts observed in different inspection runs against the same file; documented as observed rather than reconciled to a single number |
| Distinct `Section` values | 8 |
| Timestamp range | 2005-01-03 to 2008-03-20 |
| Events with a non-midnight (genuine intraday) timestamp | 57.9% of events |
| Events with an exact-midnight timestamp | 42.1% of events |
| `Number of executions` ≠ `"1"` | 1,757 events (1.17%) |
| Missing `org:group` | 16 events |
| Missing `Section` | 16 events |
| Known `Section` typo (`"Sectoin 7"`) occurrences | 32 events |
| Duplicate `(case_id, activity, timestamp)` groups | 13,396 groups, 25,379 events involved |
| — of which FULL exact duplicates (dropped) | 10,679 groups, 18,725 rows removed |
| — of which PARTIAL duplicates (retained) | 2,717 groups |

**After cleaning + deduplication (actual observed pipeline output):**
150,291 → 150,275 events after cleaning (16 dropped for missing fields, 32 `Section`
values corrected) → 131,550 events after exact-duplicate removal.

**Department collapsing (actual observed pipeline output):** 7 departments kept
individually (cumulative coverage 95.9–96.3%, observed across two runs), 35 collapsed
into `"Other department"`, giving an 8-label discovery alphabet:
`General Lab Clinical Chemistry`, `Internal Specialisms clinic`,
`Medical Microbiology`, `Nursing ward`, `Obstetrics & Gynaecology clinic`,
`Radiology`, `Radiotherapy`, plus `Other department`.

---

## 8. Complete Architecture

```
Hospital_log.xes
      ↓
Validation (src/validation/inspect_log.py) — file stats computed fresh every run
      ↓
XES parsing (src/utils/xes_parser.py) — pure-Python streaming XML parse
      ↓
Cleaning (src/cleaning/clean_events.py) — Section typo fix, missing-value drop
      ↓
Duplicate handling (src/cleaning/clean_events.py) — full-exact-duplicate removal
      ↓
Feature extraction: Waiting, Rework (src/features/)
      ↓
Department collapsing (src/process_mining/discovery.py)
      ↓
pm4py process discovery (Inductive Miner) (src/process_mining/discovery.py)
      ↓
pm4py conformance checking, variant-cached + time-budgeted (src/process_mining/conformance.py)
      ↓
Normalization + Friction Score engine (src/friction/friction_score.py)
      ↓
Parquet output (src/storage/parquet_io.py)
      ↓
Streamlit + Plotly dashboard (dashboard/app.py)
```

**Important honesty note on two architecture components that exist as code but are
NOT currently wired into the executed pipeline:**
- `src/ingestion/spark_pipeline.py` (PySpark ingestion/cleaning module) is fully
  written and syntax-checked, but `run_pipeline.py`'s actual execution path does
  **not** import or call it. The pipeline that has actually been run end-to-end uses
  the pure-Python `xes_parser` and pure-Python cleaning/feature modules, not Spark.
- `src/storage/neo4j_loader.py` (Neo4j graph loader) is fully written with a defined
  node/relationship schema and example Cypher queries, but neither `run_pipeline.py`
  nor `dashboard/app.py` currently instantiate or call it. No Neo4j server has been
  started or loaded with data in this project's actual execution history.

Both are described further in their own sections below, with this same distinction
repeated so it isn't missed.

---

## 9. Every Technology and Why It Is Used

| Technology | Why | Actually executed in this project? |
|---|---|---|
| **Python** | Core implementation language | Yes |
| **pandas / pyarrow** | Tabular data handling, Parquet I/O, pm4py's dataframe interface | Yes |
| **PySpark** | Demonstrates a production-style, horizontally-scalable ingestion architecture that would be necessary for multi-hospital/multi-year data (an explicit future-scope scenario) — not because the 81 MB BPIC 2011 file itself requires distributed processing | Module written, **not wired into the executed pipeline** (see §8) |
| **pm4py** | Process discovery (Inductive Miner) and conformance checking (alignments / token-based replay) | Yes — discovery confirmed working after a timestamp-dtype fix; conformance confirmed working after a variant-caching + time-budget fallback fix |
| **Parquet** | Efficient columnar storage for the per-case output tables the dashboard reads | Yes |
| **Neo4j** | Path/loop/journey graph queries (repeated-activity detection, transition-frequency graphs) that are natural Cypher pattern matches vs. awkward SQL self-joins | Module written, **not wired into the executed pipeline** (see §8) |
| **Streamlit + Plotly** | Interactive dashboard | Yes — confirmed running, one rendering bug found and fixed (see §22) |
| **pytest** | Test suite | Yes — 82 tests, all passing (validated via a stdlib-only local shim in the assistant's sandbox due to a network restriction there; the project's real `pytest` in `requirements.txt` is what you run) |
| **PyYAML** | Loads `configs/config.yaml`, which holds every locked threshold in one place | Yes |

---

## 10. Complete Pipeline: Input → Output

```
python run_pipeline.py --input Hospital_log.xes
```

1. **Validate** the raw XES file (fresh stats every run — file size, case/event
   counts, distinct activities/departments/sections, timestamp range, missing values,
   duplicate counts, known typo occurrences).
2. **Ingest and clean**: parse XES → correct the `Section` typo → drop rows missing
   `org:group`/`Section`.
3. **Deduplicate**: classify duplicate `(case_id, activity, timestamp)` groups into
   full-exact (dropped) vs. partial (retained); report both counts.
4. **Compute Waiting and Rework** per case.
5. **Collapse departments** (`org:group` → kept departments + `"Other department"`).
6. **Discover a process model** (pm4py Inductive Miner) over the collapsed alphabet.
7. **Compute Deviation** via conformance checking (variant-cached alignments, with an
   automatic, documented fallback to token-based replay if a time budget is
   exceeded).
8. **Normalize** all three raw components (percentile clip + min-max) and run the
   required raw-component correlation diagnostic.
9. **Combine** into the Friction Score, `F_p = (W_p + R_p + D_p)/3`.
10. **Write Parquet outputs**: `clean_events.parquet`, `patient_waiting.parquet`,
    `patient_rework.parquet`, `patient_deviation.parquet`, `friction_scores.parquet`.
11. **Dashboard**: `streamlit run dashboard/app.py` reads these Parquet files.

---

## 11. Exact Data-Cleaning Rules

- `"Sectoin 7"` → corrected to `"Section 7"` (confirmed typo, 32 events in the real
  file).
- Any event missing `org:group` or `Section` (non-null, non-blank check) is
  **dropped**, not imputed. 16 events dropped in the real file.
- No other row-level modification happens during cleaning. All drops/corrections are
  counted and reported, never silent.

---

## 12. Duplicate-Event Handling

Events sharing an identical `(case_id, activity, timestamp)` key are classified into
two categories by comparing every other captured field
(`org:group`, `Section`, `Specialism code`, `Producer code`, `Activity code`,
`lifecycle:transition`, `Number of executions`):

- **Full exact duplicates** (identical across every field) — dropped, keeping one row
  per group. 10,679 groups / 18,725 rows in the real file.
- **Partial duplicates** (differ in ≥1 other field) — retained untouched, treated as
  likely-legitimate distinct events. 2,717 groups.

This default is documented as provisional pending review of
`scripts/inspect_duplicates.py`'s output against the real file (see §24).

---

## 13. Waiting-Time Definition

`Wait_p,i = t_{i+1} − t_i`, computed from **raw event timestamps** (not collapsed to
day-level — an earlier hypothesis that timestamps were day-only was tested against
the full file and found wrong; 57.9% of events have genuine intraday time).

Gaps are computed only between consecutive **clinical** events. An event is excluded
as a wait-interval *endpoint* (never removed from the trace elsewhere) if its
activity name contains `"tarief"`, `"toesl"`, or `"klasse"` — matching confirmed
billing/tariff activity patterns in the real data
(`ordertarief`, `administratief tarief - eerste pol`, `190101 bovenreg.toesl. a101`,
`190205 klasse 3b a205`).

Negative gaps (timestamp anomalies) are reported, never silently discarded.

---

## 14. Rework Definition

```
Rework_p = Σ_a log(1 + max(0, Count_p,a − 1))
```

Raw event-row occurrence counts per activity, log-dampened so a single
hyper-repeated routine activity (e.g. a serial lab test) doesn't dominate a
long-treatment patient's score. `Number of executions` is explicitly **not** used as
a repeat multiplier — the real data shows this field takes negative and round-number
values (1.17% of events) consistent with a billing quantity/credit field, not a
clinical repeat count.

---

## 15. Path-Deviation Definition

Alignment-based conformance checking (with a documented, automatic fallback to
token-based replay — see §22) against a process model discovered via pm4py's
Inductive Miner, over the department-collapsed activity alphabet (`org:group`, not
`Section`, not raw `concept:name`).

Two efficiency techniques are used without changing what Deviation *means* for any
case:
- **Variant-level caching**: two cases with the identical department-level activity
  sequence get the identical alignment cost by construction, so each distinct
  variant is aligned once and reused, not recomputed per case.
- **Time-budgeted whole-dataset fallback**: if the alignment attempt exceeds a
  configurable wall-clock budget before finishing every distinct variant, **all**
  partial alignment results are discarded and deviation is recomputed for the
  **entire** dataset using token-based replay — so every case's `D_p` in a given run
  always comes from the same method, never a mix of the two cost scales.

---

## 16. Normalization

Percentile clipping (1st/99th percentile, configurable) followed by min-max scaling
to `[0, 1]`, applied identically to all three raw components before combination.
Degenerate cases (all values equal after clipping) return `0.0` for every case rather
than dividing by zero.

---

## 17. Friction Score Formula

```
F_p = w_W · W_p + w_R · R_p + w_D · D_p
```

Where `W_p`, `R_p`, `D_p` are the normalized components. Verified in the test suite
against the exact worked example `W=0.2, R=0.4, D=0.6 → F=0.4`.

---

## 18. Weighting

```
w_W = w_R = w_D = 1/3
```

Locked equal weighting for V1 — the only defensible neutral default absent empirical
or clinical justification. Not learned, not tuned.

---

## 19. Why These Three Components Were Selected

They represent three distinct, reliably event-log-derivable types of burden:
temporal (Waiting), repetition (Rework), and structural/complexity (Deviation).
Other candidate dimensions (handoff count, resource changes, waiting-time
variability, cancellations) were considered and explicitly excluded from V1 as not
reliably available/interpretable in this dataset — named as future work, not
silently omitted.

---

## 20. Limitations and Disclaimers

- Friction Score is an **unvalidated proxy** for observable process burden — BPIC
  2011 provides no patient-satisfaction ground truth, and the score is explicitly
  **not** a measure of satisfaction, distress, or care quality.
- Each BPIC 2011 "case" can bundle up to 16 diagnosis-treatment combinations across a
  multi-year span; Friction Score is computed over this entire bundled history, not a
  single clinical episode.
- Rework cannot distinguish clinically legitimate repetition (e.g. serial lab
  monitoring) from genuine process rework — it measures observed repetition by
  design.
- Deviation is relative to a department-level discovered model — it captures
  cross-department complexity, not fine-grained activity-level pathway nuance.
- Equal weighting is a neutral default, not empirically derived.
- Single hospital, single department (gynaecology) — generalizability untested.
- The full-exact-duplicate-drop rule (§12) is provisional pending closer review.

---

## 21. Process Discovery Methodology

pm4py's Inductive Miner (noise threshold 0.2, starting value) is run over the
department-collapsed event log (8-label alphabet). Discovery over the raw 624-value
`concept:name` field was explicitly rejected as producing an unreadable
"flower model" — this was a design decision made before implementation, not
discovered as a problem afterward.

---

## 22. Conformance Methodology and the Alignment → Token-Replay Fallback

**Problem actually encountered:** on real hardware, alignment-based conformance
completed only 12 of 914 distinct variants in ~30 minutes and caused the laptop to
overheat.

**Fix actually implemented:**
1. Variant-level caching (see §15) — reduced redundant work by ~20% in this dataset
   (1,143 cases across 914 variants), which alone was not sufficient.
2. A configurable wall-clock time budget (`alignment_time_budget_seconds`, default
   300s). Three selectable modes (`configs/config.yaml`,
   `process_discovery.conformance_method`):
   - `"auto"` (default) — attempt alignments within budget; on timeout, discard
     partial results and recompute the whole dataset via token-based replay.
   - `"alignments"` — alignments only; raises `TimeoutError` on budget exhaustion
     rather than silently switching method.
   - `"token_based_replay"` — skip alignment entirely; fastest, safest on
     constrained hardware.

The method actually used for a given run is printed explicitly by the pipeline and
recorded as a `deviation_method` column in both `patient_deviation.parquet` and
`friction_scores.parquet`.

**Not yet confirmed:** the exact console output showing which method (`alignments` or
`token_based_replay`) was used in the specific run that successfully produced the
dashboard's currently-visible data was not captured in this project's provided logs.
This should be confirmed from your own terminal output before stating it in a report
or presentation.

---

## 23. What PySpark Actually Does

As implemented in `src/ingestion/spark_pipeline.py`: reads the parsed event records
into a Spark DataFrame, applies distributed cleaning (Section correction via a
broadcasted expression, missing-value filtering) and distributed
groupBy/aggregation for department-level and case-level statistics.

**As actually executed in this project: nothing yet.** `run_pipeline.py` does not
import or call this module — see §8/§9. It is present, syntax-valid Python, and
intended as the module to wire in if/when this pipeline needs to scale to a dataset
where Spark's distributed processing is actually necessary.

---

## 24. What pm4py Actually Does

Two things, both actually executed: (1) `discover_petri_net_inductive` — process
discovery producing a Petri net, initial marking, and final marking from the
department-collapsed event log; (2) `conformance_diagnostics_alignments` and
`conformance_diagnostics_token_based_replay` — conformance checking producing the
raw Deviation cost per case, per the variant-cached/time-budgeted logic in §22.

---

## 25. What Parquet Does

Stores five per-case/per-event output tables (`clean_events`, `patient_waiting`,
`patient_rework`, `patient_deviation`, `friction_scores`) written via pandas/pyarrow.
These are what the Streamlit dashboard reads directly — confirmed working (the
dashboard successfully renders per-case data, which requires these files to exist
and be readable).

---

## 26. What Neo4j Does, If It Is Actually Implemented

**It is implemented as code, but not actually run in this project.**
`src/storage/neo4j_loader.py` defines: `(:Patient)-[:PERFORMED]->(:Event)` per-case
journey relationships, an aggregated `(:Activity)-[:NEXT_ACTIVITY {count}]->(:Activity)`
transition-frequency graph, constraint setup, a loader for both, and example Cypher
queries (patient journey retrieval, immediate-loop detection, most-frequent
transitions). None of this has been executed against a running Neo4j instance in this
project — no server has been started, no data has been loaded, no query has been run.
`docker-compose.yml` provides a Neo4j service definition for this purpose, but it has
not been brought up.

---

## 27. What Streamlit Does

Provides the interactive multi-page dashboard (`dashboard/app.py`), reading
exclusively from the Parquet outputs. Confirmed running by the user; one rendering
bug was found and fixed (duplicate `"count"` column name from a pandas-version-
dependent `value_counts().reset_index()` naming difference, on the Patient Journey
Explorer's repeated-activities table) — see §32.

---

## 28. What the Dashboard Currently Shows

Seven pages, all reading from Parquet, all present in the code and confirmed
runnable:
1. **Overview** — patient/event counts, distinct activities, mean Friction Score,
   Friction Score distribution histogram, top-decile share.
2. **Process Explorer** — activity frequency (top 30), department frequency.
3. **Bottleneck Analysis** — median total wait, timestamp-anomaly case count,
   waiting-time distribution.
4. **Rework Analysis** — Rework score distribution, Rework vs. total-events scatter.
5. **Pathway Deviation** — Deviation cost distribution.
6. **Friction Analytics** — component contribution box plot, Waiting-vs-Friction
   scatter with correlation metric, top-20 patients by Friction Score.
7. **Patient Journey Explorer** — case selector, component breakdown, dominant-
   component explanation, chronological journey table, repeated-activities table
   (bug-fixed).

Every page carries the friction-score disclaimer text (cohort-relative, not a
satisfaction measure, whole-history not single episode) directly in the UI.

---

## 29. Exact Outputs/Files Generated by the Pipeline

```
outputs/clean_events.parquet
outputs/patient_waiting.parquet
outputs/patient_rework.parquet
outputs/patient_deviation.parquet     (includes deviation_method column)
outputs/friction_scores.parquet       (includes deviation_method column)
```

Plus console output at every stage (validation report, cleaning report, deduplication
report, department-collapsing report, discovery/conformance report including the
explicit method-used statement, friction-score summary statistics).

---

## 30. How to Install and Run It

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Place `Hospital_log.xes` in the project root (never included in the repository).

```bash
python run_pipeline.py --input Hospital_log.xes
```

Optional flags: `--conformance-method {alignments,token_based_replay,auto}`,
`--skip-process-mining`, `--output-dir`.

```bash
streamlit run dashboard/app.py
```

Tests:
```bash
pytest tests/ -v
```

---

## 31. Problems Encountered During Implementation and How They Were Solved

1. **XML namespace bug**: BPIC 2011 declares a default XES namespace, causing exact
   tag-string matching to silently return zero events. **Fixed** by stripping
   namespace prefixes before tag comparison; a regression test guards against this
   recurring.
2. **Incorrect generalization from a small sample**: a 6-event sample suggested all
   timestamps were day-only (midnight). A full-file check found this wrong (57.9%
   have genuine intraday time). **Corrected** before implementation, not after — this
   was caught during methodology validation.
3. **`Number of executions` misinterpretation risk**: initially considered as a
   rework multiplier; full-file check showed negative/round values inconsistent with
   a repeat-count interpretation. **Decision**: excluded from the Rework formula
   entirely.
4. **Section typo** (`"Sectoin 7"`): found during full-file inspection. **Fixed** via
   an explicit correction rule in cleaning.
5. **Duplicate events** (16.9% of the log): not caught by earlier inspection scripts,
   surfaced only when the full pipeline ran. **Fixed** via full/partial duplicate
   classification (§12), with a dedicated diagnostic script for ongoing review.
6. **pm4py dtype error**: `"the dataframe should (at least) contain a column of type
   date"` — caused by pandas leaving a column of tz-aware `datetime.datetime` objects
   as `object` dtype instead of `datetime64`. **Fixed** via explicit
   `pd.to_datetime(..., utc=True, errors="coerce")` coercion with null-validation,
   applied both defensively inside the discovery function and explicitly in the
   pipeline before calling it.
7. **Alignment-based conformance computational infeasibility**: 12/914 variants in
   ~30 minutes, laptop overheating. **Fixed** via variant-level caching plus an
   automatic, documented, whole-dataset fallback to token-based replay on a
   configurable time budget (§22).
8. **Streamlit duplicate-column error**: `pandas.value_counts().reset_index()`
   column naming differs across pandas versions, producing two columns both named
   `"count"`. **Fixed** by explicitly setting column names instead of relying on a
   version-dependent rename.
9. **Sandbox network restriction** (development-environment-specific, not a project
   issue): the assistant's own sandbox could not reach PyPI to install `pytest`
   directly. **Worked around** with a minimal stdlib-only local test-runner shim to
   still validate all 82 tests before delivery; this has no effect on your own
   environment, which installs real `pytest` from `requirements.txt` normally.

---

## 32. Current V1 Results

**Confirmed by actual execution:**
- The full pipeline (validation → cleaning → deduplication → Waiting/Rework →
  department collapsing → pm4py discovery → conformance → normalization → Friction
  Score → Parquet write) has been run successfully against the real 1,143-case BPIC
  2011 file, producing all five Parquet output tables.
- The Streamlit dashboard successfully reads these outputs and renders per-case data
  (confirmed by a real dashboard error being raised and fixed on the Patient Journey
  Explorer page, which requires `friction_scores.parquet` and `clean_events.parquet`
  to already exist and be populated).

**Not yet confirmed/captured in this project's logs — do not assume or report these
without checking your own terminal/dashboard output first:**
- The exact Friction Score summary statistics (mean, distribution shape, count of
  high-friction cases) from a completed run.
- Which conformance method (`alignments` vs. `token_based_replay` fallback) was
  actually used in the run that produced the currently-existing Parquet outputs.
- The discovered Petri net's size (number of places/transitions) or whether the
  chosen noise threshold (0.2) produces a genuinely readable model versus something
  closer to a flower model on the real data.

---

## 33. What Is Implemented vs. Planned

| Feature | Status |
|---|---|
| XES parsing, validation | Implemented, tested, executed |
| Cleaning (Section fix, missing-value drop) | Implemented, tested, executed |
| Duplicate classification/removal | Implemented, tested, executed |
| Waiting, Rework computation | Implemented, tested, executed |
| Department collapsing | Implemented, tested, executed |
| pm4py process discovery | Implemented, executed (after dtype fix) |
| pm4py conformance (variant-cached, time-budgeted fallback) | Implemented, tested; executed but exact method-used for the confirmed successful run not captured in logs |
| Normalization, Friction Score, correlation diagnostic | Implemented, tested, executed |
| Parquet output | Implemented, executed |
| Streamlit dashboard (7 pages) | Implemented, executed, one bug found and fixed |
| PySpark ingestion module | Implemented as code, **not wired into the executed pipeline** |
| Neo4j graph loader | Implemented as code, **never run against a live Neo4j instance** |
| Docker/Docker Compose | Written, not confirmed built/run in this project |
| Weight sensitivity analysis, external validation, streaming, ML prediction | **Not implemented — future scope only (see §35)** |

---

## 34. What Has Not Been Validated Yet

- Numeric Friction Score results (see §32).
- Whether the discovered process model (noise threshold 0.2) is genuinely
  interpretable at the department-alphabet level, or needs tuning.
- The correctness of the full-vs-partial duplicate classification default against a
  close manual review of `scripts/inspect_duplicates.py`'s actual output — this was
  implemented as a provisional, documented default, not confirmed correct by manual
  inspection.
- PySpark's actual distributed behavior on this dataset (module untested at runtime).
- Neo4j's actual graph load/query correctness (module untested at runtime).
- Docker build/run correctness end-to-end.

---

## 35. Current Research Questions

- **RQ1**: How can waiting burden, rework, and pathway deviation be extracted from
  healthcare event logs? (Answered methodologically for BPIC 2011 in §13–15; not yet
  validated numerically per §34.)
- **RQ2**: Can these dimensions be combined into an interpretable patient-level
  score? (Formula implemented and tested; interpretability not yet evaluated against
  real output distributions.)
- **RQ3**: Does the composite score reveal journey-complexity information not
  captured by waiting time alone? (Requires the correlation diagnostic's actual
  output from a completed run — not yet captured, see §32.)

---

## 36. Future V2 Improvements

*(Explicitly future — none of this is implemented or claimed as part of V1.)*

- Wire the PySpark ingestion module into the actual execution path, tested against a
  multi-hospital or multi-year dataset where distributed processing is genuinely
  necessary.
- Bring up and populate the Neo4j graph, and wire its queries into the dashboard's
  Process Explorer / Patient Journey Explorer pages.
- Weight sensitivity analysis across the `(w_W, w_R, w_D)` simplex.
- A "clinical-only" activity filter as a sensitivity variant for Rework/Deviation.
- External validation against patient complaints/satisfaction data, if such data
  becomes available.
- Learned or data-driven weighting, only if empirically justified.
- Extension to additional hospital datasets via the standardized schema.

---

## 37. Potential Novelty/Patent Directions — Not a Claim of Patentability

*(Directions worth investigating with a patent professional and a proper prior-art
search — not a claim that any of this is novel or patentable. See the earlier
literature discussion in this conversation for the reasoning behind each.)*

1. A composite, explainable, patient-level process-friction metric combining
   temporal, repetition, and structural-deviation burden into a single documented
   formula with per-component attribution.
2. A required, formal validity check (raw-component correlation) run before any
   composite-score interpretation is presented, as a built-in methodological
   safeguard rather than an optional analysis step.
3. An automatic, time-budgeted, whole-dataset-consistent fallback mechanism between
   alignment-based and token-based-replay conformance checking, specifically
   designed to keep a downstream composite metric's normalization valid regardless
   of which method was used.
4. The specific combination of variant-level caching + budget-based method-switching
   for conformance checking as a practical technique for scaling process-mining-
   derived composite scores to hardware-constrained environments.

---

## 38. A 5-Minute Presentation Explanation

"We built a research analytics pipeline that reads a real hospital's historical event
log — BPIC 2011, over 150,000 recorded events across 1,143 patients — and computes,
for each patient, an explainable Friction Score: one number combining how long they
waited, how much their care repeated, and how unusual their pathway was compared to
the hospital's typical process. Each of those three pieces is itself grounded in
real, verified characteristics of this exact dataset — for example, we found that
timestamps have day-level granularity for part of the log, that some 'activities'
are actually billing codes, and that repeated events aren't always genuine
repetition versus data-export duplicates. We handled each of those explicitly, with
evidence, before finalizing the formula. The score isn't a measure of patient
satisfaction — it's a measure of observable process burden — and we say that
explicitly everywhere the score is shown. The whole pipeline — cleaning, feature
extraction, process discovery, conformance checking, and an interactive dashboard —
runs end-to-end on a normal laptop, including a fix we had to build for the fact that
full alignment-based conformance checking alone was computationally infeasible on
real hardware."

---

## 39. A 10-Minute Presentation Explanation

Extend the 5-minute version with:
- The research question and why waiting-time-only analysis is insufficient (the
  Patient A / Patient B illustrative example: similar waiting time, very different
  rework/deviation).
- Walk through the formula and each component's exact definition (§13–15), including
  why `Number of executions` was deliberately excluded and why administrative/billing
  events are excluded from waiting-gap endpoints.
- Explain the department-collapsing decision (624 raw activities is too
  high-cardinality for a readable process model; a derived 95%-coverage threshold
  keeps the top departments and collapses the rest).
- Walk through the conformance-checking scalability problem actually encountered
  (12/914 variants in 30 minutes) and the two-part fix (variant caching + time-
  budgeted fallback), emphasizing that this was a real engineering obstacle solved
  during implementation, not a hypothetical.
- Show the dashboard's Patient Journey Explorer, explaining a specific case's score
  breakdown.
- State the limitations explicitly (§20) and the honesty distinctions in §33
  (PySpark/Neo4j implemented as code but not wired into execution) — this
  demonstrates rigor rather than weakening the presentation.

---

## 40. Likely Viva Questions and Answers

**Q: Why not just use waiting time as the metric — why build a composite score?**
A: Because two patients can have similar waiting times but very different rework and
pathway deviation. We built a required diagnostic specifically to test whether the
composite adds information beyond waiting alone (§35, RQ3) — the score's value is an
empirical question we designed the pipeline to actually test, not assume.

**Q: Does a high Friction Score mean the patient had a bad experience?**
A: No — explicitly not. The score measures observable process burden derived purely
from event-log data. BPIC 2011 provides no patient-satisfaction ground truth, so we
never claim otherwise, and this disclaimer appears throughout the report and the
dashboard UI itself.

**Q: Why exclude `Number of executions` from the Rework formula?**
A: Full-file inspection showed it takes negative and round-number values inconsistent
with a clinical repeat-count interpretation — it behaves like a billing
quantity/credit field. Using it would have introduced nonsensical negative "rework."

**Q: Why does Deviation use `org:group` instead of the raw activity field?**
A: 624 distinct activities is too high-cardinality for Inductive Miner to produce an
interpretable process model. `org:group` (department) with a derived 95%-coverage
collapsing rule keeps the discovery alphabet small and readable while still being
clinically meaningful.

**Q: What did you do when alignment-based conformance checking wouldn't finish on
your hardware?**
A: Implemented variant-level caching (identical department-sequences share one
alignment computation) and a configurable time budget; if the budget is exceeded
before all variants are aligned, the pipeline discards partial alignment results and
recomputes Deviation for the whole dataset via token-based replay instead, so every
case's value comes from the same, comparable method. Which method was used is always
explicitly reported.

**Q: Is PySpark actually doing anything in this project?**
A: The module is fully written, but the pipeline that has actually been run does not
currently invoke it — it uses pure-Python parsing and pandas instead. This is stated
explicitly rather than implied; Spark is included as an architectural demonstration
for future multi-hospital scale, and wiring it in is named future work.

**Q: Is Neo4j actually running?**
A: No — the loader module and schema are implemented and documented, but no Neo4j
server has been started or populated in this project. This is stated explicitly.

**Q: What's the biggest limitation of this V1?**
A: The score is an unvalidated proxy — there is no ground truth in BPIC 2011 to
confirm it correlates with anything patients or clinicians would recognize as
"friction." Equal weighting is also a neutral assumption, not derived from data.

---

## 41. A Simple Explanation for a Non-Technical Person

Imagine a hospital keeps a detailed diary of everything that happens to every
patient — every test, every appointment, every wait. This project reads that diary
for over a thousand real patients and, for each one, works out a single "hassle
score" out of three things: how long they waited around, how often the same test or
step got repeated, and how unusual their path through the hospital was compared to
most other patients. It adds those three things together into one number, and shows
you exactly which of the three caused a high score for any given patient, so nothing
is a mystery. It does **not** try to guess whether the patient was happy or unhappy —
just how much "process hassle" is visible in the paperwork trail. It runs on an
ordinary laptop and shows the results in an interactive dashboard you can click
through, patient by patient.