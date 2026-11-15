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


def test_malformed_password_cannot_be_sent_as_part_of_a_hostname():
    with pytest.raises(ConnectionConfigurationError, match="password_encoding"):
        supabase_url("postgresql://user:dummy@fragment@aws-0-example.pooler.supabase.com/postgres")


def test_endpoint_report_contains_only_boolean_metadata(monkeypatch):
    from investment_engine.hosted_database import endpoint_diagnostics

    monkeypatch.setattr("investment_engine.hosted_database.socket.getaddrinfo", lambda *a, **k: [1])
    report = endpoint_diagnostics(
        "postgresql://user:dummy@aws-0-ap-south-1.pooler.supabase.com:5432/postgres",
        "aws-0-ap-south-1.pooler.supabase.com",
    )
    assert report["saved_hostname_matches_expected"]
    assert report["expected_hostname_resolves"]
    assert all(type(value) is bool for value in report.values())
