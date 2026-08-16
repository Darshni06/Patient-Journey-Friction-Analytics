# Patient Journey Friction Analytics (PJFA)

A research-oriented healthcare process-mining system that transforms the BPIC 2011
hospital event log into process models, bottleneck/rework/deviation insights, and an
explainable, patient-level **Patient Journey Friction Score (PJFS)**.

This is **not** a hospital SaaS product, a live monitoring system, a clinical
decision-support tool, or a patient-satisfaction prediction system. It is a batch
research analytics prototype.

> ⚠️ **Important interpretive note**, repeated throughout this README and the
> dashboard: a high Friction Score means *greater observable process burden and
> complexity*, relative to this dataset's patient cohort. It is **not** evidence
> that a patient was dissatisfied, distressed, or received worse clinical care.
> PJFS also scores each case's **entire recorded multi-year history** (BPIC 2011
> bundles up to 16 diagnosis-treatment combinations per case), not a single
> clinical episode. See "Limitations" below.

---

## Research question

*Can a composite patient-level Friction Score, combining waiting burden, rework, and
pathway deviation, provide a more informative representation of healthcare journey
complexity than waiting time alone when derived from hospital event logs?*

---

## The Friction Score

```
F_p = w_W · W_p + w_R · R_p + w_D · D_p,   w_W = w_R = w_D = 1/3
```

Where `W_p`, `R_p`, `D_p` are the normalized (percentile-clipped, min-max scaled to
[0,1]) Waiting, Rework, and Deviation components for case *p*.

| Component | Formula | Notes |
|---|---|---|
| **Waiting** | Sum of raw timestamp gaps between consecutive **clinical** events | Administrative/billing events (matched by keyword: `tarief`, `toesl`, `klasse`) are excluded as gap *endpoints* — see Methodology |
| **Rework** | `Σ_a log(1 + max(0, Count_p,a − 1))` | Log-dampened so one hyper-repeated routine lab test doesn't dominate a long-treatment patient's score |
| **Deviation** | Alignment-based conformance cost against an Inductive-Miner-discovered reference model over collapsed `org:group` | Departments kept individually until ~95% cumulative event coverage; the rest collapse to `"Other department"` |

All three raw components are clipped at the 1st/99th percentile, then min-max
normalized to `[0, 1]`, before combination.

**Required validity check**: before any composite-score interpretation is drawn, the
pipeline computes and reports the pairwise Pearson correlation between the *raw*
`W`, `R`, `D` values. If they are strongly collinear (≥0.7), this is reported as a
warning — it would mean the three "dimensions" may be driven by a common latent
factor (e.g. overall journey length) rather than being independent, which weakens the
central research claim and must be stated honestly rather than omitted.

---

## Dataset

**BPIC 2011** — a Dutch academic hospital's gynaecology department event log, supplied
locally as `Hospital_log.xes` (not included in this repository — see "Setup").

Verified by direct inspection of the real file (never hard-coded — the pipeline
recomputes these on every run):

- 1,143 cases, 150,291 events, ~131 events/case average
- 624 distinct activities (`concept:name`), 675 distinct `Activity code` values
- 42 distinct `org:group` (department) values
- Timestamp range: 2005-01-03 to 2008-03-20
- 57.9% of events have genuine intraday timestamps; 42.1% are exactly midnight
- A confirmed data typo: `"Sectoin 7"` → corrected to `"Section 7"` during cleaning

---

## Methodology — key decisions and why

This project went through an explicit methodology review before implementation.
Several definitions were revised from an initial draft based on evidence from the
actual file, not assumption. Full rationale for every decision is in
[`DEVIATIONS_FROM_PROMPT.md`](DEVIATIONS_FROM_PROMPT.md). Summary:

1. **Waiting** uses raw event timestamps (not collapsed to day-level — early inference
   from a 6-event sample suggested all timestamps were day-only; a full-file check
   showed 58% have real intraday time, so that inference was wrong and corrected).
   Gaps adjacent to administrative/billing-coded events are excluded, since those
   reflect processing lag, not patient waiting.
2. **Rework** counts raw event-row repetition (not the `Number of executions`
   field — full-file inspection showed that field takes negative and round-number
   values consistent with a billing quantity/credit field, not a clinical
   repeat-count), log-dampened to prevent one hyper-repeated activity from dominating.
3. **Deviation** is discovered over `org:group` (not `Section` — heavily skewed, 68%
   in one value, plus the typo), with a derived 95%-coverage department-collapsing
   rule (not a hard-coded "top 10-12").
4. **Normalization**: percentile clipping (1st/99th) then min-max, applied uniformly
   to all three components.
5. **Weights**: locked equal (1/3, 1/3, 1/3) for V1 — the only defensible neutral
   default absent empirical justification. Alternative weighting is Phase 2 only.
6. **Duplicate events** (found during the full-file pipeline run, not the earlier
   inspection): 16.9% of events share a `(case_id, activity, timestamp)` key. Full
   exact duplicates (identical across every field) are dropped; partial duplicates
   (differ in some other field) are retained as likely-legitimate distinct events.
   **This default is provisional** — see `scripts/inspect_duplicates.py` and
   `DEVIATIONS_FROM_PROMPT.md` point 7.

---

## Architecture

```
Hospital_log.xes
      ↓
Validation (src/validation) ── reports file stats fresh every run, never hard-coded
      ↓
PySpark ingestion + cleaning (src/ingestion, src/cleaning)
      ↓
Feature extraction: Waiting, Rework (src/features)
      ↓
pm4py process discovery + conformance (src/process_mining)
      ↓
Normalization + Friction Score engine (src/friction)
      ↓
Parquet (src/storage/parquet_io.py)  +  Neo4j (src/storage/neo4j_loader.py)
      ↓
Streamlit + Plotly dashboard (dashboard/app.py)
```

**Why PySpark on an 81 MB file?** Honestly: BPIC 2011 alone doesn't require
distributed processing. PySpark is used here as a demonstration of a production-style,
horizontally-scalable pipeline that *would* be necessary for multi-hospital or
multi-year historical data — an explicitly named future-scope scenario, not a claim
that this specific file needs it.

**Why Neo4j, specifically?** Not as a generic data dump — it's used for path/loop
queries (repeated-activity detection, transition-frequency graphs) that are natural
Cypher pattern matches but require awkward self-joins in SQL. Flat aggregates (KPIs,
friction scores, department stats) stay in Parquet.

---

## Project structure

```
patient-journey-friction/
├── src/
│   ├── ingestion/        # PySpark ingestion + orchestration
│   ├── cleaning/         # Section typo fix, missing-value drop rule
│   ├── features/         # Waiting, Rework, Normalization (pure Python, unit-tested)
│   ├── process_mining/   # Department collapsing, pm4py discovery + conformance
│   ├── friction/         # Friction Score combination + required correlation check
│   ├── storage/          # Parquet + Neo4j writers
│   ├── validation/       # Dataset inspection, integrated into the pipeline
│   └── utils/            # XES streaming parser
├── dashboard/app.py       # Streamlit + Plotly dashboard
├── tests/                 # pytest suite (58 tests, all pure-logic, no external deps required)
├── configs/config.yaml    # every locked threshold, in one place
├── scripts/               # standalone inspection scripts used during methodology validation
├── run_pipeline.py        # CLI entry point
├── Dockerfile / docker-compose.yml
└── requirements.txt
```

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

PySpark requires a JVM (Java 11+). pm4py and its own dependencies install via pip.
Neo4j requires either a local install or the provided `docker-compose.yml` service.

Place your local `Hospital_log.xes` in the project root (it is **not** included in
this repository/ZIP — see `.gitignore`).

## Running the pipeline

```bash
python run_pipeline.py --input Hospital_log.xes
```

This runs validation → ingestion/cleaning → Waiting/Rework feature extraction →
department-collapsing for process discovery, printing a full report at each stage.
Process discovery and conformance checking (pm4py, requiring the full dependency
stack) and the Parquet/Neo4j writes are exercised via the modules in
`src/process_mining/` and `src/storage/` — wire these into `run_pipeline.py`'s
remaining phases in your local environment once pm4py/Spark/Neo4j are installed and
running; the CLI already supports `--skip-process-mining` to validate everything
upstream of that dependency first.

## Running the dashboard

```bash
streamlit run dashboard/app.py
```

Reads from `outputs/*.parquet`. Pages: Overview, Process Explorer, Bottleneck
Analysis, Rework Analysis, Pathway Deviation, Friction Analytics, Patient Journey
Explorer.

## Neo4j setup

```bash
docker compose up neo4j
```

Then set `NEO4J_URI=bolt://localhost:7687`, `NEO4J_USER=neo4j`,
`NEO4J_PASSWORD=pjfa_password_change_me` (or your own, see `docker-compose.yml`).

## Running tests

```bash
pytest tests/ -v
```

58 tests covering: XES parsing (including a regression guard for the XML-namespace
bug hit during development), waiting-gap calculation and anomaly handling,
log-dampened rework, normalization edge cases (all-equal values, single value, empty
input, outlier clipping), the friction formula (including the exact
`W=0.2, R=0.4, D=0.6 → F=0.4` example), the required correlation diagnostic, cleaning
rules, and department collapsing. All are pure-Python and run without Spark, pm4py,
or Neo4j installed.

---

## Limitations

- **PJFS is an unvalidated proxy** for observable process burden, not patient
  experience. BPIC 2011 provides no patient-satisfaction ground truth.
- **Waiting** partially reflects data recording granularity, not pure clinical
  waiting — administrative events are excluded as endpoints, but this is a
  keyword-based heuristic, not a semantic guarantee.
- **Rework** cannot distinguish clinically legitimate repeated activity (e.g. serial
  lab monitoring) from genuine process rework — it measures observed repetition,
  by design, without a clinical-legitimacy judgment.
- **Deviation** is relative to a *discovered* model at department granularity — it
  captures cross-department journey complexity, not fine-grained activity-level
  pathway nuance.
- **Equal weighting** (1/3, 1/3, 1/3) is a neutral default, not empirically derived.
- Each "case" in BPIC 2011 can bundle **up to 16 diagnosis-treatment combinations**
  across a multi-year span — PJFS scores this whole bundled history as one journey.
- Single hospital, single department (gynaecology) — generalizability untested.

## Future scope (explicitly not implemented in V1)

Live hospital streams, Kafka, multiple hospitals, external patient feedback/sentiment
data, validation against actual complaints, learned/optimized weights, predictive
modeling, real-time friction monitoring.
