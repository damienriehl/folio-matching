"""Lemma-key label-index augmentation (build-time, engine-agnostic).

Promoted from folio-enrich ``FolioService._compute_label_lemmas`` after the 2026-07-16 ruler
shootout (``bench/RESULTS.md``): the lemma reachability that made enrich's spaCy ruler look
smarter — the singular surface form *agreement* reaching the plural-labelled concept
*Agreements* — lives in the **label index**, not in any matching engine. Measured on the
shootout gold sets, lemma keys bought +200/200 lemma-gold hits and +698 corpus matches for
+3 trap false positives, and the pure-Python Aho-Corasick ruler consumes them unchanged.

This module therefore augments a ``labels`` dict with lemma keys **before** patterns are built,
keeping the matching runtime zero-heavy-dep:

* spaCy is imported **lazily and only at index-build time** (computing what a label's lemma
  is). Install it via the existing optional extra: ``pip install "folio-resolve[spacy]"``.
* The computed lemma map is **disk-cached** keyed by the ontology content hash plus
  ``LEMMA_VERSION`` (bump it when the lemma rules change), so steady-state consumers never
  touch spaCy at all — they load a small JSON file.
* Without the extra, ``augment_labels(..., on_missing_spacy="skip")`` degrades gracefully to
  the un-augmented index (exactly the shootout's ``ac-base`` behavior); the default raises a
  clear :class:`SpacyNotInstalledError` naming the extra.

Rules (ported verbatim from folio-enrich): only single-word labels longer than 3 characters,
not on the per-ontology ``lemma_denylist`` (legal pluralia tantum such as *damages*), whose
lemma differs from the surface, is longer than 2 characters, and is itself not denylisted.
Lemma keys are tagged ``lemma_preferred`` / ``lemma_alternative`` and never overwrite a
higher-priority existing key (priority: preferred > lemma_preferred > alternative >
lemma_alternative > hidden > translation — folio-enrich's ``match_tier`` ordering).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from pathlib import Path

from .ontology import LabelInfo
from .spec import FOLIO_SPEC

logger = logging.getLogger(__name__)

# Bump when the lemma rules change so cached maps (keyed by ontology hash + this version)
# are not served stale after a logic change. Mirrors folio-enrich's LEMMA_VERSION discipline.
LEMMA_VERSION = "1"

# A lemmatizer: batch of lowercase single-word surfaces -> parallel batch of lemmas.
# Injectable so tests (and non-spaCy consumers with their own lemmatizer) never import spaCy.
Lemmatizer = Callable[[list[str]], list[str]]

LemmaMap = dict[str, str]

# Label-type priority (lower rank wins a single-winner index slot). Port of folio-enrich's
# match_tier ordering; unknown types sort last.
_LABEL_TYPE_ORDER: dict[str, int] = {
    "preferred": 0,
    "lemma_preferred": 1,
    "alternative": 2,
    "lemma_alternative": 3,
    "hidden": 4,
    "translation": 5,
}

# Base label types eligible to seed lemma keys, and the lemma type each produces.
_LEMMA_TYPE_FOR: dict[str, str] = {
    "preferred": "lemma_preferred",
    "alternative": "lemma_alternative",
}

DEFAULT_LEMMA_DENYLIST: frozenset[str] = FOLIO_SPEC.behavior.lemma_denylist


class SpacyNotInstalledError(ImportError):
    """Raised when lemma computation needs spaCy but the ``[spacy]`` extra is not installed."""


def _label_type_rank(label_type: str) -> int:
    return _LABEL_TYPE_ORDER.get(label_type, 99)


def spacy_lemmatizer(model: str = "en_core_web_sm", batch_size: int = 512) -> Lemmatizer:
    """Build a :data:`Lemmatizer` backed by spaCy (lazy import; build-time only).

    Noun lemmatization (*Agreements* -> *agreement*) requires the ``tagger`` and
    ``attribute_ruler`` components — without them spaCy's lemmatizer silently lowercases —
    so the pipeline is loaded with only ``ner``/``parser`` disabled and verified.
    """
    try:
        import spacy
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch in tests
        raise SpacyNotInstalledError(
            "Lemma-key augmentation needs spaCy at index-build time. "
            'Install the optional extra: pip install "folio-resolve[spacy]" '
            "(and the model: python -m spacy download en_core_web_sm). "
            "Runtime matching never needs it — a cached lemma map loads without spaCy."
        ) from exc

    try:
        nlp = spacy.load(model, disable=["ner", "parser"])
    except OSError as exc:
        raise SpacyNotInstalledError(
            f"spaCy is installed but the model {model!r} is not. "
            f"Download it with: python -m spacy download {model}"
        ) from exc

    if not {"tagger", "attribute_ruler"} <= set(nlp.pipe_names):
        raise SpacyNotInstalledError(
            f"spaCy model {model!r} lacks tagger/attribute_ruler (pipes: {nlp.pipe_names}); "
            "noun lemmatization would silently degrade to lowercasing."
        )

    def _lemmatize(words: list[str]) -> list[str]:
        out: list[str] = []
        for doc in nlp.pipe(words, batch_size=batch_size):
            out.append(doc[0].lemma_.lower() if len(doc) else doc.text.lower())
        return out

    return _lemmatize


def compute_label_lemmas(
    labels: Mapping[str, LabelInfo],
    *,
    denylist: frozenset[str] = DEFAULT_LEMMA_DENYLIST,
    lemmatize: Lemmatizer | None = None,
) -> LemmaMap:
    """Map single-word label key -> its lemma, for reachability.

    Only single-word keys (> 3 chars, not denylisted) of ``preferred``/``alternative`` entries
    are considered; a lemma is kept when it differs from the surface, is > 2 chars, and is not
    itself denylisted. Deterministic given the same labels + lemmatizer.
    """
    if lemmatize is None:
        lemmatize = spacy_lemmatizer()

    candidates = sorted(
        key
        for key, info in labels.items()
        if info.label_type in _LEMMA_TYPE_FOR
        and " " not in key
        and len(key) > 3
        and key not in denylist
    )
    if not candidates:
        return {}

    lemma_map: LemmaMap = {}
    for original, lemma in zip(candidates, lemmatize(candidates), strict=True):
        if lemma != original and len(lemma) > 2 and lemma not in denylist:
            lemma_map[original] = lemma
    logger.info("Computed %d label lemmas for reachability", len(lemma_map))
    return lemma_map


def _cache_file(cache_dir: Path, ontology_hash: str) -> Path:
    return cache_dir / f"lemmas_{ontology_hash}_v{LEMMA_VERSION}.json"


def load_lemma_cache(cache_dir: str | Path, ontology_hash: str) -> LemmaMap | None:
    """Load a cached lemma map, or None on miss/corruption (never raises)."""
    path = _cache_file(Path(cache_dir), ontology_hash)
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                logger.info("Loaded %d label lemmas from cache %s", len(data), path.name)
                return {str(k): str(v) for k, v in data.items()}
    except Exception:
        logger.debug("Lemma cache load failed for %s", path, exc_info=True)
    return None


def save_lemma_cache(cache_dir: str | Path, ontology_hash: str, lemma_map: LemmaMap) -> None:
    """Persist a lemma map (best-effort; failures are logged, never raised)."""
    path = _cache_file(Path(cache_dir), ontology_hash)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(lemma_map, indent=0, sort_keys=True), encoding="utf-8")
    except Exception:
        logger.debug("Lemma cache save failed for %s", path, exc_info=True)


def augment_labels(
    labels: Mapping[str, LabelInfo],
    *,
    lemma_map: LemmaMap | None = None,
    lemmatize: Lemmatizer | None = None,
    denylist: frozenset[str] = DEFAULT_LEMMA_DENYLIST,
    cache_dir: str | Path | None = None,
    ontology_hash: str | None = None,
    on_missing_spacy: str = "raise",
) -> dict[str, LabelInfo]:
    """Return a copy of ``labels`` with lemma keys added (the shootout's winning index).

    Resolution order for the lemma map: an explicit ``lemma_map`` argument; then the disk
    cache (when ``cache_dir`` + ``ontology_hash`` are given); then a fresh computation via
    ``lemmatize`` (defaulting to :func:`spacy_lemmatizer`, which needs the ``[spacy]`` extra),
    which is then cached.

    ``on_missing_spacy``: ``"raise"`` (default) propagates :class:`SpacyNotInstalledError`;
    ``"skip"`` logs a warning and returns the index unchanged — matching degrades to exactly
    the un-augmented (``ac-base``) behavior instead of crashing the consumer.
    """
    if on_missing_spacy not in ("raise", "skip"):
        raise ValueError(f"on_missing_spacy must be 'raise' or 'skip', got {on_missing_spacy!r}")

    cacheable = cache_dir is not None and ontology_hash is not None
    if lemma_map is None and cacheable:
        assert cache_dir is not None and ontology_hash is not None  # for the type-checker
        lemma_map = load_lemma_cache(cache_dir, ontology_hash)

    if lemma_map is None:
        try:
            lemma_map = compute_label_lemmas(labels, denylist=denylist, lemmatize=lemmatize)
        except SpacyNotInstalledError:
            if on_missing_spacy == "skip":
                logger.warning(
                    "spaCy unavailable — skipping lemma-key augmentation "
                    '(install "folio-resolve[spacy]" to enable it)'
                )
                return dict(labels)
            raise
        if cacheable:
            assert cache_dir is not None and ontology_hash is not None
            save_lemma_cache(cache_dir, ontology_hash, lemma_map)

    out: dict[str, LabelInfo] = dict(labels)
    added = 0
    for surface, lemma in lemma_map.items():
        info = labels.get(surface)
        if info is None:
            continue
        lemma_type = _LEMMA_TYPE_FOR.get(info.label_type)
        if lemma_type is None:
            continue
        existing = out.get(lemma)
        if existing is not None and _label_type_rank(existing.label_type) <= _label_type_rank(
            lemma_type
        ):
            continue  # never overwrite an equal-or-higher-priority key
        out[lemma] = LabelInfo(concept=info.concept, label_type=lemma_type)
        added += 1
    logger.info("Lemma augmentation added %d keys (%d -> %d)", added, len(labels), len(out))
    return out
