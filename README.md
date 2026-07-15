# folio-matching

**The shared FOLIO source-text→concept matching engine.** One pinned, MIT-licensed Python library
that maps arbitrary source text (book headings, deposition transcripts, intake narratives, task
titles) to concepts in [FOLIO](https://folio.openlegalstandard.org) — the open legal ontology of
18,000+ concepts.

> This is a **lift-and-improve** extraction. The matching intelligence already existed across
> `folio-mapper`, `folio-enrich`, and `folio-insights` — but it had **diverged** (enrich literally
> forked mapper's scorer) and was informally shared through a fragile `sys.path` hack. `folio-matching`
> is the single source of truth those repos now pin, plus the capabilities the recorded failures demanded.

---

## Why this exists

Three repos independently built the same engine and drifted apart:

- **folio-mapper** wrote the canonical, word-order-invariant scorer + a 4-stage pipeline + a FAISS embedding index.
- **folio-enrich** *copied* mapper's scorer (its `search.py` says "ported from folio-mapper" in the code) and added an Aho-Corasick entity ruler, a reconciler, a domain-prior judge, and a feature-rich annotate/feedback UI.
- **folio-insights** `sys.path`-imports **both** siblings at runtime — documented as fragile.

A book-annotation review (Ch02) then surfaced failures that no amount of local patching would fix:
place-names over-scoring (Slovenia → 99 units), homonyms (Action ≠ Auction), conjoined compound
headings that match nothing, metadata tagged as substance, and pure-semantic maps with no shared
label token (Presumptions → Litigation Burdens of Proof). Those became this library's new capabilities.

## What it does

| Capability | Module | Solves |
|---|---|---|
| Word-order-invariant relevance scoring | `scoring` | "arbitration rules" = "rules of arbitration" |
| Multi-strategy label search + legal expansions | `scoring`, `pipeline` | recall on paraphrases |
| Pure-Python Aho-Corasick entity ruler | `entity_ruler`, `matching` | trusted exact-label spans, no spaCy/C deps |
| Candidate reconciliation (ruler + LLM + semantic) | `reconciler` | one clean candidate set with provenance |
| **Span decomposition** (conjunction split + shared head) | `decompose` | "Findings of Fact **and** Conclusions of Law" → both siblings |
| **Place-name / short-label gates** | `gates` | kills Slovenia→99 and Presumptions→Northern Mariana Islands@90 |
| **Alias/homonym blocklist** | `blocklist` | deterministic Action ≠ Auction guard |
| **Metadata/front-matter exclusion** | `sources` | never tag the copyright page |
| **Multi-tag domain prior** (auto-suggest + validate/add) | `domain_prior` | Defenses → *Litigation* Defenses; corpus carries many subjects |
| **Score calibration** (weak-band recalibration) | `calibration` | verdict-labeled score→P(correct) fit |
| LLM judge interface + domain-prior prompts | `judge` | context-aware disambiguation, verdict enforcement |
| **Annotate primitives** (confidence, per-tag verdicts, notes, reject/restore, insights) | `annotate` | the self-improving feedback loop, as a library |
| 4-stage pipeline: filter → expand → rank → judge | `pipeline` | the build-once-use-many entry point |

## Personas

- **Book-extraction pipelines** (`folio-insights`, `books`) — offline, CLI-first tagging of treatise text.
- **Intake / matter classifiers** (`alea-intake`, `mootloop`) — narrative → FOLIO concepts for routing.
- **Interactive mappers** (`folio-mapper`, `clio-skills`) — a UI over the library's ranked candidates.
- **The FOLIO ontology team** — a reference implementation of "good" source-text→concept matching.

## Use cases

- Tag a chapter of a litigation treatise with FOLIO concepts, with a litigation domain prior so
  "Defenses" resolves to *Litigation Defenses*, not the generic sense.
- Resolve a compound heading like *"Proposed Findings of Fact and Conclusions of Law"* to the two
  sibling concepts it actually names.
- Suggest the subject tags for a corpus ("Personal Injury Depositions" → *Personal Injury* +
  *Deposition*) and let a human validate/add via a FOLIO taxonomy-tree picker.
- Feed a reviewer's `wrong` verdict on a homonym straight into the alias blocklist so the mistake
  never recurs — the self-improving loop.

## Install

```bash
uv add folio-matching                 # core (pure-Python, only pydantic)
uv add "folio-matching[folio]"        # + folio-python live ontology adapter
uv add "folio-matching[embedding]"    # + sentence-transformers / faiss for the semantic path
uv add "folio-matching[spacy]"        # + optional spaCy ruler adapter
```

The **core is pure-Python** — the scorer, decomposition, gates, blocklist, domain-prior, reconciler,
calibration, and annotate primitives depend on nothing heavier than `pydantic`. FAISS,
sentence-transformers, spaCy, and folio-python live behind `Protocol` seams with working pure-Python
defaults, so the whole test suite runs with no model downloads and no network.

## Quick start

```python
from folio_matching import InMemoryOntology, Concept, MatchPipeline, DomainPrior

ontology = InMemoryOntology([
    Concept(iri="R-defenses", label="Litigation Defenses", branch="Objectives"),
    Concept(iri="R-arb", label="Arbitration Rules", branch="Service"),
])
pipe = MatchPipeline(ontology=ontology)

# word-order-invariant
pipe.match("rules of arbitration")        # -> Arbitration Rules

# domain prior threads a subject into the (optional) judge
prior = DomainPrior.from_manifest_subjects("treatise", [("R-lit", "Litigation")])
pipe.match("Defenses", domain_prior=prior)
```

## Development

```bash
uv sync --extra dev
uv run pytest          # full suite, pure-Python, no network
uv run mypy src        # strict
uv run ruff check
```

## License & attribution

MIT — see [LICENSE](LICENSE). Every extracted component and dependency is logged in
[THIRD-PARTY.md](THIRD-PARTY.md). The migration schedule for consumer repos is in
[docs/migration/SCHEDULE.md](docs/migration/SCHEDULE.md).
