# Forecast Disaggregation Validator

A Streamlit web app that validates whether the **Statistical Forecast** disaggregation across customers is consistent with **recent Sales History** at the Material × Ship To Sub Region level.

## Deploying

**To get a permanent public URL** for your team: follow **[DEPLOYMENT.md](DEPLOYMENT.md)** — it walks you through deploying to Streamlit Community Cloud (free, no Git knowledge required) in about 25 minutes.

## What it does

Forecasts are typically generated at the **Material × Ship To Sub Region** level, then disaggregated to the **Parent Customer** level. The disaggregation should reflect what recent history is telling you — if a customer accounted for 30% of recent sales for a Material × SubRegion, they should account for roughly 30% of the forecast too.

This tool computes the mix percentages on both sides and flags every Material × Customer combination with a reason code:

- **OK** — Both history and forecast > 0; deviation within threshold
- **Mix Drift** — Both > 0; deviation exceeds threshold (default 5%)
- **New Demand** — History = 0 but Forecast > 0 (new business)
- **Lost Forecast** — History > 0 but Forecast = 0 (planner missed it)
- **No Activity** — Both = 0 (dormant combo)

See **[USER_GUIDE.md](USER_GUIDE.md)** for the full business user guide and **[FORECASTER_ACTION_PLAN.md](FORECASTER_ACTION_PLAN.md)** for what to do once issues are flagged.

## Input format

Excel `.xlsx` with these columns:

| Column | Type | Required? |
|---|---|---|
| Business Line | text | required |
| Detail | text | required |
| Material | text | required |
| Ship To Sub Region | text | required |
| Parent Cust | text | required |
| Month | date | required |
| Sales History(Kg) | number | required |
| Statistical Forecast(Kg) | number | required |
| Arkieva Review Req | Yes/No or True/False | optional |

One row per `(Detail, Month)`. For history months, both Sales History (actual) and Statistical Forecast (backtest) may be populated. For future months, only Statistical Forecast.

The app tolerates common header variants (e.g. `Forecast` instead of `Statistical Forecast(Kg)`, lowercase `(kg)` units).

If `Arkieva Review Req` is included, it's preserved through to the validation table and exposed as an additional filter on the Validation Detail and Drill-In tabs.

## Settings

Three settings, all editable in the sidebar after uploading a file:

- **Recent History Window** — pick start and end months. Defaults to the **last 6 history months** ending at the latest available history month.
- **Forecast Horizon** — pick start and end forecast months. Defaults to **(last_history_month + 4 months) through December of that calendar year**.
- **Deviation Threshold (%)** — `|Mix Deviation|` greater than this triggers a Mix Drift flag. Default 5%.

## Running locally (for development or testing)

```bash
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**First-time auth setup** (required — the app refuses to start without it):

```bash
# 1. Copy the secrets template
cp .streamlit/secrets.toml.template .streamlit/secrets.toml

# 2. Generate a password hash for each user
python add_user.py alice
#    (paste the output into .streamlit/secrets.toml under [auth.users])

# 3. Generate a cookie signing key
python add_user.py --new-cookie-key
#    (paste into .streamlit/secrets.toml under [auth])

# 4. Run the app
streamlit run app.py
```

Open `http://localhost:8501`, sign in, and upload your Excel file.

## Authentication

The app is protected by an in-app username/password login screen. Users are defined in `.streamlit/secrets.toml` as bcrypt-hashed passwords.

**For local dev**: edit `.streamlit/secrets.toml` directly (it's gitignored).
**For Streamlit Cloud**: paste the same content into the "Secrets" textbox of your app's settings on share.streamlit.io. Streamlit makes it available to the app via `st.secrets` — same code path, never touches GitHub.

### Adding a user

```bash
python add_user.py <username>
```

Generates a bcrypt hash. Paste the resulting line under `[auth.users]` in your secrets (locally) or in the Streamlit Cloud Secrets textbox.

### Auth settings (in `[auth]` section of secrets)

| Setting | Default | What it does |
|---|---|---|
| `session_hours` | 8 | Session expires after this many hours |
| `max_failed_attempts` | 5 | Lock the login form after this many wrong attempts in a row |
| `lockout_minutes` | 15 | How long the lockout lasts |
| `cookie_signing_key` | (required) | 32-byte hex; generate with `python add_user.py --new-cookie-key` |

### Security notes

- **`secrets.toml` must NEVER be committed to a public repository.** The `.gitignore` excludes it. For Streamlit Cloud deployment, use the dashboard's Secrets textbox — never the filesystem.
- **Use strong passwords** (≥ 12 characters). On a public URL the login form is internet-exposed; weak passwords can be brute-forced even with bcrypt cost-12 hashing.
- **Bcrypt cost factor 12** (~250ms per verify). 2026 industry default.
- **Lockout is per-session**, not per-IP. We can't reliably observe the original client IP behind Streamlit Cloud's edge.
- **This is not OAuth.** No Google sign-in, no SSO integration.

## App tabs

1. **Dashboard** — KPI scorecards, Business Line + Sub Region cascading filters, Flag Distribution chart, Forecast Volume by Flag chart, data-driven interpretation panel, Top 20 violators (sort by Kg Impact or absolute deviation).
2. **Validation Detail** — Filterable table at Material × SubRegion × Parent Cust grain. Cascading slicer-style filters. Color-coded flags + deviation heatmap. CSV export.
3. **Mat × Cust Rollup** — Same metrics rolled up across SubRegions. Three cascading filters.
4. **Drill-In** — Cascading filters to narrow to a single Material × Parent Cust. SubRegion breakdown + multi-series time chart of monthly history (solid) and forecast (dashed).
5. **Export** — Multi-sheet Excel report or per-table CSVs.
6. **Instructions** — Methodology, reason code definitions, input format, how-to-use guide.

## File layout

```
forecast-disagg-validator/
├── app.py                            # Streamlit UI
├── validator_engine.py               # Pure-Python core logic (no Streamlit dependency)
├── excel_exporter.py                 # Multi-sheet Excel report builder
├── auth_gate.py                      # Login gate + session management
├── add_user.py                       # CLI helper: generate bcrypt password hashes
├── requirements.txt
├── README.md                         # this file
├── DEPLOYMENT.md                     # how to deploy to Streamlit Cloud
├── USER_GUIDE.md                     # business user guide
├── FORECASTER_ACTION_PLAN.md         # what to do once issues are flagged
├── .gitignore                        # excludes secrets.toml, caches, data files
└── .streamlit/
    ├── config.toml                   # production Streamlit server settings
    ├── secrets.toml                  # YOUR users (DO NOT COMMIT — gitignored)
    └── secrets.toml.template         # Template to copy from
```
