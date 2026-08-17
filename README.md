# Patient Journey Friction Analytics

A research analytics pipeline that transforms the BPIC 2011 hospital event log into
an explainable, patient-level **Friction Score** — combining waiting burden, rework,
and pathway deviation into one interpretable number per patient.

> Not a hospital SaaS product. Not a clinical decision-support tool. Not a
> patient-satisfaction predictor. A batch research prototype, built and validated
> against a real 1,143-case, 150,291-event hospital log.

## Overview

PJFA reads a historical XES event log, cleans and validates it, extracts three
independent burden signals per patient — **Waiting**, **Rework**, and **Pathway
Deviation** — normalizes them, and combines them into a single composite score:

```
F_p = (W_p + R_p + D_p) / 3
```

Every component and threshold is documented and configurable
(`configs/config.yaml`), and every cleaning/definitional decision was made against
evidence from the actual dataset rather than assumption — see
[`docs/PROJECT_DOCUMENTATION.md`](docs/PROJECT_DOCUMENTATION.md) for the full record,
including what's implemented, what's tested, what's executed, and what's still
future work.

The pipeline runs end-to-end on ordinary laptop hardware, including a specific fix
for the fact that full alignment-based conformance checking alone was computationally
infeasible on real hardware (see Limitations and `docs/PROJECT_DOCUMENTATION.md` §22
and §31).

## Research Problem

Traditional healthcare process mining reports *aggregate, activity-level* statistics
— bottleneck activities, average waiting times, common process variants. It does not
produce a single, interpretable, *patient-level* summary of process burden. Two
patients can look identical under waiting-time analysis alone while having very
different rework and pathway complexity.

**Research question:** Can a composite patient-level Friction Score — combining
waiting burden, rework, and pathway deviation — provide a more informative
representation of healthcare journey complexity than waiting time alone, when derived
from hospital event logs?

> ⚠️ **A high Friction Score is not evidence of patient dissatisfaction, distress, or
> poor care.** It reflects observable process burden only, relative to this dataset's
> cohort, and it scores each case's entire recorded multi-year history (BPIC 2011
> bundles up to 16 diagnosis-treatment combinations per case), not a single clinical
> episode. This disclaimer is repeated on every page of the dashboard.

## The Friction Score

| Component | Definition | Why |
|---|---|---|
| **Waiting** | Raw timestamp gaps between consecutive *clinical* events (administrative/billing events excluded as gap endpoints) | Measures temporal burden without misattributing billing-processing lag as patient waiting |
| **Rework** | `Σ_a log(1 + max(0, Count_p,a − 1))` | Log-dampened repeat counting; prevents one hyper-repeated routine test from dominating |
| **Deviation** | Alignment-based conformance cost (with a documented, automatic fallback to token-based replay) against a discovered process model over collapsed departments | Measures structural pathway unusualness, computed feasibly on real hardware |

All three are percentile-clipped and min-max normalized to `[0, 1]` before combining
with locked equal weights (`1/3, 1/3, 1/3`).

## Dataset

**BPIC 2011** — Dutch academic hospital, gynaecology department. Verified directly
from the real file (recomputed fresh on every pipeline run, never hard-coded):

- 1,143 cases, 150,291 events, ~131 events/case average
- 624 distinct activities, 43 distinct departments (`org:group`), 8 distinct `Section` values
- Timestamp range 2005-01-03 to 2008-03-20; 57.9% of events carry genuine intraday time
- 25,379 duplicate `(case, activity, timestamp)` events found (16.9% of the log) — 18,725
  confirmed full-exact duplicates removed, 2,717 partial-duplicate groups retained
- A confirmed data typo (`"Sectoin 7"` → `"Section 7"`), corrected during cleaning

Full statistics table: `docs/PROJECT_DOCUMENTATION.md` §7.

## Architecture

```
Hospital_log.xes
      ↓
Validation → XES parsing → Cleaning → Deduplication
      ↓
Waiting / Rework feature extraction
      ↓
Department collapsing → pm4py process discovery → pm4py conformance checking
      ↓
Normalization → Friction Score
      ↓
Parquet output → Streamlit + Plotly dashboard
```

**Honesty note:** `src/ingestion/spark_pipeline.py` (PySpark) and
`src/storage/neo4j_loader.py` (Neo4j) are fully implemented, syntax-checked modules,
but the pipeline that has actually been run does **not** currently invoke either of
them — `run_pipeline.py` uses pure-Python parsing/cleaning and pandas for the pm4py
steps instead. Both are included as forward-looking architecture (see
`docs/PROJECT_DOCUMENTATION.md` §8, §23, §26) and are named explicitly as V2 work to
wire in, not claimed as active in V1.

## Project Structure

```
patient-journey-friction/
├── src/
│   ├── ingestion/        # PySpark module - not currently wired into execution
│   ├── cleaning/         # Section typo fix, missing-value drop, duplicate handling
│   ├── features/         # Waiting, Rework, Normalization (pure Python, unit-tested)
│   ├── process_mining/   # Department collapsing, pm4py discovery + conformance
│   ├── friction/         # Friction Score combination + required correlation check
│   ├── storage/          # Parquet writer (used) + Neo4j loader (not currently wired in)
│   ├── validation/       # Dataset inspection, integrated into the pipeline
│   └── utils/            # XES streaming parser
├── dashboard/app.py       # Streamlit + Plotly dashboard (7 pages)
├── tests/                 # pytest suite, 82 tests, pure-logic, no external deps required
├── configs/config.yaml    # every locked threshold, in one place
├── scripts/               # standalone inspection/diagnostic scripts
├── docs/PROJECT_DOCUMENTATION.md  # full project record - see this for everything
├── run_pipeline.py
└── requirements.txt
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Place your local `Hospital_log.xes` in the project root — it is never included in
this repository.

## Running the pipeline

```bash
python run_pipeline.py --input Hospital_log.xes
```

Optional flags:
- `--conformance-method {alignments,token_based_replay,auto}` — override the
  configured conformance strategy; `token_based_replay` is fastest/safest on
  constrained hardware.
- `--skip-process-mining` — validate everything upstream of pm4py without it
  installed.
- `--output-dir` — change the Parquet output location (default `outputs/`).

The pipeline prints, explicitly, which conformance method was actually used for
Deviation (`alignments` or the `token_based_replay` fallback) and why — this is also
recorded as a `deviation_method` column in the output Parquet files.

## Running the dashboard

```bash
streamlit run dashboard/app.py
```

Pages: Overview, Process Explorer, Bottleneck Analysis, Rework Analysis, Pathway
Deviation, Friction Analytics, Patient Journey Explorer.

## Running tests

```bash
pytest tests/ -v
```

82 tests covering XES parsing (including a regression guard for a real namespace
bug hit during development), waiting-gap calculation, log-dampened rework,
normalization edge cases, the Friction formula (including the exact
`W=0.2, R=0.4, D=0.6 → F=0.4` worked example), the required correlation diagnostic,
cleaning/deduplication rules, department collapsing, the pm4py timestamp-dtype fix,
and the conformance variant-caching/time-budget fallback logic.

## Limitations

See `docs/PROJECT_DOCUMENTATION.md` §20 and §34 for the complete list, including what
has and hasn't been validated yet. Key points:

- Friction Score is an unvalidated proxy for process burden, not patient experience.
- Rework cannot distinguish clinically legitimate repetition from genuine rework.
- Deviation captures cross-department complexity, not fine-grained activity nuance.
- Equal weighting is a neutral default, not empirically derived.
- The full-exact-duplicate-drop rule is documented as provisional.
- PySpark and Neo4j modules exist but have not been executed in this project.

## Future scope (not implemented)

Wiring PySpark/Neo4j into actual execution, weight sensitivity analysis, a
clinical-only activity filter, external validation against patient
complaints/satisfaction data, learned weighting, multi-hospital extension. See
`docs/PROJECT_DOCUMENTATION.md` §36 for details.

## Further reading

- [`docs/dPROJECT_DOCUMENTATION.m`](docs/PROJECT_DOCUMENTATION.md) — the complete
  project record: problem statement, motivation, exact definitions, architecture,
  every technology and why, problems encountered and how they were solved, current
  results, what's implemented vs. planned, research questions, presentation scripts,
  viva Q&A, and a plain-language explanation.