---
plan_id: 2026-07-15-001-feat-folio-matching-v0
title: folio-matching v0 — the shared FOLIO source-text→concept matching library
date: 2026-07-15
status: executing
author: folio-matching v0 execution agent (Fable lane)
approved_by: Damien (architecture, 2026-07-15)
compounds:
  - briefs/qa/2026-07-15-folio-matching-arch-answers.json  (the 6 decisions + amendments)
  - folio-insights/docs/brainstorms/2026-07-15-folio-matching-platform-brainstorm.md (bb161ee)
  - briefs/qa/2026-07-15-folio-insights-annot-answers.json  (the Ch02 verdicts that seeded this)
---

# folio-matching v0 — Plan

## 1. Intent & approved shape

Damien approved a **hybrid** architecture on 2026-07-15:

- A **new standalone `folio-matching` repo** (MIT, public, `damienriehl` org) is the pinned
  **library core** — the single source of truth for FOLIO source-text→concept matching.
- **Feedback/calibration is proven in folio-insights first**, then promoted to the shared
  layer at this v0 cut (per `feedback_share`: "PULL THE FOLIO-ENRICH FEATURES TOO … folio-matching
  must be a FIRST-CLASS, FEATURE-RICH repo, not a minimal extraction").
- The **hosted `/match` service is DEFERRED** — the library covers every current (Python) consumer.
- **Migration is opportunistic** with a **written schedule** (`docs/migration/SCHEDULE.md`); Damien
  is reminded which repo is next as each lands.

This is a **lift-and-improve**, not a rewrite. The engines already exist and are informally shared
through a fragile `sys.path` hack (folio-mapper wrote the scorer, folio-enrich forked it, folio-insights
`sys.path`-imports both). v0 formalizes that coupling into a real pinned package and adds the
capabilities the Ch02 verdicts demand.

## 2. Design principles

1. **Pure-Python core, optional heavy adapters.** The scoring, decomposition, gates, blocklist,
   domain-prior, reconciler, and annotate primitives depend on **nothing heavier than pydantic**. FAISS,
   sentence-transformers, spaCy, pyahocorasick, and folio-python live behind `Protocol` seams and
   optional extras, each with a working pure-Python default. This is why the whole test suite runs in
   CI with no model downloads and no network.
2. **Ontology-neutral.** Matching is not hardwired to FOLIO. `OntologySpec` (FOLIO_SPEC + CANON_SPEC)
   carries the per-ontology behavior (exclusions, lemma denylist, iri roots). Lifted intact from enrich.
3. **Lineage is a first-class record, kept at the annotate layer** — the scorer/ruler/reconciler never
   touch it, exactly as in enrich. Port that separation.
4. **Every recorded failure becomes a regression fixture** (synthetic/paraphrased — the repo is public,
   so no book source text). Green CI is the definition of "self-improving becomes durable, not vibes."

## 3. Extraction inventory (what comes from where)

| New module | Lifted from | What |
|---|---|---|
| `scoring.py` | folio-mapper `folio_service.py` | `_compute_relevance_score`, `word_overlap`, `tokenize`, `content_words`, `LEGAL_TERM_EXPANSIONS`, `SEARCH_STOPWORDS`, `BRANCH_SIGNAL_WORDS` — word-order-invariant set scoring (solves finding 004) |
| `search.py` | folio-mapper `_generate_search_terms` + enrich `folio/search.py` | multi-strategy term generation (sub-phrases, content words, legal expansions, stem-prefix) over an `OntologyProvider`; unifies the mapper original and enrich's "ported-from-mapper" fork |
| `ontology.py` | new seam | `Concept`, `LabelInfo`, `OntologyProvider` Protocol; `FolioPythonProvider` optional adapter; `InMemoryOntology` for tests |
| `spec.py` | enrich `ontology/spec.py` | `OntologySpec`/`OntologyBehavior`/`OntologyCoords`, `FOLIO_SPEC`, `CANON_SPEC`, lemma denylist |
| `matching/aho_corasick.py` | enrich `matching/aho_corasick.py` | multi-pattern matcher + containment-aware overlap resolution; **reimplemented pure-Python** (drops the `pyahocorasick` C dep), same `MatchResult` contract + word-boundary rules |
| `entity_ruler.py` | enrich `entity_ruler/{ruler,pattern_builder}.py` | pattern builder (label_type-encoded IDs, stopword/min-length guard) + ruler that runs on the pure-Python matcher (spaCy adapter optional) |
| `reconciler.py` | enrich `reconciliation/reconciler.py` | `ConceptMatch`, `Reconciler.reconcile()` + `reconcile_with_embedding_triage()`, diminishing boost, `RULER_ONLY_MIN_CONFIDENCE`, categories |
| `pipeline.py` | folio-mapper `pipeline/` | 4-stage orchestrator interface filter→expand→rank→judge; embedding-rerank blend; pluggable stages |
| `judge.py` | folio-mapper `stage3_judge.py` + enrich `contextual_rerank.py`/`branch_judge.py` | `Judge` Protocol, verdict enforcement (rejected→0, confirmed±5, boost cap +25), the 90+/70-89/50-69 calibration prompt, the contextual-rerank + branch-judge prompt builders that thread the domain prior |
| `embedding.py` | folio-mapper `embedding/` | `EmbeddingProvider` Protocol + `FaissIndex` optional adapter (`IndexFlatIP`, disk cache, `all-MiniLM-L6-v2`); `HashingEmbeddingProvider` deterministic fallback for tests |
| `annotate/models.py` | enrich `models/annotation.py` + `models/feedback.py` | `Span`, `StageEvent`, `FeedbackItem`, `Annotation`, `ConceptTag`, `TagVerdict` (**new** per-tag correct/weak/wrong+note), `FeedbackEntry`, `InsightsSummary` |
| `annotate/feedback_store.py` | enrich `storage/feedback_store.py` | atomic file-per-entry store + `get_insights()` aggregation |
| `annotate/lifecycle.py` | enrich `api/routes/enrich.py` | reject/restore/promote/cascade-promote/bulk-reject as pure functions stamping StageEvents |
| `annotate/render.py` | enrich `frontend/index.html:renderAnnotatedText` | boundary-sweep → non-overlapping segments → nested-span layout, ported to Python as a library primitive (offsets, not HTML) |

### New v0 capabilities (each with tests + regression fixtures)

| Module | Kills / addresses | Design |
|---|---|---|
| `gates.py` | Slovenia→99 units (003); "Presumptions"→Northern Mariana Islands @90 | `PlaceNameGate`: geographic/short-label concepts are demoted unless corroborated (explicit heading-context match OR ≥2 signals). `ShortLabelGate`: labels ≤ N chars or ≤1 content word require exact/near-exact evidence, not bare fuzzy |
| `blocklist.py` | Action≠Auction (unit 4b06); agency homonyms | `AliasBlocklist`: `(surface_term, blocked_iri, domain)` triples, consulted by the matcher; fed by `wrong` per-tag verdicts. JSON-backed, versioned in `data/` |
| `decompose.py` | "Proposed Findings of Fact and Conclusions of Law" → both siblings (12b5e434, 005) | `SpanDecomposer`: conjunction split (`A and B → [A,B]`) + shared-head expansion (`Findings of Fact and Conclusions of Law` → `Findings of Fact`, `Conclusions of Law`) → each part matched independently |
| `sources.py` | metadata/front-matter source tagged (d3c44e2a) | `SourceType` enum + `SourceClassifier` hook; non-body sources excluded from tagging |
| `domain_prior.py` | 'Defenses'→Litigation Defenses (002); Damien's amended multi-tag design | `DomainPrior` carrying MULTIPLE subject tags; `DomainPriorSuggester` auto-detects + SUGGESTS with confidence; `validate/invalidate/add`; `TaxonomyNode` picker model (folio-api tree compatible). Tags flow into every judge call |
| `calibration.py` | weak-band recalibration (004) | `ScoreCalibration`: verdict-labeled `(score → P(correct))` dataset + isotonic-style monotone fit; recalibrates the weak band |

## 4. Package layout, tooling, quality gates

- `src/folio_matching/` (package), `uv`-managed, build backend `hatchling`.
- **mypy strict**, **ruff**, **pytest** from day one. `[tool.mypy] strict = true`; `[tool.ruff]` with a
  sensible ruleset; `pytest` with `asyncio_mode = "auto"`.
- Optional extras: `folio` (folio-python), `embedding` (faiss-cpu, sentence-transformers, numpy),
  `spacy` (spaCy ruler adapter). Core install pulls only `pydantic`.
- `THIRD-PARTY.md` logs every extracted component and every dependency with its license.
- MIT `LICENSE`, full `README.md` (purpose, personas, use cases, tech), `docs/migration/SCHEDULE.md`.

## 5. folio-insights pinning (the proving consumer)

- Replace the three `sys.path` bridges (`folio_bridge`, `mapper_bridge`, `ingestion_bridge`) with the
  pinned `folio-matching` package as a path/editable dependency in `pyproject.toml`.
- The tagger's `_reconciled_to_tags` 0.6 label-resolution contract and the `FourPathReconciler`
  behavior must stay green — the existing `tests/test_folio_tagging.py` parity set is the gate.
- Add the new gates ON (place-name gate, blocklist consulted) behind the tagger, with the new fixtures.
- Do **NOT** build the v2 annotator UI — separate operation.

## 6. Migration schedule (see docs/migration/SCHEDULE.md)

Ordered: **folio-insights ✓ (this op)** → folio-enrich → folio-mapper → alea-intake → clio-skills →
mootloop (greenfield) → generative-folio (optional scorer share). `books`/`book-indexer` are false
positives ("folio" = page numbers, not the ontology) — excluded. folio-api is the reference/donor and
already uses pinned folio-python; it swaps direct calls for the library opportunistically.

## 7. Verification

- `uv run pytest` green (target: full suite, pure-Python, no network).
- `uv run mypy src` clean under strict.
- `uv run ruff check` clean.
- folio-insights: existing tagger/reconciler parity tests still green against the pinned package.
- Each recorded Ch02 failure has a fixture that now passes (place-name gate, Action≠Auction blocklist,
  conjunction decomposition, metadata exclusion, word-order match).

## 8. Out of scope for v0

Hosted `/match` service (deferred); the folio-insights v2 annotator UI (separate op); migrating
non-insights consumers (opportunistic); spaCy/OpenAI/Ollama adapters beyond thin optional stubs.
</content>
</invoke>
