"""Shared fixtures.

The concepts and cases here are **synthetic / paraphrased** — this repo is public, so no book
source text and no real matter data. The recorded Ch02 failure *cases* (place-name over-scoring,
Action≠Auction, conjoined headings, metadata sources, semantic-only maps) are reproduced as
minimal synthetic fixtures so the regressions are pinned in CI.
"""

from __future__ import annotations

import pytest

from folio_resolve import Concept, InMemoryOntology


@pytest.fixture
def ontology() -> InMemoryOntology:
    return InMemoryOntology(
        [
            Concept(iri="R-arb-rules", label="Arbitration Rules", branch="Service"),
            Concept(iri="R-defenses", label="Litigation Defenses", branch="Objectives"),
            Concept(
                iri="R-burdens",
                label="Litigation Burdens of Proof",
                definition="Allocation of the burden of proof, including presumptions.",
                branch="Objectives",
            ),
            Concept(iri="R-findings", label="Proposed Findings of Fact", branch="Document Artifacts"),
            Concept(iri="R-conclusions", label="Proposed Conclusions of Law", branch="Document Artifacts"),
            # Homonym trap: the auction concept that the fuzzy matcher pairs with "Action".
            Concept(iri="R-auction", label="Auction", branch="Events"),
            Concept(iri="R-litigation-action", label="Cause of Action", branch="Objectives"),
            # Place-name trap.
            Concept(iri="R-slovenia", label="Slovenia", branch="Location"),
            Concept(iri="R-mariana", label="Northern Mariana Islands", branch="Location"),
            Concept(iri="R-cross-exam", label="Cross-Examination", branch="Service"),
        ]
    )
