# Adaptive Investment Engine

A modular Python foundation for Indian equity research and **paper-only** portfolio
accounting. The current implementation is locally tested; it is **not an accepted
production deployment**. See [PROJECT_STATUS.md](PROJECT_STATUS.md) for evidence and blockers,
and [the supplied requirements](docs/PROJECT_REQUIREMENTS.md) for the full delivery scope.

## Run locally

Prerequisites: Python 3.12, uv, Docker with Compose. No paid services are needed for local
checks. These commands start a local PostgreSQL container, generate a local-only password
in an ignored mode-0600 .env if none exists, install locked packages and apply migrations.
Existing .env contents are preserved. Use the existing checkout, not another worktree.

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
uv sync --frozen
uv run python scripts/bootstrap.py
uv run invest doctor
uv run invest report
uv run python scripts/check.py --postgres
uv run pytest -q
uv run python scripts/restore_drill.py
```

`invest init` is idempotent and creates ₹1,00,000 cash with the emergency stop active.
After verified archival inputs have been ingested, run an isolated research backtest with:

```sh
uv run invest backtest 2025-01-01 2026-10-31 operator-reviewed-archive var/backtest.json
```

It requires explicit exchange sessions and PIT observations; it never posts simulated backtest
trades into the paper account. Empty/invalid inputs block, and output is research-only.

`invest daily` currently exits **3 (blocked)** when the verified universe, fresh observations
or necessary action normalization are missing. That is expected in an unconnected setup.
It screens research opportunities; it does not dispatch trades. `invest health` also exits 3
when a required job/calendar is missing or failed. No live broker implementation exists.

## Modules and boundaries

- `models`, `migrations`: PostgreSQL schema, foreign keys, accounting checks, revisions.
- `data`, `reference`: replaceable source adapters, quota/cache/circuit state, OHLCV contracts,
  explicit operator-reviewed ISIN reconciliation and expiring index eligibility.
- `broker`: atomic, serialized, whole-share INR accounting, risk checks and idempotency.
- `features`, `events`: deterministic technical calculations, structured fact ratios,
  corporate-event taxonomy and evidence-validated qualitative review handoff.
- `backtest`, `research`, `rl`: isolated historical simulation, purged temporal folds,
  experimental ridge/LinUCB utilities and an untrained Gymnasium environment. No approved ML/RL.
- `operations`, `monitoring`, `backup`: blocked-job recording, provenance-preserving Parquet,
  non-destructive Sheets handoff, missed-job checks and authenticated backup encryption.

See [architecture](docs/ARCHITECTURE.md), [provider policy](docs/DATA_PROVIDERS.md),
[operations](docs/RUNBOOK.md) and [external setup](docs/EXTERNAL_SETUP.md).

## Data and execution

No constituent list, market history, provider entitlement, research result or model performance
is invented. Tests use explicitly synthetic fixtures. The user has selected Yahoo/yfinance for personal educational research; no exchange-licensed feed is claimed.
Yahoo access is opt-in and unofficial; Alpha Vantage coverage/entitlements must be established.
No broker order endpoint is called. Research-generated candidates are never labeled approved buys.

The 8% stock and 25% sector ceilings, cash sufficiency, verified eligibility, fresh execution
quotes, prior-session information and participation limits are independent of the policy.
Amounts are integer paise; fees/slippage are conservative **research assumptions**, not a
verified Indian statutory fee schedule. No intraday round trips, leverage, shorting or derivatives.
Synchronous execution has no pending orders and therefore zero reserved cash; asynchronous
order reservation/settlement must be implemented before adding a pending-order workflow.

Historical fundamentals/observations retain publication and actual receipt times. Strict
as-received backtests cannot pretend newly downloaded financial history was ingested years
ago. Historical price replay and model datasets require an explicit archival-data policy and
survivorship/availability review before any performance claim.

## Verified real-data connectivity probe

After the database is running, use:

```sh
uv run python scripts/check_yahoo.py
```

This fetches a small genuine INFY.NS sample through yfinance without an account or API key,
validates prices, checks the ISIN against the official NSE security master, stores bars in
PostgreSQL and writes a Parquet archive/manifest under ignored var/research/. It does not
make a recommendation, verify Shariah membership, assign a sector or place an order.
Any detected dividend ex-dates remain unresolved evidence and are never credited as cash.
The regular `invest ingest` command still uses the original direct-chart adapter and has
separate permission/reference gates; this small probe does not enable the scheduled pipeline.


## Interactive dashboard and workbook mirror

- `dashboard/index.html`: self-contained interactive research website. Download the file and
  open it in a modern browser; its stock explorer and workbook tabs need no server or sign-in.
- `data/workbook/workbook_snapshot.xlsx`: Excel copy of all ten published tabs plus provenance.
  It preserves displayed values, not the original Google formulas or full formatting.
- `data/workbook/current.json`: structured source snapshot with all rows and hashes.
- `data/workbook/published_source.zip`: original published HTML evidence for all source tabs.

The user authorized these workbook files in the private repository. Backend holdings/ledger
are not embedded or exported into Git. No public website or paid hosting was created.

Search/filter by company, ticker, industry or decision; switch Swing/Position/Long-Term;
inspect stock details; export filtered CSV; view every source tab. Existing Sheet heuristics
are explicitly distinguished from approved models and paper executions. The workbook capital
setting is INR 1000000; the separate backend paper account starts with INR 100000.

To refresh the mirror after the published Sheet updates:

```sh
uv run python scripts/refresh_dashboard.py
```

Or open GitHub **Actions → Refresh workbook dashboard → Run workflow**. This manual-only
workflow commits updated mirror files to main; it does not change Google Sheets, trade, or
train models. Download the latest HTML again after refreshing. No automatic refresh schedule
was activated. The page always shows its snapshot retrieval time.

To show current backend cash, holdings and simulated executions, run:

```sh
uv run python scripts/serve_dashboard.py
```

Then browse port 8765 on that machine (127.0.0.1). The server binds locally and exposes only
read endpoints. A standalone HTML copy has no backend connection and clearly says so. A
permanent hosted URL would require an appropriate hosting/authentication connection.

Validation: Python snapshot/parser/XLSX integrity tests and headless Chromium checks for
search, detail dialog, horizon/filter counts, workbook browsing, backend portfolio, mobile
layout, and the self-contained research page with network disabled. The managed browser
blocks direct file:// navigation; the offline HTML was tested using a fresh browser document
with network disabled instead. No public hosting or original-sheet write access is implied.


## Secure hosted-database connection check

Save the Supabase Session pooler URI only in GitHub's `paper` environment as the secret
`PAPER_DATABASE_URL`. Do not paste it into chat, repository files or workflow inputs.
Run **Actions → Check Supabase connection → Run workflow**. The manual-only job confirms
secret availability, normalizes the PostgreSQL driver, requires hostname/certificate-verified
TLS using the supplied, fingerprint-pinned Supabase CA certificate, and executes a read-only `SELECT 1` and session checks.
It never prints the connection URI/driver exception, creates tables, initializes an account
or places orders. Only safe success/failure categories are logged.

GitHub secret-listing permissions are not required: the job receives the environment secret
directly. A successful check establishes connectivity, not completion of database migrations,
data migration, hosted dashboard wiring or activation of research/trading schedules.

If password characters cause malformed URI parsing, download and open
`tools/supabase_connection_helper.html` locally. Enter the Session pooler User and existing
database password only in that local page, copy the correctly encoded URI into the GitHub
secret, clear the fields and close it. It has no network requests, no storage and no analytics.
Never send its generated URI or entered password through chat.


## Initialize the hosted paper database

GitHub **Actions → Initialize Supabase paper database → Run workflow** securely uses the
existing `paper` environment's `PAPER_DATABASE_URL` and pinned Supabase CA. This manual-only
workflow applies Alembic migrations inside the private `investment_engine` schema, initializes
the INR 100000 paper account with its emergency stop active, and verifies committed ledger state.

One transaction and an advisory lock cover schema creation, migrations, permission changes and
the opening deposit. A schema ownership marker and expected-table checks refuse unknown existing
data. Reruns preserve existing balances and never duplicate the initial deposit. An existing
account with its emergency stop turned off requires review rather than being reset automatically.

Row-level security is enabled; PUBLIC/anon/authenticated access is revoked and checked. Supabase
Auth/Storage/public tables are untouched. In Supabase Table Editor choose schema
`investment_engine`, then `accounts` or `ledger`. Money is stored in paise: 10000000 = INR 100000.
The internal Supabase role used for deployment owns these tables; dedicated least-privilege
runtime-role configuration remains a later deployment step.

Initialization does not transfer local price archives, connect the downloaded Atlas page to
Supabase, execute orders or activate schedules. Keep PAPER_PIPELINE_ENABLED unset until the
application runtime is wired to this schema and the verified TLS connection.


## Backend-powered Streamlit app and data automation

See [deployment instructions](docs/STREAMLIT_DEPLOYMENT.md). Entry point: `streamlit_app.py`.
Unlike the earlier downloadable workbook mirror, this app reads actual backend prices, features,
experimental forecasts and the paper ledger. It does not copy spreadsheet screening scores.

```sh
uv sync --frozen
uv run streamlit run streamlit_app.py
```

For hosted data, supply PAPER_DATABASE_URL and a separate DASHBOARD_ACCESS_PASSWORD only through
private runtime/Streamlit secrets. Supabase TLS and private schema routing are automatic; the
app's DB session is read-only. Without a hosted binding, local mode is clearly labelled.

GitHub **Market data pipeline** performs paced, incremental Yahoo ingestion after market hours
at 16:15 IST weekdays. Its manual options support initial five-year backfill and experimental
price-only candidate training. It never places orders or promotes models. Three consecutive
failures stop the batch; partial/failed jobs remain explicit. Data is stored in Supabase, not Git.
The initial reference universe is 203 compiled stocks with NSE-verified ISINs; index membership
and the 204-count discrepancy remain unverified.

Model research uses 20/60/120/250-session matured labels, chronological splits, purging and a
seven-calendar-day embargo. Scaling fits training data only. Fixed-alpha ridge is compared with
zero-return/cash and train-mean baselines on untouched test observations. Parameters, dataset/code
hashes, flags and forecasts are registered in PostgreSQL. These experiments explicitly retain
current-universe/retrospective-vintage limitations and have no promotion or execution authority.
