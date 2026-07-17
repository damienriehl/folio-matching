"""Annotation lifecycle transitions.

Ported from folio-enrich's ``api/routes/enrich.py`` endpoints as pure functions: reject / restore
/ promote / cascade-promote / bulk-reject. Each stamps a ``StageEvent(stage="user", ...)`` onto
the annotation's lineage — the per-annotation audit trail — exactly as the source did at the route
layer. Keeping these framework-free lets any consumer (FastAPI, CLI, the folio-insights annotator)
reuse the same transitions.
"""

from __future__ import annotations

from .models import Annotation, StageEvent, _now


def reject(annotation: Annotation, *, comment: str = "") -> Annotation:
    annotation.state = "rejected"
    annotation.dismissed_at = _now()
    annotation.lineage.append(
        StageEvent(stage="user", action="user_rejected", detail=comment)
    )
    return annotation


def restore(annotation: Annotation) -> Annotation:
    annotation.state = "confirmed"
    annotation.dismissed_at = None
    annotation.feedback = []
    annotation.lineage.append(StageEvent(stage="user", action="user_restored"))
    return annotation


def promote(annotation: Annotation, concept_index: int) -> Annotation:
    """Swap a backup concept to primary (index 0)."""
    if not 0 <= concept_index < len(annotation.concepts):
        raise IndexError(f"concept_index {concept_index} out of range")
    concept = annotation.concepts.pop(concept_index)
    annotation.concepts.insert(0, concept)
    annotation.state = "confirmed"
    annotation.lineage.append(
        StageEvent(stage="user", action="user_promotion", detail=f"promoted {concept.iri}")
    )
    return annotation


def cascade_promote(
    annotations: list[Annotation], *, old_iri: str, new_iri: str
) -> list[Annotation]:
    """Promote ``new_iri`` over ``old_iri`` across every annotation where both are present."""
    updated: list[Annotation] = []
    for ann in annotations:
        if ann.primary_iri != old_iri:
            continue
        idx = next((i for i, c in enumerate(ann.concepts) if c.iri == new_iri), None)
        if idx is None:
            continue
        promote(ann, idx)
        ann.lineage.append(
            StageEvent(stage="user", action="user_promotion", detail=f"Cascade: {old_iri} -> {new_iri}")
        )
        updated.append(ann)
    return updated


def bulk_reject(annotations: list[Annotation], *, folio_iri: str, comment: str = "") -> list[str]:
    """Reject every non-rejected annotation whose primary IRI is ``folio_iri``. Returns their ids."""
    rejected_ids: list[str] = []
    for ann in annotations:
        if ann.state != "rejected" and ann.primary_iri == folio_iri:
            reject(ann, comment=comment)
            rejected_ids.append(ann.id)
    return rejected_ids
