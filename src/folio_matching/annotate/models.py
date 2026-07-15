"""Annotation data models.

Lifted from folio-enrich ``models/annotation.py`` + ``models/feedback.py`` and extended with
``ConceptTag`` and ``TagVerdict`` — the per-tag ``correct``/``weak``/``wrong`` + note affordance
the Ch02 review directed ("classification must be PER TAG, not per unit").
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Verdict(StrEnum):
    CORRECT = "correct"
    WEAK = "weak"
    WRONG = "wrong"


class Span(BaseModel):
    start: int
    end: int
    text: str
    sentence_text: str | None = None


class StageEvent(BaseModel):
    """A single step in an annotation's lineage (which stage did what, when)."""

    stage: str
    action: str  # "created" | "confirmed" | "rejected" | "restored" | "user_promotion" | ...
    detail: str = ""
    confidence: float | None = None
    reasoning: str = ""
    timestamp: str = Field(default_factory=_now)


class FeedbackItem(BaseModel):
    """Thumbs up/down + note on an annotation or a specific stage event."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    rating: str  # "up" | "down"
    stage: str | None = None
    comment: str = ""
    created_at: str = Field(default_factory=_now)


class ConceptTag(BaseModel):
    """A FOLIO concept anchored to a span within a unit, with why-it-fired provenance."""

    iri: str
    label: str
    confidence: float = 0.0
    branch: str = ""
    extraction_path: str = ""  # "entity_ruler" | "llm" | "semantic" | "heading_context" | "proposed_class"
    match_score: float | None = None
    span: Span | None = None


class TagVerdict(BaseModel):
    """A reviewer's per-tag judgment — the missing per-tag layer.

    Feeds the self-improving loop: a ``wrong`` verdict on a homonym appends to the alias
    blocklist; ``correct``/``weak``/``wrong`` at the match score train the score calibration; each
    verdict is a regression fixture.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    unit_id: str
    run_id: str = ""
    corpus_name: str = ""
    tag_iri: str
    tag_label: str = ""
    extraction_path: str = ""
    match_score: float | None = None
    verdict: Verdict
    note: str = ""
    domain_prior: str = ""
    book: str = ""
    chapter: str = ""
    reviewer: str = ""
    reviewed_at: str = Field(default_factory=_now)


class Annotation(BaseModel):
    """A span with one or more concept candidates, a state, lineage, and feedback."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    span: Span
    concepts: list[ConceptTag] = Field(default_factory=list)
    state: str = "preliminary"  # "preliminary" | "confirmed" | "rejected"
    dismissed_at: str | None = None
    lineage: list[StageEvent] = Field(default_factory=list)
    feedback: list[FeedbackItem] = Field(default_factory=list)

    @property
    def primary_iri(self) -> str:
        return self.concepts[0].iri if self.concepts else ""


class FeedbackEntry(BaseModel):
    """A self-contained feedback record that outlives job cleanup."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    annotation_id: str
    rating: str  # "up" | "down" | "dismissed"
    stage: str | None = None
    comment: str = ""
    annotation_text: str = ""
    sentence_text: str | None = None
    folio_iri: str | None = None
    folio_label: str | None = None
    lineage: list[dict[str, object]] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)


class InsightsSummary(BaseModel):
    """Aggregated feedback insights."""

    total_feedback: int = 0
    thumbs_up: int = 0
    thumbs_down: int = 0
    total_dismissed: int = 0
    by_stage: dict[str, dict[str, int]] = Field(default_factory=dict)
    most_downvoted_concepts: list[dict[str, object]] = Field(default_factory=list)
    most_dismissed_concepts: list[dict[str, object]] = Field(default_factory=list)
    recent_feedback: list[FeedbackEntry] = Field(default_factory=list)
