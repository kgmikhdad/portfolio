"""Evidence schemas and deterministic triage; documents never become instructions."""

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from investment_engine.models import ResearchEvent

TAXONOMY_VERSION = "1"
RULES = {
    "dividend": r"\bdividend\b",
    "earnings": r"\b(financial results|earnings|quarterly results)\b",
    "merger": r"\b(merger|amalgamation|acquisition)\b",
    "regulatory": r"\b(regulatory|litigation|penalty|show cause)\b",
    "contract": r"\b(order win|contract award|letter of award)\b",
}


def classify(text: str) -> tuple[str, bool]:
    matches = [kind for kind, rule in RULES.items() if re.search(rule, text, re.I)]
    kind = matches[0] if len(matches) == 1 else "unresolved"
    return kind, kind != "dividend"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote: str = Field(min_length=1)
    source_url: str
    page: str


class EventAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal["1"]
    event_id: str
    isin: str = Field(pattern=r"^IN[A-Z0-9]{9}[0-9]$")
    source_url: str
    published_at: int
    assessed_at: int
    classification: str
    facts: list[Evidence]
    financial_materiality: str
    economic_channels: list[str]
    positive_interpretations: list[str]
    negative_interpretations: list[str]
    expectation_uncertainty: str
    unresolved_questions: list[str]
    confidence: float = Field(ge=0, le=1)
    analysis_status: Literal["needs_evidence", "review_required", "reviewed"]

    @model_validator(mode="after")
    def evidence_required(self) -> "EventAnalysis":
        if self.assessed_at < self.published_at:
            raise ValueError("Assessment predates event")
        if self.analysis_status == "reviewed" and not self.facts:
            raise ValueError("Reviewed analysis requires evidence")
        for url in [self.source_url, *(fact.source_url for fact in self.facts)]:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username:
                raise ValueError("HTTPS evidence URL required")
        return self


def accept_analysis(
    session: Session, analysis: EventAnalysis, human_reviewed: bool = False
) -> None:
    event = session.get(ResearchEvent, analysis.event_id)
    if event is None or event.isin != analysis.isin or event.source_url != analysis.source_url:
        raise ValueError("Analysis does not match queued event")
    if event.published_at != analysis.published_at:
        raise ValueError("Publication timestamp mismatch")
    if not human_reviewed or analysis.analysis_status != "reviewed":
        raise ValueError("Verified review required before ingestion")
    if event.analysis is not None:
        raise ValueError("Existing accepted analysis is immutable; submit a versioned event")
    event.analysis = analysis.model_dump(mode="json")
    event.status = "reviewed"
    event.needs_review = False
