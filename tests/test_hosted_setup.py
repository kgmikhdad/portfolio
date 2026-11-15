from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text

from investment_engine.hosted_setup import HostedSetupError, initialize_database
from investment_engine.models import Base


@pytest.fixture()
def hosted_target(db):
    if db.dialect.name != "postgresql":
        pytest.skip("PostgreSQL-specific deployment test; exercised by PostgreSQL CI")
    # A separate connection pool avoids inheriting unit-test schema translation maps.
    target = create_engine(db.url, hide_parameters=True)
    schema = "investment_engine_test_" + uuid4().hex
    yield target, schema
    with target.begin() as connection:
        connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    target.dispose()


def test_migrations_deposit_and_reruns_preserve_existing_balance(hosted_target):
    target, schema = hosted_target
    first = initialize_database(target, schema)
    assert first["account_created"] is True
    assert first["post_commit_verified"] is True
    assert first["tables_verified"] == len(Base.metadata.tables) + 1
    with target.begin() as connection:
        assert connection.execute(text(f'SELECT count(*) FROM "{schema}".ledger')).scalar_one() == 1
        connection.execute(
            text(
                f'INSERT INTO "{schema}".ledger (id, account_id, at, amount_paise, kind) '
                "VALUES ('test-adjustment', 'paper', 1, -10000, 'test_adjustment')"
            )
        )
        connection.execute(text(f'UPDATE "{schema}".accounts SET cash_paise=9990000'))
    second = initialize_database(target, schema)
    assert second["account_created"] is False
    assert second["ledger_reconciled"] is True
    with target.connect() as connection:
        assert (
            connection.execute(
                text(f"SELECT cash_paise FROM \"{schema}\".accounts WHERE id='paper'")
            ).scalar_one()
            == 9990000
        )
        assert connection.execute(text(f'SELECT count(*) FROM "{schema}".ledger')).scalar_one() == 2
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM \"{schema}\".ledger WHERE kind='initial'")
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(
                text(
                    "SELECT bool_and(c.relrowsecurity) FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname=:schema AND c.relkind='r'"
                ),
                {"schema": schema},
            ).scalar_one()
            is True
        )
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_namespace n, "
                    "LATERAL aclexplode(coalesce(n.nspacl,acldefault('n',n.nspowner))) a "
                    "WHERE n.nspname=:schema AND a.grantee=0 AND a.privilege_type='USAGE'"
                ),
                {"schema": schema},
            ).scalar_one()
            == 0
        )


def test_unrecognized_existing_schema_is_preserved(hosted_target):
    target, schema = hosted_target
    with target.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'CREATE TABLE "{schema}".unrelated (id integer)'))
    with pytest.raises(HostedSetupError, match="existing_schema_not_owned"):
        initialize_database(target, schema)
    with target.connect() as connection:
        assert inspect(connection).get_table_names(schema=schema) == ["unrelated"]


def test_failure_rolls_back_schema_and_migrations(hosted_target, monkeypatch):
    target, schema = hosted_target

    def fail(*args, **kwargs):
        raise HostedSetupError("injected_failure_before_deposit")

    monkeypatch.setattr("investment_engine.hosted_setup.initialize", fail)
    with pytest.raises(HostedSetupError, match="injected_failure"):
        initialize_database(target, schema)
    with target.connect() as connection:
        assert not inspect(connection).has_schema(schema)


def test_schema_name_cannot_escape_application_namespace(db):
    if db.dialect.name == "postgresql":
        with pytest.raises(HostedSetupError, match="invalid_application_schema"):
            initialize_database(db, "public")
    else:
        with pytest.raises(HostedSetupError, match="requires_postgresql"):
            initialize_database(db)


def test_application_runtime_uses_private_schema_and_read_only_mode(hosted_target, monkeypatch):
    from investment_engine.hosted_database import application_engine

    target, schema = hosted_target
    initialize_database(target, schema)

    def local_engine(_):
        return create_engine(target.url, hide_parameters=True)

    monkeypatch.setattr("investment_engine.hosted_database.verified_engine", local_engine)
    app = application_engine("not-a-real-secret", read_only=True, schema=schema)
    try:
        with app.connect() as connection:
            assert connection.execute(text("SELECT current_schema()")).scalar_one() == schema
            assert connection.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
            assert (
                connection.execute(text("SELECT cash_paise FROM accounts")).scalar_one() == 10000000
            )
    finally:
        app.dispose()
