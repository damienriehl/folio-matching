"""folio-matching — the shared FOLIO source-text-to-concept matching engine.

A lift-and-improve extraction of the matching intelligence that previously lived — and diverged —
across folio-mapper, folio-enrich, and folio-insights (informally shared through a fragile
``sys.path`` hack). This package is the single pinned source of truth: the word-order-invariant
scorer, span decomposition, the place-name / short-label gates, the alias blocklist, the
domain-prior judge, and the annotate primitives.

Public surface (see module docstrings for provenance):

* scoring       — ``compute_relevance_score``, ``word_overlap``, ``LEGAL_TERM_EXPANSIONS``
* ontology      — ``Concept``, ``OntologyProvider``, ``InMemoryOntology``, ``FolioPythonProvider``
* entity_ruler  — ``FOLIOEntityRuler`` (pure-Python Aho-Corasick)
* reconciler    — ``Reconciler``, ``ConceptMatch``
* decompose     — ``decompose`` (conjunction split + shared-head)
* gates         — ``PlaceNameGate``, ``ShortLabelGate``
* blocklist     — ``AliasBlocklist`` (Action != Auction)
* sources       — ``SourceClassifier`` (metadata/front-matter exclusion)
* domain_prior  — ``DomainPrior``, ``DomainPriorSuggester``, ``TaxonomyNode`` (multi-tag)
* calibration   — ``ScoreCalibration`` (weak-band recalibration)
* judge         — ``Judge``, ``build_judge_prompt``, ``parse_judge_json``
* pipeline      — ``MatchPipeline`` (filter -> expand -> rank -> judge)
* annotate      — ``ConceptTag``, ``TagVerdict``, ``Annotation``, ``FeedbackStore``, lifecycle
"""

from __future__ import annotations

__version__ = "0.1.0"

from .blocklist import AliasBlocklist, BlockedAlias
from .calibration import CalibrationSample, ScoreCalibration
from .decompose import decompose
from .domain_prior import DomainPrior, DomainPriorSuggester, SubjectTag, TagStatus, TaxonomyNode
from .entity_ruler import FOLIOEntityRuler
from .gates import GateDecision, PlaceNameGate, ShortLabelGate
from .judge import Judge, build_judge_prompt, enforce_verdict, parse_judge_json
from .ontology import Concept, FolioPythonProvider, InMemoryOntology, LabelInfo, OntologyProvider
from .pipeline import MatchCandidate, MatchPipeline
from .reconciler import ConceptMatch, Reconciler, ReconciliationResult
from .scoring import (
    LEGAL_TERM_EXPANSIONS,
    SEARCH_STOPWORDS,
    compute_relevance_score,
    content_words,
    generate_search_terms,
    tokenize,
    word_overlap,
)
from .sources import SourceClassifier, SourceType
from .spec import BUILTIN_SPECS, CANON_SPEC, FOLIO_SPEC, OntologySpec

__all__ = [
    "BUILTIN_SPECS",
    "CANON_SPEC",
    "FOLIO_SPEC",
    "LEGAL_TERM_EXPANSIONS",
    "SEARCH_STOPWORDS",
    "AliasBlocklist",
    "BlockedAlias",
    "CalibrationSample",
    "Concept",
    "ConceptMatch",
    "DomainPrior",
    "DomainPriorSuggester",
    "FOLIOEntityRuler",
    "FolioPythonProvider",
    "GateDecision",
    "InMemoryOntology",
    "Judge",
    "LabelInfo",
    "MatchCandidate",
    "MatchPipeline",
    "OntologyProvider",
    "OntologySpec",
    "PlaceNameGate",
    "Reconciler",
    "ReconciliationResult",
    "ScoreCalibration",
    "ShortLabelGate",
    "SourceClassifier",
    "SourceType",
    "SubjectTag",
    "TagStatus",
    "TaxonomyNode",
    "__version__",
    "build_judge_prompt",
    "compute_relevance_score",
    "content_words",
    "decompose",
    "enforce_verdict",
    "generate_search_terms",
    "parse_judge_json",
    "tokenize",
    "word_overlap",
]
