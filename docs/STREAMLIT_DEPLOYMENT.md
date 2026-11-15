# Deploy the backend-powered Atlas app

The Streamlit app reads Supabase prices, independently calculated features, experimental
predictions and the paper ledger. It does not substitute the Google Sheet's scores. The old
downloadable HTML remains a separate workbook mirror.

## Account actions the owner must perform

1. Sign in to https://share.streamlit.io/ and connect your GitHub account through the supported
   authorization flow. Stay on the free offering; do not purchase hosting.
2. Create an app from the existing **private** repository `kgmikhdad/portfolio`.
3. Select branch `main` and entry-point file `streamlit_app.py`. Choose Python **3.12** in
   Advanced settings where offered. Locked `uv.lock` and hashed runtime `requirements.txt`
   are included; the entry point can load the repository's src package directly.
4. In the app's **private Secrets editor**, enter:

   ```toml
   PAPER_DATABASE_URL = """your existing verified Supabase Session pooler URI"""
   DASHBOARD_ACCESS_PASSWORD = "a separate strong private dashboard password"
   ```

   Use the same working database URI already saved in GitHub, from your own secure record.
   GitHub does not let you read back a saved secret. Never paste either value into chat,
   source files, workflow inputs or a public page. This is not the Supabase anon/service-role key.
5. Keep viewer access private/restricted. If the free account does not offer the expected
   private-viewer setting, report the options before making portfolio data public. The app also
   requires its own access password before it reads the hosted database.
6. Deploy, then open the app and enter only the **dashboard access password** on its login page.
   Share the app URL with the assistant, never the password or database URI.

The agent cannot complete the hosting-account authorization or enter owner-held secrets using
the tools currently exposed. GitHub Actions has the DB binding; Streamlit requires its own
secure binding. Connecting GitHub to a service does not automatically copy GitHub secrets.

## What the app shows

- Research: 20/60/120/250-session price momentum and liquidity, calculated from stored Yahoo
  observations. Missing historical windows stay missing. No trained-model approval is implied.
- Paper portfolio: actual persistent cash, holdings, fees and simulated executions. No trade buttons.
- Prices: stored five-year historical series where Yahoo supplies it, including source/basis notes.
- Models: genuine experimental price-only ridge models when manually trained. Holdout metrics,
  bias flags and dataset lineage are visible. These are not approved ML/RL trading policies.
- Operations: last ingestion job, failures, reference provenance and current coverage.

The app automatically refreshes its main read view every five minutes while open, with
five-minute read/chart caches. This limits unnecessary Supabase queries and egress. Refresh database
view clears the read cache. It does not download or train the universe when someone opens a page.
Supabase connections enforce the uploaded CA, hostname verification, the private application
schema and read-only sessions. No browser receives the DB credential.

## Automation and cost boundaries

The **Market data pipeline** runs at **16:15 Asia/Kolkata on weekdays** and supports manual
dispatch. Schedules are best-effort; a 20-minute job timeout limits any one run. Initial
five-year ingestion may be slower; subsequent jobs fetch an overlapping incremental window,
with coherent history refreshes when corporate actions require it. Three consecutive ingestion
failures open a circuit; affected data is not fabricated. Completed per-stock work is retained. Incremental reruns skip recently completed stocks
when a new market close could not have arrived; post-close weekday runs recheck older sessions.
A previous timed-out run is marked interrupted, rather than successful.

Manual dispatch options: backfill (five-year refresh), train_models (experimental candidates),
symbol_limit (diagnostics; zero means all 203 reference securities). Nightly training is disabled.
Daily inference refreshes experimental forecasts using fixed candidate parameters; it does
not retrain or promote models. Input hashes make repeated inference idempotent.
No order execution or live brokerage is scheduled. Keep the older PAPER_PIPELINE_ENABLED unset.

At the maximum 20-minute timeout, 23 weekday runs would be 460 minutes before CI/manual work.
Actual time is expected to be lower but must be measured. This is not a billing guarantee;
other account usage/storage and future plan rates also matter. The user's displayed $0.14 gross
usage was covered by $0.14 included discounts, with $0 billable. Use the account's budget controls
to stop paid overage. No paid service or financial commitment was created by this setup.

## Known research limits

All 203 workbook tickers have NSE-master ISINs. HFCL is BE (delivery-only). The official
October 30 factsheet reports 204 constituents; that count alone does not identify a missing
security in a November 13 compiled list. Current/historical index eligibility remains unverified.
Industry labels come from the source workbook, not an approved sector classification.

Yahoo OHLC is split-adjusted and adjusted close also reflects dividends. The engine does not
apply split adjustments a second time. Historical data was actually received at ingestion time;
retrospective model experiments explicitly flag vendor revisions/current-universe survivorship.
Price-only forecasts cannot replace fundamental long-term research. Fundamental/event ingestion,
licensed TRI comparisons, complete action entitlements, approved strategies, RL training and
prospective paper validation remain future work. No model is automatically promoted.
