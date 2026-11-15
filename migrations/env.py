from alembic import context
from sqlalchemy import Connection

from investment_engine.db import engine
from investment_engine.models import Base
from investment_engine.settings import settings


def run_on_connection(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
        version_table_schema=context.config.attributes.get("schema"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run() -> None:
    supplied = context.config.attributes.get("connection")
    if supplied is not None:
        run_on_connection(supplied)
        return
    db = engine(settings().database_url.get_secret_value())
    try:
        with db.connect() as connection:
            run_on_connection(connection)
    finally:
        db.dispose()


run()
