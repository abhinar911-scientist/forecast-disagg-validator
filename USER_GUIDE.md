# Forecast Disaggregation Validator — Business User Guide

## What problem does this tool solve?

When your forecasting engine produces a Statistical Forecast, the *total* number for a Material in a region might be perfectly reasonable. But that total has to be **disaggregated** — split across customers, sub-regions, and shipping points. If the split is wrong, you ship the wrong volume to the wrong customer even though the total is right.

The classic failure looks like this:

> *In the last 6 months, Customer A bought 40% of all your sales of Material X in Europe. But your forecast for the next 24 months is allocating only 5% to Customer A.*

That's a mix problem — and the tool is designed to find these problems automatically across thousands of Material × Customer combinations, so planners can fix the ones that matter most.

---

## The core idea: comparing two "splits"

For every customer of every Material, the tool calculates two percentages:

**1. The Historical Split (Recent Mix %)** — *How much of the Material did this customer buy in the last 6 months?*

If the total sales of "Dissolvine E-39" in Europe over the last 6 months were 100,000 Kg, and Customer A bought 30,000 of those, Customer A's Recent Mix % is **30%**.

**2. The Forecast Split (Forecast Mix %)** — *How much of the Material is the forecast giving to this customer over the next 24 months?*

If the total forecast for "Dissolvine E-39" in Europe for the next 24 months is 400,000 Kg, and Customer A's forecast is 80,000 Kg, Customer A's Forecast Mix % is **20%**.

**The deviation** is the difference: 20% − 30% = **−10%**. Since the threshold is ±5%, this combination would be flagged.

The tool does this calculation for every customer of every Material in every Sub Region in your data — and reports back which ones look wrong, by how much, and how many Kg are at stake.

---

## The five reason codes

Not every problem is a mix-drift problem. The tool classifies each Material × Customer combination into one of five categories:

| Code | What it means | Why it matters |
|---|---|---|
| **OK** | Both history and forecast are non-zero, and the deviation is within ±5% | The forecast disaggregation looks right |
| **Mix Drift** | Both history and forecast are non-zero, but the deviation exceeds 5% | Customer's share of the forecast is materially different from their recent share — investigate |
| **Lost Forecast** | History is non-zero, forecast is zero | Customer was buying recently but the forecast gives them nothing — almost always an error |
| **New Demand** | History is zero, forecast is non-zero | New customer in the forecast — could be a genuine win or stale assumption |
| **No Activity** | Both history and forecast are zero | Dormant — not actionable |

Among these, **Lost Forecast** is usually the highest-priority issue because real demand exists but the forecast is missing it entirely.

---

## The validation grain — and why Sub Region matters

Here's an important point about how the tool's math works: **the comparison is done within each Sub Region**, not across them.

The "parent" of every comparison is `Material × Sub Region`. That means:

- For Customer A in **Europe**, the tool compares Customer A's history *vs all customers' history* in Europe for that Material.
- For Customer A in **North America**, the tool does a *separate* comparison against North America totals.

This is the right way to validate forecast disaggregation, because forecasts are typically generated at the Material × Sub Region level. Mixing customers across regions would compare apples to oranges. **A customer who gets 30% of a Material in Europe might get 5% of the same Material in Asia — and both can be correct.**

So when you use the tool, **the natural unit of analysis is one Sub Region at a time**. Apply a Sub Region filter, then look at which Material × Customer combinations within that region are violating the 5% threshold.

---

## Tab-by-tab walkthrough

### 📊 Tab 1: Dashboard

**What this tab is for:** A one-look overview of the health of the entire forecast — and a quick way to focus on a specific Business Line or Sub Region.

**What you see at the top:** Five scorecards showing the count of Material × Customer combinations in each reason code. If there are 4,245 Mix Drifts and 568 Lost Forecasts in your data, those numbers tell you the size of the problem before you've even looked at any details.

**What the filters do:** Below the scorecards, there are two filters — Business Line and Sub Region. When you apply them, the **entire dashboard recalculates within the filter scope**:

- The five scorecards update to count only combinations in your selected scope
- The Flag Distribution chart (left) reflects only the filtered combinations
- The Forecast Volume by Flag chart (right) shows only the filtered forecast volume
- The Top 20 violators list narrows to only that scope

**Best practice:** Pick one Sub Region at a time (e.g. just "Europe") and look at the dashboard. The numbers you see now answer "How healthy is my Europe forecast disaggregation?" — which is exactly what a planner needs to know.

**The two charts in the middle:**

- **Flag Distribution** — counts of combinations by flag. Tells you "how many issues are there?"
- **Forecast Volume by Flag** — Kg of forecast volume that sits inside each flag. Tells you "how much volume is at stake?"

These two together answer different questions. You might have only 100 Mix Drift combinations but they hold 50% of your forecast volume — those 100 are far more important than 10,000 No Activity combinations.

**The interpretation panel ("🎯 What this tells you"):** Underneath the charts, the tool generates plain-English observations specific to your filtered data. For example: *"568 customer-material combos have recent sales but ZERO forecast — that's 12,234,890 Kg of recent history (8% of total) currently unallocated. These should be your first investigation."* The text changes as you apply filters, so it always describes the slice you're looking at.

**The Top 20 violators table:** Shows the 20 Material × Customer combinations with the biggest issues, sortable two ways:
- **By Kg Impact** — the volume of misallocation, in Kg. Best for "where is the most money at stake?"
- **By |Mix Deviation|** — the size of the mix shift in percentage points. Best for "which combinations have the most extreme mix mismatch?"

---

### 🔍 Tab 2: Validation Detail

**What this tab is for:** The full filterable worklist. This is where a planner spends most of their time once they've decided which scope to investigate.

**What's being compared on this tab:** Each row is a **Material × Sub Region × Customer** combination. The tool shows:

- Recent Hist (Kg) — that customer's history in that Material × Sub Region over the last 6 months
- Forecast (Kg) — that customer's forecast in that Material × Sub Region over the next 24 months
- Recent Mix % — customer's share of total Material × Sub Region history
- Forecast Mix % — customer's share of total Material × Sub Region forecast
- Mix Deviation — the difference between the two
- Kg Impact — the size of the misallocation in Kg
- Flag — the reason code

**The five filters at the top of this tab cascade like Excel slicers.** That means: when you select a Business Line, the Sub Region dropdown only shows Sub Regions that exist for that Business Line; when you also select a Material, the Customer dropdown narrows to customers that exist for that Material in that Business Line, and so on.

**Recommended workflow on this tab:**

1. **Start with the Sub Region filter.** Pick one Sub Region (e.g. Europe). This is the "fixed" boundary of your analysis — exactly the best practice you've described.
2. **Filter by Flag** — start with "Lost Forecast" (highest priority), then "Mix Drift", then "New Demand". Skip "No Activity" and "OK" unless you have a specific reason.
3. **Sort by Kg Impact** (click the column header) so the biggest issues come to the top.
4. **Drill into the top items** — open them in the Drill-In tab to see the underlying monthly pattern.

You can download whatever you've filtered as a CSV for offline review.

---

### 📦 Tab 3: Mat × Cust Rollup

**What this tab is for:** A view that combines all Sub Regions for the same Material × Customer pair — answering the question *"across all the Sub Regions where Customer A buys Material X, is the forecast mix consistent with history?"*

**The key difference from Tab 2:** Here, the "parent" is the **Material total across all Sub Regions**, not the Material × Sub Region. So Recent Mix % is the customer's share of *global* Material X recent sales (across every Sub Region combined).

**When this tab is genuinely useful:**

- Account-level conversations with large customers who buy across multiple regions — you want a single number for "Customer A's share of Material X" rather than four separate numbers for four regions.
- Spotting customers who are over-weight or under-weight at the global Material level even if each individual Sub Region looks fine.

**When to use Tab 2 instead:**

- Almost always for forecast-quality validation, because the forecast is generated at the Sub Region level. A 30% share in Europe and 5% share in North America will average out at the global level and might look reasonable, even if both regions individually have issues.

The Mat × Cust Rollup tab uses the same cascading filter approach, just with fewer columns (Material, Customer, Flag).

---

### 🎯 Tab 4: Drill-In

**What this tab is for:** Investigating a specific Material × Customer in depth — the "what's actually going on with this one?" view.

**How to use it:** Apply the four cascading filters (Business Line → Sub Region → Material → Customer) to narrow down to one specific Material × Customer pair. Then the tab shows:

1. **Top scorecards** — the rolled-up flag, recent Kg, forecast Kg, recent mix %, forecast mix % for the whole Material × Customer (across all the customer's Sub Regions).
2. **Sub Region breakdown table** — same metrics but split by Sub Region. This is where you see "Customer A is 30% in Europe but 5% in North America" — so a global-level number wouldn't tell the whole story.
3. **Monthly time-series chart** — the actual Kg per month per Sub Region, with history shown as solid lines and forecast as dashed lines, separated by a vertical "History | Forecast" boundary. This is where you see whether the forecast curve is following the recent trend or doing something different.

**When to come here:** After you've identified a problem case in the Validation Detail or Top 20, this is where you confirm what's going on month-by-month and decide what to do about it.

---

### 💾 Tab 5: Export

**What this tab is for:** Getting the analysis out of the app and into Excel or CSV for sharing or further analysis.

You can download:

- **Excel report (.xlsx)** — a multi-sheet workbook containing a Summary, the Validation Detail, the Mat × Cust Rollup, and the Settings used. This is the format to share with a manager or another planner.
- **Validation Detail CSV** — just the per-Sub Region grain table.
- **Mat × Cust Rollup CSV** — just the rollup table.

The Excel export is a snapshot of the *current settings*, so if you've changed the threshold or window in the sidebar, the export reflects that.

---

### 📖 Tab 6: Instructions

**What this tab is for:** The methodology and reason-code reference, embedded in the app itself so a new user can find it quickly. Same content, more compact format than this guide.

---

## What changes when filters are applied?

This is one of the most common questions, so worth being explicit:

**On the Dashboard tab:** Filters recompute the rollup *within the scope*. So if you filter to "Europe", the Recent Mix % for Customer A is recalculated as Customer A's share of Material X **in Europe only** — the rest of the world is excluded from the math. Like an Excel pivot table.

**On the Validation Detail tab:** The math doesn't change (each row is already at Material × Sub Region × Customer grain) — filters just hide rows that don't match. The mix percentages on each row stay the same regardless of filters.

**On the Mat × Cust Rollup tab:** Same as Validation Detail — the math is fixed, filters just hide rows. The mix percentages here are always at the global Material level.

**On the Drill-In tab:** Filters narrow the candidate Material × Customer combinations until you've selected one to drill into.

**Practical implication:** If you want to know "what is Customer A's share of Material X in Europe specifically?", use the **Validation Detail tab** with a Sub Region = Europe filter — the row already shows that exact number. If you use the Dashboard with the same filter, it'll match. If you use the Mat × Cust Rollup tab, you'll see Customer A's *global* share, which is a different question.

---

# User Manual — Step-by-Step

## Setup (one-time)

1. **Install the app.** Unzip the deliverable and open a terminal in the folder. Run:
   ```
   pip install -r requirements.txt
   streamlit run app.py
   ```
   The app will open in your browser at `http://localhost:8501`.

2. **Have your data ready.** Your Excel file needs these 8 columns:
   - Business Line
   - Detail
   - Material
   - Ship To Sub Region
   - Parent Cust
   - Month (date)
   - Sales History(Kg)
   - Statistical Forecast(Kg)

   One row per (Detail, Month). For history months, Sales History should have a value. For future months, only Statistical Forecast.

---

## Daily / Weekly Review Workflow

Once your data is uploaded, here's a recommended pattern for using the tool:

### Step 1 — Get the lay of the land (Dashboard tab, no filters)

Open the Dashboard. Read the five scorecards across the top. You're answering: *"What's the overall scale of disaggregation issues right now?"*

If you see something like:
- 4,245 Mix Drift
- 568 Lost Forecast
- 396 New Demand

…then you know you have real work to do. If everything is in single digits, your forecast disaggregation is in good shape.

### Step 2 — Pick a region to focus on (Dashboard tab, with Sub Region filter)

Apply a **Sub Region filter** — pick one (e.g. Europe). This is the best-practice unit of analysis because forecasts are generated at the Sub Region level.

The dashboard recomputes for Europe only. Now read:
- The scorecards (how many issues in Europe?)
- The Forecast Volume by Flag chart (how much Kg of Europe forecast sits in each problem category?)
- The interpretation panel (it now describes the Europe slice specifically)

### Step 3 — Add a Business Line filter if you own a specific BL

If you're responsible for "Cleaning" (or any specific Business Line), add the BL filter. The dashboard now shows your slice.

### Step 4 — Identify the worst offenders (Top 20 on the Dashboard)

Scroll down to the Top 20 violators on the Dashboard. Sort by **Kg Impact**.

These 20 are your starting worklist for this region/BL. The biggest Kg impact issues are typically where the planner can recover the most volume.

### Step 5 — Investigate (Drill-In tab)

For each item in your worklist, go to the **Drill-In tab**. Use the cascading filters to land on that exact Material × Customer.

Look at:
- The Sub Region breakdown — is the issue concentrated in one Sub Region or spread across several?
- The monthly chart — does the recent history show a clear trend (up, down, flat)? Does the forecast follow it or diverge?

This is where you decide what to do — adjust the forecast, ignore (false positive), or escalate to the customer team.

### Step 6 — Build a worklist (Validation Detail tab)

For comprehensive review (not just top 20), use the **Validation Detail tab**:

1. Apply the same Sub Region filter you've been using
2. Filter by **Flag = Lost Forecast** first — these are usually the most severe issues
3. Sort by Kg Impact descending
4. Work through the top items

Then repeat for Flag = Mix Drift and Flag = New Demand.

### Step 7 — Share / archive (Export tab)

When you've done a review, go to the **Export tab** and download the Excel report. This becomes your record of what was reviewed, with the settings at that point in time. Save it with a date so you can compare reviews over time.

---

## Settings — when to change them

In the sidebar, you can change:

- **Recent History Window** — default 6 months. Lengthen if your business has very long sales cycles or strong seasonality you want to smooth over. Shorten if you've had a recent disruption (like a major customer change) that you want the analysis to reflect quickly.
- **Forecast Horizon** — default 24 months. Match this to the planning horizon you actually care about. If you only care about the next 12 months for a particular review, set it to 12.
- **Deviation Threshold** — default 5%. Tighter (e.g. 3%) means more combinations get flagged as Mix Drift. Looser (e.g. 10%) means only big mix shifts get flagged.

Settings apply globally across all tabs. Changing them recomputes everything — give it a few seconds for big files.

---

## Tips and gotchas

- **Always pin Sub Region first.** This is the natural boundary of forecast disaggregation. Cross-region averages can hide real region-specific problems.
- **Lost Forecast = your first call.** It almost always means real demand that has no allocated forecast — and that's a planner-fixable issue.
- **No Activity is noise.** A combination with zero history AND zero forecast isn't actionable. The tool excludes it from the Top 20 by default.
- **Mix Drift in tiny Materials can look scary on percentage terms but trivial in Kg.** Always check the Kg Impact number alongside the % deviation.
- **A "New Demand" flag isn't necessarily wrong.** It just means the forecast contains a customer with no recent sales. That can be a genuine new win — but it's worth verifying with the account team.
- **Removing the file resets everything.** Click the × next to the uploaded filename in the sidebar to clear all data and start fresh with a different file.

---

## Quick reference: what to ask, where to look

| If you want to know... | Go to this tab | Apply these filters |
|---|---|---|
| How healthy is my forecast overall? | Dashboard | None |
| How healthy is forecast for Europe? | Dashboard | Sub Region = Europe |
| What are the top 20 worst issues in Europe? | Dashboard | Sub Region = Europe, scroll down |
| What's wrong with Customer A's forecast for Material X? | Drill-In | All four filters |
| Show me every Lost Forecast issue in Europe | Validation Detail | Sub Region = Europe, Flag = Lost Forecast |
| What's Customer A's global share of Material X? | Mat × Cust Rollup | Search Material = X, Customer = A |
| Give me an Excel report I can email | Export | Whatever filters were applied don't matter; export contains the full data |
