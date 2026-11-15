# Provider evaluation and permissions

As of this session, the environment proxy denies financial-provider/Google/GitHub API hosts.
A draft allowlist was saved; saving it is not runtime access. No live provider response,
free-tier quota, licensed redistribution right or India coverage has been verified. The
following are adapters/candidates, not approved production sources.

| Source | Implemented capability | Constraints and unresolved verification |
|---|---|---|
| Yahoo chart data (the source used by yfinance) | Explicit NSE `.NS` identifier, daily OHLCV, adjusted close, source hashes, split detection; rejects unresolved dividend entitlement | Unofficial endpoint; no exchange licence assumed. Access disabled until permitted usage established. History and adjustments may revise. No cookie/crumb bypass. Local cap 100 requests/day is a self-imposed safety cap, not a provider entitlement. |
| Alpha Vantage | Compact daily endpoint adapter with persistent local quota/cache/circuit state | Indian symbols and account endpoint entitlement unverified. Default 25-request local daily budget is conservative configuration, not a verified current free tier. Compact history cannot be claimed to cover the required horizons. No blanket 203-stock daily coverage assumed. |
| Nifty Indices / NSE | Reviewed source-document reference importer, explicit membership validity and ISIN checksum | Actual 204-member authoritative list and historical membership not retrieved. No inferred missing stock. Official calendars, actions and disclosures need authorized ingestion and parsing. |
| BSE/company IR/XBRL | Provenance/event schemas and taxonomy | No production ingestion adapter/parser connected. Confirm permitted automated access and source contracts before implementation. |
| NSDL/CDSL/SEBI | Versioned observation schema | Actual FPI/DII/sector time-series adapters and revision contracts pending. |
| RBI/macro/global data | Observation schema | Source, licence, frequency, revisions and availability pending; no substituted numbers. |
| Brokerage data | Interface boundary only | No authorized account supplied. Market data scope only; no trading access requested. |
| Shariah TRI | No substituted benchmark | Licensed/authorized total-return series required. A price-only index is not a total-return benchmark. |

Official starting points to review after access is available:

- https://www.alphavantage.co/documentation/ and https://www.alphavantage.co/support/#api-key
- https://policies.yahoo.com/us/en/yahoo/terms/otos/index.htm and https://ranaroussi.github.io/yfinance/
- https://www.niftyindices.com/indices/equity/thematic-indices/nifty500-shariah
- https://www.nseindia.com/ and https://www.bseindia.com/
- https://www.sebi.gov.in/ and https://www.rbi.org.in/

A CSV/document may be imported only after an operator verifies its official source, publication
and extracted constituents; its file hash must match the reference manifest. This is an
operator attestation, not automated proof of authenticity. Imports record actual receipt now,
never backdated receipt. Reconcile compiled versus official ISIN sets, duplicates, effective
dates and identifier changes before marking universe coverage complete. Keep the Google Sheet
original untouched and back it up through authorized Drive access before any writes.
