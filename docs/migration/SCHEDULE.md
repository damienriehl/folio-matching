# folio-matching — Consumer Migration Schedule

Damien approved **opportunistic** migration (each repo migrates as it next touches FOLIO matching)
**plus** this written schedule, and asked to be **reminded which repo is next as each migration
completes**. Status legend: ✅ done · ▶️ next · ⏳ queued · ➖ excluded.

> **NEXT UP: `folio-mapper`.** (folio-enrich migrated 2026-07-16 — Stage 1 merged, delta clean.)

| # | Repo | Status | How it matches FOLIO today | What migration entails | Effort |
|---|---|---|---|---|---|
| 1 | **folio-insights** | ✅ this operation | 4-path tagger importing folio-enrich + folio-mapper via `sys.path` bridges (`folio_bridge`, `mapper_bridge`, `ingestion_bridge`); `FourPathReconciler` wraps enrich's `Reconciler`; B9 rapidfuzz verifier | Replace the three bridges with the pinned `folio-matching` package; keep the tagger/reconciler parity tests green; turn the new gates on | Done |
| 2 | **folio-enrich** | ✅ 2026-07-16 | Its `folio/search.py` is literally "ported from folio-mapper"; owns the reconciler, entity ruler, domain-prior judge, feedback/annotate UI | Retire the forked `search.py` and reconciler/ruler; consume the library. Its display code stays as the annotator reference. This closes the copy-paste divergence at its source | Real |
| 3 | **folio-mapper** | ▶️ next | The canonical scorer + 4-stage pipeline + FAISS index (the donor of most of this library) | Collapse the Python backend into a thin layer over `folio-matching`; the repo becomes primarily its TS UI. Behavior-parity tests guard the swap | Real |
| 4 | **alea-intake** | ⏳ queued | Heaviest external consumer: 3-stage cascade in `services/folio/concept_resolver.py` (embedding + hand-rolled word-overlap + LLM), FAISS/pgvector backends, `analysis/semantic_fit.py` LLM judge, `folio/term_expansions.py` ("ported from folio-mapper") | Replace all three stages + the inline scorer + weighted-combine with the library API; decide whether `semantic_fit` moves into the lib; keep alea's pgvector backend or delegate | Real (largest surface) |
| 5 | **clio-skills** | ⏳ queued | Polyglot: TS `fuzzy-match.ts` (bespoke Dice) + Python subprocess bridges (`folio_embedding.py` FAISS `IndexFlatIP`, `folio_bridge.py` rapidfuzz) | Replace the Dice scorer + both Python bridge scripts. Because it's Next/TS, either call a future `/match` service or keep one thin Python bridge that imports the library | Real (language split) |
| 6 | **mootloop** | ⏳ queued (greenfield) | None yet — `taskspec.py` has placeholder `folio_iri`/`folio_label`; resolution is deterministic keyword in v1, LLM concept-resolution lands in FE-3 | Nothing to rip out; wire `folio-matching` directly when FE-3 lands. The ideal first *native* consumer | Adopt |
| 7 | **generative-folio** | ⏳ optional | Uses rapidfuzz only for QA dedup of *generated* concepts (`qa/detectors.py`) — not inbound matching | Optional: adopt the shared token scorer for dedup. Low value | Optional |
| — | **folio-api** | ➖ reference/donor | Already a FOLIO match service: `/search/label` (folio-python fuzzy) + ~18 `/llm/*` classifiers; uses pinned `folio-python` | No correctness change needed. It defines the eventual `/match` contract; swaps direct calls for the library opportunistically. Candidate host if/when the deferred `/match` service is built | Light-shim |
| — | **books** | ➖ excluded | "folio" = physical page numbers, not the ontology | N/A — naming collision | None |
| — | **book-indexer** | ➖ excluded | "folio" = physical page numbers; index-term extraction, not FOLIO | N/A — naming collision | None |

## Reminder protocol (per Damien's directive)

As each migration lands, the executing agent posts a one-line reminder naming the next repo:

- ✅ **folio-insights migrated → NEXT UP: folio-enrich** (retire its forked `search.py`).
- ✅ **folio-enrich migrated (2026-07-16, Stage 1: deterministic core; ruler kept per Damien; fallback kept) → NEXT UP: folio-mapper** (collapse Python backend into the library).
- ⬜ folio-mapper migrated → NEXT UP: alea-intake (biggest rewrite; exercises embed+label+LLM+judge).
- ⬜ alea-intake migrated → NEXT UP: clio-skills (validate the polyglot/service path).
- ⬜ clio-skills migrated → NEXT UP: mootloop FE-3 (greenfield native adoption).

## Deferred, revisit reminders

- **Hosted `/match` service** — deferred per Damien; the library covers every current (Python)
  consumer. Reconsider when a non-Python or remote consumer (clio-skills TS, an external caller)
  needs it; folio-api is the natural host.
