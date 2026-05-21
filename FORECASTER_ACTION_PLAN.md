# Forecaster's Action Plan — From Detection to Correction

## Where the tool ends and your job begins

The validator finds *where* the forecast disaggregation looks wrong. It can't tell you *why* it's wrong, and it can't fix it for you. That's the forecaster's job.

This guide is about what to do once the tool has flagged a combination. Not every flag means "go change the forecast." Some mean "talk to someone first." Some mean "check the data, not the forecast." Some genuinely do mean "edit the number." Knowing which is which is the skill.

## Three things to remember before you correct anything

**1. Disaggregation, not generation.** You typically don't change the *total* Material × Sub Region forecast — that's the output of the statistical engine and reflects aggregate demand. What you change is **how that total gets split across customers**. So your levers are usually about adjusting the *split ratios*, not the *headline number*.

**2. The split is driven by a historical profile.** Most forecast engines disaggregate by computing each customer's historical share over some lookback window (often 12 months) and applying that ratio to the future. A flag in this tool almost always means *the profile being used is no longer representative of current demand*.

**3. You should distinguish three types of action:**
   - **Correct in your model** — adjust a profile, override a value, exclude an outlier.
   - **Escalate / consult** — talk to commercial, account manager, master data team.
   - **Accept** — confirm the flag is a true positive but the current forecast is actually right (rare, but happens).

---

## Action plans by reason code

### 🚨 Lost Forecast — recent history > 0, forecast = 0

**What it means in business terms:** The customer was actively buying this Material recently, but the forecast gives them zero volume for the next 24 months. This is almost never intentional.

**Why this typically happens:**
- The disaggregation profile was built on a longer historical window that excluded recent purchases (e.g. customer was dormant, then reactivated)
- The customer was recently moved to a different Parent Cust or merged in master data, leaving the old account empty in the forecast
- A manual zero override was applied at some point and never reverted
- The customer's history was flagged as outliers and excluded from the profile build
- Customer-Material relationship was severed in the planning system but not in the order book

**Diagnostic questions before you act:**
1. Look at the monthly chart in the Drill-In tab. Is this a steady recent buyer or a one-off purchase?
2. Is the customer still active in your sales / order management systems?
3. Is there a known commercial reason — contract ended, customer switched supplier, product discontinued for them?

**Action by scenario:**

| Scenario | What to do |
|---|---|
| Customer is still active, no commercial reason for stop | **Recompute disaggregation using a shorter window (3 or 6 months)** so recent purchases are reflected. Re-run the forecast for that Material × Sub Region. |
| Customer was dormant, reactivated in last few months | **Manual override** — put a baseline forecast in for the customer matching their recent monthly average. Document why. |
| Customer recently moved Parent Cust in master data | **Master data fix first** — get the historical sales mapped to the new Parent Cust, then rebuild the profile. Don't manually override; that creates an audit nightmare. |
| Account/sales team confirms customer has stopped buying | **Accept the zero forecast.** Add a note to the audit trail explaining why this was confirmed correct. |
| Outlier exclusion accidentally zeroed the customer | **Review the outlier rules** for that profile. Reinstate the customer's history. |

**Priority ranking within Lost Forecast bucket:**

Sort by Kg Impact descending. The top items are where the most volume is at stake. If a Lost Forecast row has 50,000 Kg of recent history, that's 50,000 Kg of volume that will be unallocated unless you fix it — and that's volume your supply chain isn't planning for.

**Don't:**
- Mass-override hundreds of Lost Forecast rows by hand. If you have many, the disaggregation profile is broken — fix that, don't paper over it.
- Skip the master data check. Many "Lost Forecast" cases are master data drift in disguise.

---

### ⚠️ Mix Drift — both > 0, deviation exceeds 5%

**What it means:** The customer is buying, the forecast has them buying, but their *share* of the total has shifted significantly. The forecast is using stale proportions.

**Why this typically happens:**
- A different customer's share has grown or shrunk recently, displacing this one in the mix
- One-off bulk orders in history are still influencing the profile
- A long historical window is averaging across an old period that no longer reflects current relationships
- Promotional activity, product launches, or supply allocations changed the mix temporarily and the profile hasn't caught up

**Diagnostic questions before you act:**
1. Is the deviation positive (forecast over-allocates) or negative (forecast under-allocates)?
2. In the Drill-In monthly chart, does the recent history show a sustained trend or a single spike?
3. Has anything changed in the last 3-6 months that would explain the shift — a competitor lost, a contract won, a new ship-to point added?

**Action by sign of deviation:**

**Positive deviation (Forecast Mix > Recent Mix):** Forecast over-allocates to this customer.
- If recent history shows the customer's share genuinely declining → shorten the disaggregation window or apply more weight to recent months
- If a one-off bulk order in history inflated the customer's profile → exclude that month as an outlier in the profile build
- If a competing customer gained share → those Kg are likely missing from a different customer's forecast — check if Lost Forecast or under-allocated Mix Drift exists for the same Material × Sub Region

**Negative deviation (Forecast Mix < Recent Mix):** Forecast under-allocates.
- If recent history shows growing share → shorten the disaggregation window
- If the customer recently signed a contract or expanded → manually override to match expected share, document the reason
- If a different customer is over-forecast → the volume is misallocated, not missing — both rows need to be corrected together

**Action by magnitude:**

| Deviation size | Recommended action |
|---|---|
| 5% to 10% | Likely fixable by adjusting the lookback window. Try 3-month vs 12-month profile and pick the one that matches recent reality. |
| 10% to 25% | Investigate before correcting. Likely a structural shift (gained/lost business, mix change). May need manual override and commercial confirmation. |
| > 25% | Almost always requires escalation — either a commercial event has happened that's not yet in the system, or the profile method is fundamentally wrong for this Material. |

**Don't:**
- Trust a single month's history. A spike in March doesn't justify shifting 30% of the next 24 months' forecast. Ask: is this a trend or a blip?
- Fix mix drift in isolation. If Customer A's share dropped 10pp, that 10pp went somewhere — check the other customers in the same Material × Sub Region for the corresponding rise.

---

### 🆕 New Demand — recent history = 0, forecast > 0

**What it means:** The forecast is allocating volume to a customer who hasn't bought this Material in the last 6 months. Either it's a genuine new piece of business, or it's a stale assumption.

**Why this typically happens:**
- A new customer was won and someone added their forecast manually — legitimate
- The disaggregation profile is built on a 12+ month window, so customers who bought 9 months ago but not in the last 6 still get a forecast share
- A pipeline / opportunity was loaded into the forecast prematurely (deal not closed)
- A customer who used to buy and then stopped is still in the profile based on old data

**This is the one bucket where the forecaster usually can't decide alone.**

**Diagnostic questions before you act:**
1. Is there an open opportunity or signed contract for this customer-material in the CRM?
2. Did the customer buy this Material more than 6 months ago? (Check 12- or 24-month history in the Drill-In chart.)
3. Has the account manager been told to forecast this volume?

**Action by scenario:**

| Scenario | What to do |
|---|---|
| Confirmed new contract / opportunity | **Keep the forecast.** Add a note linking to the opportunity ID. Set a reminder to re-validate when actuals start coming in. |
| Customer bought 7-12 months ago, not since | **Trim or remove.** The profile is stale. Either shorten the disaggregation window or override the customer to a small "ramp-down" amount. |
| No commercial confirmation, no recent history | **Escalate to the account team.** Don't keep forecast volume on a customer no one can confirm is buying. |
| Speculative volume from sales team | **Confirm with commercial leadership** that this is committed before keeping it in the statistical forecast. Consider moving to a separate "uncommitted opportunities" bucket. |

**Priority within New Demand bucket:**

Sort by Forecast (Kg) descending. The biggest forecasted-but-unconfirmed customers are where the most volume risk sits. If you can't confirm the demand, the supply chain is going to over-build.

**Don't:**
- Keep New Demand rows in your forecast just because they were there last cycle. Re-validate them every review.
- Treat all New Demand as wrong. Genuine new wins are exactly what this category should contain.

---

### ✅ OK — both > 0, deviation within 5%

**What it means:** The disaggregation is consistent with recent history. No action needed.

**What to actually do:** Nothing — but don't ignore the OK bucket entirely.

**Once per quarter:** Spot-check 5-10 OK combinations to confirm the algorithm is making sensible decisions for the right reasons, not by accident. Look at:
- A few high-volume OK combinations (the workhorses of your forecast)
- A few OK combinations near the threshold (4.5% deviation) — they could flip to Mix Drift next cycle
- Any OK combination where you suspect something has changed but the math is still passing

This is your sanity check that the threshold is calibrated correctly. If many OK combinations are near 4.5%, your threshold may be too loose. If most OK combinations are near 0.5%, the threshold may be too tight.

---

### ℹ️ No Activity — both = 0

**What it means:** The customer has neither recent sales nor any forecast for this Material in this Sub Region. They're dormant or inactive in this combination.

**Action: usually none.** This bucket exists to be informative, not actionable. It tells you the size of the "long tail" of dormant Material × Customer combinations in your master data.

**When it does deserve attention:**
- If the No Activity count is very large (e.g. > 50% of all combinations), it suggests master data has many dormant customers that should be cleaned up. Talk to the master data owner about deactivating them.
- If a specific customer appears in many No Activity rows, they may have stopped buying entirely — flag this to the account team.
- If you're loading new customers into master data faster than they're being activated, this bucket grows over time. Periodic cleanup keeps the tool's signal clean.

---

## A weekly process — putting it all together

Here's a working cadence you can adopt:

### Monday — Detect (30-60 minutes)

1. Run the validator against your latest forecast snapshot
2. On the Dashboard tab, set Sub Region = your region
3. Read the scorecards. If the Lost Forecast or Mix Drift counts have grown materially since last week, that's your headline issue.
4. Read the interpretation panel. It will already point to the highest-impact bucket.
5. Export the worklist to Excel for the rest of the week's review.

### Tuesday — Triage Lost Forecast (1-2 hours)

1. On the Validation Detail tab, filter to Sub Region = your region, Flag = Lost Forecast
2. Sort by Kg Impact descending
3. For the top 10-20:
   - Check the customer's status in your sales/order system
   - Drill in to confirm the monthly pattern
   - Decide: profile fix, manual override, master data fix, or accept
4. Record actions in your audit log

### Wednesday — Triage Mix Drift (2-3 hours)

1. Filter to Flag = Mix Drift, sort by Kg Impact descending
2. Group by Material — if multiple customers within one Material × Sub Region show drift in opposite directions, treat them together (volume is being reallocated within the same parent total)
3. For each significant cluster:
   - Decide if a profile-window change fixes the bulk of them at once
   - Identify the few that need individual manual overrides
4. Re-run the disaggregation if you've changed window settings; revisit the same combinations

### Thursday — Triage New Demand & escalate (1-2 hours)

1. Filter to Flag = New Demand, sort by Forecast (Kg) descending
2. For each — pull the latest CRM/opportunity record
3. Send a weekly digest to the commercial team listing the New Demand combinations that need confirmation
4. Move unconfirmed volume to a separate "uncommitted" bucket if your forecast structure supports it

### Friday — Verify and document (30-60 minutes)

1. Re-run the validator against your now-corrected forecast
2. Confirm the Kg Impact in the issue buckets has dropped meaningfully
3. Export the new state and archive both Monday's and Friday's snapshots — this becomes your before/after record
4. Note any combinations you couldn't fix this week — they go into next week's queue

---

## A few rules of thumb

- **The 80/20 rule applies hard.** In most forecasts, the top 50 combinations by Kg Impact account for the majority of total misallocation. Fixing those gives you most of the benefit. Don't get bogged down in the long tail.

- **Always fix profiles before manual overrides.** A profile change fixes hundreds of combinations at once. A manual override fixes one. If you're manually overriding more than 10-15 combinations in a single review, you've found a profile-level problem masquerading as many small ones.

- **Document every override.** Your future self (or the next forecaster) needs to know *why* a number was changed. A line of comment per override is the minimum.

- **Don't chase OK combinations to perfection.** A 3% deviation that happens to be within threshold isn't worth your time. A 25% deviation with high Kg Impact is.

- **Look at the corresponding rise when you see a fall.** If Customer A's Forecast Mix dropped 10pp from their Recent Mix, those 10pp are sitting on someone else's row in the same Material × Sub Region. Find that row.

- **Weekly is better than monthly.** The cost of running this validator is small; the cost of letting bad disaggregation persist for a month is large. Frequent small corrections beat occasional big resets.

---

## When to call for help

Signs that the issue is bigger than what the forecaster can fix alone:

- Lost Forecast count has stayed roughly the same for 3+ weeks despite your interventions → escalate to the planning manager; the disaggregation method may need redesign
- Many Mix Drift combinations within one Business Line all point in the same direction → there's a systemic event (market shift, supply allocation) that needs a planning-wide response
- New Demand consistently shows up for customers that commercial teams disclaim → conversation with sales leadership about pipeline-vs-forecast discipline
- A specific Sub Region has a much higher issue rate than others → may indicate that region's master data or the local profile-building rules need a refresh

---

## Bottom line

The validator's job is to point. Yours is to act with judgment. Most flags resolve to one of three actions: **adjust the profile window**, **add a manual override with documentation**, or **escalate for confirmation before changing anything**. Knowing which action fits each flag — and which flags belong to which bucket — is the entire skill.

Detection without correction is reporting. Correction without detection is guesswork. The two together, run on a weekly cadence, are how forecast disaggregation stays trustworthy over time.
