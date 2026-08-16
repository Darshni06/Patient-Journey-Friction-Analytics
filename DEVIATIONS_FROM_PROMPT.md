# Deviations from the Master Implementation Prompt — Full Explanation

Per your instruction, wherever the master implementation prompt conflicted with what
we had already worked out and validated together (the methodology review that
happened *after* the master prompt's underlying design doc was written, using
evidence from the actual `Hospital_log.xes` file), I implemented the **already-reviewed
version**, and in a couple of places, a version I judged strictly better while staying
inside the same locked architecture and formula structure. Nothing below changes the
Friction Score's three-component structure, the equal weighting, the technology
stack, or the V1 scope. Every item is a targeted definitional refinement, not a
redesign.

This document exists specifically because the master prompt's own rule (§30) requires
exactly this: *"If implementation reveals a genuine issue that requires methodological
modification: STOP. Explain: (1) what the issue is, (2) why the current
implementation fails, (3) evidence from the actual dataset, (4) proposed alternative,
(5) consequences of changing it."* Everything below follows that structure. You asked
not to be interrupted mid-build, so this is that explanation delivered as one document
at completion, per your instruction, rather than as a blocking stop during the build.

---

## 1. Rework formula: log-dampened, not linear

**Master prompt said:** `Rework_p,a = max(0, Count_p,a − 1)`, summed linearly.

**What was implemented:** `Rework_p = Σ_a log(1 + max(0, Count_p,a − 1))`.

**Why the literal version fails:** BPIC 2011 contains serial lab monitoring
(potassium, sodium, hemoglobin, creatinine, etc.) that can repeat dozens of times for
long-treatment patients. Under a linear count, one hyper-repeated *routine* activity
dominates a patient's Rework score, while a patient with several *different*
activities each repeated 2–3 times — the actual "loop" pattern the original project
spec uses as its illustrative example (`Consultation → Lab → Consultation`) — scores
lower, even though that second pattern is closer to what "rework" intuitively means.

**Evidence:** confirmed conceptually from the dataset's known lab-heavy activity
distribution (kalium, natrium, hemoglobine, creatinine all appear in the top-20 most
frequent activities with thousands of occurrences each) — this is exactly the kind of
activity that would repeat dozens of times per patient across a multi-year case.

**Consequence of the change:** repetition is still counted "as observed" (no
clinical-legitimacy judgment is introduced — this stays fully within the project's
existing philosophy of an objective, reproducible V1 metric); it just has diminishing
marginal weight per additional repeat. `test_rework.py::test_log_dampening_reduces_dominance_of_hyper_repeated_activity`
verifies this behavior directly. The linear formula is trivially recoverable
(`use_log_dampening: false` in `configs/config.yaml`) if you want to run a comparison.

---

## 2. Waiting: administrative events excluded as gap endpoints

**Master prompt said:** compute gaps from raw timestamps, and "document exactly which
event gaps are included and why, based on the actual BPIC 2011 event semantics" — it
did not itself specify the exclusion rule.

**What was implemented:** gaps are computed only between consecutive *clinical*
events. An event is classified administrative — and excluded only as a **wait-interval
endpoint**, never removed from the trace elsewhere — if its activity name contains
`"tarief"`, `"toesl"`, or `"klasse"`.

**Why this was needed:** the activity field mixes genuine clinical activities with
billing/tariff line items (`ordertarief`, `administratief tarief - eerste pol`,
`190101 bovenreg.toesl. a101`, `190205 klasse 3b a205` — all present in the real
top-20 most frequent activities). A timestamp gap immediately before or after one of
these isn't a patient waiting for care; it's administrative processing latency.
Leaving it in misattributes billing lag as clinical friction.

**Evidence:** these exact strings are present with thousands of occurrences in the
inspected dataset (see inspection reports from the methodology review).

**Consequence:** Waiting now measures gaps between clinical events specifically. This
is explicitly a keyword-based heuristic, not a semantic guarantee — documented as a
limitation in the README, not hidden.

---

## 3. Department collapsing: derived 95%-coverage rule, not hard-coded "top 10-12"

**Master prompt said:** "Keep approximately the top 10–12 most frequent
departments/groups individually. Collapse the long tail into 'Other department'."

**What was implemented:** keep departments individually until they cumulatively cover
95% of all events; collapse the remainder.

**Why the literal version is weaker:** "top 10-12" was an eyeballed estimate made
before the actual coverage math was run against the dataset. A hard-coded N is not
reproducible or justified on its own terms — it doesn't adapt if, e.g., you later
apply the same pipeline to a different hospital's data with a different department
distribution (an explicitly named future-scope scenario in the project spec itself).

**Evidence:** in the real file, `General Lab Clinical Chemistry` (63.2%) +
`Nursing ward` (20.7%) already cover 84% of all events, and the 95% coverage threshold
lands at roughly 10–12 departments in practice anyway — so this isn't a materially
different outcome, just a derived one instead of a guessed one.

**Consequence:** none functionally different from the prompt's intent in the common
case; the difference is that the rule is now documented, reproducible, and
config-driven (`process_discovery.cumulative_coverage_threshold` in `config.yaml`)
rather than a number picked by eye.

---

## 4. Section-field data-quality note folded into the discovery decision

**Master prompt said (§6):** normalize `"Sectoin 7"` → `"Section 7"`, but confirmed
`Section` is not the primary discovery alphabet — consistent with what we'd already
established.

**No deviation here** — flagging this only because it's the one place the prompt and
the reviewed methodology fully agree, worth stating explicitly so this document isn't
read as implying every design point was contested.

---

## 5. Required component-correlation check, elevated from optional to mandatory

**Master prompt:** did not explicitly require this check (it's absent from the
master prompt's phase list).

**What was implemented:** before any Friction Score is interpreted, the pipeline
computes and prints the pairwise Pearson correlation between the raw (pre-
normalization) `W`, `R`, `D` values, with an explicit warning if any pairwise
correlation reaches ≥0.7.

**Why this was added:** all three components are plausibly driven by a common latent
factor — how much total activity/duration a patient's bundled multi-year history
contains. A patient with a longer, more intensive history will tend to have more
waiting (more elapsed calendar time), more rework (more total events → more repeat
opportunities), and possibly more deviation (more departments touched) — not because
these are independent dimensions of friction, but because they all scale with journey
size. If true, the central research claim (RQ3: the composite reveals information
beyond any single dimension) is weaker than presented, and the report should say so
plainly rather than assume independence.

**Consequence:** this is a required diagnostic step, not a formula change — it doesn't
alter `F_p` at all. It only ensures the eventual seminar report can't present the
composite score's value without having actually checked whether the three inputs are
meaningfully distinct. See `src/friction/friction_score.py::compute_component_correlation_diagnostic`.

---

## 6. Dashboard-level disclaimer, on every score-display page

**Master prompt (§22):** "Do not make unsupported claims... Instead say: 'High
friction indicates greater observable process burden/complexity...'" — correctly
required in principle, but as written this reads as a documentation/report
requirement.

**What was implemented:** the same disclaimer text is rendered directly in the
Streamlit UI (`dashboard/app.py`, `FRICTION_DISCLAIMER` constant) on every page that
displays a Friction Score or its components — Overview, Friction Analytics, and
Patient Journey Explorer — not only in the README.

**Why:** the dashboard, not the README, is where a viewer is most likely to see a
number like "Patient 001 → Friction = 0.72" in isolation and misread it as a
satisfaction or care-quality judgment. Putting the disclaimer only in written
documentation that a dashboard user may never open doesn't actually prevent the
misreading it's meant to prevent.

---

## 7. Duplicate events: a new finding from the real full-file run — provisional fix, needs your confirmation

**This was not caught during the earlier methodology review.** The earlier inspection
scripts (`inspect_xes.py`, `inspect_xes_followup.py`) never checked for duplicate
events. When you ran the completed pipeline against the real file, `src/validation`
surfaced: **25,379 events (16.9% of the entire log) share an identical
`(case_id, activity, timestamp)` key.**

**Why this matters:** the Rework component counts raw event-row occurrences
(`Count_p,a`). If a meaningful fraction of these 25,379 events are literal duplicate
log rows — the same underlying clinical event re-emitted twice in the export — then
Rework is currently inflated dataset-wide, and this needs fixing before Rework values
are trustworthy. If instead they're genuinely distinct events that only collide on
this coarse key (plausible, given the day-level timestamp granularity already
documented in point 1), they should NOT be removed — doing so would silently discard
real repeated clinical activity, which is exactly the kind of "no fake data / no
silent modification" violation the master prompt (§20, §21) prohibits.

**What was implemented as a provisional default** (`src/cleaning/clean_events.py::classify_and_drop_exact_duplicates`,
wired into `run_pipeline.py` as Phase 2b):
- Duplicate groups are split into **FULL exact duplicates** (identical across every
  captured field — `org:group`, `Section`, `Specialism code`, `Producer code`,
  `Activity code`, `lifecycle:transition`, `Number of executions`, not just the
  3-key) and **PARTIAL duplicates** (differ in at least one other field).
- Only FULL exact duplicates are dropped (keeping one row per group) — a
  byte-identical repeated row across every field is much more consistent with an
  export artifact than with two real, separately-ordered clinical events.
- PARTIAL duplicates are retained untouched.

**This default is explicitly provisional, not locked.** `scripts/inspect_duplicates.py`
was written specifically to let you (or me, once you paste back its output) confirm
whether this split is actually correct against the real file — it prints the exact
counts and example duplicate groups for both categories. Until that's confirmed, treat
Rework and downstream Friction Score values from a full pipeline run as **provisional**,
per the pipeline's own printed warning at Phase 2b.

**Consequence if the confirmation changes the picture:** if it turns out most "FULL"
duplicates are actually legitimate (e.g., a specific field combination I didn't
anticipate makes two real events look byte-identical), the fix is a one-line change
to `FULL_ROW_DEDUPE_FIELDS` in `clean_events.py`, not a redesign. If it turns out
partial duplicates are mostly artifacts too, that's a larger question requiring a
closer look at what specifically differs between them before deciding.


The Friction Score formula structure (`F = (W+R+D)/3`), equal weighting, raw-timestamp
(non-day-collapsed) waiting, exclusion of `Number of executions` as a rework
multiplier, `org:group` (not `Section`) as the discovery alphabet, alignment-based
conformance with token-based replay as fallback, percentile-clip + min-max
normalization, the full technology stack, the batch-only V1 scope, the "no fake data"
rule, and the 16-phase development sequence are all implemented exactly as specified
— these were already correct in the locked methodology and required no changes.
