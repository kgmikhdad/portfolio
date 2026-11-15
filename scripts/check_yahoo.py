"""Download and persist a real, identified research sample; never authorize a trade.

Usage: uv run python scripts/check_yahoo.py [NSE_SYMBOL]
Only the user's educational/research Yahoo use is intended. Membership is not inferred.
"""

import csv
import hashlib
import io
import json
import sys
import time
from datetime import datetime
from datetime import time as walltime
from fractions import Fraction
from pathlib import Path

import httpx
import yfinance as yf

from investment_engine.data import (
    IST,
    DataUnavailable,
    PriceBar,
    digest,
    paise,
    persist_actions,
    persist_bars,
)
from investment_engine.db import engine, transaction
from investment_engine.models import Identifier, Security
from investment_engine.reference import valid_isin
from investment_engine.settings import settings


def main() -> None:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "INFY"
    if not symbol.replace("-", "").replace("&", "").isalnum():
        raise ValueError("Expected an NSE cash-equity symbol")
    directory = Path("var/research")
    directory.mkdir(parents=True, exist_ok=True)
    source = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
    response = httpx.get(source, timeout=30)
    response.raise_for_status()
    records = [
        {k.strip(): v.strip() for k, v in row.items()}
        for row in csv.DictReader(io.StringIO(response.text))
    ]
    matches = [r for r in records if r.get("SYMBOL") == symbol and r.get("SERIES") == "EQ"]
    if len(matches) != 1 or not valid_isin(matches[0]["ISIN NUMBER"]):
        raise DataUnavailable("NSE identifier reconciliation failed")
    isin = matches[0]["ISIN NUMBER"]
    stamp = int(time.time())
    master = directory / f"nse-equity-master-{stamp}.csv"
    master.write_bytes(response.content)
    yf.set_tz_cache_location("var/cache/yfinance")
    ticker = yf.Ticker(symbol + ".NS")
    frame = ticker.history(period="1mo", auto_adjust=False, actions=True)
    if frame.empty:
        raise DataUnavailable("Yahoo returned no history")
    metadata = ticker.history_metadata
    if metadata.get("currency") != "INR" or metadata.get("symbol") != symbol + ".NS":
        raise DataUnavailable("Yahoo identifier/currency mismatch")
    received = int(time.time())
    bars, actions = [], []
    for index, row in frame.iterrows():
        day = index.date()
        close_at = int(datetime.combine(day, walltime(15, 30), IST).timestamp())
        if close_at > received:
            continue
        bars.append(
            PriceBar(
                isin=isin,
                day=day,
                source="yfinance-research",
                open_paise=paise(row["Open"]),
                high_paise=paise(row["High"]),
                low_paise=paise(row["Low"]),
                close_paise=paise(row["Close"]),
                adjusted_close_paise=paise(row["Adj Close"]),
                volume=int(row["Volume"]),
                published_at=close_at,
                received_at=received,
            )
        )
        for column, kind in (("Dividends", "dividend"), ("Stock Splits", "split")):
            if float(row.get(column, 0)):
                ratio = Fraction(str(row[column])).limit_denominator(100000)
                actions.append(
                    {
                        "id": digest(
                            {
                                "source": "yfinance-research",
                                "isin": isin,
                                "day": str(day),
                                "kind": kind,
                                "value": str(row[column]),
                            }
                        ),
                        "isin": isin,
                        "kind": kind,
                        "effective_at": int(index.timestamp()),
                        # Actual announcement time unknown: never invent past availability.
                        "published_at": received,
                        "received_at": received,
                        "numerator": ratio.numerator if kind == "split" else None,
                        "denominator": ratio.denominator if kind == "split" else None,
                        "cash_paise": paise(row[column]) if kind == "dividend" else None,
                        "source": "yfinance-research:ex-date-unreconciled",
                    }
                )
    if not bars:
        raise DataUnavailable("No completed valid daily bars")
    db = engine(settings().database_url.get_secret_value())
    with transaction(db) as session:
        security = session.get(Security, isin)
        if security is None:
            session.add(Security(isin=isin, symbol=symbol, sector="Unclassified"))
            session.flush()
            session.add(
                Identifier(
                    isin=isin,
                    provider="yahoo",
                    symbol=symbol + ".NS",
                    valid_from=received,
                    source=source,
                )
            )
        elif security.symbol != symbol:
            raise DataUnavailable("Stored identifier conflicts with NSE master")
        inserted = persist_bars(session, bars)
        persist_actions(session, actions)
    archive = directory / f"{symbol}-{received}.parquet"
    frame.to_parquet(archive)
    result = {
        "status": "real_data_validated_and_persisted",
        "source": "yfinance",
        "symbol": symbol + ".NS",
        "isin": isin,
        "currency": "INR",
        "rows_validated": len(bars),
        "new_database_rows": inserted,
        "latest_session": str(bars[-1].day),
        "latest_close_inr": bars[-1].close_paise / 100,
        "received_at": received,
        "archive": str(archive),
        "identifier_source": source,
        "identifier_source_sha256": hashlib.sha256(response.content).hexdigest(),
        "corporate_actions_pending_reconciliation": len(actions),
        "eligibility": "not_verified",
        "orders_executed": 0,
        "purpose": "educational_research_only",
    }
    (directory / f"{symbol}-{received}.manifest.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
