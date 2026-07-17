"""Multi-tag domain prior (Damien's amended design).

Ch02 finding 002: give the judge the document-level domain prior so *"Defenses"* disambiguates
to *Litigation Defenses* in a litigation treatise. Damien amended the shape:

    A single corpus carries MULTIPLE subject tags (e.g. "Personal Injury Depositions" =
    Personal Injury + Deposition). The library (1) SUGGESTS candidate tags with confidence,
    (2) lets a human validate / invalidate, and (3) lets a human ADD tags via a type-ahead
    FOLIO taxonomy-tree picker. Validated tags flow into every judge call.

This module ships the data model + suggestion engine (the library half). The type-ahead picker
UI is folio-insights v2 work; here we expose the ``TaxonomyNode`` tree model it drives (shaped to
be folio-api ``/taxonomy/tree`` compatible) and the validate/invalidate/add API it calls.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from .ontology import OntologyProvider
from .scoring import content_words


class TagStatus(StrEnum):
    SUGGESTED = "suggested"  # proposed by the suggester, awaiting human review
    VALIDATED = "validated"  # human confirmed
    INVALIDATED = "invalidated"  # human rejected
    ADDED = "added"  # human added directly (via the picker)


@dataclass
class SubjectTag:
    """One practice-area / subject tag on a corpus."""

    iri: str
    label: str
    confidence: float = 1.0
    status: TagStatus = TagStatus.SUGGESTED
    source: str = "suggester"  # "suggester" | "human" | "manifest"

    @property
    def is_active(self) -> bool:
        """Active tags flow into judge calls: validated, added, or manifest-declared."""
        return self.status in (TagStatus.VALIDATED, TagStatus.ADDED)


@dataclass
class TaxonomyNode:
    """A node in the FOLIO taxonomy tree, for the type-ahead picker.

    Shaped to be compatible with folio-api's ``/taxonomy/tree`` payload so a UI can render and
    search the same structure. ``children`` may be lazily populated.
    """

    iri: str
    label: str
    definition: str | None = None
    parent_iri: str | None = None
    children: list[TaxonomyNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "iri": self.iri,
            "label": self.label,
            "definition": self.definition,
            "parent_iri": self.parent_iri,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class DomainPrior:
    """The set of subject tags for one corpus, with a validate / invalidate / add lifecycle."""

    corpus_name: str
    tags: list[SubjectTag] = field(default_factory=list)

    def _find(self, iri: str) -> SubjectTag | None:
        return next((t for t in self.tags if t.iri == iri), None)

    def add(self, iri: str, label: str, *, confidence: float = 1.0, source: str = "human") -> SubjectTag:
        """Add a tag directly (human picked it from the taxonomy tree)."""
        existing = self._find(iri)
        if existing is not None:
            existing.status = TagStatus.ADDED
            existing.source = source
            return existing
        tag = SubjectTag(
            iri=iri, label=label, confidence=confidence, status=TagStatus.ADDED, source=source
        )
        self.tags.append(tag)
        return tag

    def validate(self, iri: str) -> SubjectTag | None:
        tag = self._find(iri)
        if tag is not None:
            tag.status = TagStatus.VALIDATED
        return tag

    def invalidate(self, iri: str) -> SubjectTag | None:
        tag = self._find(iri)
        if tag is not None:
            tag.status = TagStatus.INVALIDATED
        return tag

    def merge_suggestions(self, suggestions: Iterable[SubjectTag]) -> None:
        """Add suggested tags that are not already present (never overwrites human decisions)."""
        for sug in suggestions:
            if self._find(sug.iri) is None:
                self.tags.append(sug)

    def active_tags(self) -> list[SubjectTag]:
        """Tags that flow into judge calls."""
        return [t for t in self.tags if t.is_active]

    def as_judge_context(self) -> str:
        """Render the active prior as a document-type string for the judge prompt builders."""
        labels = [t.label for t in self.active_tags()]
        if not labels:
            return ""
        if len(labels) == 1:
            return labels[0]
        return " / ".join(labels)

    @classmethod
    def from_manifest_subjects(
        cls, corpus_name: str, subjects: Sequence[tuple[str, str]]
    ) -> DomainPrior:
        """Build a prior from human-declared ``(iri, label)`` subjects on a CorpusManifest."""
        return cls(
            corpus_name=corpus_name,
            tags=[
                SubjectTag(iri=iri, label=label, status=TagStatus.ADDED, source="manifest")
                for iri, label in subjects
            ],
        )


class DomainPriorSuggester:
    """Auto-detect candidate subject tags for a corpus and SUGGEST them for human validation.

    Strategy: extract salient phrases from a corpus summary (title, sample headings, sample text),
    search them against the ontology, and return the strongest distinct concepts as suggestions.
    Deterministic and dependency-free beyond the injected ``OntologyProvider``.
    """

    def __init__(
        self, ontology: OntologyProvider, *, max_suggestions: int = 5, min_score: float = 70.0
    ) -> None:
        self._ontology = ontology
        self._max = max_suggestions
        self._min_score = min_score

    def suggest(
        self, *, title: str = "", headings: Sequence[str] = (), sample_text: str = ""
    ) -> list[SubjectTag]:
        phrases = self._candidate_phrases(title, headings, sample_text)
        best_by_iri: dict[str, SubjectTag] = {}
        for phrase in phrases:
            for concept, score in self._ontology.search_by_label(phrase, limit=3):
                if score < self._min_score:
                    continue
                prior = best_by_iri.get(concept.iri)
                confidence = round(min(score / 100.0, 1.0), 3)
                if prior is None or confidence > prior.confidence:
                    best_by_iri[concept.iri] = SubjectTag(
                        iri=concept.iri,
                        label=concept.preferred_label or concept.label,
                        confidence=confidence,
                        status=TagStatus.SUGGESTED,
                        source="suggester",
                    )
        ranked = sorted(best_by_iri.values(), key=lambda t: t.confidence, reverse=True)
        return ranked[: self._max]

    def _candidate_phrases(self, title: str, headings: Sequence[str], sample_text: str) -> list[str]:
        phrases: list[str] = []
        if title.strip():
            phrases.append(title.strip())
        phrases.extend(h.strip() for h in headings if h.strip())
        # Salient bigrams from the title supply "Personal Injury" + "Depositions" style splits.
        title_words = [w for w in title.split() if content_words(w)]
        for i in range(len(title_words) - 1):
            phrases.append(f"{title_words[i]} {title_words[i + 1]}")
        for w in title_words:
            if len(w) >= 5:
                phrases.append(w)
        # Deduplicate preserving order.
        seen: set[str] = set()
        out: list[str] = []
        for p in phrases:
            pl = p.lower()
            if pl and pl not in seen:
                seen.add(pl)
                out.append(p)
        return out
