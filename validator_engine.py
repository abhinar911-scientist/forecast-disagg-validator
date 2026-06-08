"""
Forecast Disaggregation Validation Engine — v2

Methodology
-----------
Forecast is generated at the **Material × Ship To Sub Region** level (parent),
then disaggregated to **Material × Ship To Sub Region × Parent Cust** (child).
This engine validates that the forecast mix at the child level is consistent
with the recent-history mix at the same child level.

  Recent Mix % = sum(SalesHistory last N months at child)
                 / sum(SalesHistory last N months at parent)
  Forecast Mix % = sum(StatForecast next M months at child)
                 / sum(StatForecast next M months at parent)
  Mix Deviation = Forecast Mix − Recent Mix

Flag Reason Codes (per child combo)
  - No Activity:   Both history and forecast are 0
  - Lost Forecast: History > 0, Forecast = 0
  - New Demand:    History = 0, Forecast > 0
  - Mix Drift:     Both > 0 but |Mix Deviation| > threshold
  - OK:            Both > 0 and within threshold
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple, Dict, List, Optional
import pandas as pd
import numpy as np
from dateutil.relativedelta import relativedelta


# ---------------------------------------------------------------------------
# Schema and aliases
# ---------------------------------------------------------------------------
REQUIRED_COLS = [
    'Business Line', 'Detail', 'Material', 'Ship To Sub Region',
    'Parent Cust', 'Month', 'Sales History(Kg)', 'Statistical Forecast(Kg)'
]

# Optional columns — preserved through cleaning if present in the input.
OPTIONAL_COLS = ['Arkieva Review Req']

ALIAS_MAP = {
    'business line': 'Business Line', 'businessline': 'Business Line', 'bl': 'Business Line',
    'detail': 'Detail', 'detail code': 'Detail', 'detail_code': 'Detail',
    'material': 'Material', 'sku': 'Material', 'material code': 'Material',
    'ship to sub region': 'Ship To Sub Region', 'sub region': 'Ship To Sub Region',
    'subregion': 'Ship To Sub Region', 'ship-to sub region': 'Ship To Sub Region',
    'parent cust': 'Parent Cust', 'parent customer': 'Parent Cust',
    'parent_customer': 'Parent Cust', 'customer': 'Parent Cust',
    'month': 'Month', 'period': 'Month', 'date': 'Month',
    'sales history(kg)': 'Sales History(Kg)', 'sales history': 'Sales History(Kg)',
    'sales': 'Sales History(Kg)', 'history': 'Sales History(Kg)',
    'sales history (kg)': 'Sales History(Kg)', 'history(kg)': 'Sales History(Kg)',
    'statistical forecast(kg)': 'Statistical Forecast(Kg)',
    'statistical forecast': 'Statistical Forecast(Kg)',
    'statistical forecast (kg)': 'Statistical Forecast(Kg)',
    # "Committed" variant — some exports name the final forecast column
    # "Statistical Forecast Committed (kg)". Treat it as the same forecast column
    # so the header is always normalized to the canonical 'Statistical Forecast(Kg)'.
    'statistical forecast committed (kg)': 'Statistical Forecast(Kg)',
    'statistical forecast committed(kg)': 'Statistical Forecast(Kg)',
    'statistical forecast committed': 'Statistical Forecast(Kg)',
    'statistical forecast committed (kgs)': 'Statistical Forecast(Kg)',
    'forecast': 'Statistical Forecast(Kg)', 'forecast(kg)': 'Statistical Forecast(Kg)',
    'fcst': 'Statistical Forecast(Kg)',
    # Optional column aliases
    'arkieva review req': 'Arkieva Review Req',
    'arkieva review required': 'Arkieva Review Req',
    'review required': 'Arkieva Review Req',
    'review required status': 'Arkieva Review Req',
    'review req': 'Arkieva Review Req',
    'review_required': 'Arkieva Review Req',
}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@dataclass
class Settings:
    """Validation parameters.

    The recent / forecast windows can be specified two ways:
      1. As month counts (recent_window / fcst_window) — simple "last N months"
         and "next M months" relative to the data's anchor dates. This is the
         legacy default.
      2. As explicit start/end dates (recent_start / recent_end /
         fcst_start / fcst_end) — overrides the month counts when provided.
         Either both members of a pair are set, or neither.

    If dates are out of range of the data, the engine will clamp them to the
    available data and emit no error.
    """
    recent_window: int = 6        # legacy: months of recent history
    fcst_window: int = 24         # legacy: months of forecast horizon
    threshold: float = 0.05       # |deviation| > this -> Mix Drift

    # Optional explicit date ranges. If set, override the window counts above.
    recent_start: Optional[pd.Timestamp] = None
    recent_end: Optional[pd.Timestamp] = None
    fcst_start: Optional[pd.Timestamp] = None
    fcst_end: Optional[pd.Timestamp] = None

    def validate(self) -> List[str]:
        issues = []
        if self.recent_window < 1:
            issues.append("Recent window must be ≥ 1 month")
        if self.fcst_window < 1:
            issues.append("Forecast window must be ≥ 1 month")
        if self.threshold < 0:
            issues.append("Threshold must be ≥ 0")
        # Date-range sanity
        if self.recent_start is not None and self.recent_end is not None:
            if self.recent_start > self.recent_end:
                issues.append("Recent History start date must be ≤ end date")
        if self.fcst_start is not None and self.fcst_end is not None:
            if self.fcst_start > self.fcst_end:
                issues.append("Forecast Horizon start date must be ≤ end date")
        # Half-set date ranges are invalid
        if (self.recent_start is None) != (self.recent_end is None):
            issues.append("Both Recent Start AND Recent End must be set, or neither")
        if (self.fcst_start is None) != (self.fcst_end is None):
            issues.append("Both Forecast Start AND Forecast End must be set, or neither")
        return issues


@dataclass
class ValidationResult:
    validation_df: pd.DataFrame      # per Material × SubRegion × Parent Cust
    matcust_rollup_df: pd.DataFrame  # per Material × Parent Cust
    meta: Dict
    monthly_pivot: pd.DataFrame


# ---------------------------------------------------------------------------
# Flag classification
# ---------------------------------------------------------------------------
FLAG_CODES = ['OK', 'Mix Drift', 'New Demand', 'Lost Forecast', 'No Activity']

FLAG_COLORS = {
    'OK':            '#70AD47',
    'Mix Drift':     '#ED7D31',
    'New Demand':    '#5B9BD5',
    'Lost Forecast': '#C00000',
    'No Activity':   '#A6A6A6',
}


def classify_flag(recent_kg: float, fcst_kg: float, deviation: float, threshold: float) -> str:
    if recent_kg <= 0 and fcst_kg <= 0:
        return 'No Activity'
    if recent_kg > 0 and fcst_kg <= 0:
        return 'Lost Forecast'
    if recent_kg <= 0 and fcst_kg > 0:
        return 'New Demand'
    if abs(deviation) > threshold:
        return 'Mix Drift'
    return 'OK'


# ---------------------------------------------------------------------------
# Input cleaning
# ---------------------------------------------------------------------------
def _normalize_header(h: str) -> str:
    # Lowercase, strip, and collapse any internal runs of whitespace to a single
    # space so headers like "Statistical Forecast  (kg)" (double space) still match.
    return ' '.join(str(h).strip().lower().split())


def normalize_columns(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    rename = {}
    seen = set()
    # Process non-"committed" headers first. If a file ever contains BOTH a
    # standard forecast column AND a "Statistical Forecast Committed (kg)" column,
    # the standard one claims the canonical name and the committed one is ignored.
    # (sorted is stable, so original column order is preserved within each group.)
    ordered_cols = sorted(df.columns,
                          key=lambda c: 'committed' in _normalize_header(c))
    for col in ordered_cols:
        canon = ALIAS_MAP.get(_normalize_header(col))
        if canon and canon not in seen:
            rename[col] = canon
            seen.add(canon)
    df = df.rename(columns=rename)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    return df, missing


def load_and_validate_input(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str], List[str]]:
    errors, warnings = [], []
    df, missing = normalize_columns(df)
    if missing:
        errors.append(f"Missing required columns: {', '.join(missing)}")
        return df, errors, warnings

    # Keep only required + any optional columns that are present
    keep_cols = REQUIRED_COLS + [c for c in OPTIONAL_COLS if c in df.columns]
    df = df[keep_cols].copy()

    try:
        df['Month'] = pd.to_datetime(df['Month'], errors='coerce')
    except Exception as e:
        errors.append(f"Could not parse Month column: {e}")
        return df, errors, warnings
    bad = df['Month'].isna().sum()
    if bad > 0:
        warnings.append(f"{bad} rows have unparseable Month — dropped.")
        df = df.dropna(subset=['Month'])
    df['Month'] = df['Month'].dt.to_period('M').dt.to_timestamp()

    for col in ['Sales History(Kg)', 'Statistical Forecast(Kg)']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

    for col in ['Business Line', 'Detail', 'Material', 'Ship To Sub Region', 'Parent Cust']:
        df[col] = df[col].astype(str).str.strip()
    for col in ['Material', 'Ship To Sub Region', 'Parent Cust']:
        if (df[col] == '').any() or df[col].isna().any():
            errors.append(f"Column '{col}' has missing values.")

    # Coerce optional columns to user-friendly forms
    if 'Arkieva Review Req' in df.columns:
        col_data = df['Arkieva Review Req']
        # Map booleans / 0-1 / "True"-"False" / "Yes"-"No" all to the same Yes/No display
        def _to_yn(v):
            if pd.isna(v):
                return 'Unknown'
            s = str(v).strip().lower()
            if s in ('true', '1', '1.0', 'yes', 'y', 't'):
                return 'Yes'
            if s in ('false', '0', '0.0', 'no', 'n', 'f', ''):
                return 'No'
            # Anything else, keep as-is (preserves arbitrary categorical values)
            return str(v).strip()
        df['Arkieva Review Req'] = col_data.map(_to_yn)

    if errors:
        return df, errors, warnings

    n_dups = df.duplicated(['Detail', 'Month']).sum()
    if n_dups > 0:
        warnings.append(f"{n_dups} duplicate (Detail, Month) rows — summing.")
        # Build groupby keys (always include the optional column if present so it's
        # preserved in the dedup; we take "first" for it)
        gb_keys = ['Business Line', 'Detail', 'Material', 'Ship To Sub Region',
                   'Parent Cust', 'Month']
        agg_spec = {'Sales History(Kg)': 'sum', 'Statistical Forecast(Kg)': 'sum'}
        if 'Arkieva Review Req' in df.columns:
            agg_spec['Arkieva Review Req'] = 'first'
        df = df.groupby(gb_keys, as_index=False).agg(agg_spec)

    has_hist = (df['Sales History(Kg)'] > 0).any()
    has_fcst_only = ((df['Sales History(Kg)'] == 0) & (df['Statistical Forecast(Kg)'] > 0)).any()
    if not has_hist:
        errors.append("No Sales History values > 0 found.")
    if not has_fcst_only:
        errors.append("No future-only forecast rows found "
                      "(rows where Sales History = 0 and Statistical Forecast > 0).")

    return df, errors, warnings


# ---------------------------------------------------------------------------
# Helper: aggregate child + parent volumes for any grain
# ---------------------------------------------------------------------------
def _build_validation(df: pd.DataFrame, child_keys: List[str], parent_keys: List[str],
                      rec_slice: pd.DataFrame, fcst_slice: pd.DataFrame,
                      threshold: float) -> pd.DataFrame:
    """Build a validation dataframe at the given grain.

    child_keys: e.g. ['Material', 'Ship To Sub Region', 'Parent Cust']
    parent_keys: e.g. ['Material', 'Ship To Sub Region']
    """
    child_recent = (rec_slice.groupby(child_keys, as_index=False)['Sales History(Kg)']
                    .sum().rename(columns={'Sales History(Kg)': 'Recent Hist (Kg)'}))
    child_fcst = (fcst_slice.groupby(child_keys, as_index=False)['Statistical Forecast(Kg)']
                  .sum().rename(columns={'Statistical Forecast(Kg)': 'Forecast (Kg)'}))
    parent_recent = (rec_slice.groupby(parent_keys, as_index=False)['Sales History(Kg)']
                     .sum().rename(columns={'Sales History(Kg)': 'Parent Recent (Kg)'}))
    parent_fcst = (fcst_slice.groupby(parent_keys, as_index=False)['Statistical Forecast(Kg)']
                   .sum().rename(columns={'Statistical Forecast(Kg)': 'Parent Forecast (Kg)'}))

    # Universe of child combos = anything that ever appears in the input
    all_children = df[child_keys].drop_duplicates().reset_index(drop=True)

    val = (all_children
           .merge(child_recent, on=child_keys, how='left')
           .merge(child_fcst, on=child_keys, how='left')
           .merge(parent_recent, on=parent_keys, how='left')
           .merge(parent_fcst, on=parent_keys, how='left'))

    for c in ['Recent Hist (Kg)', 'Forecast (Kg)',
              'Parent Recent (Kg)', 'Parent Forecast (Kg)']:
        val[c] = val[c].fillna(0.0)

    val['Recent Mix %'] = np.where(val['Parent Recent (Kg)'] > 0,
                                    val['Recent Hist (Kg)'] / val['Parent Recent (Kg)'], 0.0)
    val['Forecast Mix %'] = np.where(val['Parent Forecast (Kg)'] > 0,
                                      val['Forecast (Kg)'] / val['Parent Forecast (Kg)'], 0.0)
    val['Mix Deviation'] = val['Forecast Mix %'] - val['Recent Mix %']

    # Kg Impact: absolute volume impact of the misallocation.
    impact_base = np.where(val['Parent Forecast (Kg)'] > 0,
                            val['Parent Forecast (Kg)'],
                            val['Parent Recent (Kg)'])
    val['Kg Impact'] = np.abs(val['Mix Deviation']) * impact_base

    val['Flag'] = [classify_flag(r, f, d, threshold)
                   for r, f, d in zip(val['Recent Hist (Kg)'],
                                      val['Forecast (Kg)'],
                                      val['Mix Deviation'])]
    # Override Kg Impact for special flags
    val.loc[val['Flag'] == 'Lost Forecast', 'Kg Impact'] = val.loc[val['Flag'] == 'Lost Forecast', 'Recent Hist (Kg)']
    val.loc[val['Flag'] == 'New Demand', 'Kg Impact'] = val.loc[val['Flag'] == 'New Demand', 'Forecast (Kg)']
    val.loc[val['Flag'] == 'No Activity', 'Kg Impact'] = 0.0

    return val


# ---------------------------------------------------------------------------
# Core entry point
# ---------------------------------------------------------------------------
def run_validation(df: pd.DataFrame, settings: Settings) -> ValidationResult:
    issues = settings.validate()
    if issues:
        raise ValueError(f"Settings invalid: {'; '.join(issues)}")

    # Date anchors (always derived from the input data)
    hist_mask = df['Sales History(Kg)'] > 0
    fcst_only_mask = (df['Sales History(Kg)'] == 0) & (df['Statistical Forecast(Kg)'] > 0)
    last_hist_date = df.loc[hist_mask, 'Month'].max()
    # Forecast horizon anchor = months strictly AFTER last_hist_date.
    # We don't trust the "first forecast date" detected from data because some past
    # months (when a Detail had no history yet) also have non-zero forecast — those
    # are not part of the planner's current forward forecast.
    first_fcst_date = (last_hist_date + relativedelta(months=1))
    last_fcst_date = df.loc[fcst_only_mask & (df['Month'] >= first_fcst_date), 'Month'].max()

    # ---- Resolve the recent and forecast windows ----
    # Priority: explicit dates > month-count defaults.
    if settings.recent_start is not None and settings.recent_end is not None:
        rec_start = pd.Timestamp(settings.recent_start).to_period('M').to_timestamp()
        rec_end = pd.Timestamp(settings.recent_end).to_period('M').to_timestamp()
    else:
        rec_end = last_hist_date
        rec_start = last_hist_date - relativedelta(months=settings.recent_window - 1)

    if settings.fcst_start is not None and settings.fcst_end is not None:
        fc_start = pd.Timestamp(settings.fcst_start).to_period('M').to_timestamp()
        fc_end = pd.Timestamp(settings.fcst_end).to_period('M').to_timestamp()
    else:
        fc_start = first_fcst_date
        fc_end = first_fcst_date + relativedelta(months=settings.fcst_window - 1)

    rec_slice = df[(df['Month'] >= rec_start) & (df['Month'] <= rec_end) &
                   (df['Sales History(Kg)'] > 0)]
    fcst_slice = df[(df['Month'] >= fc_start) & (df['Month'] <= fc_end) &
                    (df['Statistical Forecast(Kg)'] > 0)]

    # ---- Validation at child grain (Mat × SubRegion × Cust) ----
    val = _build_validation(df,
                            child_keys=['Material', 'Ship To Sub Region', 'Parent Cust'],
                            parent_keys=['Material', 'Ship To Sub Region'],
                            rec_slice=rec_slice, fcst_slice=fcst_slice,
                            threshold=settings.threshold)

    # Add Business Line + #Details for context
    bl_map = (df.sort_values('Month')
                .groupby(['Material', 'Ship To Sub Region', 'Parent Cust'])['Business Line']
                .first().reset_index())
    val = val.merge(bl_map, on=['Material', 'Ship To Sub Region', 'Parent Cust'], how='left')

    n_details = (df.groupby(['Material', 'Ship To Sub Region', 'Parent Cust'])['Detail'].nunique()
                   .reset_index().rename(columns={'Detail': '# Details'}))
    val = val.merge(n_details, on=['Material', 'Ship To Sub Region', 'Parent Cust'], how='left')

    # Optional: propagate Arkieva Review Req if present (first-seen per child combo)
    has_arkieva = 'Arkieva Review Req' in df.columns
    if has_arkieva:
        ark_map = (df.sort_values('Month')
                     .groupby(['Material', 'Ship To Sub Region', 'Parent Cust'])
                     ['Arkieva Review Req'].first().reset_index())
        val = val.merge(ark_map, on=['Material', 'Ship To Sub Region', 'Parent Cust'], how='left')

    base_cols = ['Business Line', 'Material', 'Ship To Sub Region', 'Parent Cust',
                 '# Details']
    if has_arkieva:
        base_cols.append('Arkieva Review Req')
    val = val[base_cols + ['Recent Hist (Kg)', 'Forecast (Kg)',
                            'Parent Recent (Kg)', 'Parent Forecast (Kg)',
                            'Recent Mix %', 'Forecast Mix %',
                            'Mix Deviation', 'Kg Impact', 'Flag']]
    val = val.sort_values(['Material', 'Ship To Sub Region', 'Parent Cust']).reset_index(drop=True)

    # ---- Material × Parent Cust ROLLUP (parent = Material alone) ----
    rl = _build_validation(df,
                           child_keys=['Material', 'Parent Cust'],
                           parent_keys=['Material'],
                           rec_slice=rec_slice, fcst_slice=fcst_slice,
                           threshold=settings.threshold)

    n_sr = (df.groupby(['Material', 'Parent Cust'])['Ship To Sub Region'].nunique()
              .reset_index().rename(columns={'Ship To Sub Region': '# SubRegions'}))
    rl = rl.merge(n_sr, on=['Material', 'Parent Cust'], how='left')

    # Propagate Arkieva at rollup grain too (any-True wins, since rollup spans
    # multiple SubRegions and "review required" should bubble up if anything inside
    # needs review)
    if has_arkieva:
        ark_rollup = (df.assign(_ark_yes=df['Arkieva Review Req'].eq('Yes'))
                        .groupby(['Material', 'Parent Cust'])
                        ['_ark_yes'].any().reset_index())
        ark_rollup['Arkieva Review Req'] = ark_rollup['_ark_yes'].map({True: 'Yes', False: 'No'})
        ark_rollup = ark_rollup[['Material', 'Parent Cust', 'Arkieva Review Req']]
        rl = rl.merge(ark_rollup, on=['Material', 'Parent Cust'], how='left')

    base_rl_cols = ['Material', 'Parent Cust', '# SubRegions']
    if has_arkieva:
        base_rl_cols.append('Arkieva Review Req')
    rl = rl[base_rl_cols + ['Recent Hist (Kg)', 'Forecast (Kg)',
                             'Parent Recent (Kg)', 'Parent Forecast (Kg)',
                             'Recent Mix %', 'Forecast Mix %',
                             'Mix Deviation', 'Kg Impact', 'Flag']]
    rl = rl.sort_values(['Material', 'Parent Cust']).reset_index(drop=True)

    # ---- Monthly pivot for time-series viz ----
    df_p = df.copy()
    df_p['Type'] = np.where(df_p['Sales History(Kg)'] > 0, 'History',
                    np.where(df_p['Statistical Forecast(Kg)'] > 0, 'Forecast', 'Empty'))
    pivot = df_p[df_p['Type'] != 'Empty'].copy()

    # ---- Meta ----
    flag_counts = val['Flag'].value_counts().to_dict()
    rollup_flag_counts = rl['Flag'].value_counts().to_dict()
    meta = {
        'last_hist_date': last_hist_date,
        'first_fcst_date': first_fcst_date,
        'last_fcst_date': last_fcst_date,
        'recent_window_start': rec_start,
        'recent_window_end': rec_end,
        'fcst_window_start': fc_start,
        'fcst_window_end': fc_end,
        'n_child_combos': len(val),
        'n_rollup_combos': len(rl),
        'total_recent_kg': float(val['Recent Hist (Kg)'].sum()),
        'total_forecast_kg': float(val['Forecast (Kg)'].sum()),
        'flag_counts': flag_counts,
        'rollup_flag_counts': rollup_flag_counts,
        'n_violators': int((val['Flag'] != 'OK').sum()),
        'n_violators_rollup': int((rl['Flag'] != 'OK').sum()),
        'pct_ok': float((val['Flag'] == 'OK').mean()),
        'pct_ok_rollup': float((rl['Flag'] == 'OK').mean()),
        'settings': {
            'recent_window': settings.recent_window,
            'fcst_window': settings.fcst_window,
            'threshold': settings.threshold,
            'recent_start': rec_start,
            'recent_end': rec_end,
            'fcst_start': fc_start,
            'fcst_end': fc_end,
        },
    }

    return ValidationResult(validation_df=val, matcust_rollup_df=rl,
                            meta=meta, monthly_pivot=pivot)
