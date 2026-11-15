"""Operator-reviewed reference imports; no bundled or guessed index constituents."""

import hashlib
import time
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from investment_engine.data import digest
from investment_engine.models import Identifier, Membership, Security

OFFICIAL_HOSTS = {
    "www.niftyindices.com",
    "niftyindices.com",
    "nsearchives.nseindia.com",
    "www.nseindia.com",
}


def valid_isin(value: str) -> bool:
    if len(value) != 12 or not value.startswith("IN") or not value[-1].isdigit():
        return False
    if not value.isascii() or not value.isalnum() or value != value.upper():
        return False
    expanded = "".join(str(ord(c) - 55) if c.isalpha() else c for c in value)
    total = 0
    for index, digit in enumerate(reversed(expanded)):
        number = int(digit) * (2 if index % 2 else 1)
        total += number // 10 + number % 10
    return total % 10 == 0


class Constituent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    isin: str
    symbol: str = Field(min_length=1)
    sector: str = Field(min_length=1)
    yahoo_symbol: str | None = None

    @model_validator(mode="after")
    def identifier(self) -> "Constituent":
        if not valid_isin(self.isin):
            raise ValueError("Invalid ISIN checksum")
        return self


class ReferenceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_url: str
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    published_at: int
    valid_from: int
    valid_to: int
    constituents: list[Constituent] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent(self) -> "ReferenceManifest":
        if urlsplit(self.source_url).hostname not in OFFICIAL_HOSTS:
            raise ValueError("Official index/exchange source required")
        if urlsplit(self.source_url).scheme != "https":
            raise ValueError("HTTPS official source required")
        if self.valid_to <= self.valid_from or self.valid_to - self.valid_from > 31 * 86400:
            raise ValueError("Explicit eligibility expiry within 31 days required")
        if self.published_at > int(time.time()):
            raise ValueError("Future publication prohibited")
        if len({c.isin for c in self.constituents}) != len(self.constituents):
            raise ValueError("Duplicate ISIN in official reference")
        if len({c.symbol for c in self.constituents}) != len(self.constituents):
            raise ValueError("Duplicate ticker requires reconciliation")
        return self


def import_reference(
    session: Session, manifest: ReferenceManifest, document: Path, operator_reviewed: bool = False
) -> int:
    if not operator_reviewed:
        raise ValueError("Operator must verify the source document and extracted membership")
    if hashlib.sha256(document.read_bytes()).hexdigest() != manifest.document_sha256:
        raise ValueError("Source document digest mismatch")
    received = int(time.time())
    count = 0
    for member in manifest.constituents:
        security = session.get(Security, member.isin)
        if security is None:
            session.add(Security(isin=member.isin, symbol=member.symbol, sector=member.sector))
            session.flush()
        elif security.symbol != member.symbol or security.sector != member.sector:
            raise ValueError("Identifier/sector revision needs an explicit reviewed migration")
        existing = session.scalar(
            select(Membership.id).where(
                Membership.isin == member.isin,
                Membership.document_hash == manifest.document_sha256,
                Membership.valid_from == manifest.valid_from,
            )
        )
        if existing is None:
            session.add(
                Membership(
                    isin=member.isin,
                    valid_from=manifest.valid_from,
                    valid_to=manifest.valid_to,
                    published_at=manifest.published_at,
                    received_at=received,
                    source=manifest.source_url,
                    document_hash=manifest.document_sha256,
                    verified=True,
                )
            )
            count += 1
        if member.yahoo_symbol:
            identifiers = session.scalars(
                select(Identifier).where(
                    Identifier.isin == member.isin,
                    Identifier.provider == "yahoo",
                    Identifier.valid_to.is_(None),
                )
            ).all()
            if identifiers and any(i.symbol != member.yahoo_symbol for i in identifiers):
                raise ValueError("Conflicting Yahoo identifier; reconcile explicitly")
            if not identifiers:
                session.add(
                    Identifier(
                        isin=member.isin,
                        provider="yahoo",
                        symbol=member.yahoo_symbol,
                        valid_from=received,
                        source=manifest.source_url,
                    )
                )
    session.flush()
    return count


def reconcile_universe(compiled: list[str], official: list[str]) -> dict[str, object]:
    return {
        "compiled_count": len(compiled),
        "official_count": len(official),
        "missing_from_compiled": sorted(set(official) - set(compiled)),
        "not_in_official": sorted(set(compiled) - set(official)),
        "compiled_duplicates": sorted({i for i in compiled if compiled.count(i) > 1}),
        "official_duplicates": sorted({i for i in official if official.count(i) > 1}),
        "official_set_hash": digest(sorted(official)),
    }
