# Architecture and current boundaries

One Python application, a PostgreSQL ledger, Parquet research archives, a readout to Google
Sheets, and opt-in GitHub Actions. No microservices, real-money broker or paid resource creation.
Local PostgreSQL is a development deployment, not durable managed cloud hosting.

## Storage and consistency

Alembic owns schema changes. Securities use ISIN primary keys, provider identifiers have
validity intervals, and index eligibility has publication, receipt, effective and expiry times.
Prices are append-only revisions keyed by content hash; identical refetches preserve their
first receipt timestamp. Multiple providers for the same day require explicit reconciliation.
Financial/macro/flow observations retain their revisions and units. Research events retain
source URL, document hash and evidence review status. Models/predictions/features have lineage
fields; experiment utilities are not a complete production registry.

Accounts, orders, holdings, corporate-action postings, cash ledger, decisions, valuations,
jobs and backtests have separate tables. `broker.execute` locks the account before checking
an order ID and balances. One transaction contains risk checks, holding updates, execution and
ledger postings. A PostgreSQL row lock serializes concurrent workers; SQLite uses an immediate
write transaction for isolated portability checks. Independent cash/quantity reconciliation
runs before commit. Failed research jobs are recorded in a separate transaction.

Source records are append-only by application convention. Database roles/permissions and
immutable archival retention still need deployment-specific hardening. Observation is a typed
provenance envelope, not a finished taxonomy of every financial fact or filing parser.

## Temporal rules

Both publication and receipt must precede a decision. A reviewed membership snapshot expires
within 31 days. Execution requires a verified session, a later trading day than the signal,
and quotes published/received by execution and no older than 15 minutes. Whole-portfolio marks
are mandatory. Next-session-open historical fills are explicitly simulated assumptions and do
not imply fills in the live market. Research features see only previous-session PIT records.

Corporate split accounting is idempotent and preserves basis; fractional entitlements block.
Forward total-return functions test split/dividend normalization. Automatic dividends block
until record-date entitlement and payment evidence are available; the Yahoo adapter does not
silently book ex-date cash. Signals with corporate actions block pending normalized PIT data.
No claim of a complete corporate-action/backtest production subsystem is made.

The backtest baseline uses a 20-session momentum signal and 7% initial-capital orders with
common risk checks, adverse slippage, fees, cash and daily closing valuation. It rejects
ambiguous fill revisions and missing marks. Results are reproducible from supplied fixed
inputs. Benchmark comparison remains null unless licensed total-return data is supplied.
Calendar data is explicit; weekdays are never guessed to be exchange trading days.

## Research promotion

Ridge, LinUCB and Gymnasium are experimental research building blocks. Temporal folds purge
training labels overlapping validation, with embargo. Dataset hashes include reference and
price data. No production candidate was trained on market data. Adaptive gating, calibrated
uncertainty, horizon-specific targets, ablations, full benchmark comparisons, RL training and
prospective evaluation remain unimplemented/blocked by the research-data prerequisite.
Promotion requires sufficient out-of-sample/prospective evidence and an independent approval ID;
thresholds are engineering gates, not proof of financial validity or statistical significance.

## Integrations

Google Sheets writes require a verified original-workbook backup and create new backend tabs;
source tabs are not updated or deleted. This client is locally implemented, not externally
verified. Google Drive encrypted backup upload, authenticated account binding, and a complete
portfolio dashboard remain pending. Local AES-GCM encrypted PostgreSQL backup and isolated
restore drill are implemented. Local drill keys are not an acceptable production key strategy.

The daily scheduled workflow is inert unless PAPER_PIPELINE_ENABLED is explicitly true and a
persistent database is configured. It performs research only; data ingestion, verified fills,
qualitative Work scheduling and model retraining must be connected and tested before activation.
GitHub schedules are best-effort; manual `as_of` dispatch supports research catch-up, while the
monitor reports missed runs. There is no claim that the full daily trading pipeline is deployed.
