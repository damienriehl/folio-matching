"""End-to-end pipeline — the Ch02 regression cases running through filter->expand->rank->judge."""

from __future__ import annotations

from folio_matching import (
    AliasBlocklist,
    BlockedAlias,
    DomainPrior,
    InMemoryOntology,
    MatchPipeline,
)
from folio_matching.embedding import BruteForceIndex, HashingEmbeddingProvider


def test_word_order_invariant_match(ontology: InMemoryOntology) -> None:
    pipe = MatchPipeline(ontology=ontology)
    results = pipe.match("rules of arbitration")
    assert results
    assert results[0].iri == "R-arb-rules"


def test_conjoined_heading_resolves_both_siblings(ontology: InMemoryOntology) -> None:
    # Ch02 unit 12b5e434: the compound heading must yield BOTH sibling concepts.
    pipe = MatchPipeline(ontology=ontology)
    results = pipe.match("Proposed Findings of Fact and Conclusions of Law")
    iris = {r.iri for r in results}
    assert "R-findings" in iris
    assert "R-conclusions" in iris


def test_action_not_auction_blocked(ontology: InMemoryOntology) -> None:
    # Ch02 unit 4b06a90c.
    bl = AliasBlocklist([BlockedAlias("Action", "R-auction")])
    pipe = MatchPipeline(ontology=ontology, blocklist=bl)
    results = pipe.match("Action")
    assert all(r.iri != "R-auction" for r in results)


def test_place_name_not_propagated(ontology: InMemoryOntology) -> None:
    # Ch02 finding 003 / Presumptions -> Northern Mariana Islands @90.
    pipe = MatchPipeline(ontology=ontology)
    results = pipe.match("Presumptions")
    # The place-name gate must keep Mariana Islands from topping the list.
    if results:
        assert results[0].iri != "R-mariana"


def test_metadata_source_excluded(ontology: InMemoryOntology) -> None:
    # Ch02 unit d3c44e2a.
    pipe = MatchPipeline(ontology=ontology)
    assert pipe.match("Cross-Examination", section_label="Copyright Page") == []
    assert pipe.match("Cross-Examination", section_label="Chapter 2") != []


def test_semantic_path_recovers_no_shared_token_map() -> None:
    # Ch02 finding 005: "Presumptions" -> "Litigation Burdens of Proof" (no shared label token).
    ont = InMemoryOntology.__new__(InMemoryOntology)
    from folio_matching import Concept

    ont = InMemoryOntology(
        [
            Concept(
                iri="R-burdens",
                label="Litigation Burdens of Proof",
                definition="How presumptions allocate the burden of proof at trial.",
                branch="Objectives",
            ),
        ]
    )
    index = BruteForceIndex(HashingEmbeddingProvider())
    index.build(["R-burdens"], ["Litigation Burdens of Proof"], ["How presumptions allocate the burden of proof at trial."])
    pipe = MatchPipeline(ontology=ont, semantic_index=index, score_floor=0.0)
    results = pipe.match("presumptions burden of proof")
    assert any(r.iri == "R-burdens" and r.extraction_path == "semantic" for r in results)


def test_domain_prior_flows_to_judge(ontology: InMemoryOntology) -> None:
    captured: dict[str, str] = {}

    class FakeJudge:
        def complete(self, system: str, user: str) -> str:
            captured["user"] = user
            return '{"judged": [{"iri_hash": "R-defenses", "adjusted_score": 90, "verdict": "confirmed"}]}'

    prior = DomainPrior.from_manifest_subjects("treatise", [("R-lit", "Litigation")])
    pipe = MatchPipeline(ontology=ontology, judge=FakeJudge())
    results = pipe.match("Litigation Defenses", domain_prior=prior, run_judge=True)
    assert "Litigation" in captured.get("user", "")
    assert results and results[0].iri == "R-defenses"
