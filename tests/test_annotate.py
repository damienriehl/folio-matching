"""Annotate primitives — per-tag verdicts, lifecycle, feedback store, render."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

from folio_resolve.annotate import (
    Annotation,
    ConceptTag,
    Span,
    TagVerdict,
    Verdict,
    bulk_reject,
    cascade_promote,
    promote,
    reject,
    render_segments,
    restore,
)
from folio_resolve.annotate.feedback_store import FeedbackStore
from folio_resolve.annotate.models import FeedbackEntry


def _ann(iri: str, start: int, end: int, text: str, conf: float = 0.9) -> Annotation:
    return Annotation(
        span=Span(start=start, end=end, text=text),
        concepts=[ConceptTag(iri=iri, label=text, confidence=conf)],
    )


def test_per_tag_verdict_model() -> None:
    v = TagVerdict(unit_id="u1", tag_iri="R1", verdict=Verdict.WRONG, note="Action != Auction")
    assert v.verdict == "wrong"
    assert v.note


def test_reject_restore_lifecycle() -> None:
    ann = _ann("R1", 0, 5, "court")
    reject(ann, comment="not relevant")
    assert ann.state == "rejected"
    assert ann.dismissed_at is not None
    assert ann.lineage[-1].action == "user_rejected"
    restore(ann)
    assert ann.state == "confirmed"
    assert ann.dismissed_at is None
    assert ann.lineage[-1].action == "user_restored"


def test_promote_swaps_primary() -> None:
    ann = Annotation(
        span=Span(start=0, end=3, text="law"),
        concepts=[ConceptTag(iri="R1", label="A"), ConceptTag(iri="R2", label="B")],
    )
    promote(ann, 1)
    assert ann.primary_iri == "R2"


def test_cascade_promote() -> None:
    anns = [
        Annotation(
            span=Span(start=0, end=3, text="x"),
            concepts=[ConceptTag(iri="R-old", label="old"), ConceptTag(iri="R-new", label="new")],
        )
        for _ in range(3)
    ]
    updated = cascade_promote(anns, old_iri="R-old", new_iri="R-new")
    assert len(updated) == 3
    assert all(a.primary_iri == "R-new" for a in anns)


def test_bulk_reject() -> None:
    anns = [_ann("R-bad", 0, 1, "a"), _ann("R-bad", 2, 3, "b"), _ann("R-ok", 4, 5, "c")]
    rejected = bulk_reject(anns, folio_iri="R-bad")
    assert len(rejected) == 2
    assert anns[2].state != "rejected"


def test_render_segments_non_overlapping() -> None:
    text = "cross examination of the expert witness"
    anns = [
        _ann("R-cross", 0, 17, "cross examination"),
        _ann("R-witness", 25, 39, "expert witness"),
    ]
    segments = render_segments(text, anns)
    # Segments partition the text with no gaps/overlaps.
    assert segments[0].start == 0
    assert segments[-1].end == len(text)
    for a, b in pairwise(segments):
        assert a.end == b.start


def test_feedback_store_roundtrip_and_insights(tmp_path: Path) -> None:
    store = FeedbackStore(tmp_path)
    store.save(FeedbackEntry(job_id="j1", annotation_id="a1", rating="down", folio_iri="R1", folio_label="X"))
    store.save(FeedbackEntry(job_id="j1", annotation_id="a2", rating="up", folio_iri="R2"))
    store.save(FeedbackEntry(job_id="j1", annotation_id="a3", rating="dismissed", folio_iri="R1", folio_label="X"))
    insights = store.get_insights("j1")
    assert insights.total_feedback == 3
    assert insights.thumbs_up == 1
    assert insights.thumbs_down == 1
    assert insights.total_dismissed == 1
    assert insights.most_downvoted_concepts[0]["iri"] == "R1"
