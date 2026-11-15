import hashlib
import time

import httpx
import pytest
from cryptography.exceptions import InvalidTag

from investment_engine.backup import decrypt_dump, encrypt_dump
from investment_engine.data import DataUnavailable, JsonTransport
from investment_engine.db import transaction
from investment_engine.monitoring import health
from investment_engine.reference import (
    ReferenceManifest,
    import_reference,
    reconcile_universe,
    valid_isin,
)


def test_encrypted_backup_detects_tampering(tmp_path):
    key = b"A" * 32
    destination = tmp_path / "backup.aie"
    checksum = encrypt_dump(b"test PostgreSQL dump", key, destination)
    assert checksum == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert decrypt_dump(destination, key) == b"test PostgreSQL dump"
    with pytest.raises(FileExistsError):
        encrypt_dump(b"new", key, destination)
    with pytest.raises(InvalidTag):
        decrypt_dump(destination, b"B" * 32)
    payload = bytearray(destination.read_bytes())
    payload[-1] ^= 1
    destination.write_bytes(payload)
    with pytest.raises(InvalidTag):
        decrypt_dump(destination, key)


def test_reference_integrity_and_idempotency(db, tmp_path):
    document = tmp_path / "official.csv"
    document.write_text("SYNTHETIC TEST DOCUMENT; NOT AN ACTUAL MEMBERSHIP LIST")
    now = int(time.time())
    manifest = ReferenceManifest(
        source_url="https://www.niftyindices.com/test-only",
        published_at=now - 100,
        document_sha256=hashlib.sha256(document.read_bytes()).hexdigest(),
        valid_from=now,
        valid_to=now + 86400,
        constituents=[
            {"isin": "INE009A01021", "symbol": "INFY", "sector": "IT", "yahoo_symbol": "INFY.NS"}
        ],
    )
    assert valid_isin("INE009A01021") and not valid_isin("INE009A01022")
    with transaction(db) as session:
        with pytest.raises(ValueError, match="verify"):
            import_reference(session, manifest, document)
        assert import_reference(session, manifest, document, True) == 1
        assert import_reference(session, manifest, document, True) == 0
    document.write_text("modified")
    with transaction(db) as session:
        with pytest.raises(ValueError, match="digest"):
            import_reference(session, manifest, document, True)
    report = reconcile_universe(["A", "A", "C"], ["A", "B"])
    assert report["missing_from_compiled"] == ["B"]
    assert report["compiled_duplicates"] == ["A"]


def test_transport_cache_quota_and_circuit(tmp_path, monkeypatch):
    requests = []

    def get(self, url, params):
        requests.append(url)
        return httpx.Response(200, json={"authenticity": "mock response only"})

    monkeypatch.setattr(httpx.Client, "get", get)
    transport = JsonTransport(tmp_path, daily_quota=1, interval=0)
    assert transport.get("https://example.test/data", {})["authenticity"]
    assert transport.get("https://example.test/data", {})["authenticity"]
    assert len(requests) == 1
    with pytest.raises(DataUnavailable, match="quota"):
        transport.get("https://example.test/other", {})


def test_transport_circuit_opens_without_leaking_credentials(tmp_path, monkeypatch):
    def get(self, url, params):
        raise httpx.ConnectError("request URL might include a secret")

    monkeypatch.setattr(httpx.Client, "get", get)
    monkeypatch.setattr("investment_engine.data.time.sleep", lambda _: None)
    transport = JsonTransport(tmp_path, daily_quota=10, interval=0)
    with pytest.raises(DataUnavailable, match="no data substituted"):
        transport.get("https://example.test/data", {"apikey": "not-a-real-key"})
    with pytest.raises(DataUnavailable, match="circuit"):
        transport.get("https://example.test/data", {})
    assert "not-a-real-key" not in (tmp_path / "status.json").read_text()


def test_monitoring_reports_missing_calendar_and_job(db, market):
    report = health(db, "test", market[1])
    assert report["status"] == "blocked"
    assert "no_job_history" in report["reasons"]
