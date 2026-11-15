# Project status — 2026-11-15

**Overall: foundation tested locally and in GitHub CI; one real-data source verified; other integrations pending. Production acceptance
has NOT been met. No real-money execution, approved predictive model or validated profitable
strategy exists.** Full scope: [requirements](docs/PROJECT_REQUIREMENTS.md).

## Milestone evidence

- Python 3.12.14 environment installed with a committed uv lockfile.
- Local PostgreSQL 17 Docker service healthy; two Alembic migrations applied. `alembic check`
  reports no ungenerated schema changes. A ₹1,00,000 cash-only paper account is persistent,
  with emergency stop active and zero orders. Real-money interface always raises.
- `uv run python scripts/check.py --postgres`: lint, format, strict mypy pass; **42 tests pass**.
  Tests cover concurrent duplicate orders, transaction rollback, no negative cash/shorting,
  8% stock / 25% sector limits, participation, stale/future prices, eligibility, fees/basis,
  P&L/NAV reconciliation, splits, PIT revisions, purging, deterministic backtests, research
  gates, event failure isolation, reference integrity, encryption and provider failure controls.
- Gymnasium environment contract passes on synthetic data. Its intentionally unbounded Box
  observation space produces two checker warnings; no policy was trained or approved.
- SQLite portability suite: 42 tests pass (same synthetic fixtures; not 84 distinct tests).
- Dependency audit after upgrading cryptography to 50.0.2: no known vulnerabilities found.
  Source and initial full Git-history scans: no leaks found.
- Encrypted PostgreSQL backup restored into a separate temporary database; account, ledger,
  order, price counts and schema revision match. Drill database removed; source unchanged.
  Backup/key remain ignored local artifacts. No Google Drive backup upload performed.
- Operational `invest daily` exits 3 and persists a blocked job because the security master
  lacks verified membership/calendar. No orders are executed. This is a verified failure state, not successful research.

All market, calendar and index inputs in automated tests are **synthetic test fixtures**.
Verified genuine market coverage: **one security (INFY.NS), 22 daily price rows**
from yfinance; ISIN independently reconciled against the official NSE equity master.
Latest sample session: 2026-11-13. This does not verify Shariah eligibility or a recommendation. The 203/204 membership
reconciliation is unresolved; no stock has been guessed or silently marked eligible.

## Release tracker

| Release | Current state | Implemented | Remaining acceptance work |
|---|---|---|---|
| 1 Operational foundation | Tested locally; partial | Package/lock, migrations, persistent ledger, risk controls, CLI, source adapters, CI and opt-in schedule definitions | Verify private GitHub, remote CI, persistent hosted DB, genuine authorized ingestion, operational scheduling |
| 2 Research data | Partial; integration blocked | ISIN validation/import, expiring memberships, receipt/publication revisions, hashes, Parquet, taxonomy, split accounting | Official calendars/history/universe, corporate-disclosure parsers, complete actions/dividend entitlement, source licences/coverage |
| 3 Baseline strategy | Tested on synthetic fixtures; partial | Technical features, selected fundamental ratios, momentum simulation, costs/cash/constraints, summary metrics | Complete feature library, realistic fee schedule/settlement, archived historical eligibility, TRI/passive/Sheet baselines, uncertainty/attribution |
| 4 Adaptive ML | Experimental utilities tested | Purged/embargoed folds, ridge ranking, lineage schema and promotion gate | Real horizon targets, calibrated uncertainty, conditional factor weighting, ablations, trained models, independent OOS/prospective evaluation |
| 5 RL | Experimental utilities tested | LinUCB with cash arm and Gymnasium environment using independent risk engine | Appropriate research dataset, full state, candidate-policy training/comparisons, robustness and promotion evidence |
| 6 Qualitative Work research | Partial; account capability blocked | Versioned evidence JSON schema, taxonomy/triage, reviewed ingestion gate | Official filing collection, durable authorized handoff, manual integration test, supported recurring Work task |
| 7 Operations/dashboard | Partial; external integration blocked | Job failure recording, health checks, local encrypted restore, non-destructive Sheets client | Google authorization, verified original backup, dashboard views, remote backup retention, hosted monitoring/alerts |
| 8 Production acceptance | Blocked | Local accounting/concurrency/data-failure/restore checks | Genuine end-to-end pipeline, CI/remote scheduler evidence, security/role hardening and all external acceptance criteria |

## Capability/access record

- Existing repository: `kgmikhdad/portfolio`, initially empty; no source files/user changes
  were overwritten. Git read works through the platform's HTTPS proxy.
- GitHub API request to repository metadata returned Forbidden. An injected GH_TOKEN variable
  is present, but its value was never inspected. API access, privacy and Actions status are
  unverified; a missing token has not been inferred.
- No connected Google Drive/Sheets or Work scheduling tools are exposed. Desktop capability
  is declared, but no desktop/browser-control tool is exposed in this session.
- Google Sheet and provider HTTP requests failed at the CONNECT proxy (403), before content
  retrieval. The workbook has not been inspected, backed up or modified.
- Draft network additions saved for GitHub API, Google APIs/Docs, Yahoo, Alpha Vantage,
  Nifty/NSE/BSE and selected flow/regulatory hosts. Package-manager presets preserved.
  Draft saving does not apply/publish access; retest after settings are saved and published.

## GitHub delivery and schedules

Initial foundation commit: [dc584b6bdca7b094a59fb87a768c15d5c8759efa](https://github.com/kgmikhdad/portfolio/commit/dc584b6bdca7b094a59fb87a768c15d5c8759efa),
pushed to `main` and independently verified using `git ls-remote`. Follow-up implementation
adds verified after-market timing, successful/repeatable screening checks and a CLI for isolated
backtests; see branch history for its exact commit. Both GitHub workflow definitions pass
`actionlint` 1.7.7 locally. Remote CI execution remains unverified because the API is blocked.
Repeated bootstrap preserved the local database/account and active emergency stop. A second
encrypted restore drill also passed after the crypto upgrade. Required `install_script` and
`start_skill` were saved in the environment draft, along with network additions; publication
and fresh-task restoration remain unverified.

The cron is 16:00 IST weekdays; the job is disabled unless PAPER_PIPELINE_ENABLED is true.
It performs research only, requires an explicit persistent database secret, and cannot trade.

## External action checklist and next executable step

See [precise setup instructions](docs/EXTERNAL_SETUP.md). First review/save the network draft
in environment settings and publish. Then retest existing GitHub/Google/provider access,
confirm repository privacy, back up/inspect the existing workbook through authorized Google
access, obtain the authoritative dated universe/calendar and verify permitted market data.
Use an existing authorized PostgreSQL service for deployment; none was purchased/created.
Do not paste credentials into chat or enable the scheduled pipeline before manual verification.

Spending: no paid service was purchased and no financial commitment was created. Existing
cloud compute billing is not visible. Free-tier eligibility and ongoing production cost have
not been established.


## Latest connectivity verification (after billing repair and publication)

- Repository confirmed private using GitHub API. GitHub API read/write access now works.
- Manually dispatched **Tests and security** passed on GitHub:
  https://github.com/kgmikhdad/portfolio/actions/runs/43685920977 . The billing lock no longer
  prevents workflow startup. This verifies CI, not the scheduled research/trading pipeline.
- yfinance 1.8.0 fetched 22 genuine daily INR records for INFY.NS with no Yahoo account/API key.
  `uv run python scripts/check_yahoo.py` reproduces the research probe, validates OHLCV, checks
  symbol/currency, reconciles ISIN against official NSE EQUITY_L.csv and persists data in the
  existing PostgreSQL database. Source CSV, Parquet and manifest stay in ignored var/research/.
  No index membership, sector classification or investment recommendation is inferred.
- The sample contains one dividend ex-date, stored as unresolved corporate-action evidence.
  No dividend cash is credited and no trade is placed. Complete action reconciliation is pending.
- Yahoo's cookie helper endpoint is still unreachable; the library reports that limitation and
  successfully uses its normal available path. No proxy restriction or TLS check was bypassed.
- Existing local PostgreSQL container was stopped after the environment restart. It was restarted
  using its original volume; its portfolio data was preserved, not reinitialized.
- Official NSE security master and Nifty Indices index page are reachable now. The universe
  constituent list/calendar and the 203/204 discrepancy still require investigation.
- Existing Google workbook returns HTTP 401 without Google authorization. The Spreadsheets tag
  is present in chat but provides no callable tools to this agent. The configured Google credential
  file contains no usable credential fields. No workbook content was read or modified.
- No API key is required for this Yahoo research path. Do not add Alpha Vantage credentials
  just to fetch the same prices. Next external step: make authorized Spreadsheets tools available
  for the designated workbook. No environment draft changes were reapplied or published.

Earlier connectivity notes above describe the initial setup and are superseded by this section.


## Workbook mirror and interactive dashboard

The user explicitly authorized saving the published workbook in GitHub and creating an
interactive dashboard. All ten published tabs and 203 source signal records were fetched
and mirrored in data/workbook/ as XLSX (display values), JSON and zipped original HTML.
The source Sheet was not modified; its formulas are not available in the published export.

`dashboard/index.html` contains a complete, self-contained research UI with horizon selection,
search/industry/decision filters, stock details, CSV export, source-tab browsing, and provenance.
These are the existing Sheet's heuristic signals, not new trained-model recommendations.
Its source snapshot shows 40 Position buy candidates, 20 Watch, and 203 missing fundamentals.
Backend holdings/executions are accessed only via a local read-only server, never embedded in
the committed dashboard. The user-authorized workbook mirror exception is documented in AGENTS.md.

Local PostgreSQL suite now passes **46 tests**, with lint/format and strict mypy passing.
The Excel copy was reopened and checked against every source tab. Formula-like cell values
are written as text. The dashboard uses textContent for source values and escapes embedded
JSON to prevent source text becoming executable HTML. Refresh workflow passes actionlint.
Dependency audit reports no known vulnerabilities. Headless browser validation covers desktop
and mobile, 203 rows, source candidate counts, missing-fundamental handling, details, workbook
tabs, backend account and network-disabled research browsing. Direct file:// navigation is
blocked by the managed browser policy; no attempt was made to bypass it.

Use the manual GitHub workflow **Refresh workbook dashboard** to fetch/commit updates. It has
no cron and does not run training, trades or Sheet writes. A locally running dashboard server
is available for this session on port 8765. No publicly hosted website or paid service was
created; the downloadable HTML is the portable interactive dashboard.


## Supabase connection verification

The user saved PAPER_DATABASE_URL in GitHub's paper environment. GitHub's secret-listing
API is denied to this integration; a manual Actions job securely received the binding instead.
The read-only check confirms **secret_present: true**, but connection is **blocked** with safe
reason `database_hostname_not_resolved`. No successful database connection, TLS session, schema
migration or hosted account initialization is claimed. No database writes or trades occurred.

Read-only checker: src/investment_engine/hosted_database.py and scripts/check_supabase.py.
It accepts a Supabase PostgreSQL URI, normalizes the psycopg driver, enforces verify-full TLS
and system CA trust, and performs only read-only queries. Driver exceptions/URIs are never
printed; safe status annotations remain accessible even when Actions log downloads are denied.

Evidence: https://github.com/kgmikhdad/portfolio/actions/runs/43689941574 .
The safe annotation confirms the binding and DNS blocker; it does not establish a bad password.
Next external information needed: the non-secret Host field from Supabase Connect → Session
pooler, plus confirmation the project is running. Never paste the whole connection URI or
password into chat. After diagnosis/correction, rerun Check Supabase connection.

Local lint/format/type checks and all **55 tests** pass, including nine new credential-safe
configuration/diagnostic tests. The manual connection-check workflow passes actionlint.
The production scheduler and local database configuration remain unchanged.


### Supabase endpoint-format diagnosis

User supplied the non-secret Session pooler Host aws-0-ap-south-1.pooler.supabase.com.
Local DNS is unavailable even for GitHub, so local resolver failure is not evidence against
this Supabase host. A further GitHub Actions check validates the parsed URI host before any
network request. It reports `secret_present: true` and
`invalid_database_hostname_check_password_encoding`. This supersedes the earlier generic
DNS error: the saved URI is being parsed with reserved/invalid characters in the host.
An unencoded password delimiter is one possible cause; actual credentials were not inspected.

Evidence: https://github.com/kgmikhdad/portfolio/actions/runs/43692598668 .
The user must replace the URI securely with a correctly assembled/encoded Session pooler URI.
The provided tools/supabase_connection_helper.html builds it entirely in the owner's browser,
with network access prohibited by CSP. It never stores/transmits credentials. A headless browser
check verified special-character encoding, clearing fields, and zero network requests using
only dummy inputs. No real user password was entered into agent tools.

The connection checker now rejects malformed hosts before DNS, and can report only boolean
endpoint comparisons. Local lint/type checks and **57 tests** pass. No schema/trade changes.


### Supabase recheck after user corrected the secret

Run https://github.com/kgmikhdad/portfolio/actions/runs/43693252962 confirms the saved URI
now parses, its host matches the supplied Session pooler host, and both expected/saved
hostnames resolve from GitHub. The remaining error is `tls_certificate_verification_failed`.
Database authentication has not yet been verified because TLS fails first. No schema/data
changes or trades occurred. The helper is not needed for further troubleshooting.

Official Supabase documentation says verified TLS requires downloading the server root
certificate from Database settings → SSL Configuration and supplying it as sslrootcert
with verify-full. Current system-trust verification is insufficient for this connection.
Next external prerequisite: the public CA certificate downloaded from the user's authenticated
Supabase dashboard; no password, private key or connection URI needs to be shared.
Reference: https://github.com/supabase/supabase/blob/master/apps/docs/content/guides/platform/ssl-enforcement.mdx
