# Operations and recovery

## Local startup

`uv run python scripts/bootstrap.py` is repeatable and preserves .env. PostgreSQL must be
healthy before Alembic migrations, `invest doctor`, and `invest init`. `invest report` verifies
cash and holdings against the ledger. `docker compose stop postgres` stops only this project's
service. Do not delete its volume. Processes do not survive snapshot restoration; restart via
bootstrap. The generated local password is not a production service credential.

## Blocked ingestion or decisions

Do not disable validation, TLS, signatures or quotas. Inspect provider status/freshness and
reference expiry without printing secrets. An HTTP failure, missing/ambiguous source, open
circuit or missing feature blocks affected research. Jobs record blocked/failed independently
of portfolio transactions. A daily exit 3 is not success. No scheduled process automatically
turns off emergency stops. Existing readouts require fresh marks to claim NAV with holdings.

## Reference import

Verify the original official document and its ISIN extraction before using:

`invest reference manifest.json downloaded-official-document.csv --reviewed`

The manifest has source_url, document_sha256, published_at, valid_from, valid_to (UTC epoch),
and constituents containing isin, symbol, sector and optional reconciled yahoo_symbol.
Keep source documents/manifests in ignored var/, not public Git artifacts. Eligibility must
expire within 31 days. A downloaded current list cannot establish historical membership.
Calendar records must come from a verified official session schedule, including special days;
the current importer for exchange session documents still needs implementation.

## Paper accounting

Orders are synchronous and atomic, with no pending reservations. Use one db.transaction and
broker.execute; never insert a trade directly or patch cash. Order IDs must be durable job /
decision IDs. A duplicate same-intent ID returns its original fill, while a changed intent
fails. Account row locks protect concurrent execution. Stop on reconciliation mismatch;
restore into an isolated database and investigate before considering any repair migration.
The operational CLI deliberately does not expose arbitrary manual fills or an enable-live flag.

## Backups

`uv run python scripts/restore_drill.py` dumps ONLY the local Compose database, encrypts with
AES-256-GCM, verifies decryption, restores into a newly named isolated database, compares table
counts and migration version, then removes that drill database. It never replaces the source.
The current drill does not establish managed database disaster recovery or Google Drive upload.
Its ignored local key exists for local testing; production requires a separately recoverable
key in a managed secret store, encrypted remote retention, and restore drills from that store.
Never publish dumps, keys, holdings or private artifacts in Actions logs/artifacts.

## Missed run / catch-up

`invest health` checks reconciliation, verified calendar coverage and the most recent job.
Research supports `invest daily --as-of <epoch>` or a manual workflow dispatch. Run each missed
verified session in order after data availability is restored. Historical research catches up
without creating backdated paper fills. Never pretend a missed historical trade was executed.
The scheduled workflow's cron is 16:00 IST weekdays, subject to GitHub delay and verified
exchange calendars. It is configured behind an opt-in variable and has not been observed running.

## Model / event failures

A failed qualitative task must leave its event pending; schema-invalid or unmatched analysis
is rejected before changes. Reviewed evidence still requires independent source verification.
No model is promoted automatically. Preserve dataset hash, code commit, parameters, folds,
seed and untouched test period. Revert only an explicitly versioned approved model, never a
portfolio ledger. Synthetic test runs do not satisfy any model-acceptance requirement.
