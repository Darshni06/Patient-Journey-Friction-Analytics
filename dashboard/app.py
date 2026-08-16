"""
Patient Journey Friction Analytics - Streamlit Dashboard

Run with:
    streamlit run dashboard/app.py

Reads exclusively from the Parquet outputs produced by run_pipeline.py
(outputs/*.parquet) and, for journey/loop exploration, from Neo4j (see
src/storage/neo4j_loader.py). Never fabricates data - if a required output
table hasn't been generated yet, the relevant page says so explicitly and
tells you which pipeline command to run, rather than showing an empty or
fake chart.
"""

from __future__ import annotations

import os

import pandas as pd
import plotly.express as px
import streamlit as st

OUTPUTS_DIR = os.environ.get("PJFA_OUTPUTS_DIR", "outputs")

FRICTION_DISCLAIMER = (
    "Friction Score reflects observable process burden (waiting, repetition, "
    "pathway deviation) relative to this dataset's patient cohort. It is "
    "**not** a measure of patient satisfaction, distress, or care quality, "
    "and it scores each case's entire recorded multi-year history, not a "
    "single clinical episode."
)


@st.cache_data
def load_table(name: str) -> pd.DataFrame | None:
    path = os.path.join(OUTPUTS_DIR, f"{name}.parquet")
    if not os.path.exists(path):
        return None
    return pd.read_parquet(path)


def missing_table_notice(name: str, pipeline_hint: str) -> None:
    st.warning(
        f"`{name}.parquet` not found in `{OUTPUTS_DIR}/`. Run the pipeline "
        f"first:\n\n```\npython run_pipeline.py --input Hospital_log.xes\n```\n\n"
        f"({pipeline_hint})"
    )


def page_overview():
    st.header("📊 Overview")
    st.caption(FRICTION_DISCLAIMER)

    events = load_table("clean_events")
    friction = load_table("friction_scores")

    if friction is None:
        missing_table_notice("friction_scores", "Produces per-case Friction Scores.")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Patients / cases", f"{friction['case_id'].nunique():,}")
    if events is not None:
        col2.metric("Total events", f"{len(events):,}")
        col3.metric("Distinct activities", f"{events['concept:name'].nunique():,}")
    col4.metric("Mean Friction Score", f"{friction['friction_score'].mean():.3f}")

    st.subheader("Friction Score distribution")
    fig = px.histogram(friction, x="friction_score", nbins=30)
    st.plotly_chart(fig, use_container_width=True)

    high_friction_pct = (friction["friction_score"] >= friction["friction_score"].quantile(0.9)).mean() * 100
    st.metric("Share of patients in top decile of Friction", f"{high_friction_pct:.1f}%")


def page_process_explorer():
    st.header("🔄 Process Explorer")
    events = load_table("clean_events")
    if events is None:
        missing_table_notice("clean_events", "Produces the cleaned event log used here.")
        return

    st.subheader("Activity frequency (top 30)")
    top_activities = events["concept:name"].value_counts().head(30).reset_index()
    top_activities.columns = ["activity", "count"]
    fig = px.bar(top_activities, x="count", y="activity", orientation="h")
    fig.update_layout(yaxis={"categoryorder": "total ascending"}, height=700)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Department (org:group) frequency")
    dept_counts = events["org:group"].value_counts().reset_index()
    dept_counts.columns = ["department", "count"]
    fig2 = px.bar(dept_counts, x="count", y="department", orientation="h")
    fig2.update_layout(yaxis={"categoryorder": "total ascending"}, height=600)
    st.plotly_chart(fig2, use_container_width=True)
    st.caption(
        "Process discovery for the Deviation component runs over a collapsed "
        "version of this field (top departments by ~95% cumulative coverage; "
        "the long tail is grouped as 'Other department') - see README "
        "methodology section for why."
    )


def page_bottleneck_analysis():
    st.header("🚧 Bottleneck Analysis (Waiting)")
    waiting = load_table("patient_waiting")
    if waiting is None:
        missing_table_notice("patient_waiting", "Produces per-case Waiting Burden.")
        return

    st.caption(
        "Waiting is computed from raw event timestamps between consecutive "
        "*clinical* events; administrative/billing entries are excluded as "
        "wait-interval endpoints. See README for the exact rule."
    )

    col1, col2 = st.columns(2)
    col1.metric("Median total wait (hours)", f"{(waiting['total_wait_seconds'].median() / 3600):.1f}")
    col2.metric("Cases with reported timestamp anomalies", int((waiting.get("anomaly_count", 0) > 0).sum()))

    st.subheader("Total waiting time distribution (hours)")
    waiting_hours = waiting["total_wait_seconds"] / 3600
    fig = px.histogram(waiting_hours, nbins=40, labels={"value": "Total wait (hours)"})
    st.plotly_chart(fig, use_container_width=True)


def page_rework_analysis():
    st.header("🔁 Rework Analysis")
    rework = load_table("patient_rework")
    if rework is None:
        missing_table_notice("patient_rework", "Produces per-case Rework Burden.")
        return

    st.caption(
        "Rework_p = Σ log(1 + max(0, Count_p,a − 1)), log-dampened so that "
        "one hyper-repeated routine activity (e.g. a serial lab test) "
        "doesn't dominate the score. See README methodology section."
    )

    st.subheader("Rework score distribution")
    fig = px.histogram(rework, x="rework_score", nbins=30)
    st.plotly_chart(fig, use_container_width=True)

    if "total_events" in rework.columns:
        st.subheader("Rework vs. total events per case")
        fig2 = px.scatter(rework, x="total_events", y="rework_score", hover_data=["case_id"])
        st.plotly_chart(fig2, use_container_width=True)


def page_deviation_analysis():
    st.header("📈 Pathway Deviation")
    deviation = load_table("patient_deviation")
    if deviation is None:
        missing_table_notice("patient_deviation", "Produces per-case Deviation cost from conformance checking.")
        return

    st.caption(
        "Deviation is computed via alignment-based conformance checking "
        "against an Inductive-Miner-discovered reference process model over "
        "collapsed departments (org:group). Higher deviation means a more "
        "structurally unusual journey relative to the discovered model - "
        "**not** necessarily worse care."
    )

    st.subheader("Deviation cost distribution")
    fig = px.histogram(deviation, x="raw_deviation_cost", nbins=30)
    st.plotly_chart(fig, use_container_width=True)


def page_friction_analysis():
    st.header("📈 Friction Analytics")
    st.caption(FRICTION_DISCLAIMER)

    friction = load_table("friction_scores")
    if friction is None:
        missing_table_notice("friction_scores", "Produces per-case Friction Scores.")
        return

    st.subheader("Component contribution (Waiting vs Rework vs Deviation)")
    melted = friction.melt(
        id_vars=["case_id", "friction_score"],
        value_vars=["waiting_norm", "rework_norm", "deviation_norm"],
        var_name="component",
        value_name="normalized_value",
    )
    fig = px.box(melted, x="component", y="normalized_value")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Waiting vs Friction (does the composite add information beyond waiting alone?)")
    fig2 = px.scatter(
        friction, x="waiting_norm", y="friction_score", color="dominant_component",
        hover_data=["case_id"],
    )
    st.plotly_chart(fig2, use_container_width=True)
    corr = friction["waiting_norm"].corr(friction["friction_score"])
    st.metric("Correlation: Waiting (normalized) vs Friction Score", f"{corr:.3f}")
    st.caption(
        "A correlation well below 1.0 indicates the composite score is "
        "genuinely diverging from waiting-time-only ranking for at least "
        "some patients - the core research question (RQ3)."
    )

    st.subheader("Top 20 patients by Friction Score")
    top20 = friction.sort_values("friction_score", ascending=False).head(20)
    st.dataframe(
        top20[["case_id", "friction_score", "waiting_norm", "rework_norm", "deviation_norm", "dominant_component"]],
        use_container_width=True,
    )


def page_patient_explorer():
    st.header("👤 Patient Journey Explorer")
    friction = load_table("friction_scores")
    events = load_table("clean_events")

    if friction is None:
        missing_table_notice("friction_scores", "Needed to look up a case's score.")
        return

    case_id = st.selectbox("Select a case", sorted(friction["case_id"].unique()))
    row = friction[friction["case_id"] == case_id].iloc[0]

    st.subheader(f"Case {case_id}")
    st.caption(FRICTION_DISCLAIMER)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Waiting (norm)", f"{row['waiting_norm']:.2f}")
    col2.metric("Rework (norm)", f"{row['rework_norm']:.2f}")
    col3.metric("Deviation (norm)", f"{row['deviation_norm']:.2f}")
    col4.metric("Friction Score", f"{row['friction_score']:.2f}")

    dominant = row["dominant_component"]
    dominant_value = row[f"{dominant}_norm"]
    st.info(
        f"This patient's friction is driven primarily by **{dominant}** "
        f"({dominant_value:.2f} normalized), given equal component weights (1/3 each)."
    )

    if events is not None:
        st.subheader("Chronological journey")
        case_events = events[events["case_id"] == case_id].sort_values("_timestamp_iso")
        display_cols = [c for c in ["_timestamp_iso", "concept:name", "org:group", "Section"] if c in case_events.columns]
        st.dataframe(case_events[display_cols], use_container_width=True)

        st.subheader("Repeated activities in this journey")
        counts = case_events["concept:name"].value_counts()
        repeated = counts[counts > 1].reset_index()
        # value_counts().reset_index() column naming differs across pandas
        # versions (older pandas names the count column after the original
        # series - "concept:name" - newer pandas names it "count"). Setting
        # .columns directly avoids relying on a version-specific name and
        # avoids ever producing two columns with the same name (which is
        # what caused "Duplicate column names found: ['count', 'count']").
        repeated.columns = ["activity", "count"]
        if len(repeated) == 0:
            st.write("No repeated activities in this case's journey.")
        else:
            st.dataframe(repeated, use_container_width=True)


def main():
    st.set_page_config(page_title="Patient Journey Friction Analytics", layout="wide")
    st.sidebar.title("PJFA Dashboard")
    st.sidebar.caption(
        "Research analytics tool - not a hospital SaaS product, not a "
        "clinical decision-support system, not a live monitoring system."
    )

    pages = {
        "📊 Overview": page_overview,
        "🔄 Process Explorer": page_process_explorer,
        "🚧 Bottleneck Analysis": page_bottleneck_analysis,
        "🔁 Rework Analysis": page_rework_analysis,
        "📈 Pathway Deviation": page_deviation_analysis,
        "📈 Friction Analytics": page_friction_analysis,
        "👤 Patient Journey Explorer": page_patient_explorer,
    }
    choice = st.sidebar.radio("Navigate", list(pages.keys()))
    pages[choice]()


if __name__ == "__main__":
    main()