from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session


def engine(url: str) -> Engine:
    result = create_engine(url, hide_parameters=True)
    if result.dialect.name == "sqlite":

        @event.listens_for(result, "connect")
        def sqlite_pragmas(connection: object, _: object) -> None:
            cursor = connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.close()

    return result


@contextmanager
def transaction(db: Engine) -> Iterator[Session]:
    with Session(db) as session, session.begin():
        # Serialize SQLite writers before reading account balances. PostgreSQL uses row locks.
        if db.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield session
