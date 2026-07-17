"""Aho-Corasick matcher + entity ruler contract (ported from enrich's test_aho_corasick)."""

from __future__ import annotations

from folio_resolve import Concept, FOLIOEntityRuler, InMemoryOntology
from folio_resolve.matching import AhoCorasickMatcher


def test_match_offsets_and_word_boundary() -> None:
    m = AhoCorasickMatcher()
    m.add_pattern("court")
    m.build()
    hits = m.search("The court ruled.")
    assert len(hits) == 1
    assert (hits[0].start, hits[0].end) == (4, 9)
    assert "The court ruled."[hits[0].start : hits[0].end] == "court"


def test_word_boundary_rejects_substring() -> None:
    m = AhoCorasickMatcher()
    m.add_pattern("contract")
    m.build()
    # "contractual" must NOT match "contract".
    assert m.search("a contractual clause") == []
    assert len(m.search("the contract terms")) == 1


def test_overlap_longer_wins_partial() -> None:
    m = AhoCorasickMatcher()
    m.add_patterns({"burden of proof": {}, "proof of service": {}})
    m.build()
    # Non-overlapping distinct phrases both survive.
    hits = m.search("burden of proof and proof of service")
    labels = sorted(h.pattern for h in hits)
    assert labels == ["burden of proof", "proof of service"]


def test_contained_spans_both_kept() -> None:
    m = AhoCorasickMatcher()
    m.add_patterns({"cross": {}, "cross-examination": {}})
    m.build()
    hits = m.search("cross-examination begins")
    patterns = {h.pattern for h in hits}
    assert "cross-examination" in patterns
    assert "cross" in patterns  # contained, both survive


def test_entity_ruler_emits_iri_tagged_spans() -> None:
    ont = InMemoryOntology(
        [Concept(iri="R-cross", label="Cross-Examination", alternative_labels=("Cross Exam",))]
    )
    ruler = FOLIOEntityRuler()
    ruler.load_patterns(ont.all_labels())
    matches = ruler.find_matches("The cross-examination was brutal.")
    assert any(mm.entity_id == "R-cross" and mm.match_type == "preferred" for mm in matches)


def test_entity_ruler_confidence_by_label_type() -> None:
    ont = InMemoryOntology(
        [Concept(iri="R-x", label="Deposition", alternative_labels=("Depo",))]
    )
    ruler = FOLIOEntityRuler()
    ruler.load_patterns(ont.all_labels())
    pref = ruler.find_matches("A deposition today.")
    alt = ruler.find_matches("A depo today.")
    assert pref[0].confidence > alt[0].confidence
