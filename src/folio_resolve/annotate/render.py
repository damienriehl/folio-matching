"""Span-layout primitive — the boundary-sweep, ported to Python.

folio-enrich's ``renderAnnotatedText`` computes non-overlapping display segments from possibly
overlapping/nested annotation spans by collecting all boundary points, sorting them, and, for each
adjacent-point segment, finding the annotations that cover it. That algorithm is display-framework
agnostic, so we lift it as a **library primitive** that returns ``RenderedSegment`` offset tuples;
the folio-insights v2 Svelte component (separate op) consumes these to draw nested chips. Returning
offsets — not HTML — keeps the library UI-neutral.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Annotation


@dataclass(frozen=True)
class RenderedSegment:
    start: int
    end: int
    text: str
    annotation_ids: tuple[str, ...]  # covering annotations, highest-confidence-first


def render_segments(text: str, annotations: list[Annotation]) -> list[RenderedSegment]:
    """Flatten overlapping annotation spans into ordered, non-overlapping display segments."""
    if not text:
        return []

    points: set[int] = {0, len(text)}
    for ann in annotations:
        points.add(max(0, ann.span.start))
        points.add(min(len(text), ann.span.end))
    ordered = sorted(p for p in points if 0 <= p <= len(text))

    segments: list[RenderedSegment] = []
    for i in range(len(ordered) - 1):
        seg_start, seg_end = ordered[i], ordered[i + 1]
        if seg_start >= seg_end:
            continue
        covering = [
            ann for ann in annotations if ann.span.start <= seg_start and ann.span.end >= seg_end
        ]
        # Dedup by primary IRI, keeping the highest-confidence annotation per IRI.
        best_by_iri: dict[str, Annotation] = {}
        for ann in covering:
            iri = ann.primary_iri or f"__no_iri_{ann.id}"
            conf = ann.concepts[0].confidence if ann.concepts else 0.0
            existing = best_by_iri.get(iri)
            existing_conf = (
                existing.concepts[0].confidence if existing and existing.concepts else -1.0
            )
            if existing is None or conf > existing_conf:
                best_by_iri[iri] = ann
        ranked = sorted(
            best_by_iri.values(),
            key=lambda a: (a.concepts[0].confidence if a.concepts else 0.0),
            reverse=True,
        )
        segments.append(
            RenderedSegment(
                start=seg_start,
                end=seg_end,
                text=text[seg_start:seg_end],
                annotation_ids=tuple(a.id for a in ranked),
            )
        )
    return segments
