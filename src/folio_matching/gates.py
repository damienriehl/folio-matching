"""Match gates — deterministic guards that demote pathological candidates.

Two Ch02 failures share a root cause: the rapidfuzz label matcher pathologically over-scores
short country/place labels. ``search_concepts("Presumptions")`` returned *Northern Mariana
Islands, Portugal, Spain, Puerto Rico, Réunion* all at 90 — above the genuinely relevant
*Presumption of Innocence* at 86. That single defect explains both:

* finding 003 — "Slovenia" in a heading propagating to 99 units, and
* the recall noise that buries real concepts under place-name hits.

``PlaceNameGate`` demotes geographic concepts unless corroborated. ``ShortLabelGate`` demotes
matches on very short / single-content-word labels unless the evidence is near-exact. Both are
pure functions over a candidate; they return an adjusted score and a reason.
"""

from __future__ import annotations

from dataclasses import dataclass

from .scoring import content_words

# Branch labels (and substrings) that indicate a geographic/place concept in FOLIO.
_PLACE_BRANCH_MARKERS = ("location", "geograph", "country", "jurisdiction", "place")

# A curated set of place-name tokens that notoriously over-score. Extend from verdict data.
_PLACE_NAME_TOKENS = frozenset(
    {
        "slovenia", "portugal", "spain", "reunion", "puerto", "rico", "mariana",
        "islands", "guam", "samoa", "chad", "mali", "togo", "fiji", "oman",
        "qatar", "peru", "cuba", "chile", "kenya", "ghana", "nepal",
    }
)

# Score floor a demoted candidate is pushed to (below the typical weak-band).
_DEMOTED_SCORE = 40.0


@dataclass(frozen=True)
class GateDecision:
    score: float
    demoted: bool
    reason: str


def _is_place_concept(label: str, branch: str) -> bool:
    branch_l = branch.lower()
    if any(marker in branch_l for marker in _PLACE_BRANCH_MARKERS):
        return True
    label_tokens = {t.lower() for t in label.split()}
    return bool(label_tokens & _PLACE_NAME_TOKENS)


class PlaceNameGate:
    """Demote place-name candidates unless corroborated by ≥ ``min_signals`` signals."""

    def __init__(self, min_signals: int = 2, demoted_score: float = _DEMOTED_SCORE) -> None:
        self._min_signals = min_signals
        self._demoted_score = demoted_score

    def evaluate(
        self,
        *,
        query: str,
        label: str,
        branch: str,
        score: float,
        heading_context_match: bool = False,
        corroborating_signals: int = 1,
    ) -> GateDecision:
        if not _is_place_concept(label, branch):
            return GateDecision(score=score, demoted=False, reason="not-a-place")

        # An exact label match to the query is always allowed — the place is really named.
        if query.strip().lower() == label.strip().lower():
            return GateDecision(score=score, demoted=False, reason="exact-place-name")

        signals = corroborating_signals + (1 if heading_context_match else 0)
        if signals >= self._min_signals:
            return GateDecision(score=score, demoted=False, reason="corroborated-place")

        return GateDecision(
            score=min(score, self._demoted_score),
            demoted=True,
            reason=f"place-name demoted (signals={signals} < {self._min_signals})",
        )


class ShortLabelGate:
    """Demote fuzzy hits on very short or single-content-word labels."""

    def __init__(
        self, min_chars: int = 4, near_exact_threshold: float = 95.0, demoted_score: float = _DEMOTED_SCORE
    ) -> None:
        self._min_chars = min_chars
        self._near_exact = near_exact_threshold
        self._demoted_score = demoted_score

    def evaluate(self, *, query: str, label: str, score: float) -> GateDecision:
        short_by_chars = len(label.strip()) < self._min_chars
        single_content = len(content_words(label)) <= 1
        if not (short_by_chars or single_content):
            return GateDecision(score=score, demoted=False, reason="not-short")

        # Allow if the evidence is near-exact (real, specific match) or an exact string equality.
        if score >= self._near_exact or query.strip().lower() == label.strip().lower():
            return GateDecision(score=score, demoted=False, reason="near-exact-short-label")

        return GateDecision(
            score=min(score, self._demoted_score),
            demoted=True,
            reason="short-label demoted (fuzzy match below near-exact)",
        )
