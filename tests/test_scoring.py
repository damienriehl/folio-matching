"""Scorer behavior — word-order invariance, expansions, specificity penalty."""

from __future__ import annotations

from folio_resolve.scoring import (
    compute_relevance_score,
    content_words,
    generate_search_terms,
    word_overlap,
)


def test_word_order_invariant() -> None:
    # Ch02 finding 004: "arbitration rules" == "rules of arbitration".
    a = content_words("arbitration rules")
    b = content_words("rules of arbitration")
    assert a == b == {"arbitration", "rules"}
    assert word_overlap(a, b) == 1.0


def test_exact_match_scores_99() -> None:
    q = content_words("Antitrust and Competition Law")
    assert compute_relevance_score(q, "Antitrust and Competition Law", "Antitrust and Competition Law") == 99.0


def test_rules_of_arbitration_matches_arbitration_rules() -> None:
    q = content_words("rules of arbitration")
    score = compute_relevance_score(q, "rules of arbitration", "Arbitration Rules")
    assert score >= 85.0


def test_specificity_penalty() -> None:
    q = content_words("Antitrust")
    close = compute_relevance_score(q, "Antitrust", "Antitrust Claims")
    specific = compute_relevance_score(q, "Antitrust", "Antitrust - Bundled Pricing Claims")
    assert specific < close


def test_generate_search_terms_includes_legal_expansions() -> None:
    terms = [t.lower() for t in generate_search_terms("Commercial Litigation")]
    assert "litigation practice" in terms
    assert "litigation service" in terms


def test_generate_search_terms_dedups_and_keeps_full_phrase_first() -> None:
    terms = generate_search_terms("Arbitration")
    assert terms[0] == "Arbitration"
    assert len(terms) == len(set(t.lower() for t in terms))
