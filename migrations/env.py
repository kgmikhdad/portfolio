from alembic import context
from investment_engine.db import engine
from investment_engine.models import Base
from investment_engine.settings import settings


def run() -> None:
    db = engine(settings().database_url.get_secret_value())
    with db.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            compare_type=True,
            render_as_batch=db.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


run()
