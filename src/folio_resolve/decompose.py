"""Span decomposition — conjunction splitting and shared-head expansion.

Ch02 finding 005 / unit ``12b5e434``: the heading *"Proposed Findings of Fact and Conclusions
of Law"* names **two** sibling FOLIO concepts (``Proposed Findings of Fact`` +
``Proposed Conclusions of Law``) with an elided shared head. No single concept equals the whole
string, so whole-string label matching returns nothing and the tagger emits ``proposed_class``.

The fix is decomposition, not scoring: split on conjunctions and re-attach the shared head so
each part can be matched independently. This module is deterministic and dependency-free.
"""

from __future__ import annotations

import re

# Conjunctions that join co-heads in a compound heading.
_CONJUNCTIONS = (" and ", " or ", " and/or ", "; ", ", and ", ", or ")

# Leading modifiers that form a shared head across conjuncts, e.g. "Proposed <X> and <Y>".
_SHARED_HEAD_PREFIXES = (
    "proposed",
    "draft",
    "amended",
    "supplemental",
    "joint",
    "stipulated",
    "preliminary",
    "final",
)

# Trailing shared tails, e.g. "<X> and <Y> Agreement" -> both get "Agreement".
_SHARED_TAIL_WORDS = (
    "agreement",
    "law",
    "claims",
    "claim",
    "act",
    "clause",
    "clauses",
    "provisions",
    "rights",
)


def _split_on_conjunctions(text: str) -> list[str]:
    pattern = "|".join(re.escape(c) for c in sorted(_CONJUNCTIONS, key=len, reverse=True))
    parts = re.split(pattern, text)
    return [p.strip() for p in parts if p.strip()]


def _leading_shared_head(parts: list[str]) -> str | None:
    """If the first conjunct begins with a shared-head modifier, return that modifier."""
    if not parts:
        return None
    first_words = parts[0].split()
    if first_words and first_words[0].lower() in _SHARED_HEAD_PREFIXES:
        return first_words[0]
    return None


def _trailing_shared_tail(parts: list[str]) -> str | None:
    """If the last conjunct ends with a shared-tail noun, return it (title-cased as written)."""
    if not parts:
        return None
    last_words = parts[-1].split()
    if last_words and last_words[-1].lower() in _SHARED_TAIL_WORDS:
        return last_words[-1]
    return None


def decompose(text: str) -> list[str]:
    """Decompose a compound heading into candidate concept strings.

    Returns the original string plus each conjunct with the elided shared head/tail restored.
    The original is always first so a whole-string match still wins when one exists.

    Examples
    --------
    >>> decompose("Proposed Findings of Fact and Conclusions of Law")
    ['Proposed Findings of Fact and Conclusions of Law', 'Proposed Findings of Fact', 'Proposed Conclusions of Law']
    >>> decompose("Arbitration and Mediation")
    ['Arbitration and Mediation', 'Arbitration', 'Mediation']
    """
    text = text.strip()
    parts = _split_on_conjunctions(text)
    if len(parts) < 2:
        return [text]

    head = _leading_shared_head(parts)
    # A leading shared head ("Proposed X and Y") and a trailing shared tail ("X and Y Law") are
    # mutually exclusive readings; prefer the head when present so we don't append a spurious tail.
    tail = None if head else _trailing_shared_tail(parts)

    expanded: list[str] = [text]
    for i, part in enumerate(parts):
        candidate = part
        # Restore a leading shared head onto conjuncts that lack it (all but the first).
        if head and i > 0 and not candidate.lower().startswith(head.lower()):
            candidate = f"{head} {candidate}"
        # Restore a trailing shared tail onto conjuncts that lack it (all but the last).
        if tail and i < len(parts) - 1 and not candidate.lower().endswith(tail.lower()):
            candidate = f"{candidate} {tail}"
        if candidate not in expanded:
            expanded.append(candidate)
    return expanded
