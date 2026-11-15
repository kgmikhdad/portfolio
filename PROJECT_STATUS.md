# Project status — 2026-11-15

**Overall: locally tested foundation; external integration blocked. Production acceptance
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
  is empty. No orders are executed. This is a verified failure state, not successful research.

All market, calendar and index inputs in automated tests are **synthetic test fixtures**.
Verified genuine market coverage: **zero securities / zero price rows**. The 203/204 membership
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
