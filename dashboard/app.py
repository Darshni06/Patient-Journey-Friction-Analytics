"""
Patient Journey Friction Analytics - Streamlit Dashboard

Run with:
    streamlit run dashboard/app.py

Reads exclusively from the Parquet outputs produced by run_pipeline.py
(outputs/*.parquet). Never fabricates data - if a required output
table hasn't been generated yet, the relevant page says so explicitly.
"""

from __future__ import annotations

import os
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

OUTPUTS_DIR = os.environ.get("PJFA_OUTPUTS_DIR", "outputs")

FRICTION_DISCLAIMER = (
    "Friction Score reflects observable process burden (waiting, repetition, "
    "pathway deviation) relative to this dataset's patient cohort. It is "
    "**not** a measure of patient satisfaction, distress, or care quality, "
    "and it scores each case's entire recorded multi-year history, not a "
    "single clinical episode."
)

DEVIATION_DISCLAIMER = (
    "Deviation measures difference from the discovered reference process. "
    "A deviation does not automatically indicate poor care or an inappropriate "
    "clinical decision."
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

def safe_get_data(data, col, default=None):
    if data is not None and col in data.columns:
        return data[col]
    return default

def safe_has_column(data, col):
    return data is not None and col in data.columns

def normalize_for_display(data, col, max_val=1.0):
    if data is None or col not in data.columns:
        return None
    return data[col].clip(0, max_val)

@st.cache_data
def get_friction_categories(friction_df):
    if friction_df is None:
        return None
    df = friction_df.copy()
    q1, q3 = df['friction_score'].quantile(0.33), df['friction_score'].quantile(0.67)
    df['friction_category'] = pd.cut(
        df['friction_score'],
        bins=[-float('inf'), q1, q3, float('inf')],
        labels=['Lower Friction', 'Moderate Friction', 'Higher Friction']
    )
    return df

def page_overview():
    st.header("📊 Executive Overview")
    st.caption(FRICTION_DISCLAIMER)
    
    # Load data
    events = load_table("clean_events")
    friction = load_table("friction_scores")
    
    if friction is None:
        missing_table_notice("friction_scores", "Produces per-case Friction Scores.")
        return
    
    # Ensure required columns exist
    required_friction_cols = ['case_id', 'friction_score', 'waiting_norm', 'rework_norm', 'deviation_norm']
    for col in required_friction_cols:
        if col not in friction.columns:
            st.error(f"Required column '{col}' not found in friction_scores.parquet")
            return
    
    # KPI Cards
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Total Patients", f"{friction['case_id'].nunique():,}")
    
    if events is not None:
        col2.metric("Total Events", f"{len(events):,}")
        if 'concept:name' in events.columns:
            col3.metric("Activities", f"{events['concept:name'].nunique():,}")
    else:
        col2.metric("Total Events", "N/A")
        col3.metric("Activities", "N/A")
    
    col4.metric("Avg Friction", f"{friction['friction_score'].mean():.3f}")
    col5.metric("Max Friction", f"{friction['friction_score'].max():.3f}")
    
    # Get categories if we can
    cat_df = get_friction_categories(friction)
    if cat_df is not None:
        cat_counts = cat_df['friction_category'].value_counts()
        if len(cat_counts) > 0:
            most_common = cat_counts.index[0]
            col6.metric("Most Common Category", most_common)
        else:
            col6.metric("Most Common Category", "N/A")
    else:
        col6.metric("Most Common Category", "N/A")
    
    st.divider()
    
    # Visualization A: Friction Score Distribution
    st.subheader("Friction Score Distribution")
    fig = px.histogram(
        friction, 
        x='friction_score', 
        nbins=30,
        labels={'friction_score': 'Friction Score', 'count': 'Number of Patients'},
        title="Distribution of Observable Process Burden"
    )
    fig.update_layout(
        xaxis_title="Friction Score",
        yaxis_title="Number of Patients",
        showlegend=False,
        height=400
    )
    fig.add_vline(x=friction['friction_score'].mean(), line_dash="dash", line_color="red", 
                  annotation_text=f"Mean: {friction['friction_score'].mean():.3f}")
    fig.add_vline(x=friction['friction_score'].median(), line_dash="dot", line_color="green",
                  annotation_text=f"Median: {friction['friction_score'].median():.3f}")
    st.plotly_chart(fig, use_container_width=True)
    
    with st.expander("📖 What this shows"):
        st.markdown("""
        This distribution shows whether friction is concentrated around a typical range or whether a 
        smaller group of journeys experiences substantially greater process burden.
        
        **Key observations to look for:**
        - **Skewness**: A right-skewed distribution means most patients have low friction, but a few have very high friction
        - **Spread**: Wide distribution indicates varying process burden across patients
        - **Peaks**: Multiple peaks might suggest distinct journey patterns
        """)
    
    # Visualization B: W/R/D Contribution
    st.subheader("Component Contribution Analysis")
    
    # Prepare data for component comparison
    comp_df = friction[['waiting_norm', 'rework_norm', 'deviation_norm']].copy()
    comp_means = comp_df.mean()
    comp_medians = comp_df.median()
    
    # Create a combined bar chart with mean values
    fig2 = go.Figure()
    
    # Add mean bars
    fig2.add_trace(go.Bar(
        x=['Waiting', 'Rework', 'Deviation'],
        y=comp_means.values,
        name='Mean',
        marker_color=['#1f77b4', '#ff7f0e', '#2ca02c'],
        text=[f"{v:.3f}" for v in comp_means.values],
        textposition='outside'
    ))
    
    # Add median points
    fig2.add_trace(go.Scatter(
        x=['Waiting', 'Rework', 'Deviation'],
        y=comp_medians.values,
        mode='markers+lines',
        name='Median',
        marker=dict(size=12, color='red', symbol='diamond'),
        line=dict(dash='dash', color='red')
    ))
    
    fig2.update_layout(
        title="Normalized Component Contributions",
        xaxis_title="Component",
        yaxis_title="Normalized Value",
        height=400,
        showlegend=True,
        yaxis_range=[0, max(comp_means.max(), comp_medians.max()) * 1.2]
    )
    
    st.plotly_chart(fig2, use_container_width=True)
    
    with st.expander("📖 What this shows"):
        st.markdown("""
        The Friction Score is composed equally from normalized Waiting, Rework, and Deviation in V1. 
        This view shows which dimensions are comparatively higher across the analyzed population.
        
        **Interpretation:**
        - Higher Waiting suggests time gaps are a major contributor to process burden
        - Higher Rework indicates repeated activities are common
        - Higher Deviation suggests journeys often differ from the reference process
        """)
    
    # Visualization C: Friction Category Distribution
    if cat_df is not None and 'friction_category' in cat_df.columns:
        st.subheader("Friction Category Distribution")
        
        # Count categories
        cat_counts = cat_df['friction_category'].value_counts().reset_index()
        cat_counts.columns = ['Category', 'Count']
        
        fig3 = px.pie(
            cat_counts, 
            values='Count', 
            names='Category',
            title="Distribution by Friction Category",
            color_discrete_sequence=['#2ecc71', '#f1c40f', '#e74c3c']
        )
        fig3.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig3, use_container_width=True)
        
        with st.expander("📖 What this shows"):
            st.markdown(f"""
            Patients are categorized into three descriptive groups based on their Friction Score:
            
            - **Lower Friction**: Bottom 33% of scores (≤ {cat_df['friction_score'].quantile(0.33):.3f})
            - **Moderate Friction**: Middle 33% ({cat_df['friction_score'].quantile(0.33):.3f} - {cat_df['friction_score'].quantile(0.67):.3f})
            - **Higher Friction**: Top 33% (≥ {cat_df['friction_score'].quantile(0.67):.3f})
            
            These are descriptive quantile-based categories for easier interpretation, not clinically meaningful thresholds.
            """)

def page_friction_analytics():
    st.header("📈 Friction Analytics")
    st.caption(FRICTION_DISCLAIMER)
    
    friction = load_table("friction_scores")
    if friction is None:
        missing_table_notice("friction_scores", "Produces per-case Friction Scores.")
        return
    
    # Ensure required columns
    required_cols = ['case_id', 'friction_score', 'waiting_norm', 'rework_norm', 'deviation_norm']
    for col in required_cols:
        if col not in friction.columns:
            st.error(f"Required column '{col}' not found in friction_scores.parquet")
            return
    
    # Sidebar filters
    with st.sidebar:
        st.markdown("### 🔍 Filter Controls")
        
        # Friction range filter
        min_friction, max_friction = float(friction['friction_score'].min()), float(friction['friction_score'].max())
        friction_range = st.slider(
            "Friction Score Range",
            min_value=min_friction,
            max_value=max_friction,
            value=(min_friction, max_friction),
            step=0.01
        )
        
        # Patient selector (multi-select)
        patients = friction['case_id'].unique()
        selected_patients = st.multiselect(
            "Select Patients",
            options=patients,
            default=[],
            help="Select specific patients to analyze"
        )
        
        # Apply filters
        filtered_df = friction.copy()
        if selected_patients:
            filtered_df = filtered_df[filtered_df['case_id'].isin(selected_patients)]
        filtered_df = filtered_df[
            (filtered_df['friction_score'] >= friction_range[0]) &
            (filtered_df['friction_score'] <= friction_range[1])
        ]
        
        if len(filtered_df) == 0:
            st.warning("No patients match the current filters.")
    
    # A. W vs R Scatter Plot
    st.subheader("Waiting vs Rework Relationship")
    fig = px.scatter(
        filtered_df,
        x='waiting_norm',
        y='rework_norm',
        color='friction_score',
        hover_data=['case_id'],
        labels={
            'waiting_norm': 'Normalized Waiting',
            'rework_norm': 'Normalized Rework',
            'friction_score': 'Friction Score'
        },
        title="Waiting vs Rework Relationship"
    )
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)
    
    with st.expander("📖 What this shows"):
        st.markdown("""
        This scatter plot investigates whether waiting and rework tend to increase together across patient journeys.
        
        **Important**: Correlation does NOT establish causation. Patients with high values in both dimensions may share 
        common underlying factors such as journey complexity.
        """)
    
    # B. W vs D Scatter Plot
    st.subheader("Waiting vs Deviation Relationship")
    fig2 = px.scatter(
        filtered_df,
        x='waiting_norm',
        y='deviation_norm',
        color='friction_score',
        hover_data=['case_id'],
        labels={
            'waiting_norm': 'Normalized Waiting',
            'deviation_norm': 'Normalized Deviation',
            'friction_score': 'Friction Score'
        },
        title="Waiting vs Deviation Relationship"
    )
    fig2.update_layout(height=400)
    st.plotly_chart(fig2, use_container_width=True)
    
    # C. R vs D Scatter Plot
    st.subheader("Rework vs Deviation Relationship")
    fig3 = px.scatter(
        filtered_df,
        x='rework_norm',
        y='deviation_norm',
        color='friction_score',
        hover_data=['case_id'],
        labels={
            'rework_norm': 'Normalized Rework',
            'deviation_norm': 'Normalized Deviation',
            'friction_score': 'Friction Score'
        },
        title="Rework vs Deviation Relationship"
    )
    fig3.update_layout(height=400)
    st.plotly_chart(fig3, use_container_width=True)
    
    # D. Component Correlation Matrix
    st.subheader("Component Correlation Matrix")
    
    # Calculate correlations
    corr_matrix = filtered_df[['waiting_norm', 'rework_norm', 'deviation_norm']].corr()
    
    # Create heatmap
    fig4 = px.imshow(
        corr_matrix,
        text_auto=True,
        color_continuous_scale='RdBu_r',
        range_color=[-1, 1],
        title="Correlation Between Components"
    )
    fig4.update_layout(height=400)
    st.plotly_chart(fig4, use_container_width=True)
    
    with st.expander("📖 What this shows"):
        st.markdown("""
        The three components may share common drivers such as journey size or complexity. 
        Correlation analysis helps determine whether the composite score contains multiple dimensions 
        or is dominated by one underlying factor.
        
        **Interpretation guide:**
        - **High correlation (>0.6)**: Components may be measuring similar underlying factors
        - **Moderate correlation (0.3-0.6)**: Some relationship but distinct dimensions
        - **Low correlation (<0.3)**: Components are relatively independent
        """)
    
    # E. Top High-Friction Patients
    st.subheader("Top High-Friction Patients")
    
    top_n = st.slider("Number of patients to show", min_value=5, max_value=50, value=20, step=5)
    top_patients = filtered_df.nlargest(top_n, 'friction_score')
    
    # Create interactive table with selection
    display_cols = ['case_id', 'friction_score', 'waiting_norm', 'rework_norm', 'deviation_norm']
    
    # Use a selectable table
    for idx, row in top_patients[display_cols].iterrows():
        cols = st.columns([2, 1, 1, 1, 1, 1])
        cols[0].write(f"**{row['case_id']}**")
        cols[1].write(f"{row['friction_score']:.3f}")
        cols[2].write(f"{row['waiting_norm']:.3f}")
        cols[3].write(f"{row['rework_norm']:.3f}")
        cols[4].write(f"{row['deviation_norm']:.3f}")
        if cols[5].button("🔍", key=f"view_{row['case_id']}_{idx}"):
            st.session_state['selected_patient'] = row['case_id']
            st.session_state['navigate_to'] = "👤 Patient Journey Explorer"
    
    # Display as dataframe as well for sorting
    st.caption("Click '🔍' to view detailed patient journey")
    st.dataframe(
        top_patients[display_cols].reset_index(drop=True),
        use_container_width=True,
        hide_index=True
    )

def page_patient_explorer():
    st.header("👤 Patient Journey Explorer")
    st.caption(FRICTION_DISCLAIMER)
    
    # Load data
    friction = load_table("friction_scores")
    events = load_table("clean_events")
    deviation = load_table("patient_deviation")
    waiting = load_table("patient_waiting")
    rework = load_table("patient_rework")
    
    if friction is None:
        missing_table_notice("friction_scores", "Needed to look up a case's score.")
        return
    
    # Patient selection
    all_patients = sorted(friction['case_id'].unique())
    
    # Check if we have a selected patient from another page
    if 'selected_patient' in st.session_state and st.session_state['selected_patient'] in all_patients:
        default_index = all_patients.index(st.session_state['selected_patient'])
    else:
        default_index = 0
    
    selected_case = st.selectbox("Select a patient", all_patients, index=default_index)
    
    # Get patient data
    patient_row = friction[friction['case_id'] == selected_case].iloc[0]
    
    # Friction Score Card
    st.markdown("### 🎯 Friction Score")
    score = patient_row['friction_score']
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    
    # Color based on score
    if score < 0.33:
        color = "green"
        status = "Lower"
    elif score < 0.67:
        color = "orange"
        status = "Moderate"
    else:
        color = "red"
        status = "Higher"
    
    col1.markdown(
        f"""
        <div style="background-color:{color}; padding:20px; border-radius:10px; text-align:center;">
            <h1 style="color:white; margin:0;">{score:.3f}</h1>
            <p style="color:white; margin:0;">Friction Score ({status})</p>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    # Component scores
    w = patient_row['waiting_norm']
    r = patient_row['rework_norm']
    d = patient_row['deviation_norm']
    
    col2.metric("Waiting (W)", f"{w:.3f}")
    col3.metric("Rework (R)", f"{r:.3f}")
    col4.metric("Deviation (D)", f"{d:.3f}")
    
    # WHY IS THIS SCORE HIGH? - Prominent explanation
    st.markdown("### ❓ WHY IS THIS SCORE HIGH?")
    
    dominant = patient_row.get('dominant_component', 'waiting_norm')
    dominant_clean = dominant.replace('_norm', '')
    dominant_value = patient_row[f'{dominant_clean}_norm']
    
    # Build explanation
    explanation_parts = []
    explanation_parts.append(f"**Patient {selected_case}** has a Friction Score of **{score:.3f}**.")
    
    # Component contributions
    comps = []
    if w > 0.2:
        comps.append(f"Waiting: {w:.3f}")
    if r > 0.2:
        comps.append(f"Rework: {r:.3f}")
    if d > 0.2:
        comps.append(f"Deviation: {d:.3f}")
    
    if comps:
        explanation_parts.append("\n\nThe largest observable contributors are:")
        for comp in comps:
            explanation_parts.append(f"• {comp}")
    else:
        explanation_parts.append("\n\nAll components are relatively low, contributing to a lower overall score.")
    
    # Add specific details based on available data
    if events is not None:
        case_events = events[events['case_id'] == selected_case]
        if not case_events.empty:
            activity_count = case_events['concept:name'].nunique()
            total_events = len(case_events)
            explanation_parts.append(f"\n\nThe journey contains {total_events} events across {activity_count} distinct activities.")
            
            # Check for repeated activities
            activity_counts = case_events['concept:name'].value_counts()
            repeated = activity_counts[activity_counts > 1]
            if len(repeated) > 0:
                explanation_parts.append(f"There are {len(repeated)} activities that appear multiple times in the journey.")
    
    if deviation is not None and selected_case in deviation['case_id'].values:
        dev_row = deviation[deviation['case_id'] == selected_case].iloc[0]
        if 'raw_deviation_cost' in dev_row:
            dev_cost = dev_row['raw_deviation_cost']
            explanation_parts.append(f"\n\nThe journey differs from the reference pathway with a deviation cost of {dev_cost:.2f}.")
    
    st.info(" ".join(explanation_parts))
    
    st.caption("The Friction Score is calculated as: **F = (W + R + D) / 3**, with equal weights in V1.")
    
    # Score decomposition visualization
    st.subheader("Score Decomposition")
    comp_df = pd.DataFrame({
        'Component': ['Waiting (W)', 'Rework (R)', 'Deviation (D)'],
        'Value': [w, r, d],
        'Contribution to Score': [w/3, r/3, d/3]
    })
    
    fig = px.bar(
        comp_df,
        x='Component',
        y='Value',
        title="Component Contributions to Friction Score",
        text=[f"{v:.3f}" for v in comp_df['Value']],
        color='Component',
        color_discrete_sequence=['#1f77b4', '#ff7f0e', '#2ca02c']
    )
    fig.update_layout(
        yaxis_title="Normalized Value",
        height=300,
        showlegend=False
    )
    fig.update_traces(textposition='outside')
    st.plotly_chart(fig, use_container_width=True)
    
    # Also show the contribution to the final score
    st.caption(f"Each component contributes equally (1/3) to the final score: "
               f"({w:.3f} + {r:.3f} + {d:.3f}) / 3 = {score:.3f}")
    
    # Journey Visualization
    if events is not None:
        st.subheader("Chronological Journey")
        case_events = events[events['case_id'] == selected_case].sort_values('_timestamp_iso')
        
        if not case_events.empty:
            # Timeline visualization
            display_cols = ['concept:name', 'org:group', 'Section'] if 'Section' in case_events.columns else ['concept:name', 'org:group']
            display_cols = [c for c in display_cols if c in case_events.columns]
            
            # Create a horizontal timeline
            if '_timestamp_iso' in case_events.columns:
                case_events['timestamp'] = pd.to_datetime(case_events['_timestamp_iso'])
                
                # Create a Gantt-like chart
                fig2 = px.timeline(
                    case_events,
                    x_start='timestamp',
                    x_end='timestamp',
                    y='concept:name',
                    color='org:group' if 'org:group' in case_events.columns else None,
                    title="Patient Journey Timeline",
                    hover_data=['concept:name', 'org:group'] if 'org:group' in case_events.columns else ['concept:name']
                )
                fig2.update_layout(
                    height=300,
                    xaxis_title="Time",
                    yaxis_title="Activity"
                )
                st.plotly_chart(fig2, use_container_width=True)
            
            # Show the events table
            with st.expander("📋 View all events"):
                st.dataframe(
                    case_events[['_timestamp_iso', 'concept:name', 'org:group'] if 'org:group' in case_events.columns else ['_timestamp_iso', 'concept:name']],
                    use_container_width=True
                )
        else:
            st.write("No events found for this patient.")
    
    # Repeated Activities
    if events is not None:
        st.subheader("Repeated Activities")
        case_events = events[events['case_id'] == selected_case]
        if not case_events.empty:
            activity_counts = case_events['concept:name'].value_counts()
            repeated = activity_counts[activity_counts > 1].reset_index()
            if not repeated.empty:
                repeated.columns = ['Activity', 'Count']
                
                fig3 = px.bar(
                    repeated,
                    x='Count',
                    y='Activity',
                    orientation='h',
                    title="Activities Repeated in This Journey",
                    color='Count',
                    color_continuous_scale='Reds'
                )
                fig3.update_layout(height=300, yaxis={'categoryorder': 'total ascending'})
                st.plotly_chart(fig3, use_container_width=True)
                
                st.caption("Repeated activity is treated as observable process repetition. Repetition does not necessarily imply inappropriate care.")
            else:
                st.write("No repeated activities in this journey.")
    
    # Waiting Hotspots (if waiting data available)
    if waiting is not None and selected_case in waiting['case_id'].values:
        st.subheader("Waiting Hotspots")
        wait_row = waiting[waiting['case_id'] == selected_case].iloc[0]
        
        total_wait_hours = wait_row.get('total_wait_seconds', 0) / 3600
        st.metric("Total Observed Waiting Time", f"{total_wait_hours:.1f} hours")
        
        st.caption("Waiting is computed from raw event timestamps between consecutive clinical events. Observed elapsed time does not necessarily represent patient waiting experience.")
    
    # Reference vs Actual Path Comparison
    st.subheader("Reference Process vs Actual Pathway")
    
    # Try to load reference process if available
    # This would typically come from a process model file or reference process data
    # For now, we'll show a conceptual comparison
    
    if events is not None:
        case_events = events[events['case_id'] == selected_case]
        if not case_events.empty:
            # Show the actual sequence
            activities = case_events['concept:name'].tolist()
            if len(activities) > 15:
                display_activities = activities[:15] + ['...']
            else:
                display_activities = activities
            
            st.write("**Actual Pathway:**")
            st.write(" → ".join(display_activities))
            
            st.caption(DEVIATION_DISCLAIMER)

def page_process_discovery():
    st.header("🔄 Process Discovery")
    st.caption("Discovered reference process and pathway patterns")
    
    events = load_table("clean_events")
    friction = load_table("friction_scores")
    
    if events is None:
        missing_table_notice("clean_events", "Produces the cleaned event log used for process discovery.")
        return
    
    # Most common pathways
    st.subheader("Most Common Pathways")
    
    # Group by case and create pathway strings
    if 'case_id' in events.columns and 'concept:name' in events.columns:
        # Get top pathways
        case_pathways = events.groupby('case_id')['concept:name'].apply(lambda x: ' → '.join(x.head(10)))
        pathway_counts = case_pathways.value_counts().head(10).reset_index()
        pathway_counts.columns = ['Pathway', 'Count']
        
        fig = px.bar(
            pathway_counts,
            x='Count',
            y='Pathway',
            orientation='h',
            title="Top 10 Most Common Patient Pathways",
            color='Count',
            color_continuous_scale='Blues'
        )
        fig.update_layout(height=400, yaxis={'categoryorder': 'total ascending'})
        st.plotly_chart(fig, use_container_width=True)
        
        with st.expander("📖 What this shows"):
            st.markdown("""
            This shows the most frequent journey patterns observed in the event log.
            
            **Interpretation:**
            - Longer pathways may indicate more complex journeys
            - Higher count patterns represent typical patient flows
            - Less frequent pathways may represent outliers or specific patient conditions
            """)
    
    # Department transitions
    if 'org:group' in events.columns:
        st.subheader("Department Transitions")
        
        # Create transition matrix
        try:
            # Group by case and get sequence of departments
            dept_sequences = events.groupby('case_id')['org:group'].apply(list)
            
            # Count transitions
            transitions = {}
            for seq in dept_sequences:
                for i in range(len(seq)-1):
                    key = (seq[i], seq[i+1])
                    transitions[key] = transitions.get(key, 0) + 1
            
            if transitions:
                trans_df = pd.DataFrame([
                    {'From': k[0], 'To': k[1], 'Count': v} 
                    for k, v in sorted(transitions.items(), key=lambda x: x[1], reverse=True)[:15]
                ])
                
                fig2 = px.bar(
                    trans_df,
                    x='Count',
                    y='To',
                    color='From',
                    orientation='h',
                    title="Most Common Department Transitions",
                    labels={'To': 'Department To', 'Count': 'Number of Transitions'}
                )
                fig2.update_layout(height=400)
                st.plotly_chart(fig2, use_container_width=True)
                
                with st.expander("📖 What this shows"):
                    st.markdown("""
                    This reveals where patients commonly move between organizational groups.
                    
                    **Interpretation:**
                    - Frequent transitions indicate common patient flow between departments
                    - Unusual transitions may represent exceptional care pathways
                    - The pattern of transitions helps understand the patient journey structure
                    """)
        except Exception as e:
            st.warning("Could not compute department transitions. Data may be insufficient.")
    
    # Process model placeholder (would display image if available)
    st.subheader("Discovered Process Model")
    model_path = os.path.join(OUTPUTS_DIR, "process_model.png")
    if os.path.exists(model_path):
        st.image(model_path, caption="Discovered Process Model")
    else:
        st.info("No process model image found. This may be generated by the pipeline in future versions.")
    
    with st.expander("📖 What this shows"):
        st.markdown("""
        The discovered process model represents the most common patterns in the event log.
        
        **Components of the model:**
        - **Nodes**: Activities or departments
        - **Edges**: Transitions between activities
        - **Frequency**: Thicker lines or larger nodes indicate more common patterns
        
        This model serves as the reference for the Deviation component calculation.
        """)

def page_bottleneck_analysis():
    st.header("🚧 Operational Insights")
    st.caption("Observed patterns and high-volume areas")
    
    events = load_table("clean_events")
    friction = load_table("friction_scores")
    waiting = load_table("patient_waiting")
    rework = load_table("patient_rework")
    
    if events is None:
        missing_table_notice("clean_events", "Provides event data for analysis.")
        return
    
    # Activities with long elapsed gaps (if timestamp data available)
    st.subheader("Activities with Long Elapsed Gaps")
    if '_timestamp_iso' in events.columns and 'concept:name' in events.columns:
        try:
            # Calculate gaps between consecutive events for each case
            events_sorted = events.sort_values(['case_id', '_timestamp_iso'])
            events_sorted['prev_timestamp'] = events_sorted.groupby('case_id')['_timestamp_iso'].shift(1)
            events_sorted['gap_seconds'] = (pd.to_datetime(events_sorted['_timestamp_iso']) - 
                                            pd.to_datetime(events_sorted['prev_timestamp'])).dt.total_seconds()
            
            # Filter gaps > 0 and get top activities
            gap_activities = events_sorted[events_sorted['gap_seconds'] > 0]
            if not gap_activities.empty:
                avg_gaps = gap_activities.groupby('concept:name')['gap_seconds'].mean().sort_values(ascending=False).head(15).reset_index()
                avg_gaps['gap_hours'] = avg_gaps['gap_seconds'] / 3600
                
                fig = px.bar(
                    avg_gaps,
                    x='gap_hours',
                    y='concept:name',
                    orientation='h',
                    title="Activities with Longest Average Elapsed Gaps",
                    labels={'gap_hours': 'Average Gap (hours)', 'concept:name': 'Activity'},
                    color='gap_hours',
                    color_continuous_scale='Oranges'
                )
                fig.update_layout(height=400, yaxis={'categoryorder': 'total ascending'})
                st.plotly_chart(fig, use_container_width=True)
                
                st.caption("Observed elapsed time between activities. This does not necessarily represent patient waiting experience.")
            else:
                st.write("No gap data available.")
        except Exception as e:
            st.warning("Could not compute elapsed gaps. Timestamp data may be incomplete.")
    
    # Departments with high event volume
    if 'org:group' in events.columns:
        st.subheader("High-Volume Departments")
        dept_volume = events['org:group'].value_counts().head(15).reset_index()
        dept_volume.columns = ['Department', 'Count']
        
        fig2 = px.bar(
            dept_volume,
            x='Count',
            y='Department',
            orientation='h',
            title="Departments by Event Volume",
            color='Count',
            color_continuous_scale='Blues'
        )
        fig2.update_layout(height=400, yaxis={'categoryorder': 'total ascending'})
        st.plotly_chart(fig2, use_container_width=True)
        
        with st.expander("📖 What this shows"):
            st.markdown("""
            This shows departments with the highest number of recorded events.
            
            **Interpretation:**
            - High-volume departments may represent major touchpoints in patient journeys
            - This could indicate where patients spend significant time or interact frequently
            - Does not necessarily indicate problems - may reflect normal care patterns
            """)
    
    # Repeated activities
    if rework is not None:
        st.subheader("Frequently Repeated Activities")
        
        # Load rework details if available
        if 'activity_rework_counts' in rework.columns:
            # Try to get activity-level rework
            try:
                # This would require activity-level data which may not be in patient_rework
                st.info("Activity-level rework data is not available in the current output.")
            except:
                pass
        
        # Show rework distribution
        if 'rework_score' in rework.columns:
            st.subheader("Rework Score Distribution")
            fig3 = px.histogram(
                rework,
                x='rework_score',
                nbins=30,
                title="Distribution of Rework Scores",
                labels={'rework_score': 'Rework Score', 'count': 'Number of Patients'}
            )
            fig3.add_vline(x=rework['rework_score'].mean(), line_dash="dash", line_color="red",
                          annotation_text=f"Mean: {rework['rework_score'].mean():.3f}")
            st.plotly_chart(fig3, use_container_width=True)
    
    # High-friction journey patterns
    if friction is not None:
        st.subheader("High-Friction Journey Patterns")
        
        # Get top patients by friction
        top_patients = friction.nlargest(10, 'friction_score')['case_id'].tolist()
        
        if events is not None:
            # Show patterns for top patients
            top_events = events[events['case_id'].isin(top_patients)]
            if not top_events.empty:
                # Get common activities among high-friction patients
                top_activities = top_events['concept:name'].value_counts().head(20).reset_index()
                top_activities.columns = ['Activity', 'Count']
                
                fig4 = px.bar(
                    top_activities,
                    x='Count',
                    y='Activity',
                    orientation='h',
                    title="Activities in High-Friction Journeys",
                    color='Count',
                    color_continuous_scale='Reds'
                )
                fig4.update_layout(height=400, yaxis={'categoryorder': 'total ascending'})
                st.plotly_chart(fig4, use_container_width=True)
                
                st.caption("This shows activities that commonly appear in journeys with high friction scores.")

def methodology_section():
    """Display the research methodology in a collapsible section."""
    with st.expander("🔬 Research Methodology", expanded=False):
        st.markdown("""
        ### Methodology Overview
        
        This project analyzes recorded healthcare event logs to measure observable process burden across patient journeys.
        
        **Data Source:** BPIC 2011 Dataset (hospital event log)
        
        **Pipeline Stages:**
        Raw XES Event Log
        ↓
        Data Cleaning & Preprocessing
        ↓
        Waiting Time Calculation (W)
        ↓
        Rework Calculation (R)
        ↓
        Process Discovery (Inductive Miner)
        ↓
        Conformance Checking / Deviation (D)
        ↓
        Normalization (per patient, 0-1 scale)
        ↓
        Friction Score: F = (W + R + D) / 3
        ↓
        Dashboard Insights

        
### Component Definitions

**Waiting Time (W):**
- Computed from raw timestamp gaps between consecutive clinical events
- Administrative/billing entries are excluded as wait-interval endpoints
- Represents observed elapsed time, not confirmed patient waiting experience

**Rework (R):**
- Calculated as: Reworkₚ = Σ log(1 + max(0, Countₚ,ₐ − 1))
- Counts repeated activity occurrences within a patient's journey
- Log-dampened so that one hyper-repeated activity doesn't dominate

**Deviation (D):**
- Computed via alignment-based conformance checking
- Against an Inductive-Miner-discovered reference process model
- Uses collapsed departments (org:group) for the discovery process

### Normalization & Weighting

- All components are normalized to a 0-1 scale per patient
- **V1 uses equal weighting:** F = (W + R + D) / 3
- This is intentional - reflects equal contribution from each dimension

### Technology Stack

- **Processing:** PySpark, pm4py
- **Visualization:** Streamlit, Plotly
- **Data Storage:** Parquet files
- **Graph Database:** Neo4j (for specific journey exploration)
""")

def main():
    st.set_page_config(
        page_title="Patient Journey Friction Analytics",
        page_icon="🏥",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Sidebar
    with st.sidebar:
        st.title("🏥 PJFA")
        st.markdown("### Patient Journey Friction Analytics")
        st.caption("Research Dashboard V1")
        st.divider()

        st.markdown("**About**")
        st.markdown(FRICTION_DISCLAIMER[:200] + "...")

        st.divider()

        # Navigation
        st.markdown("### Navigation")
        pages = {
            "📊 Executive Overview": page_overview,
            "📈 Friction Analytics": page_friction_analytics,
            "👤 Patient Journey Explorer": page_patient_explorer,
            "🔄 Process Discovery": page_process_discovery,
            "🚧 Operational Insights": page_bottleneck_analysis,
        }

        # Check if we have a navigation target from another page
        if 'navigate_to' in st.session_state:
            nav_target = st.session_state['navigate_to']
            if nav_target in pages:
                st.session_state['navigate_to'] = None
                choice = nav_target
            else:
                choice = st.radio("Select Page", list(pages.keys()))
        else:
            choice = st.radio("Select Page", list(pages.keys()))

        st.divider()

        # Dataset info
        st.markdown("**Dataset Information**")
        if os.path.exists(OUTPUTS_DIR):
            friction = load_table("friction_scores")
            if friction is not None:
                st.metric("Patients", f"{friction['case_id'].nunique():,}")

            events = load_table("clean_events")
            if events is not None:
                st.metric("Events", f"{len(events):,}")
        else:
            st.caption("Dataset information not available")

        st.divider()
        st.caption("Research use only. Not for clinical decision support.")

    # Main content
    pages[choice]()

    # Show methodology at the bottom
    methodology_section()


if __name__ == "__main__":
    main()