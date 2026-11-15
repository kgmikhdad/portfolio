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
is invented. Tests use explicitly synthetic fixtures. Current data usage rights are not verified.
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
