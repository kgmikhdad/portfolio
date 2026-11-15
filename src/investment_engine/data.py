import hashlib
import json
import time
from datetime import UTC, date, datetime
from datetime import time as walltime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from investment_engine.models import Bar, CorporateAction

IST = ZoneInfo("Asia/Kolkata")


class DataUnavailable(RuntimeError):
    pass


def paise(value: object) -> int:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Price must be finite and positive")
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class PriceBar(BaseModel):
    isin: str = Field(pattern=r"^IN[A-Z0-9]{9}[0-9]$")
    day: date
    source: str
    open_paise: int = Field(gt=0)
    high_paise: int = Field(gt=0)
    low_paise: int = Field(gt=0)
    close_paise: int = Field(gt=0)
    adjusted_close_paise: int | None = Field(default=None, gt=0)
    volume: int = Field(ge=0)
    published_at: int
    received_at: int

    @model_validator(mode="after")
    def consistent(self) -> "PriceBar":
        if not self.low_paise <= min(self.open_paise, self.close_paise):
            raise ValueError("Invalid OHLC range")
        if self.high_paise < max(self.open_paise, self.close_paise, self.low_paise):
            raise ValueError("Invalid OHLC range")
        if self.published_at > self.received_at:
            raise ValueError("Future publication")
        if datetime.fromtimestamp(self.published_at, IST).date() < self.day:
            raise ValueError("Publication precedes session")
        return self


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def persist_bars(session: Session, bars: list[PriceBar]) -> int:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert

        count = 0
        for offset in range(0, len(bars), 500):
            batch_values = []
            for bar in bars[offset : offset + 500]:
                row = bar.model_dump(mode="json")
                row["content_hash"] = digest({k: v for k, v in row.items() if k != "received_at"})
                batch_values.append(row)
            statement = (
                insert(Bar)
                .values(batch_values)
                .on_conflict_do_nothing(index_elements=["isin", "day", "source", "content_hash"])
                .returning(Bar.id)
            )
            count += len(session.scalars(statement).all())
        return count
    count = 0
    for bar in bars:
        values = bar.model_dump(mode="json")
        # receipt time changes on refetch; identical source contents are not new revisions.
        content_hash = digest({k: v for k, v in values.items() if k != "received_at"})
        existing = session.scalar(
            select(Bar.id).where(
                Bar.isin == bar.isin,
                Bar.day == str(bar.day),
                Bar.source == bar.source,
                Bar.content_hash == content_hash,
            )
        )
        if existing is None:
            session.add(Bar(**values, content_hash=content_hash))
            session.flush()
            count += 1
    return count


def point_in_time_bars(session: Session, isin: str, at: int) -> list[Bar]:
    rows = session.scalars(
        select(Bar)
        .where(
            Bar.isin == isin,
            Bar.published_at <= at,
            Bar.received_at <= at,
        )
        .order_by(Bar.day, Bar.received_at, Bar.id)
    ).all()
    sources: dict[str, set[str]] = {}
    for row in rows:
        sources.setdefault(row.day, set()).add(row.source)
    if any(len(source_set) > 1 for source_set in sources.values()):
        raise DataUnavailable("Multiple sources require explicit reconciliation")
    latest = {row.day: row for row in rows}
    return [latest[day] for day in sorted(latest)]


class PriceProvider(Protocol):
    def history(self, isin: str, symbol: str, start: date, end: date) -> list[PriceBar]: ...


class JsonTransport:
    """Single-host persistent quota, cache, bounded retries and circuit breaker.

    A file lock spans requests to serialize local workers. Shared deployments must use one
    scheduled ingestion worker (workflow concurrency) or an external distributed limiter.
    """

    def __init__(self, state: Path, daily_quota: int = 25, interval: float = 1.0) -> None:
        self.state = state
        self.quota = daily_quota
        self.interval = interval

    def get(self, url: str, params: dict[str, Any], cache_seconds: int = 3600) -> Any:
        import fcntl

        self.state.mkdir(parents=True, exist_ok=True)
        key = digest({"url": url, "params": params})
        cached = self.state / f"{key}.json"
        with (self.state / "lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            now = time.time()
            if cached.exists() and now - cached.stat().st_mtime < cache_seconds:
                return json.loads(cached.read_text())
            status_file = self.state / "status.json"
            status = json.loads(status_file.read_text()) if status_file.exists() else {}
            today = datetime.now(UTC).date().isoformat()
            if status.get("day") != today:
                status = {"day": today, "requests": 0, "failures": 0, "last": 0}
            if now < status.get("open_until", 0):
                raise DataUnavailable("Provider circuit open")
            for attempt in range(3):
                if status["requests"] >= self.quota:
                    raise DataUnavailable("Provider daily quota exhausted")
                delay = self.interval - (time.time() - status["last"])
                if delay > 0:
                    time.sleep(delay)
                status["requests"] += 1
                status["last"] = time.time()
                status_file.write_text(json.dumps(status))
                try:
                    with httpx.Client(timeout=20, follow_redirects=False) as client:
                        response = client.get(url, params=params)
                    if response.status_code in (429, 500, 502, 503, 504):
                        raise DataUnavailable(f"Provider HTTP {response.status_code}")
                    if response.status_code != 200:
                        raise ValueError(f"Provider HTTP {response.status_code}")
                    payload = response.json()
                    if isinstance(payload, dict) and any(
                        key in payload for key in ("Note", "Information", "Error Message")
                    ):
                        raise DataUnavailable("Provider reports quota, access or invalid request")
                    cached.write_text(json.dumps(payload))
                    status["failures"] = 0
                    status_file.write_text(json.dumps(status))
                    return payload
                except (httpx.HTTPError, DataUnavailable, ValueError):
                    status["failures"] += 1
                    if status["failures"] >= 3:
                        status["open_until"] = time.time() + 300
                    status_file.write_text(json.dumps(status))
                    if attempt < 2:
                        time.sleep(2**attempt)
            # Do not expose request URLs containing credentials.
            raise DataUnavailable("Provider request failed; no data substituted")


class YahooResearchProvider:
    """Unofficial Yahoo chart endpoint; research only, usage permission is required.

    No claim of an exchange licence. No cookie/crumb bypass, scraping or fallback source.
    """

    def __init__(self, transport: JsonTransport, permitted: bool = False) -> None:
        self.transport, self.permitted = transport, permitted
        self.actions: list[dict[str, Any]] = []

    def history(self, isin: str, symbol: str, start: date, end: date) -> list[PriceBar]:
        if not self.permitted:
            raise DataUnavailable("Yahoo usage permission has not been established")
        if not symbol.endswith(".NS") or not symbol.replace(".", "").replace("-", "").isalnum():
            raise ValueError("Expected explicit reconciled NSE Yahoo identifier")
        payload = self.transport.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            {
                "period1": int(datetime.combine(start, walltime(), UTC).timestamp()),
                "period2": int(datetime.combine(end, walltime(), UTC).timestamp()),
                "interval": "1d",
                "events": "div,splits",
            },
        )
        try:
            result = payload["chart"]["result"][0]
            if result["meta"]["currency"] != "INR":
                raise DataUnavailable("Unexpected source currency")
            quote = result["indicators"]["quote"][0]
            adjusted = result["indicators"].get("adjclose", [{}])[0].get("adjclose", [])
            received = int(time.time())
            self.actions = []
            for action_type, kind in (("splits", "split"), ("dividends", "dividend")):
                for source_id, event in result.get("events", {}).get(action_type, {}).items():
                    effective = int(event["date"])
                    if kind == "dividend":
                        # Yahoo reports ex-date, not verified entitlement/payment date.
                        # Preserve in the event queue instead of crediting portfolio cash.
                        raise DataUnavailable(
                            "Dividend ex-date detected; payment/entitlement reconciliation required"
                        )
                    self.actions.append(
                        {
                            "id": digest({"source": "yahoo", "isin": isin, "event": source_id}),
                            "isin": isin,
                            "kind": kind,
                            "effective_at": effective,
                            "published_at": received,
                            "received_at": received,
                            "numerator": int(event["numerator"]),
                            "denominator": int(event["denominator"]),
                            "source": "yahoo-research",
                        }
                    )
            bars = []
            for i, timestamp in enumerate(result["timestamp"]):
                day = datetime.fromtimestamp(timestamp, IST).date()
                values = {name: quote[name][i] for name in ("open", "high", "low", "close")}
                if any(value is None for value in values.values()) or quote["volume"][i] is None:
                    raise DataUnavailable("Source contains missing OHLCV")
                publication = int(datetime.combine(day, walltime(15, 30), IST).timestamp())
                if publication > received:
                    continue  # incomplete session is never a final daily bar
                bars.append(
                    PriceBar(
                        isin=isin,
                        day=day,
                        source="yahoo-research",
                        **{f"{name}_paise": paise(value) for name, value in values.items()},
                        adjusted_close_paise=(
                            paise(adjusted[i]) if adjusted and adjusted[i] else None
                        ),
                        volume=int(quote["volume"][i]),
                        published_at=publication,
                        received_at=received,
                    )
                )
            if not bars:
                raise DataUnavailable("No completed daily bars")
            return bars
        except (KeyError, IndexError, TypeError) as error:
            raise DataUnavailable("Provider schema mismatch") from error


class AlphaVantageProvider:
    """Opt-in adapter; coverage and entitlement must be verified per symbol/account."""

    def __init__(self, transport: JsonTransport, api_key: str) -> None:
        self.transport, self.api_key = transport, api_key

    def history(self, isin: str, symbol: str, start: date, end: date) -> list[PriceBar]:
        data = self.transport.get(
            "https://www.alphavantage.co/query",
            {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": "compact",
                "apikey": self.api_key,
            },
        )
        series = data.get("Time Series (Daily)")
        if not series:
            raise DataUnavailable("Daily endpoint/Indian symbol not available for this account")
        now = int(time.time())
        bars = []
        for day_text, row in sorted(series.items()):
            day = date.fromisoformat(day_text)
            if start <= day < end:
                published = int(datetime.combine(day, walltime(15, 30), IST).timestamp())
                if published <= now:
                    bars.append(
                        PriceBar(
                            isin=isin,
                            day=day,
                            source="alphavantage",
                            open_paise=paise(row["1. open"]),
                            high_paise=paise(row["2. high"]),
                            low_paise=paise(row["3. low"]),
                            close_paise=paise(row["4. close"]),
                            volume=int(row["5. volume"]),
                            published_at=published,
                            received_at=now,
                        )
                    )
        if not bars:
            raise DataUnavailable("No daily observations in requested interval")
        return bars


def persist_actions(session: Session, actions: list[dict[str, Any]]) -> int:
    if not actions:
        return 0
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert

        statement = (
            insert(CorporateAction)
            .values(actions)
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(CorporateAction.id)
        )
        return len(session.scalars(statement).all())
    count = 0
    for values in actions:
        if session.get(CorporateAction, values["id"]) is None:
            session.add(CorporateAction(**values))
            count += 1
    session.flush()
    return count
