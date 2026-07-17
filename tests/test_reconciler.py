"""Reconciler — agreement boost, ruler-only threshold, embedding triage."""

from __future__ import annotations

from folio_resolve import ConceptMatch, Reconciler


def _cm(text: str, iri: str = "", conf: float = 0.7, **kw: object) -> ConceptMatch:
    return ConceptMatch(concept_text=text, folio_iri=iri, confidence=conf, **kw)  # type: ignore[arg-type]


def test_both_agree_gets_boost() -> None:
    r = Reconciler()
    results = r.reconcile([_cm("witness", "R1", 0.7)], [_cm("witness", "R1", 0.6)])
    assert len(results) == 1
    assert results[0].category == "both_agree"
    assert results[0].concept.confidence > 0.7


def test_ruler_only_below_threshold_filtered() -> None:
    r = Reconciler()
    results = r.reconcile([_cm("vague", "R9", 0.35)], [])
    assert results == []


def test_ruler_only_above_threshold_kept() -> None:
    r = Reconciler()
    results = r.reconcile([_cm("deposition", "R2", 0.72)], [])
    assert len(results) == 1
    assert results[0].category == "ruler_only"


def test_llm_only_kept() -> None:
    r = Reconciler()
    results = r.reconcile([], [_cm("presumption", "R3", 0.8)])
    assert results[0].category == "llm_only"


def test_embedding_triage_resolves_iri_conflict() -> None:
    # ruler->R-A, llm->R-B for same text; injected similarity favors R-B.
    def sim_batch(pairs: list[tuple[str, str]]) -> list[float]:
        # pairs: [(text, ruler_label), (text, llm_label)] -> ruler low, llm high
        return [0.2, 0.95]

    r = Reconciler(similarity_batch=sim_batch, index_size=10)
    ruler = [_cm("charge", "R-A", 0.7, folio_label="Encumbrance")]
    llm = [_cm("charge", "R-B", 0.7, folio_label="Criminal Charge")]
    results = r.reconcile_with_embedding_triage(ruler, llm)
    resolved = [x for x in results if x.category == "conflict_resolved"]
    assert len(resolved) == 1
    assert resolved[0].concept.folio_iri == "R-B"
