import os
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from investment_engine.broker import initialize
from investment_engine.data import IST, PriceBar, persist_bars
from investment_engine.db import engine, transaction
from investment_engine.models import Base, MarketSession, Membership, Security

ISIN = "INE000A01010"


def timestamp(day: str, hour: int, minute: int = 0) -> int:
    return int(
        datetime.fromisoformat(f"{day}T{hour:02}:{minute:02}:00").replace(tzinfo=IST).timestamp()
    )


@pytest.fixture()
def db(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        schema = "test_" + uuid4().hex
        root = create_engine(url, hide_parameters=True)
        with root.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        result = root.execution_options(schema_translate_map={None: schema})
        Base.metadata.create_all(result)
        yield result
        with root.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root.dispose()
    else:
        result = engine(f"sqlite:///{tmp_path}/test.db")
        Base.metadata.create_all(result)
        yield result
        result.dispose()


@pytest.fixture()
def market(db):
    signal = timestamp("2026-11-10", 15, 35)
    execute_at = timestamp("2026-11-11", 9, 15)
    with transaction(db) as session:
        session.add(Security(isin=ISIN, symbol="SYNTHETIC", sector="test-sector"))
        session.add(
            MarketSession(
                day="2026-11-11",
                opens_at=execute_at,
                closes_at=timestamp("2026-11-11", 15, 30),
                source="synthetic-test-calendar",
                verified=True,
            )
        )
        session.flush()
        session.add(
            Membership(
                isin=ISIN,
                valid_from=signal - 100000,
                valid_to=signal + 1000000,
                published_at=signal - 100000,
                received_at=signal - 99999,
                source="synthetic-test-membership",
                document_hash="test",
                verified=True,
            )
        )
        persist_bars(
            session,
            [
                PriceBar(
                    isin=ISIN,
                    day="2026-11-10",
                    source="synthetic-test",
                    open_paise=10000,
                    high_paise=11000,
                    low_paise=9000,
                    close_paise=10000,
                    volume=1000000,
                    published_at=signal - 300,
                    received_at=signal - 240,
                )
            ],
        )
        account = initialize(session, "test", signal)
        account.stopped = False
    return signal, execute_at
