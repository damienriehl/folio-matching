"""FOLIO entity ruler.

Ports folio-enrich's ``entity_ruler`` (pattern builder + ruler) but runs on the pure-Python
:class:`~folio_resolve.matching.aho_corasick.AhoCorasickMatcher` instead of spaCy, so it needs
no model download. Pattern IDs encode ``iri|label_type`` exactly as the source, and the
stopword / minimum-length guards are preserved.
"""

from __future__ import annotations

from dataclasses import dataclass

from .matching.aho_corasick import AhoCorasickMatcher
from .ontology import LabelInfo

MIN_PATTERN_LENGTH = 3
_ID_SEP = "|"

# Common short English words that are false-positive matches for FOLIO concepts.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "to", "of", "in", "on", "at", "by", "for", "or",
        "and", "is", "it", "be", "as", "do", "no", "so", "up", "if", "my",
        "me", "he", "we", "am", "us", "go", "re", "al", "de", "la", "le",
        "mr", "ms", "dr", "st", "vs", "id", "ie", "eg", "etc", "per", "via",
        "not", "but", "has", "had", "was", "are", "its", "may", "can", "did",
        "she", "his", "her", "him", "our", "who", "how", "all", "any", "new",
        "one", "two", "out", "own", "set", "use", "way", "day", "get", "see",
        "now", "old", "end", "put", "run", "let", "say", "too", "yet", "off",
        "try", "ask", "got", "met", "cut", "pay", "due", "add",
    }
)

# Confidence assigned to a ruler hit by label type (preferred labels are more trustworthy).
_PREFERRED_CONFIDENCE = 0.72
_ALTERNATIVE_CONFIDENCE = 0.55


@dataclass
class EntityRulerMatch:
    text: str
    start_char: int
    end_char: int
    entity_id: str  # FOLIO IRI (decoded)
    match_type: str  # "preferred" | "alternative"
    confidence: float


def encode_pattern_id(iri: str, label_type: str) -> str:
    return f"{iri}{_ID_SEP}{label_type}"


def decode_pattern_id(pattern_id: str) -> tuple[str, str]:
    if _ID_SEP in pattern_id:
        iri, label_type = pattern_id.rsplit(_ID_SEP, 1)
        return iri, label_type
    return pattern_id, "unknown"


def build_patterns(labels: dict[str, LabelInfo]) -> dict[str, dict[str, object]]:
    """Build matcher patterns (``label -> {id, label_type}``) from ontology labels."""
    patterns: dict[str, dict[str, object]] = {}
    for label_text, info in labels.items():
        if not label_text or label_text in patterns:
            continue
        if len(label_text) < MIN_PATTERN_LENGTH:
            continue
        if label_text.lower() in _STOPWORDS:
            continue
        patterns[label_text] = {
            "id": encode_pattern_id(info.concept.iri, info.label_type),
            "label_type": info.label_type,
        }
    return patterns


class FOLIOEntityRuler:
    """Aho-Corasick ruler over FOLIO labels; emits IRI-tagged spans with char offsets."""

    def __init__(self) -> None:
        self._matcher = AhoCorasickMatcher()
        self._loaded = False

    def load_patterns(self, labels: dict[str, LabelInfo]) -> None:
        self._matcher = AhoCorasickMatcher()
        self._matcher.add_patterns(build_patterns(labels))
        self._matcher.build()
        self._loaded = True

    @property
    def pattern_count(self) -> int:
        return self._matcher.pattern_count

    def find_matches(self, text: str) -> list[EntityRulerMatch]:
        if not self._loaded:
            return []
        out: list[EntityRulerMatch] = []
        for m in self._matcher.search(text):
            raw_id = str(m.value.get("id", ""))
            iri, label_type = decode_pattern_id(raw_id)
            confidence = (
                _PREFERRED_CONFIDENCE if label_type == "preferred" else _ALTERNATIVE_CONFIDENCE
            )
            out.append(
                EntityRulerMatch(
                    text=text[m.start : m.end],
                    start_char=m.start,
                    end_char=m.end,
                    entity_id=iri,
                    match_type=label_type,
                    confidence=confidence,
                )
            )
        return out
