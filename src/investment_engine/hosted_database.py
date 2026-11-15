"""Read-only hosted PostgreSQL readiness check with credential-safe diagnostics."""

import re
import socket
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url


class ConnectionConfigurationError(ValueError):
    pass


def supabase_url(value: str) -> URL:
    if not value.strip():
        raise ConnectionConfigurationError("missing_secret")
    try:
        url = make_url(value.strip())
    except Exception:
        raise ConnectionConfigurationError("invalid_connection_uri") from None
    if url.drivername not in ("postgres", "postgresql", "postgresql+psycopg"):
        raise ConnectionConfigurationError("expected_postgresql_uri")
    host = (url.host or "").lower()
    if not (host.endswith(".pooler.supabase.com") or host.endswith(".supabase.co")):
        raise ConnectionConfigurationError("expected_supabase_database_host")
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        raise ConnectionConfigurationError("invalid_database_hostname_check_password_encoding")
    if not url.username or not url.password or not url.database:
        raise ConnectionConfigurationError("incomplete_connection_uri")
    if "[YOUR-PASSWORD]" in url.password or "[your-password]" in url.password:
        raise ConnectionConfigurationError("password_placeholder_not_replaced")
    if url.port not in (None, 5432):
        raise ConnectionConfigurationError("use_session_pooler_port_5432")
    # Ignore supplied TLS/query overrides. Verification is mandatory below.
    return url.set(drivername="postgresql+psycopg", query={})


def verified_engine(value: str) -> Engine:
    return create_engine(
        supabase_url(value),
        hide_parameters=True,
        echo=False,
        connect_args={"sslmode": "verify-full", "sslrootcert": "system", "connect_timeout": 15},
    )


def failure_code(error: Exception) -> str:
    if isinstance(error, ConnectionConfigurationError):
        return str(error)
    # Use driver text only for local classification. Never return it: it may include credentials.
    message = str(error).lower()
    if "password authentication failed" in message or "authentication failed" in message:
        return "database_password_or_username_rejected"
    if "tenant or user not found" in message:
        return "pooler_project_or_username_not_found"
    if "certificate" in message or "sslrootcert" in message:
        return "tls_certificate_verification_failed"
    if "could not translate host" in message or "name or service not known" in message:
        return "database_hostname_not_resolved"
    if "timeout" in message or "timed out" in message:
        return "database_connection_timed_out"
    if "network is unreachable" in message:
        return "database_network_unreachable_use_session_pooler"
    return "database_connection_failed_details_suppressed"


def check_connection(value: str) -> dict[str, Any]:
    db = verified_engine(value)
    try:
        with db.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '15s'"))
            if connection.execute(text("SELECT 1")).scalar_one() != 1:
                raise RuntimeError("Read query failed")
            encrypted: bool = connection.execute(
                text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
            ).scalar_one()
            if encrypted is not True:
                raise RuntimeError("TLS session required")
            readonly: str = connection.execute(text("SHOW transaction_read_only")).scalar_one()
            return {
                "status": "connected",
                "provider": "supabase",
                "read_query": "passed",
                "tls": "certificate_and_hostname_verified",
                "encrypted_session": True,
                "transaction_read_only": readonly == "on",
                "schema_changes": False,
                "trades_executed": 0,
            }
    finally:
        db.dispose()


def endpoint_diagnostics(value: str, expected_host: str) -> dict[str, bool]:
    """Return only booleans, never the hostname parsed from a secret or its credentials."""
    url = supabase_url(value)
    if not re.fullmatch(r"[a-z0-9.-]+\.pooler\.supabase\.com", expected_host):
        raise ConnectionConfigurationError("invalid_expected_pooler_hostname")

    def resolves(host: str) -> bool:
        try:
            return bool(socket.getaddrinfo(host, 5432, type=socket.SOCK_STREAM))
        except OSError:
            return False

    return {
        "saved_hostname_matches_expected": url.host == expected_host,
        "expected_hostname_resolves": resolves(expected_host),
        "saved_hostname_resolves": resolves(url.host or ""),
        "saved_endpoint_is_direct": bool(url.host and url.host.endswith(".supabase.co")),
    }
