# Patient Journey Friction Analytics (PJFA)
## Design Decisions & Answers to Open Questions

This document resolves every open question raised against the Master Specification. Where the spec left something ambiguous, a concrete decision is made below and should be treated as binding for Version 1 unless revisited in Phase 2.

---

## A. Conceptual Foundations

**What exactly do we mean by "friction"? Observable process burden/complexity?**
Yes. Friction is defined strictly as *the observable process-related burden and complexity encountered by a patient during their recorded healthcare journey*, as derived purely from event-log data (timestamps, activities, repetition, and structural deviation from a reference process).

**Are we explicitly not claiming patient dissatisfaction?**
Correct — explicitly and repeatedly. This is stated in the spec (§3) and must be restated in the report abstract, the methodology section, and directly in the dashboard UI (e.g., a persistent caveat banner on the Friction Analytics page). PJFS is a *process-burden proxy*, not a satisfaction, pain, or quality-of-care measure.

**What is our exact problem statement?**
*Can the observable process burden and complexity of an individual patient's journey be characterized by combining multiple event-log-derived dimensions (waiting, rework, deviation) into a single explainable, patient-level composite metric?*

**What limitation of traditional process mining are we solving?**
Traditional process mining reports *aggregate, activity-level* statistics (bottleneck activities, overall waiting distributions, common variants). It does not produce a single, interpretable, *patient-level* summary that lets you say "this specific patient's journey was more burdensome than that one, and here is why." PJFA fills that gap.

**Why do we need a Friction Score at all? What does it tell us that waiting, rework, and deviation separately don't?**
Individually, the three metrics can disagree or be misleading in isolation — e.g., a patient with low waiting time but high rework and high deviation looks "fine" under waiting-time-only analysis. The composite score lets two patients with similar values on one dimension but different values on the others be meaningfully compared and ranked, which is the entire point of the "Patient A vs Patient B" example in §2 and §24.

**Why exactly these 3 parameters (Waiting, Rework, Pathway deviation)?**
They are the three *distinct, reliably observable* categories of burden extractable from a standard event log:
- Waiting → temporal burden
- Rework → repetition burden
- Deviation → structural/complexity burden

**Why aren't we including 5–10 other features?**
Decision for V1: deliberately excluded (handoff count, department changes, resource changes, journey duration, waiting-time variability, cancellations, entropy) because:
1. Not all are reliably present/clean in BPIC 2011.
2. Adding more dimensions increases weighting/normalization complexity disproportionately to the marginal explanatory value for a seminar-scope deliverable.
3. A 3-dimension model is easier to validate, sensitivity-test, and explain to a non-technical dashboard user.
These become explicit **Future Work** (§31), not omissions we hide.

**What does a high Friction Score actually mean? What can/can't we conclude?**
- ✅ Can conclude: the journey exhibits more combined waiting + repetition + structural deviation *relative to the rest of the cohort in this dataset*.
- ❌ Cannot conclude: the patient was dissatisfied, received worse clinical care, experienced a medical error, or that any single dimension caused the burden without checking the breakdown.

---

## B. Mathematical Formulation

**Exact formula:** `F_p = w_W·W_p + w_R·R_p + w_D·D_p`, with `w_W + w_R + w_D = 1`.

**Why are initial weights equal (1/3 each)?**
Decision: no defensible prior exists for weighting one burden type over another without empirical/clinical justification, which BPIC 2011 doesn't support. Equal weighting is the only *neutral, unbiased* default and gives a clean baseline for the Phase 2 sensitivity analysis.

**Will weights stay equal in the final paper, or will alternatives be tested?**
Decision: **Equal weights are the reported V1/seminar result.** Phase 2 (§30, Experiment 4) tests alternative weight configurations purely as a *sensitivity analysis*, not as a replacement default — unless a data-driven justification emerges, in which case it becomes an explicitly labeled "V2 weighting" variant, never silently swapped in.

**How exactly are components normalized to 0–1?**
Decision: dataset-wide min-max normalization, computed once over the full patient cohort (not per batch/partition), applied *after* outlier handling (below). Formula as given in §7–9.

**What happens with extreme outliers?**
Decision: apply **percentile clipping (1st/99th percentile) or winsorization** to each raw component (TotalWait, Rework count, DeviationCost) *before* min-max normalization. Without this, a handful of extreme waiting times would compress the rest of the cohort near zero, destroying the score's discriminative power. This choice is documented and reported as a explicit preprocessing step, with a note on how many points were clipped.

---

## C. Waiting-Time Definition

**What exactly counts as "waiting" in BPIC 2011?**
BPIC 2011 (Dutch academic hospital, gynaecology department) generally provides a **single completion timestamp per event** — it does not consistently include paired start/complete lifecycle transitions the way some other BPIC logs do. This means we **cannot cleanly separate "waiting" from "service duration"** at the event level using timestamps alone.

**Decision (operational definition for V1):**
`Wait_p,i = t_p,i+1 − t_p,i` is treated as the **inter-event gap** between the completion of one activity and the completion of the next in a patient's trace. This is explicitly documented as an approximation: it may absorb some portion of actual service/treatment time for the following activity, because BPIC 2011's event semantics don't allow a cleaner split. This limitation is stated directly in the report methodology and limitations sections — we do not claim a purer definition than the data supports.

**Are all timestamp differences waiting?**
No — this must still be confirmed by profiling the actual event log after loading (some consecutive events may share a timestamp, or represent instantaneous administrative transitions that shouldn't count as "waiting" at all). Decision: gaps below a small threshold (e.g., same-timestamp or sub-minute) are treated as zero-wait, not negative or noise.

**Missing/inconsistent timestamps?**
Decision: events with missing or malformed timestamps are **dropped** during the PySpark ingestion/cleaning layer rather than imputed — imputing clinical event timing is not defensible. Drop counts/percentages are logged and reported for transparency.

---

## D. Rework Definition

**Exact definition used for V1:**
`Rework_p,a = max(0, Count_p,a − 1)`, summed across all activities `a` in the patient's trace. This counts every occurrence of an activity beyond its first as one unit of rework, regardless of clinical intent.

**Is the second Consultation in `Registration → Consultation → Laboratory → Consultation` rework?**
Yes, under the V1 definition — it is counted, deliberately without judgment about clinical legitimacy.

**What about `Laboratory → Laboratory` (immediate repeat)?**
Also counted as rework under the same rule — no special-casing for adjacency vs. non-adjacency in V1.

**What about a clinically legitimate repeated test?**
V1 does **not** distinguish this. This is an explicit, documented limitation (already flagged in spec §8): the metric is *objective and reproducible* but *not clinically aware*. Distinguishing legitimate repetition from true rework is named as Future Work (§31) and would require clinical metadata not present/labeled in BPIC 2011.

**Are we measuring repeated activities, loops, or both?**
Decision: the **score** uses simple repeated-activity counts only (above). Full **loop-pattern detection** (e.g., `Consultation → Laboratory → Consultation`) is a separate, descriptive dashboard feature (§21) for visualization and insight — it does not feed into the numeric Rework component in V1, to keep the metric simple and reproducible.

---

## E. Pathway Deviation

**What is the reference/"normal" pathway?**
Decision: a **discovered process model** (not simply the single most-common trace), built via **pm4py's Inductive Miner** over the full event log, producing a Petri net that represents the generalized process behavior.

**Which pm4py conformance technique?**
Decision: **alignment-based conformance checking** against the Inductive Miner model, using per-case alignment cost as the deviation measure. Rationale: alignments give a principled, interpretable cost per trace (number/severity of log moves and model moves) rather than a binary fit/no-fit. If alignments prove too computationally expensive at full scale, **token-based replay** is the documented fallback, with the trade-off (speed vs. precision) explicitly noted in the methodology.

**How is the deviation value produced and normalized?**
Alignment cost per case → outlier clipping → dataset-wide min-max normalization, identical procedure to the other two components (§9).

**Does "more deviation = more friction" make theoretical sense?**
Yes, but with an explicit interpretive caveat repeated throughout the report and dashboard: higher deviation means the journey is *structurally less typical relative to the discovered model*, not necessarily a worse outcome. A legitimately complex specialist pathway would score high on this dimension without implying poor care.

---

## F. Dataset

**What does BPIC 2011 contain?**
- **Case ID**: anonymized patient identifier
- **Activity**: hospital activity code + description (very high cardinality — several hundred distinct activities)
- **Timestamp**: completion time of each event
- **Other attributes**: producer/department code, specialism code, diagnosis code, treatment code, patient age, number of executions
- **Approximate scale** (to be verified against the actual file after loading, not assumed from memory): on the order of ~1,000+ patient cases and ~150,000 events, from a single hospital's gynaecology department.

**Is BPIC 2011 genuinely "big data"? Does PySpark make sense here?**
Honest answer: **no, not at this raw size** — a single department's log of this size fits comfortably in memory and could be processed with Pandas alone. Decision on how we justify PySpark: we do **not** overclaim a scalability requirement the dataset doesn't have. Instead, the report explicitly states that PySpark is used to demonstrate a **production-style, horizontally-scalable pipeline architecture** that would be *necessary* if the same pipeline were applied to multi-hospital or multi-year historical logs (explicitly named as Future Work, §31/§17). This honesty is safer than pretending BPIC 2011 forces the need for Spark.

---

## G. Architecture

**Why PySpark instead of Pandas?**
Engineering/architectural demonstration of a scalable batch pipeline (see F above), and to satisfy the "big-data processing" component of the project's technical scope even though the current dataset doesn't strictly require it.

**Why pm4py?**
It's the standard open-source Python library for process discovery and conformance checking, with mature Inductive Miner and alignment implementations.

**Why Neo4j?**
See section H below — used for its native fit to path/loop/journey queries.

**Why Parquet?**
Columnar, compressed, schema-carrying analytical storage format that integrates natively with Spark and is efficient for the repeated read/aggregation patterns the dashboard needs.

**Why Streamlit?**
Fast to build an interactive, multi-page research dashboard with minimal front-end engineering overhead; pairs well with Plotly for the required chart types.

**What happens in each layer?**
As specified in §13–17 of the master spec — Ingestion (Spark: read, validate, clean, dedupe, sort) → Processing (Spark: waiting extraction, features; pm4py: discovery, variants, conformance; Friction Engine: combine into F_p) → Storage (Parquet for tabular, Neo4j for graph) → Visualization (Streamlit + Plotly).

**Why not Kafka / real-time?**
Decision: explicitly out of scope because (1) the project is historical/batch by design, (2) BPIC 2011 is a static historical export with no streaming source, and (3) adding real-time infrastructure would add substantial engineering overhead disproportionate to a seminar-scope deliverable. Named directly as Future Work (§12, §31).

---

## H. Neo4j

**What are the nodes and relationships?**
Decision:
- Nodes: `Patient` (case), `Activity` (distinct activity type), optionally `Event` (individual timestamped occurrence)
- Relationships: `(:Patient)-[:PERFORMED]->(:Event)`, `(:Event)-[:NEXT]->(:Event)` (per-patient sequence), and an aggregated `(:Activity)-[:NEXT_ACTIVITY {count}]->(:Activity)` graph for global transition-frequency analysis.

**What can Neo4j do that Parquet/SQL can't do as conveniently?**
Variable-length path queries — finding loops, common sub-sequences, and multi-hop transition patterns — require expensive self-joins in SQL/Parquet but are natural, indexable Cypher queries in Neo4j (e.g., "find all patients whose journey contains a 3-cycle through Consultation/Laboratory"). It's also better suited to interactive graph exploration in the dashboard.

**Is Neo4j genuinely contributing, or just there for the rubric?**
Honest answer, to be stated as-is in the report: it's **partially rubric-motivated**, but it does provide **genuine, non-trivial value** specifically for the rework/loop-pattern and journey-exploration analyses (§21, §23), where path-based queries are meaningfully simpler and faster to express than the SQL-on-Parquet equivalent. It is not used as a "dump" for data that Parquet already serves well (e.g., flat friction scores, KPI aggregates stay in Parquet).

---

## I. Dashboard

**Main pages:** Overview, Process Explorer, Bottleneck Analysis, Rework Analysis, Friction Analytics, Patient Journey Explorer — exactly as specified in §18–23.

**Can the user select an individual patient?**
Yes — a case-ID selector/dropdown on the Patient Journey Explorer page (§23).

**Can the dashboard explain *why* a patient's score is high?**
Yes — this is treated as a first-class requirement, not an afterthought. Each patient view shows: (1) the visual journey trace with repeated/deviating steps flagged inline, (2) a component-breakdown bar chart (Waiting / Rework / Deviation contributions), and (3) a short generated explanatory line (e.g., "This patient's friction is driven primarily by rework: 3 repeated activities out of 8 total events"). Explainability is the dashboard's core design goal per §23.

---

## J. Evaluation

**How do we know the Friction Score is useful? What is the baseline?**
Decision: the baseline is **waiting time alone** (`W_p`), since it's the metric traditional process mining already reports.

**Can two patients have similar waiting times but different friction scores?**
This is the central empirical test (Phase 2, Experiment 1–2): identify patient pairs/clusters with similar `W_p` but divergent `F_p`, and show the driver is `R_p` and/or `D_p`.

**Does adding rework and deviation reveal additional information?**
Tested via correlation analysis: if `corr(F_p, W_p)` is high (~1.0), the composite adds little; a meaningfully lower correlation, combined with concrete counter-example patient pairs, is the evidence that it adds information. This is a core reported result, not assumed.

**How will we evaluate score stability?**
Decision: leave-one-out sensitivity of the min-max normalization bounds (does removing extreme cases change everyone's ranking materially?) plus rank stability checks.

**Sensitivity analysis on weights?**
Yes, formally in Phase 2 (§30, Experiment 4): vary `(w_W, w_R, w_D)` across the weight simplex and measure ranking stability (e.g., Spearman correlation between patient rankings at different weight settings) to see how sensitive conclusions are to the equal-weight assumption.

---

## K. Research / Paper

**Research question, hypothesis, contribution:** as stated in §25–26 of the master spec, unchanged.

**Working hypothesis for Phase 2:** *H1 — the PJFS ranking of patients is not fully explained by waiting time alone* (i.e., `corr(F_p, W_p) < 1`, with identifiable patient pairs where rework/deviation change the ranking materially).

**Are we claiming novelty correctly?**
Yes — the claim is explicitly narrow: a *specific, reproducible, explainable composite metric + integrated pipeline*, not "the first patient-centric process mining system" (§26 already states this correctly; this document reaffirms it should never be reworded to sound broader in the final report/abstract).

**Limitations (to be stated explicitly, not buried):**
- PJFS is an unvalidated proxy for observable process burden, not patient experience (§27).
- Waiting-time definition is an approximation forced by BPIC 2011's single-timestamp event semantics (Section C above).
- V1 rework definition cannot distinguish clinically legitimate repetition from true rework.
- Equal weighting is a neutral default, not empirically derived.
- Deviation is relative to a *discovered* model, which itself carries discovery-algorithm bias (Inductive Miner assumptions).
- Single hospital, single department (gynaecology) — generalizability to other departments/hospitals is untested.

**What constitutes success for V1?**
An end-to-end reproducible pipeline; a documented, working PJFS with clear component breakdowns; a dashboard that visibly explains individual scores; and at least one concrete demonstration that PJFS diverges meaningfully from waiting-time-only ranking for some patients.

---

## L. Scope

- **Only BPIC 2011 for V1** — yes, confirmed (§10).
- **Other hospital datasets** — architecture is designed to be schema-extensible (§11), but *not implemented or tested* in V1; remains Future Work.
- **Required format for future external data** — the standardized internal schema: `case_id`, `activity`, `timestamp`, optional `resource`, optional `event_type` (§11).
- **Live hospital streams, ML/prediction, patient satisfaction prediction, clinical decision support** — all explicitly and entirely out of scope for V1, per §29, with no exceptions.

---

## M. Data-Validated Revisions (from actual `Hospital_log.xes` inspection)

The methodology decisions above were made before inspecting the real file. Running the inspection script against the actual 81.41 MB / 1,143-case / 150,291-event log confirmed some assumptions and **forced concrete revisions** to others. This section supersedes the relevant parts of sections C, E, F, and K above where they conflict.

**Confirmed facts:**
- 1,143 cases, 150,291 events, avg. 131.49 events/case — this is real BPIC 2011, matches expectations.
- Every event's `lifecycle:transition = "complete"` — confirms there are no start/complete event pairs (Section C's original reasoning holds).
- Event-level fields are ~100% filled (`org:group`/`Section` at 99.99%, everything else 100%) — no meaningful missing-data problem.
- 624 distinct `concept:name` activity values; `Activity code` has 675.

**Revision 1 — Waiting-time definition (supersedes §C; corrected after full-file check):**
The initial small sample (6 events) happened to all be midnight timestamps, leading to a premature conclusion that *all* event timestamps are day-only. A full-file check (`inspect_xes_followup.py`) shows this generalization was wrong: **57.9% of events carry genuine intraday timestamps**; only 42.1% are exactly midnight. Average events per (case, day) is 7.56, consistent with legitimate batched lab panels drawn at once — same-instant clustering here often reflects real clinical behavior, not a data-quality gap.
**Final decision:** `Wait_p,i` is computed directly from **raw event timestamps** (not collapsed to day-granularity as originally proposed). The proportion of midnight-stamped events (42.1%) is documented as a transparency note in the methodology — some zero/near-zero waits are attributable to it — but it does not justify discarding sub-day precision for the majority of the log. Trace-level DTC `Start date`/`End date` (full `HH:MM:SS` precision) remain available as a secondary cross-check on total episode span.

**Revision 3 (resolved) — `Number of executions` is NOT a rework multiplier:**
Full-file check: only 1.17% of events (1,757 / 150,291) have `Number of executions != 1`, and the deviating values include negative numbers (`-1`, `-200`, `-300`, `-100`, `-20`, `-2`) alongside round figures (`300`, `200`, `100`...). Negative "execution counts" only make sense as a **billing quantity/credit-reversal field**, not a clinical repeat count — consistent with Revision 3's finding that the activity field mixes in tariff/billing line items.
**Final decision:** the Rework formula stays exactly as originally specified — `Rework_p,a = max(0, Count_p,a − 1)` on raw event-row occurrences. `Number of executions` is excluded from the formula entirely; using it would have introduced nonsensical negative "rework" contributions from billing corrections.

**Revision 2 — What a "case" represents (supersedes the implicit assumption in §2 and §27):**
Trace-level attributes repeat up to 15 times (`Diagnosis:1..15`, `Treatment code:1..15`, `Specialism code:1..15`, `Start/End date:1..15`), meaning a single case can bundle **up to 16 distinct diagnosis-treatment combinations**, consistent with the ~131 events/case average and the 2005–2008 date range.
**Decision:** V1 still scores the entire case as one journey (unchanged behavior), but the report must state explicitly that a "journey" in this dataset is a patient's **entire multi-year recorded history**, not a single clinical episode. This is now a first-class limitation, not a footnote.

**Revision 3 — Activity field contains administrative/billing entries (refines §D and §8):**
Top-frequency `concept:name` values include clear billing/tariff line items (`ordertarief`, `administratief tarief - eerste pol`, `190205 klasse 3b a205`, `190101 bovenreg.toesl. a101`) mixed with genuine clinical activities (lab tests, consultations).
**Decision:** V1 keeps the full, unfiltered activity set by default (preserves objectivity/reproducibility), but the report must explicitly name this as a confound — repeated billing entries will inflate `R_p` without representing genuine clinical rework. A "clinical-only" filtered activity variant is added to the Phase 2 sensitivity-analysis list (alongside weight sensitivity), not applied silently in V1.

**Revision 4 (finalized) — Discovery alphabet for the reference process model (supersedes §E's implicit assumption):**
624 distinct `concept:name` activities is too high-cardinality for Inductive Miner to produce an interpretable process model — it would yield an unreadable/flower model and near-meaningless deviation costs. Two coarser candidate fields were checked at full-file scale:
- `Section` (7 values) — rejected: extremely skewed (68% of all events fall into a single value, `"Section 4"`), and contains a data-quality bug — `"Sectoin 7"` (32 events) is a typo for `"Section 7"` that must be normalized during PySpark cleaning (§13) before any grouping, regardless of which field is used downstream.
- `org:group` (42 values) — accepted, with a long tail: `General Lab Clinical Chemistry` (63.2%) + `Nursing ward` (20.7%) alone cover 84% of events; ~30 departments have under 100 events each.

**Final decision:** the reference process model (for conformance/`D_p`) is discovered at the **`org:group`** level, with a **frequency-threshold collapse**: the top ~10–12 departments are kept individually, and the long tail is merged into an `"Other department"` category. This keeps the discovery alphabet small enough for Inductive Miner to produce a readable model, stays clinically interpretable, and conveniently doubles as the "resource" field in the standardized schema (§11). Full `concept:name` granularity is retained separately for the Rework component and for detailed Process Explorer views in the dashboard.

**Revision 5 — Scalability honesty (refines §F):**
81 MB / 150K events is confirmed to be modest in absolute terms — reinforces the existing decision not to overclaim a "big data" justification for Spark; the report continues to frame PySpark as an architectural/scalability demonstration for future multi-hospital extension, not a requirement of this file.

**Status: all originally-flagged open items are now resolved.** Waiting-time, Rework, and the discovery-alphabet questions all have final, data-validated definitions above. The remaining unresolved item for the methodology is the exact percentile-clipping thresholds for outlier handling (§B), which will be determined empirically once the actual `W_p`, `R_p`, `D_p` distributions are computed during pipeline implementation — this is expected engineering, not an open design question.
