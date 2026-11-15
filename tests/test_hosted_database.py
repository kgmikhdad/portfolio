import pytest

from investment_engine.hosted_database import (
    ConnectionConfigurationError,
    failure_code,
    supabase_url,
)


def test_session_pooler_uri_normalizes_driver_and_discards_tls_downgrades():
    url = supabase_url(
        "postgresql://postgres.example:not-a-real-password@aws-0-ap-south-1.pooler.supabase.com"
        ":5432/postgres?sslmode=disable"
    )
    assert url.drivername == "postgresql+psycopg"
    assert url.query == {}
    assert url.password == "not-a-real-password"


@pytest.mark.parametrize(
    "value,reason",
    [
        ("", "missing_secret"),
        ("not a connection", "invalid_connection_uri"),
        ("https://example.test", "expected_postgresql_uri"),
        ("postgresql://user:dummy@untrusted.test:5432/postgres", "expected_supabase_database_host"),
        ("postgresql://user@db.example.supabase.co/postgres", "incomplete_connection_uri"),
        (
            "postgresql://user:[YOUR-PASSWORD]@db.example.supabase.co/postgres",
            "password_placeholder_not_replaced",
        ),
        (
            "postgresql://user:dummy@aws-0-example.pooler.supabase.com:6543/postgres",
            "use_session_pooler_port_5432",
        ),
    ],
)
def test_invalid_configuration_has_safe_failure_reason(value, reason):
    with pytest.raises(ConnectionConfigurationError) as caught:
        supabase_url(value)
    assert str(caught.value) == reason


def test_diagnostics_do_not_expose_driver_messages():
    error = RuntimeError("password authentication failed; confidential connection information")
    assert failure_code(error) == "database_password_or_username_rejected"
    assert "confidential" not in failure_code(error)
    assert failure_code(RuntimeError("secret detail")) == (
        "database_connection_failed_details_suppressed"
    )
