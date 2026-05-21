"""
Forecast Disaggregation Validator — Streamlit App (v2)

Methodology
-----------
Forecast is generated at Material × Ship To Sub Region (parent), then
disaggregated to Material × Ship To Sub Region × Parent Cust (child).
This app validates that each child's forecast share is consistent with its
recent-history share, and surfaces violators by impact and by deviation.

Run with: streamlit run app.py
"""
from __future__ import annotations
import io
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from validator_engine import (
    REQUIRED_COLS, Settings, FLAG_CODES, FLAG_COLORS,
    load_and_validate_input, run_validation, ValidationResult,
)
from excel_exporter import build_excel_export
from auth_gate import require_login, render_user_sidebar


# ---------------------------------------------------------------------------
# Page config & global style
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Forecast Disaggregation Validator",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

NAVY = "#1F3864"
TEAL = "#2E86AB"
LIGHT_BG = "#F8F9FA"

CUSTOM_CSS = f"""
<style>
    .main .block-container {{
        padding-top: 1.5rem;
        max-width: 1500px;
    }}
    h1, h2, h3 {{ color: {NAVY}; }}
    .kpi-card {{
        background: {LIGHT_BG};
        border-left: 4px solid {NAVY};
        padding: 14px 18px;
        border-radius: 4px;
        height: 100%;
    }}
    .kpi-label {{
        color: #595959;
        font-size: 0.82rem;
        font-weight: 600;
        margin-bottom: 4px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }}
    .kpi-value {{
        color: {NAVY};
        font-size: 1.8rem;
        font-weight: 700;
        line-height: 1.2;
    }}
    .kpi-sub {{
        color: #888;
        font-size: 0.78rem;
        margin-top: 2px;
        font-style: italic;
    }}
    .stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
    .stTabs [data-baseweb="tab"] {{
        background-color: {LIGHT_BG};
        border-radius: 4px 4px 0 0;
        padding: 8px 18px;
    }}
    .stTabs [aria-selected="true"] {{
        background-color: {NAVY};
        color: white;
    }}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Authentication gate
# ---------------------------------------------------------------------------
# Must be called BEFORE any other UI/state — renders a login form and stops
# the script if the session isn't authenticated. Reads users from
# .streamlit/secrets.toml. See README.md → Authentication setup.
require_login()


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
def init_state():
    defaults = {
        'raw_df': None, 'clean_df': None, 'errors': [], 'warnings': [],
        'input_filename': None, 'input_file_id': None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def reset_input_state():
    """Wipe all uploaded-file state and clear validation cache.
    Called when the user removes the file from the uploader, or when an upload fails.
    """
    st.session_state.raw_df = None
    st.session_state.clean_df = None
    st.session_state.errors = []
    st.session_state.warnings = []
    st.session_state.input_filename = None
    st.session_state.input_file_id = None
    # Clear cached validation results so the next upload starts fresh
    try:
        compute_validation.clear()
    except Exception:
        pass

init_state()


# ---------------------------------------------------------------------------
# Cached computation (declared before sidebar so reset_input_state can clear it)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False, max_entries=2)
def compute_validation(cache_key: str, df: pd.DataFrame, settings_dict: dict):
    s = Settings(**settings_dict)
    return run_validation(df, s)


# ---------------------------------------------------------------------------
# Sidebar — upload + settings
# ---------------------------------------------------------------------------
with st.sidebar:
    # Authenticated-user info + Logout button (rendered first inside the
    # sidebar so it's always at the top)
    render_user_sidebar()

    st.title("📊 Validator")
    st.caption("Forecast Disaggregation Health Check")
    st.markdown("---")

    st.subheader("1. Upload Data")
    uploaded = st.file_uploader(
        "Excel file (.xlsx)",
        type=["xlsx", "xls"],
        help=("Required cols: Business Line, Detail, Material, "
              "Ship To Sub Region, Parent Cust, Month, "
              "Sales History(Kg), Statistical Forecast(Kg)."),
        key="file_uploader",
    )

    # Detect upload-state transitions:
    #  - A NEW file (different file_id) replaces any previous data
    #  - File REMOVED (uploaded is None but we have data) -> reset everything
    current_file_id = uploaded.file_id if uploaded is not None else None
    previous_file_id = st.session_state.input_file_id

    if uploaded is not None and current_file_id != previous_file_id:
        # New file uploaded — reset previous state, then load this one fresh
        reset_input_state()
        try:
            with st.spinner(f"Reading {uploaded.name}..."):
                df_raw = pd.read_excel(uploaded)
            st.session_state.raw_df = df_raw
            st.session_state.input_filename = uploaded.name
            st.session_state.input_file_id = current_file_id
            clean, errors, warnings = load_and_validate_input(df_raw)
            st.session_state.clean_df = clean
            st.session_state.errors = errors
            st.session_state.warnings = warnings
        except Exception as e:
            reset_input_state()
            st.session_state.errors = [f"Could not read file: {e}"]
        # Trigger a rerun so the UI immediately reflects the new file
        st.rerun()
    elif uploaded is None and previous_file_id is not None:
        # File was removed via the uploader's X button — full reset
        reset_input_state()
        st.rerun()

    if st.session_state.raw_df is not None:
        st.success(f"Loaded: {st.session_state.input_filename}")
        st.caption(f"{len(st.session_state.raw_df):,} rows")

    st.markdown("---")
    st.subheader("2. Settings")

    # Threshold is always available; date-range pickers need data to set defaults.
    threshold_pct = st.number_input(
        "Deviation Threshold (%)", min_value=0.0, max_value=50.0,
        value=5.0, step=0.5, format="%.1f",
        help="|Mix Deviation| > this triggers a 'Mix Drift' flag.",
        key="settings_threshold_pct")

    # Date-range pickers — populated after file is loaded.
    # Defaults:
    #   Recent History = last 6 months ending at last_hist_date
    #   Forecast Horizon = (last_hist_date + 4 months) through Dec of that year
    #     → falls back to Dec of NEXT year if the window would otherwise be empty.
    recent_start_pick = None
    recent_end_pick = None
    fcst_start_pick = None
    fcst_end_pick = None

    if st.session_state.clean_df is not None:
        clean_df = st.session_state.clean_df
        # Compute available history & forecast months from the data
        hist_mask_local = clean_df['Sales History(Kg)'] > 0
        fcst_only_mask_local = ((clean_df['Sales History(Kg)'] == 0) &
                                (clean_df['Statistical Forecast(Kg)'] > 0))
        last_hist_date_local = clean_df.loc[hist_mask_local, 'Month'].max()
        first_fcst_local = (last_hist_date_local + pd.DateOffset(months=1))
        last_fcst_local = clean_df.loc[
            fcst_only_mask_local & (clean_df['Month'] >= first_fcst_local), 'Month'].max()

        # Build the lists of months available for each window
        hist_months = sorted(clean_df.loc[hist_mask_local, 'Month'].unique())
        fcst_months = sorted(clean_df.loc[
            fcst_only_mask_local & (clean_df['Month'] >= first_fcst_local), 'Month'].unique())

        def fmt_month(ts):
            return pd.Timestamp(ts).strftime('%b %Y')

        if not hist_months or not fcst_months:
            st.warning("Cannot infer date ranges — data missing history or forecast months.")
        else:
            # ---- Recent History Window: default = last 6 months ----
            default_recent_end = hist_months[-1]
            # Find the index 5 positions back, or position 0 if fewer than 6 months
            recent_default_start_idx = max(0, len(hist_months) - 6)
            default_recent_start = hist_months[recent_default_start_idx]

            st.markdown("**Recent History Window**")
            col_rs, col_re = st.columns(2)
            # Use month index in the list as the value to make the default robust
            hist_labels = [fmt_month(m) for m in hist_months]
            with col_rs:
                rec_start_label = st.selectbox(
                    "Start", hist_labels,
                    index=recent_default_start_idx,
                    key="rec_start_label",
                    help="First month of the recent-history window.")
            with col_re:
                rec_end_label = st.selectbox(
                    "End", hist_labels,
                    index=len(hist_labels) - 1,
                    key="rec_end_label",
                    help="Last month of the recent-history window (inclusive).")
            recent_start_pick = hist_months[hist_labels.index(rec_start_label)]
            recent_end_pick = hist_months[hist_labels.index(rec_end_label)]

            # ---- Forecast Horizon: default = (last_hist + 4) through Dec of that year ----
            # Logic:
            #   target_start = last_hist_date_local + 4 months
            #   target_end = December of target_start's calendar year
            #   If target_end < target_start (we're already past Dec), stretch to Dec of NEXT year
            target_start = pd.Timestamp(last_hist_date_local) + pd.DateOffset(months=4)
            target_end = pd.Timestamp(year=target_start.year, month=12, day=1)
            if target_end < target_start:
                target_end = pd.Timestamp(year=target_start.year + 1, month=12, day=1)

            # Snap to the closest available forecast months
            fcst_months_ts = [pd.Timestamp(m) for m in fcst_months]

            def closest_idx(target, candidates):
                """Return idx of the candidate >= target if any, else last idx."""
                for i, c in enumerate(candidates):
                    if c >= target:
                        return i
                return len(candidates) - 1

            def closest_idx_le(target, candidates):
                """Return idx of the latest candidate <= target if any, else 0."""
                last = 0
                found = False
                for i, c in enumerate(candidates):
                    if c <= target:
                        last = i
                        found = True
                    else:
                        break
                return last if found else 0

            default_fcst_start_idx = closest_idx(target_start, fcst_months_ts)
            default_fcst_end_idx = closest_idx_le(target_end, fcst_months_ts)
            # If the resolved default end < default start (e.g. target_end is before any fcst month),
            # default the end to the last fcst month available
            if default_fcst_end_idx < default_fcst_start_idx:
                default_fcst_end_idx = len(fcst_months_ts) - 1

            st.markdown("**Forecast Horizon**")
            col_fs, col_fe = st.columns(2)
            fcst_labels = [fmt_month(m) for m in fcst_months]
            with col_fs:
                fc_start_label = st.selectbox(
                    "Start", fcst_labels,
                    index=default_fcst_start_idx,
                    key="fc_start_label",
                    help="First forecast month included.")
            with col_fe:
                fc_end_label = st.selectbox(
                    "End", fcst_labels,
                    index=default_fcst_end_idx,
                    key="fc_end_label",
                    help="Last forecast month included (inclusive).")
            fcst_start_pick = fcst_months[fcst_labels.index(fc_start_label)]
            fcst_end_pick = fcst_months[fcst_labels.index(fc_end_label)]

            # Quick recap of the resolved windows
            st.caption(
                f"Recent: **{fmt_month(recent_start_pick)} – {fmt_month(recent_end_pick)}** • "
                f"Forecast: **{fmt_month(fcst_start_pick)} – {fmt_month(fcst_end_pick)}**"
            )

    settings = Settings(
        threshold=threshold_pct / 100.0,
        recent_start=pd.Timestamp(recent_start_pick) if recent_start_pick is not None else None,
        recent_end=pd.Timestamp(recent_end_pick) if recent_end_pick is not None else None,
        fcst_start=pd.Timestamp(fcst_start_pick) if fcst_start_pick is not None else None,
        fcst_end=pd.Timestamp(fcst_end_pick) if fcst_end_pick is not None else None,
    )

    st.markdown("---")
    st.caption("ℹ️ Click the **Instructions** tab for methodology, "
               "flag definitions, and input format.")


# ---------------------------------------------------------------------------
# Helper to get cached result
# ---------------------------------------------------------------------------
def get_result() -> Optional[ValidationResult]:
    if st.session_state.clean_df is None or st.session_state.errors:
        return None
    df = st.session_state.clean_df
    settings_dict = settings.__dict__
    cache_key = f"{st.session_state.input_filename}|{len(df)}|{settings_dict}"
    try:
        with st.spinner("Computing validation..."):
            return compute_validation(cache_key, df, settings_dict)
    except Exception as e:
        st.error(f"Computation failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown(f"<h1 style='margin-bottom:0;'>📊 Forecast Disaggregation Validator</h1>",
            unsafe_allow_html=True)
st.markdown(
    "<p style='color:#595959;font-style:italic;margin-top:0;'>"
    "Validates that the Statistical Forecast disaggregation across Parent Customers "
    "matches recent history at the Material × Ship To Sub Region level."
    "</p>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Schema gate — show landing prompt when no file is loaded
# ---------------------------------------------------------------------------
if st.session_state.raw_df is None:
    # Big, friendly upload prompt
    st.markdown("---")
    st.markdown(
        f"""
        <div style="background:{LIGHT_BG};border:2px dashed {NAVY};border-radius:8px;
                    padding:40px;text-align:center;margin:20px 0;">
            <div style="font-size:3rem;margin-bottom:12px;">📤</div>
            <h2 style="color:{NAVY};margin:0 0 8px 0;">Upload your Excel file to begin</h2>
            <p style="color:#595959;font-size:1.05rem;margin:0;">
                Use the file uploader in the left sidebar to select your
                <code>.xlsx</code> file.
            </p>
            <p style="color:#888;font-size:0.9rem;margin-top:12px;font-style:italic;">
                Need help with the format or methodology? Once uploaded, the
                <strong>Instructions</strong> tab has full documentation.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    # Quick preview of expected columns
    with st.expander("📋 Quick reference — expected input columns", expanded=False):
        st.code("\n".join(f"  - {c}" for c in REQUIRED_COLS), language="text")
        st.caption("One row per (Detail, Month). For history months, Sales History "
                   "may have a value (actuals) and Statistical Forecast may also have "
                   "a value (backtest). For future months, only Statistical Forecast "
                   "is populated.")
    st.stop()

if st.session_state.errors:
    st.error("**Cannot proceed — fix these issues:**")
    for e in st.session_state.errors:
        st.markdown(f"- {e}")
    if st.session_state.raw_df is not None:
        st.markdown("**Detected columns in your file:**")
        st.code("\n".join(str(c) for c in st.session_state.raw_df.columns), language="text")
    st.info("Remove the file from the uploader (click the × next to its name) "
            "and upload a corrected file.")
    st.stop()

if st.session_state.warnings:
    with st.expander(f"⚠️ {len(st.session_state.warnings)} data warning(s)", expanded=False):
        for w in st.session_state.warnings:
            st.markdown(f"- {w}")

result = get_result()
if result is None:
    st.error("Validation could not be computed.")
    st.stop()


# ---------------------------------------------------------------------------
# Helper: pandas Styler with flag pills
# ---------------------------------------------------------------------------
def color_flag(v):
    color = FLAG_COLORS.get(v)
    if color is None:
        return ""
    text_color = "#fff" if v in ("Lost Forecast",) else "#000"
    return f"background-color:{color};color:{text_color};font-weight:600;"


# ---------------------------------------------------------------------------
# Helper: cascading slicer-style options
# ---------------------------------------------------------------------------
def slicer_options(df: pd.DataFrame, all_filters: dict, exclude_col: str) -> list:
    """Return sorted unique values of `exclude_col` from `df` after applying
    every filter in `all_filters` EXCEPT the one for `exclude_col`.

    This mimics Excel slicer behavior: each slicer's available options are
    computed from the data filtered by every OTHER active slicer, so options
    cascade as you select.

    `all_filters` is a dict of {column_name: list_of_selected_values}.
    Empty selections are treated as "no filter on that column".
    """
    sub = df
    for col, selected in all_filters.items():
        if col == exclude_col:
            continue
        if selected:
            sub = sub[sub[col].isin(selected)]
    return sorted(sub[exclude_col].dropna().unique())


def apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """Apply every active filter from `filters` to `df`."""
    sub = df
    for col, selected in filters.items():
        if selected:
            sub = sub[sub[col].isin(selected)]
    return sub


def rollup_to_matcust(child_df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Recompute the Material × Parent Cust rollup from a (possibly filtered)
    child-grain validation dataframe.

    Within the rollup:
      Parent volume = sum of child Recent/Forecast for the Material across
                      whatever SubRegions remain in the filter scope.
      Recent Mix %  = customer's share of that filtered Material total.
      Forecast Mix % = customer's share of that filtered Material total.

    This makes the rollup behave like an Excel pivot — it reflects the
    currently-filtered universe rather than the full dataset.
    """
    from validator_engine import classify_flag
    if child_df.empty:
        return pd.DataFrame(columns=[
            'Material', 'Parent Cust', '# SubRegions',
            'Recent Hist (Kg)', 'Forecast (Kg)',
            'Parent Recent (Kg)', 'Parent Forecast (Kg)',
            'Recent Mix %', 'Forecast Mix %',
            'Mix Deviation', 'Kg Impact', 'Flag'])

    # Sum child volumes up to Mat × Cust
    rollup = (child_df.groupby(['Material', 'Parent Cust'], as_index=False)
              .agg({'Recent Hist (Kg)': 'sum',
                    'Forecast (Kg)': 'sum',
                    'Ship To Sub Region': 'nunique'})
              .rename(columns={'Ship To Sub Region': '# SubRegions'}))

    # Material-level totals across the (filtered) child rows.
    # Each child row in the input has its parent volumes already; but those
    # are the FULL Mat × SubRegion parents. To stay consistent within the
    # filter scope, we sum unique (Material, SubRegion) parent volumes:
    parents = (child_df[['Material', 'Ship To Sub Region',
                          'Parent Recent (Kg)', 'Parent Forecast (Kg)']]
               .drop_duplicates(['Material', 'Ship To Sub Region']))
    mat_parent = (parents.groupby('Material', as_index=False)
                  .agg({'Parent Recent (Kg)': 'sum',
                        'Parent Forecast (Kg)': 'sum'}))
    rollup = rollup.merge(mat_parent, on='Material', how='left')

    rollup['Parent Recent (Kg)'] = rollup['Parent Recent (Kg)'].fillna(0.0)
    rollup['Parent Forecast (Kg)'] = rollup['Parent Forecast (Kg)'].fillna(0.0)
    rollup['Recent Mix %'] = np.where(rollup['Parent Recent (Kg)'] > 0,
                                       rollup['Recent Hist (Kg)'] / rollup['Parent Recent (Kg)'],
                                       0.0)
    rollup['Forecast Mix %'] = np.where(rollup['Parent Forecast (Kg)'] > 0,
                                         rollup['Forecast (Kg)'] / rollup['Parent Forecast (Kg)'],
                                         0.0)
    rollup['Mix Deviation'] = rollup['Forecast Mix %'] - rollup['Recent Mix %']

    impact_base = np.where(rollup['Parent Forecast (Kg)'] > 0,
                            rollup['Parent Forecast (Kg)'],
                            rollup['Parent Recent (Kg)'])
    rollup['Kg Impact'] = np.abs(rollup['Mix Deviation']) * impact_base

    rollup['Flag'] = [classify_flag(r, f, d, threshold)
                      for r, f, d in zip(rollup['Recent Hist (Kg)'],
                                          rollup['Forecast (Kg)'],
                                          rollup['Mix Deviation'])]
    rollup.loc[rollup['Flag'] == 'Lost Forecast', 'Kg Impact'] = \
        rollup.loc[rollup['Flag'] == 'Lost Forecast', 'Recent Hist (Kg)']
    rollup.loc[rollup['Flag'] == 'New Demand', 'Kg Impact'] = \
        rollup.loc[rollup['Flag'] == 'New Demand', 'Forecast (Kg)']
    rollup.loc[rollup['Flag'] == 'No Activity', 'Kg Impact'] = 0.0

    return rollup[['Material', 'Parent Cust', '# SubRegions',
                   'Recent Hist (Kg)', 'Forecast (Kg)',
                   'Parent Recent (Kg)', 'Parent Forecast (Kg)',
                   'Recent Mix %', 'Forecast Mix %',
                   'Mix Deviation', 'Kg Impact', 'Flag']]


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_dash, tab_validation, tab_rollup, tab_drill, tab_export, tab_instructions = st.tabs(
    ["📊 Dashboard", "🔍 Validation Detail", "📦 Mat × Cust Rollup",
     "🎯 Drill-In", "💾 Export", "📖 Instructions"]
)


# ============================================================================
# TAB 1 — Dashboard
# ============================================================================
with tab_dash:
    meta = result.meta
    val_full = result.validation_df  # child grain — has Business Line and SubRegion

    # ---- Top filters: Business Line + Sub Region (cascading) ----
    # These filters drive EVERY downstream component on this tab:
    # KPI scorecards, Flag Distribution chart, Forecast Volume by Flag chart,
    # Top 20 violators, and the interpretation panel.
    dash_filters = {
        "Business Line": st.session_state.get("dash_bl", []),
        "Ship To Sub Region": st.session_state.get("dash_sr", []),
    }
    # Prune invalid selections (in case data changed)
    for col, current in list(dash_filters.items()):
        avail = slicer_options(val_full, dash_filters, exclude_col=col)
        avail_set = set(avail)
        valid = [v for v in current if v in avail_set]
        if valid != current:
            dash_filters[col] = valid
            key_map = {"Business Line": "dash_bl", "Ship To Sub Region": "dash_sr"}
            st.session_state[key_map[col]] = valid

    # Period caption (always shown — independent of filters)
    # Compute duration in months from the resolved window dates
    rw_start = pd.Timestamp(meta['recent_window_start'])
    rw_end = pd.Timestamp(meta['recent_window_end'])
    fw_start = pd.Timestamp(meta['fcst_window_start'])
    fw_end = pd.Timestamp(meta['fcst_window_end'])
    rw_months = (rw_end.year - rw_start.year) * 12 + (rw_end.month - rw_start.month) + 1
    fw_months = (fw_end.year - fw_start.year) * 12 + (fw_end.month - fw_start.month) + 1
    st.caption(
        f"Recent: **{rw_start.strftime('%b %Y')} – {rw_end.strftime('%b %Y')}** "
        f"({rw_months} mo) • "
        f"Forecast: **{fw_start.strftime('%b %Y')} – {fw_end.strftime('%b %Y')}** "
        f"({fw_months} mo)"
    )

    # Filter row
    fc1, fc2, fc3 = st.columns([2, 2, 1])
    with fc1:
        bl_opts = slicer_options(val_full, dash_filters, "Business Line")
        bl_filter = st.multiselect(
            "Business Line", bl_opts, key="dash_bl",
            help=f"{len(bl_opts)} options available given other filters")
    with fc2:
        sr_opts = slicer_options(val_full, dash_filters, "Ship To Sub Region")
        sr_filter = st.multiselect(
            "Sub Region", sr_opts, key="dash_sr",
            help=f"{len(sr_opts)} options available given other filters")
    with fc3:
        st.markdown("&nbsp;", unsafe_allow_html=True)  # vertical alignment spacer
        if st.button("Clear filters", key="dash_clear"):
            for k in ["dash_bl", "dash_sr"]:
                if k in st.session_state:
                    del st.session_state[k]
            st.rerun()

    # Apply the dashboard filters to the child-grain table
    dash_filters = {"Business Line": bl_filter, "Ship To Sub Region": sr_filter}
    val_filtered = apply_filters(val_full, dash_filters)

    # Recompute the rollup dynamically given the filter scope (Excel-pivot-style)
    rl_filtered = rollup_to_matcust(val_filtered, meta['settings']['threshold'])

    # ---- KPI row (filter-aware, all integer counts) ----
    rollup_counts = rl_filtered['Flag'].value_counts().to_dict()
    n_total = len(rl_filtered)

    if n_total == 0:
        st.warning("No data matches the selected filters. Adjust filters above.")
        st.stop()

    k1, k2, k3, k4, k5 = st.columns(5)
    kpis = [
        (k1, "OK",
         f"{rollup_counts.get('OK', 0):,}",
         f"of {n_total:,} total combos", FLAG_COLORS['OK']),
        (k2, "Mix Drift",
         f"{rollup_counts.get('Mix Drift', 0):,}",
         f"|deviation| > {meta['settings']['threshold']:.0%}", FLAG_COLORS['Mix Drift']),
        (k3, "Lost Forecast",
         f"{rollup_counts.get('Lost Forecast', 0):,}",
         "history > 0, forecast = 0", FLAG_COLORS['Lost Forecast']),
        (k4, "New Demand",
         f"{rollup_counts.get('New Demand', 0):,}",
         "history = 0, forecast > 0", FLAG_COLORS['New Demand']),
        (k5, "No Activity",
         f"{rollup_counts.get('No Activity', 0):,}",
         "both zero (dormant)", FLAG_COLORS['No Activity']),
    ]
    for col, label, value, sub, color in kpis:
        with col:
            st.markdown(
                f"""
                <div class="kpi-card" style="border-left-color:{color};">
                  <div class="kpi-label">{label}</div>
                  <div class="kpi-value" style="color:{color};">{value}</div>
                  <div class="kpi-sub">{sub}</div>
                </div>
                """, unsafe_allow_html=True)

    # Show what filter scope we're looking at
    scope_parts = []
    if bl_filter:
        scope_parts.append(f"BL: {', '.join(bl_filter)}")
    if sr_filter:
        scope_parts.append(f"SubRegion: {', '.join(sr_filter)}")
    scope_str = " • ".join(scope_parts) if scope_parts else "All Business Lines & Sub Regions"
    st.caption(f"📌 Scope: **{scope_str}** • **{n_total:,}** Material × Parent Cust combos")

    st.markdown("---")

    # ---- Flag Distribution + Forecast Volume by Flag (side-by-side) ----
    col_flag, col_vol = st.columns([1, 1])

    with col_flag:
        st.subheader("Flag Distribution — Material × Parent Cust")
        flag_df = pd.DataFrame([
            {"Flag": code, "Count": rollup_counts.get(code, 0)}
            for code in FLAG_CODES
        ])
        flag_df = flag_df[flag_df["Count"] > 0]
        if flag_df.empty:
            st.info("No combos in this filter scope.")
        else:
            fig = go.Figure()
            fig.add_bar(
                y=flag_df["Flag"], x=flag_df["Count"],
                orientation="h",
                marker_color=[FLAG_COLORS[c] for c in flag_df["Flag"]],
                text=flag_df["Count"].apply(lambda x: f"{x:,}"),
                textposition="outside",
            )
            fig.update_layout(
                height=300, margin=dict(l=10, r=40, t=10, b=10),
                yaxis=dict(autorange="reversed"),
                xaxis_title="# of Mat × Parent Cust combos",
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)

    with col_vol:
        st.subheader("Forecast Volume by Flag")
        vol_by_flag = (rl_filtered.groupby('Flag', as_index=False)['Forecast (Kg)']
                       .sum()
                       .rename(columns={'Forecast (Kg)': 'Forecast Volume (Kg)'}))
        # Order in canonical flag order
        vol_by_flag['_order'] = vol_by_flag['Flag'].apply(
            lambda x: FLAG_CODES.index(x) if x in FLAG_CODES else 99)
        vol_by_flag = vol_by_flag.sort_values('_order').drop(columns='_order')
        total_fcst = vol_by_flag['Forecast Volume (Kg)'].sum()
        vol_by_flag['Pct'] = np.where(
            total_fcst > 0, vol_by_flag['Forecast Volume (Kg)'] / total_fcst, 0.0)

        if total_fcst <= 0:
            st.info("No forecast volume in this filter scope.")
        else:
            fig = go.Figure()
            fig.add_bar(
                y=vol_by_flag['Flag'], x=vol_by_flag['Forecast Volume (Kg)'],
                orientation="h",
                marker_color=[FLAG_COLORS[f] for f in vol_by_flag['Flag']],
                text=[f"{v:,.0f} ({p:.0%})"
                      for v, p in zip(vol_by_flag['Forecast Volume (Kg)'],
                                       vol_by_flag['Pct'])],
                textposition="outside",
                customdata=vol_by_flag['Pct'],
                hovertemplate=("<b>%{y}</b><br>"
                               "Forecast: %{x:,.0f} Kg<br>"
                               "Share: %{customdata:.1%}<extra></extra>"),
            )
            fig.update_layout(
                height=300, margin=dict(l=10, r=80, t=10, b=10),
                yaxis=dict(autorange="reversed"),
                xaxis_title="Forecast Volume (Kg)",
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)

    # ---- Interpretation panel — data-driven planner guidance ----
    st.markdown("##### 🎯 What this tells you")
    interp_msgs = []

    # Use rollup_counts and vol_by_flag for the narrative
    pct_ok = rollup_counts.get('OK', 0) / n_total if n_total > 0 else 0
    n_mix_drift = rollup_counts.get('Mix Drift', 0)
    n_lost = rollup_counts.get('Lost Forecast', 0)
    n_new = rollup_counts.get('New Demand', 0)
    n_no_act = rollup_counts.get('No Activity', 0)

    # Sum recent history and forecast totals for richer interpretation
    recent_total = float(rl_filtered['Recent Hist (Kg)'].sum())
    fcst_total = float(rl_filtered['Forecast (Kg)'].sum())

    # Volume by flag (in Kg) - same as the chart numbers
    vbf = (rl_filtered.groupby('Flag')[['Recent Hist (Kg)', 'Forecast (Kg)']]
                       .sum().to_dict('index'))

    # --- Build prioritized observations ---
    observations = []

    # 1. Lost Forecast — recent history without forecast (highest planner priority)
    if n_lost > 0:
        lost_recent = vbf.get('Lost Forecast', {}).get('Recent Hist (Kg)', 0)
        lost_pct = lost_recent / recent_total if recent_total > 0 else 0
        observations.append({
            'priority': 1,
            'flag': 'Lost Forecast',
            'icon': '🚨',
            'headline': f"{n_lost:,} customer-material combos have recent sales but ZERO forecast",
            'detail': (f"That's **{lost_recent:,.0f} Kg** of recent history "
                       f"({lost_pct:.0%} of total) currently unallocated in your forecast. "
                       "These should be your first investigation — confirm whether the "
                       "demand has truly stopped or whether the forecast is missing it."),
        })

    # 2. Mix Drift — both > 0 but deviation exceeds threshold
    if n_mix_drift > 0:
        drift_fcst = vbf.get('Mix Drift', {}).get('Forecast (Kg)', 0)
        drift_fcst_pct = drift_fcst / fcst_total if fcst_total > 0 else 0
        # How much Kg is misallocated within Mix Drift?
        drift_subset = rl_filtered[rl_filtered['Flag'] == 'Mix Drift']
        drift_impact = float(drift_subset['Kg Impact'].sum())
        observations.append({
            'priority': 2 if n_lost == 0 else 3,
            'flag': 'Mix Drift',
            'icon': '⚠️',
            'headline': f"{n_mix_drift:,} combos show Mix Drift > {meta['settings']['threshold']:.0%}",
            'detail': (f"They carry **{drift_fcst:,.0f} Kg** of forecast volume "
                       f"({drift_fcst_pct:.0%} of total), with approximately "
                       f"**{drift_impact:,.0f} Kg of misallocation** vs. recent history. "
                       "Use the Top 20 below to focus on the highest-impact ones."),
        })

    # 3. New Demand — forecast for combos with no recent history
    if n_new > 0:
        new_fcst = vbf.get('New Demand', {}).get('Forecast (Kg)', 0)
        new_pct = new_fcst / fcst_total if fcst_total > 0 else 0
        observations.append({
            'priority': 4,
            'flag': 'New Demand',
            'icon': '🆕',
            'headline': f"{n_new:,} combos have forecast but no recent history",
            'detail': (f"**{new_fcst:,.0f} Kg** of forecast ({new_pct:.0%} of total) "
                       "is going to combos that haven't traded in the recent window. "
                       "Verify these are genuine new wins, not stale assumptions."),
        })

    # 4. Healthy if % OK is dominant
    if pct_ok >= 0.5 and n_total > 0:
        observations.append({
            'priority': 5,
            'flag': 'OK',
            'icon': '✅',
            'headline': f"{pct_ok:.0%} of combos in this scope are aligned",
            'detail': "The bulk of the disaggregation is consistent with recent history. "
                      "Focus your attention on the issues called out above.",
        })

    # 5. Heavy dormant scope
    if n_no_act > 0 and n_total > 0:
        no_act_pct = n_no_act / n_total
        if no_act_pct > 0.30:
            observations.append({
                'priority': 6,
                'flag': 'No Activity',
                'icon': 'ℹ️',
                'headline': f"{n_no_act:,} combos ({no_act_pct:.0%}) are dormant",
                'detail': "These have neither recent history nor forecast — likely "
                          "discontinued or not-yet-active products/customers. They are "
                          "not actionable from a forecast-quality standpoint.",
            })

    if not observations:
        st.info("No issues to flag in this scope. Everything looks clean.")
    else:
        # Sort by priority
        observations.sort(key=lambda x: x['priority'])
        for obs in observations:
            color = FLAG_COLORS[obs['flag']]
            text_color = "#fff" if obs['flag'] == "Lost Forecast" else "#000"
            st.markdown(
                f"""
                <div style="border-left:4px solid {color};background:{LIGHT_BG};
                            padding:10px 16px;margin:8px 0;border-radius:4px;">
                    <div style="display:flex;align-items:center;gap:10px;">
                        <span style="font-size:1.2rem;">{obs['icon']}</span>
                        <span style="background:{color};color:{text_color};
                                     padding:2px 10px;border-radius:10px;
                                     font-size:0.78rem;font-weight:700;">{obs['flag']}</span>
                        <strong style="color:{NAVY};">{obs['headline']}</strong>
                    </div>
                    <div style="color:#444;margin-top:6px;font-size:0.92rem;line-height:1.5;">
                        {obs['detail']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ---- Top 20 violators (filter-aware) ----
    violators_rl = rl_filtered[rl_filtered["Flag"] != "OK"].copy()

    st.subheader("Top 20 Material × Parent Cust Violators")
    st.caption("Filter the table by flag type, then sort by either Kg Impact or "
               "absolute Mix Deviation. Reflects the Business Line / Sub Region scope above.")

    # Filter row (flag types + sort mode for the Top 20)
    fc1, fc2 = st.columns([2, 2])
    with fc1:
        flag_filter = st.multiselect(
            "Show flag types",
            ["Mix Drift", "Lost Forecast", "New Demand", "No Activity"],
            default=["Mix Drift", "Lost Forecast", "New Demand"],
            key="dash_top20_flags",
            help="No Activity is excluded by default since both volumes are zero.")
    with fc2:
        sort_mode = st.radio(
            "Sort by",
            ["Kg Impact (high → low)", "|Mix Deviation| (high → low)"],
            horizontal=True, key="dash_top20_sort")

    if flag_filter:
        filtered = violators_rl[violators_rl["Flag"].isin(flag_filter)].copy()
    else:
        filtered = violators_rl.copy()

    if "Kg" in sort_mode:
        top20 = filtered.nlargest(20, "Kg Impact")
    else:
        filtered["_abs_dev"] = filtered["Mix Deviation"].abs()
        top20 = filtered.nlargest(20, "_abs_dev").drop(columns="_abs_dev")

    if len(top20) == 0:
        st.info("No violators match the selected flag types in this scope.")
    else:
        chart_col, table_col = st.columns([1, 1])

        with chart_col:
            st.markdown("##### Visual ranking")
            top20_chart = top20.copy()
            top20_chart["Label"] = (top20_chart["Material"].str[:30] +
                                    " — " + top20_chart["Parent Cust"].str[:25])
            top20_chart["abs_dev"] = top20_chart["Mix Deviation"].abs()

            x_col = "Kg Impact" if "Kg" in sort_mode else "abs_dev"
            x_title = "Kg Impact" if "Kg" in sort_mode else "|Mix Deviation|"

            fig = go.Figure()
            fig.add_bar(
                y=top20_chart["Label"], x=top20_chart[x_col],
                orientation="h",
                marker_color=[FLAG_COLORS[f] for f in top20_chart["Flag"]],
                customdata=np.column_stack([
                    top20_chart["Recent Mix %"], top20_chart["Forecast Mix %"],
                    top20_chart["Mix Deviation"], top20_chart["Flag"]]),
                hovertemplate=("<b>%{y}</b><br>"
                               "Recent Mix: %{customdata[0]:.1%}<br>"
                               "Forecast Mix: %{customdata[1]:.1%}<br>"
                               "Deviation: %{customdata[2]:+.1%}<br>"
                               "Flag: %{customdata[3]}<extra></extra>"),
            )
            tickformat = ",.0f" if "Kg" in sort_mode else ".0%"
            fig.update_layout(
                height=600, margin=dict(l=10, r=40, t=10, b=10),
                yaxis=dict(autorange="reversed", tickfont=dict(size=10)),
                xaxis=dict(title=x_title, tickformat=tickformat),
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)

        with table_col:
            st.markdown("##### Details")
            display = top20[[
                "Material", "Parent Cust",
                "Recent Hist (Kg)", "Forecast (Kg)",
                "Recent Mix %", "Forecast Mix %",
                "Mix Deviation", "Kg Impact", "Flag"
            ]].copy()

            styled = (display.style
                      .format({
                          "Recent Hist (Kg)": "{:,.0f}",
                          "Forecast (Kg)": "{:,.0f}",
                          "Recent Mix %": "{:.1%}",
                          "Forecast Mix %": "{:.1%}",
                          "Mix Deviation": "{:+.1%}",
                          "Kg Impact": "{:,.0f}",
                      })
                      .map(color_flag, subset=["Flag"]))
            st.dataframe(styled, use_container_width=True, height=600,
                         hide_index=True)


# ============================================================================
# TAB 2 — Validation Detail (Mat × SubRegion × Cust)
# ============================================================================
with tab_validation:
    st.subheader("Validation Detail — Material × Ship To Sub Region × Parent Cust")
    st.caption(
        "Validation grain is the child level (Material × SubRegion × Parent Cust). "
        "Mix percentages here are computed relative to the Material × SubRegion "
        "parent (the level at which forecast is generated). Filters cascade — "
        "each filter's options reflect what's available given the others."
    )

    val_full = result.validation_df
    has_arkieva = 'Arkieva Review Req' in val_full.columns

    # Read current filter selections from session state (default empty)
    val_filters = {
        "Flag": st.session_state.get("val_flag_filter",
                                      ["Mix Drift", "Lost Forecast", "New Demand"]),
        "Business Line": st.session_state.get("val_bl", []),
        "Ship To Sub Region": st.session_state.get("val_sr", []),
        "Material": st.session_state.get("val_material", []),
        "Parent Cust": st.session_state.get("val_cust", []),
    }
    if has_arkieva:
        val_filters["Arkieva Review Req"] = st.session_state.get("val_arkieva", [])

    # Drop selections that have become invalid (e.g. user changed an upstream
    # filter and the previously-selected values no longer exist in the cascade)
    key_map = {
        "Flag": "val_flag_filter", "Business Line": "val_bl",
        "Ship To Sub Region": "val_sr", "Material": "val_material",
        "Parent Cust": "val_cust", "Arkieva Review Req": "val_arkieva",
    }
    for col, current in list(val_filters.items()):
        avail = slicer_options(val_full, val_filters, exclude_col=col)
        avail_set = set(avail)
        valid = [v for v in current if v in avail_set]
        if valid != current:
            val_filters[col] = valid
            st.session_state[key_map[col]] = valid

    # Render filters: 5 in row 1, optional 6th (Arkieva) in row 2 if available
    f1, f2, f3, f4, f5 = st.columns([1.2, 1.4, 1.2, 1.6, 1.6])
    with f1:
        flag_filter = st.multiselect(
            "Flag", FLAG_CODES,
            default=val_filters["Flag"], key="val_flag_filter")
    with f2:
        bl_opts = slicer_options(val_full, val_filters, "Business Line")
        bl_filter = st.multiselect(
            "Business Line", bl_opts, key="val_bl",
            help=f"{len(bl_opts)} options available given other filters")
    with f3:
        sr_opts = slicer_options(val_full, val_filters, "Ship To Sub Region")
        sr_filter = st.multiselect(
            "Sub Region", sr_opts, key="val_sr",
            help=f"{len(sr_opts)} options available given other filters")
    with f4:
        mat_opts = slicer_options(val_full, val_filters, "Material")
        material_filter = st.multiselect(
            "Material", mat_opts, key="val_material",
            help=f"{len(mat_opts)} options available given other filters")
    with f5:
        cust_opts = slicer_options(val_full, val_filters, "Parent Cust")
        cust_filter = st.multiselect(
            "Parent Cust", cust_opts, key="val_cust",
            help=f"{len(cust_opts)} options available given other filters")

    arkieva_filter = []
    if has_arkieva:
        ark_opts = slicer_options(val_full, val_filters, "Arkieva Review Req")
        arkieva_filter = st.multiselect(
            "Arkieva Review Req", ark_opts, key="val_arkieva",
            help=("Filter rows by their Arkieva Review Req value "
                  f"({len(ark_opts)} options available given other filters)"))

    # Reset filters button
    if st.button("Clear all filters", key="val_clear"):
        clear_keys = ["val_flag_filter", "val_bl", "val_sr", "val_material", "val_cust"]
        if has_arkieva:
            clear_keys.append("val_arkieva")
        for k in clear_keys:
            if k in st.session_state:
                del st.session_state[k]
        st.rerun()

    # Apply filters with the latest user selections
    val_filters = {
        "Flag": flag_filter,
        "Business Line": bl_filter,
        "Ship To Sub Region": sr_filter,
        "Material": material_filter,
        "Parent Cust": cust_filter,
    }
    if has_arkieva:
        val_filters["Arkieva Review Req"] = arkieva_filter
    val_df = apply_filters(val_full, val_filters)

    st.caption(f"**{len(val_df):,}** rows match (of {len(val_full):,} total)")

    # Display columns + formatting
    show_cols = ['Business Line', 'Material', 'Ship To Sub Region', 'Parent Cust',
                 '# Details']
    if has_arkieva:
        show_cols.append('Arkieva Review Req')
    show_cols += ['Recent Hist (Kg)', 'Forecast (Kg)',
                   'Recent Mix %', 'Forecast Mix %',
                   'Mix Deviation', 'Kg Impact', 'Flag']

    if len(val_df) > 0:
        styled = (val_df[show_cols].style
                  .format({
                      "Recent Hist (Kg)": "{:,.0f}",
                      "Forecast (Kg)": "{:,.0f}",
                      "Recent Mix %": "{:.1%}",
                      "Forecast Mix %": "{:.1%}",
                      "Mix Deviation": "{:+.1%}",
                      "Kg Impact": "{:,.0f}",
                  })
                  .map(color_flag, subset=["Flag"])
                  .background_gradient(cmap="RdYlGn_r",
                                        subset=["Mix Deviation"],
                                        vmin=-0.30, vmax=0.30))
        st.dataframe(styled, use_container_width=True, height=540,
                     hide_index=True)

        csv = val_df[show_cols].to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download filtered (CSV)", data=csv,
                           file_name="validation_filtered.csv", mime="text/csv")
    else:
        st.info("No rows match the filters.")


# ============================================================================
# TAB 3 — Mat × Cust Rollup
# ============================================================================
with tab_rollup:
    st.subheader("Material × Parent Customer Rollup")
    st.caption(
        "Rolled up across Sub Regions. At this grain, the parent volume is the "
        "Material total (across all SubRegions), and Recent/Forecast Mix % is the "
        "Customer's share of the Material's recent / forecast volume. "
        "Filters cascade — each filter's options reflect what's available given the others."
    )

    rl_full = result.matcust_rollup_df

    rl_filters = {
        "Flag": st.session_state.get("rl_flag_filter",
                                      ["Mix Drift", "Lost Forecast", "New Demand"]),
        "Material": st.session_state.get("rl_material", []),
        "Parent Cust": st.session_state.get("rl_cust", []),
    }
    # Prune invalid selections
    for col, current in list(rl_filters.items()):
        avail = slicer_options(rl_full, rl_filters, exclude_col=col)
        avail_set = set(avail)
        valid = [v for v in current if v in avail_set]
        if valid != current:
            rl_filters[col] = valid
            key_map = {"Flag": "rl_flag_filter", "Material": "rl_material",
                       "Parent Cust": "rl_cust"}
            st.session_state[key_map[col]] = valid

    f1, f2, f3 = st.columns([1, 2, 2])
    with f1:
        flag_filter = st.multiselect(
            "Flag", FLAG_CODES,
            default=rl_filters["Flag"], key="rl_flag_filter")
    with f2:
        mat_opts = slicer_options(rl_full, rl_filters, "Material")
        material_filter = st.multiselect(
            "Material", mat_opts, key="rl_material",
            help=f"{len(mat_opts)} options available given other filters")
    with f3:
        cust_opts = slicer_options(rl_full, rl_filters, "Parent Cust")
        cust_filter = st.multiselect(
            "Parent Cust", cust_opts, key="rl_cust",
            help=f"{len(cust_opts)} options available given other filters")

    if st.button("Clear all filters", key="rl_clear"):
        for k in ["rl_flag_filter", "rl_material", "rl_cust"]:
            if k in st.session_state:
                del st.session_state[k]
        st.rerun()

    rl_filters = {"Flag": flag_filter, "Material": material_filter,
                  "Parent Cust": cust_filter}
    rl_df = apply_filters(rl_full, rl_filters)

    st.caption(f"**{len(rl_df):,}** combos match (of {len(rl_full):,} total)")

    show_cols = ['Material', 'Parent Cust', '# SubRegions',
                 'Recent Hist (Kg)', 'Forecast (Kg)',
                 'Recent Mix %', 'Forecast Mix %',
                 'Mix Deviation', 'Kg Impact', 'Flag']

    if len(rl_df) > 0:
        styled = (rl_df[show_cols].style
                  .format({
                      "Recent Hist (Kg)": "{:,.0f}",
                      "Forecast (Kg)": "{:,.0f}",
                      "Recent Mix %": "{:.1%}",
                      "Forecast Mix %": "{:.1%}",
                      "Mix Deviation": "{:+.1%}",
                      "Kg Impact": "{:,.0f}",
                  })
                  .map(color_flag, subset=["Flag"])
                  .background_gradient(cmap="RdYlGn_r",
                                        subset=["Mix Deviation"],
                                        vmin=-0.30, vmax=0.30))
        st.dataframe(styled, use_container_width=True, height=560, hide_index=True)
        csv = rl_df[show_cols].to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download filtered (CSV)", data=csv,
                           file_name="matcust_rollup_filtered.csv", mime="text/csv")


# ============================================================================
# TAB 4 — Drill-In
# ============================================================================
with tab_drill:
    st.subheader("Drill-In: Material × Parent Cust")
    st.caption("Use the cascading filters to narrow down to one Material × Parent Cust, "
               "then see the SubRegion breakdown and underlying monthly history + forecast. "
               "Each filter's options reflect what's available given the others.")

    # Drive the drill-in from the child-grain validation table since we need
    # Business Line and Sub Region context too (the rollup table doesn't carry those)
    val_full = result.validation_df
    has_arkieva = 'Arkieva Review Req' in val_full.columns

    drill_filters = {
        "Business Line": st.session_state.get("drill_bl", []),
        "Ship To Sub Region": st.session_state.get("drill_sr", []),
        "Material": st.session_state.get("drill_mat_ms", []),
        "Parent Cust": st.session_state.get("drill_cust_ms", []),
    }
    if has_arkieva:
        drill_filters["Arkieva Review Req"] = st.session_state.get("drill_arkieva", [])

    # Prune invalid selections
    key_map = {"Business Line": "drill_bl",
               "Ship To Sub Region": "drill_sr",
               "Material": "drill_mat_ms",
               "Parent Cust": "drill_cust_ms",
               "Arkieva Review Req": "drill_arkieva"}
    for col, current in list(drill_filters.items()):
        avail = slicer_options(val_full, drill_filters, exclude_col=col)
        avail_set = set(avail)
        valid = [v for v in current if v in avail_set]
        if valid != current:
            drill_filters[col] = valid
            st.session_state[key_map[col]] = valid

    if has_arkieva:
        fc1, fc2, fc3, fc4, fc5 = st.columns(5)
    else:
        fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        bl_opts = slicer_options(val_full, drill_filters, "Business Line")
        bl_filter = st.multiselect(
            "Business Line", bl_opts, key="drill_bl",
            help=f"{len(bl_opts)} options available")
    with fc2:
        sr_opts = slicer_options(val_full, drill_filters, "Ship To Sub Region")
        sr_filter = st.multiselect(
            "Sub Region", sr_opts, key="drill_sr",
            help=f"{len(sr_opts)} options available")
    with fc3:
        mat_opts = slicer_options(val_full, drill_filters, "Material")
        mat_filter = st.multiselect(
            "Material", mat_opts, key="drill_mat_ms",
            help=f"{len(mat_opts)} options available")
    with fc4:
        cust_opts = slicer_options(val_full, drill_filters, "Parent Cust")
        cust_filter = st.multiselect(
            "Parent Cust", cust_opts, key="drill_cust_ms",
            help=f"{len(cust_opts)} options available")

    arkieva_filter = []
    if has_arkieva:
        with fc5:
            ark_opts = slicer_options(val_full, drill_filters, "Arkieva Review Req")
            arkieva_filter = st.multiselect(
                "Arkieva Review Req", ark_opts, key="drill_arkieva",
                help=f"{len(ark_opts)} options available given other filters")

    if st.button("Clear all filters", key="drill_clear"):
        clear_keys = ["drill_bl", "drill_sr", "drill_mat_ms", "drill_cust_ms"]
        if has_arkieva:
            clear_keys.append("drill_arkieva")
        for k in clear_keys:
            if k in st.session_state:
                del st.session_state[k]
        st.rerun()

    drill_filters = {
        "Business Line": bl_filter,
        "Ship To Sub Region": sr_filter,
        "Material": mat_filter,
        "Parent Cust": cust_filter,
    }
    if has_arkieva:
        drill_filters["Arkieva Review Req"] = arkieva_filter
    filtered = apply_filters(val_full, drill_filters)

    # Determine the unique (Material, Parent Cust) pairs in the filtered data
    mat_cust_pairs = (filtered[["Material", "Parent Cust"]]
                       .drop_duplicates().sort_values(["Material", "Parent Cust"]))

    if mat_cust_pairs.empty:
        st.warning("No Material × Parent Cust combinations match the current filters. "
                   "Adjust filters above.")
        st.stop()

    if len(mat_cust_pairs) == 1:
        sel_mat = mat_cust_pairs.iloc[0]["Material"]
        sel_cust = mat_cust_pairs.iloc[0]["Parent Cust"]
        st.success(f"Single combination matched: **{sel_mat} × {sel_cust}**")
    else:
        st.info(f"**{len(mat_cust_pairs):,}** Material × Parent Cust combinations match "
                "the filters above. Pick one to drill into:")
        # Show a compact picker. Use a label that combines both for clarity.
        labels = [f"{m} — {c}" for m, c in zip(mat_cust_pairs["Material"],
                                                mat_cust_pairs["Parent Cust"])]
        sel_label = st.selectbox("Choose a Material × Parent Cust", labels,
                                  key="drill_pick")
        sel_idx = labels.index(sel_label)
        sel_mat = mat_cust_pairs.iloc[sel_idx]["Material"]
        sel_cust = mat_cust_pairs.iloc[sel_idx]["Parent Cust"]

    # Look up the rollup row for this combo (from the rollup table)
    rl_df_full = result.matcust_rollup_df
    rl_match = rl_df_full[(rl_df_full["Material"] == sel_mat) &
                          (rl_df_full["Parent Cust"] == sel_cust)]
    if rl_match.empty:
        st.warning("No rollup data for this combo (this can happen if the combo only "
                   "appears in dormant 'No Activity' rows).")
        st.stop()
    rl_row = rl_match.iloc[0]

    cc1, cc2, cc3, cc4, cc5 = st.columns(5)
    cc1.metric("Flag", rl_row["Flag"])
    cc2.metric("Recent Hist (Kg)", f"{rl_row['Recent Hist (Kg)']:,.0f}")
    cc3.metric("Forecast (Kg)", f"{rl_row['Forecast (Kg)']:,.0f}")
    cc4.metric("Recent Mix %", f"{rl_row['Recent Mix %']:.1%}")
    cc5.metric("Forecast Mix %", f"{rl_row['Forecast Mix %']:.1%}",
               delta=f"{rl_row['Mix Deviation']:+.1%}", delta_color="off")

    st.markdown("")

    # SubRegion breakdown for this Mat × Cust
    sub = result.validation_df[
        (result.validation_df["Material"] == sel_mat) &
        (result.validation_df["Parent Cust"] == sel_cust)
    ].copy()

    if sub.empty:
        st.info("No SubRegion-level breakdown available for this combo.")
    else:
        st.markdown("##### SubRegion Breakdown")
        st.caption("Each row is a Material × SubRegion × Parent Cust child. "
                   "Recent/Forecast Mix % is computed within Material × SubRegion.")
        breakdown_cols = ['Ship To Sub Region', '# Details']
        if has_arkieva:
            breakdown_cols.append('Arkieva Review Req')
        breakdown_cols += ['Recent Hist (Kg)', 'Forecast (Kg)',
                           'Parent Recent (Kg)', 'Parent Forecast (Kg)',
                           'Recent Mix %', 'Forecast Mix %',
                           'Mix Deviation', 'Kg Impact', 'Flag']
        sub_show = sub[breakdown_cols]
        styled = (sub_show.style
                  .format({
                      "Recent Hist (Kg)": "{:,.0f}",
                      "Forecast (Kg)": "{:,.0f}",
                      "Parent Recent (Kg)": "{:,.0f}",
                      "Parent Forecast (Kg)": "{:,.0f}",
                      "Recent Mix %": "{:.1%}",
                      "Forecast Mix %": "{:.1%}",
                      "Mix Deviation": "{:+.1%}",
                      "Kg Impact": "{:,.0f}",
                  })
                  .map(color_flag, subset=["Flag"]))
        st.dataframe(styled, use_container_width=True,
                     height=min(40 + 35 * len(sub_show), 280),
                     hide_index=True)

    st.markdown("")
    st.markdown("##### Monthly History + Forecast")
    st.caption("Solid line = Sales History, dashed = Statistical Forecast. "
               "Multiple lines if there are multiple SubRegions or Details.")

    pv = result.monthly_pivot
    pv_sub = pv[(pv["Material"] == sel_mat) & (pv["Parent Cust"] == sel_cust)].copy()

    if pv_sub.empty:
        st.info("No monthly data for this selection.")
    else:
        # Aggregate to SubRegion level for time-series
        ts = (pv_sub.groupby(['Ship To Sub Region', 'Month'], as_index=False)
              .agg({'Sales History(Kg)': 'sum',
                    'Statistical Forecast(Kg)': 'sum'}))
        sub_regions = sorted(ts['Ship To Sub Region'].unique())
        palette = (px.colors.qualitative.Set2 + px.colors.qualitative.Set3 +
                   px.colors.qualitative.Pastel)
        color_map = {sr: palette[i % len(palette)] for i, sr in enumerate(sub_regions)}

        fig = go.Figure()
        for sr in sub_regions:
            seg = ts[ts['Ship To Sub Region'] == sr].sort_values('Month')
            color = color_map[sr]
            # History line: only where SalesHist > 0
            h = seg[seg['Sales History(Kg)'] > 0]
            f = seg[seg['Statistical Forecast(Kg)'] > 0]
            if len(h) > 0:
                fig.add_trace(go.Scatter(
                    x=h['Month'], y=h['Sales History(Kg)'],
                    name=f"{sr} (history)", mode="lines+markers",
                    line=dict(color=color, width=2),
                    legendgroup=sr,
                    hovertemplate=f"<b>{sr}</b><br>%{{x|%b %Y}}: %{{y:,.0f}} Kg<extra></extra>"))
            if len(f) > 0:
                fig.add_trace(go.Scatter(
                    x=f['Month'], y=f['Statistical Forecast(Kg)'],
                    name=f"{sr} (forecast)", mode="lines+markers",
                    line=dict(color=color, width=2, dash="dash"),
                    marker=dict(symbol="diamond"),
                    legendgroup=sr, showlegend=False,
                    hovertemplate=f"<b>{sr} fcst</b><br>%{{x|%b %Y}}: %{{y:,.0f}} Kg<extra></extra>"))

        # Boundary line — workaround for pandas+plotly Timestamp issue
        boundary_x = result.meta["last_hist_date"]
        if hasattr(boundary_x, "to_pydatetime"):
            boundary_x = boundary_x.to_pydatetime()
        fig.add_vline(x=boundary_x, line_dash="dot", line_color="#666")
        fig.add_annotation(
            x=boundary_x, y=1, yref="paper", yanchor="bottom",
            text="History | Forecast",
            showarrow=False, font=dict(size=10, color="#666"))

        fig.update_layout(
            height=420, margin=dict(l=10, r=10, t=20, b=10),
            yaxis=dict(title="Volume (Kg)", tickformat=",.0f"),
            xaxis=dict(title="Month"),
            hovermode="x unified",
            legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig, use_container_width=True)


# ============================================================================
# TAB 5 — Export
# ============================================================================
with tab_export:
    st.subheader("Export Results")
    st.markdown(
        "Download the full validation as a multi-sheet Excel file or per-table CSV."
    )

    col_x1, col_x2, col_x3 = st.columns(3)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")

    with col_x1:
        st.markdown("**📊 Excel report**")
        st.caption("Multi-sheet workbook: Summary, Validation Detail, "
                   "Mat × Cust Rollup, Settings.")
        try:
            excel_bytes = build_excel_export(result, settings)
            st.download_button(
                "📥 Download Excel (.xlsx)",
                data=excel_bytes,
                file_name=f"forecast_validation_{timestamp}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )
        except Exception as e:
            st.error(f"Excel export failed: {e}")

    with col_x2:
        st.markdown("**📄 Validation Detail (CSV)**")
        st.caption("Per Material × SubRegion × Parent Cust.")
        csv_val = result.validation_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Download Validation (CSV)",
            data=csv_val,
            file_name=f"validation_detail_{timestamp}.csv",
            mime="text/csv")

    with col_x3:
        st.markdown("**📄 Mat × Cust Rollup (CSV)**")
        csv_rl = result.matcust_rollup_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Download Rollup (CSV)",
            data=csv_rl,
            file_name=f"matcust_rollup_{timestamp}.csv",
            mime="text/csv")

    st.markdown("---")
    st.markdown("##### Settings used")
    rw_start = pd.Timestamp(result.meta['recent_window_start'])
    rw_end = pd.Timestamp(result.meta['recent_window_end'])
    fw_start = pd.Timestamp(result.meta['fcst_window_start'])
    fw_end = pd.Timestamp(result.meta['fcst_window_end'])
    st.json({
        "recent_history_window": f"{rw_start.strftime('%b %Y')} to {rw_end.strftime('%b %Y')}",
        "forecast_horizon_window": f"{fw_start.strftime('%b %Y')} to {fw_end.strftime('%b %Y')}",
        "deviation_threshold": settings.threshold,
    })


# ============================================================================
# TAB 6 — Instructions
# ============================================================================
with tab_instructions:
    st.subheader("Instructions & Methodology")

    st.markdown("### What this tool does")
    st.markdown("""
Forecasts are typically generated at the **Detail (7 Key attributes)** level,
then are aggregated to multiple higher levels. The disaggregation/aggregation
should be guided by what recent history is telling you — if a customer
accounted for 30% of recent sales for a Material × SubRegion, they should
account for roughly 30% of the forecast too.

This tool computes the mix percentages on both sides and flags every
**Material × Parent Customer** combination where the disaggregation is
misaligned with recent history, with a clear reason code so demand planners
know exactly what to fix.
    """)

    st.markdown("### Reason codes")
    rc_rows = [
        ("OK", FLAG_COLORS["OK"],
         "Both history and forecast > 0; deviation is within the threshold (default ±5%). "
         "Disaggregation is consistent with recent history."),
        ("Mix Drift", FLAG_COLORS["Mix Drift"],
         "Both history and forecast > 0, but the absolute deviation exceeds the threshold. "
         "The customer's share of the forecast has materially shifted away from their "
         "share of recent history."),
        ("New Demand", FLAG_COLORS["New Demand"],
         "Recent history is 0 but forecast is > 0. Could be legitimate new business "
         "or a misallocation — review separately."),
        ("Lost Forecast", FLAG_COLORS["Lost Forecast"],
         "Recent history is > 0 but forecast is 0. The planner has not allocated any "
         "forecast to a customer who has been actively buying — typically a high-impact "
         "issue worth investigating first."),
        ("No Activity", FLAG_COLORS["No Activity"],
         "Both history and forecast are 0. Dormant combinations — not actionable, "
         "filtered out of the Top 20 violators by default."),
    ]
    for code, color, desc in rc_rows:
        text_color = "#fff" if code == "Lost Forecast" else "#000"
        st.markdown(
            f"""
            <div style="display:flex;align-items:flex-start;margin:10px 0;">
                <div style="background:{color};color:{text_color};font-weight:700;
                            padding:4px 14px;border-radius:12px;font-size:0.85rem;
                            min-width:120px;text-align:center;margin-right:14px;
                            flex-shrink:0;">{code}</div>
                <div style="color:#333;font-size:0.95rem;line-height:1.5;">{desc}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("### Methodology")
    st.markdown("""
**Validation grain**: Material × Ship To Sub Region × Parent Customer (the *child*
of the disaggregation). The *parent* is Material × Ship To Sub Region.

| Metric | Definition |
|---|---|
| **Recent Mix %** | sum(Sales History last 6 months for the child) ÷ sum(Sales History last 6 months for the parent) |
| **Forecast Mix %** | sum(Statistical Forecast next 24 months for the child) ÷ sum(Statistical Forecast next 24 months for the parent) |
| **Mix Deviation** | Forecast Mix − Recent Mix |
| **Kg Impact** | Magnitude of misallocation in Kg. For Mix Drift: \\|deviation\\| × parent forecast volume. For Lost Forecast: recent history volume. For New Demand: forecast volume. For No Activity: 0. |

The **Mat × Cust Rollup** tab aggregates Sub Regions for the same Material ×
Customer pair and re-computes the mix at that grain (parent = Material total
across all Sub Regions).

All windows and thresholds are configurable in the sidebar.
    """)

    st.markdown("### Required input format")
    st.markdown("Your Excel file should have these columns:")
    st.code("\n".join(f"  - {c}" for c in REQUIRED_COLS), language="text")
    st.markdown("""
- One row per **(Detail, Month)** combination.
- For **history** months: `Sales History(Kg)` has the actual; `Statistical Forecast(Kg)`
  may also have a value (the backtest forecast for that month).
- For **future** months: only `Statistical Forecast(Kg)` is populated.
- The app tolerates common header variants (e.g. `Forecast` instead of
  `Statistical Forecast(Kg)`, `Customer` instead of `Parent Cust`).
    """)

    st.markdown("### How to use")
    st.markdown("""
1. **Upload** your Excel file in the sidebar (left).
2. **Adjust settings** if needed:
   - Recent History Window (default 6 months)
   - Forecast Horizon (default 24 months)
   - Deviation Threshold (default 5%)
3. **Dashboard** shows the headline numbers and the Top 20 violators —
   sortable by either Kg Impact or |Mix Deviation|.
4. **Validation Detail** is your full filterable worklist at the
   Material × SubRegion × Parent Cust grain.
5. **Mat × Cust Rollup** is the same view aggregated up.
6. **Drill-In** lets you pick a specific Material × Parent Cust to see the
   SubRegion breakdown and the underlying monthly history+forecast curves.
7. **Export** generates a multi-sheet Excel report or per-table CSVs.

To analyse a different file, simply upload it via the sidebar — the app
replaces all data with the new file. Click the **×** on the uploaded file to
reset the app entirely.
    """)

    st.markdown("### What planners typically look for")
    st.markdown("""
- **Lost Forecast** rows with high Kg Impact — these are customers who have been
  actively buying but were not allocated any forecast at all.
- **Mix Drift** rows with large deviation magnitude — customers whose share of
  the forecast has shifted significantly from their share of recent history.
  Investigate whether the demand signal has been picked up.
- **New Demand** rows — confirm whether these are genuine new wins or
  misallocations of the forecast model.
    """)
