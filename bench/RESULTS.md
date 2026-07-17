# Ruler Shootout — spaCy (folio-enrich) vs Aho-Corasick (folio-resolve)

**Date:** 2026-07-16 · **Benchmark:** `bench/ruler_shootout.py` (deterministic, $0 LLM, seed 42) ·
**Committed numbers:** `bench/summary.json` (raw per-engine captures in `bench/results/`, gitignored)

## Question

Which entity ruler should be promoted into `folio-resolve` so every consumer (folio-enrich,
folio-insights, folio-mapper next) gets it: enrich's spaCy `FOLIOEntityRuler`, the library's
pure-Python Aho-Corasick ruler, or a hybrid?

## The architectural fact that frames the answer

**Both rulers consume the identical `labels` dict** from folio-enrich's
`FolioService.get_all_labels()`. The "smart" parts attributed to enrich's spaCy ruler — lemma
reachability (surface `agreement` → concept *Agreements*) and multi-branch expansion — live
**upstream in that label index**, not in the spaCy matching engine. spaCy's tagger is used only
at *index-build* time to compute the lemma map (disk-cached by OWL content hash). So the fair
shootout is three variants:

| Variant | Engine | Label index |
|---|---|---|
| `spacy` | enrich spaCy EntityRuler | lemma-augmented (enrich today: 69,368 keys, 968 lemma keys) |
| `ac` | folio-resolve Aho-Corasick | same lemma-augmented index (**the hybrid candidate**) |
| `ac-base` | folio-resolve Aho-Corasick | without lemma keys (what the library alone gives today: 68,400 keys) |

Corpus: folio-enrich's 22 synthetic demo documents (~157KB legal text; no matter data), plus a
×6 concat (~941KB) stress doc. Gold sets: stratified deterministic samples of real label keys
embedded in sentences; homonym-trap sentences where any match is a false positive.

## Numbers

### Match quality

| Metric | spaCy | AC + lemma (hybrid) | AC base |
|---|---|---|---|
| Gold recall — preferred labels (n=300) | 255 (85.0%) | **300 (100%)** | 300 (100%) |
| Gold recall — alternative labels (n=200) | 187 (93.5%) | **200 (100%)** | 200 (100%) |
| Gold recall — lemma_preferred keys (n=150) | 150 (100%) | **150 (100%)** | 0 (index lacks keys) |
| Gold recall — lemma_alternative keys (n=50) | 50 (100%) | **50 (100%)** | 0 |
| Gold recall — punctuated multi-word labels (n=150) | 110 (73.3%) | **150 (100%)** | 150 (100%) |
| Homonym-trap false positives (15 traps) | 13 | 13 | **10** |
| Whitespace-mangled labels found (newline / double-space, n=100 each) | 3 / 3 | 3 / 3 | 2 / 2 |
| Demo-corpus matches (157KB) | 3,820 | **4,914** | 4,216 |
| Corpus matches unique to this engine (vs the other) | 2 | 1,096 | — |

### Speed & footprint

| Metric | spaCy | AC + lemma (hybrid) | AC base |
|---|---|---|---|
| Pattern build time (69K patterns) | **1.63 s** | 2.31 s | 2.31 s |
| Peak RSS after build | 1,093 MB | **641 MB** | 642 MB |
| Throughput, 157KB demo corpus | 9,940 chars/s | **537,260 chars/s (54×)** | 742,869 chars/s |
| Throughput, 941KB stress doc | 9,699 chars/s | 95,851 chars/s | 134,133 chars/s |
| 1.10MB document | **hard failure** (spaCy `E088`: `nlp.max_length` cap at 1,000,000 chars) | 79,401 chars/s | ok |

## Findings

1. **The AC engine wins match quality outright.** spaCy's token-pattern builder
   (`pattern_builder.py` splits labels on whitespace into `{"LOWER": token}` sequences) can
   never match the **12,901 multi-word labels (18.6% of all 69K patterns)** whose tokens carry
   punctuation — spaCy's tokenizer splits `"license (agreement)"` / `"fed. r. civ. p."`
   differently than `str.split()`. That single defect explains the 45/300 preferred and 40/150
   punctuated gold misses. AC is char-based with word-boundary checks and matched 800/800.
2. **spaCy's hypothesized advantages did not materialize.**
   - *Whitespace robustness:* both engines scored 3/100 on newline/double-space-mangled labels —
     spaCy tokenizes the newline as its own token, breaking the token sequence. No advantage.
   - *Unique corpus recall:* 2 matches out of 3,820 (hyphen-tokenization artifacts like
     `post-trial`), vs **1,096** AC-only matches (nested/contained spans + punctuated labels +
     all-caps forms suppressed by spaCy's longest-ent-wins policy).
3. **False positives are index-determined, not engine-determined.** 13 = 13 trap FPs on the
   identical index; the engines pattern-match the same keys. The 3-FP delta vs `ac-base` is the
   price of the 968 lemma keys — and lemma keys buy +200/200 lemma gold hits and +698 corpus
   matches. FP control belongs downstream (folio-resolve's gates/blocklist + enrich's 0.60
   ruler-only confidence floor), not in the engine.
4. **Speed is not close.** 54× faster on the demo corpus, ~10× on the stress doc, half the RSS
   (spaCy holds a 452MB larger footprint), and spaCy **cannot process documents over 1M chars
   at all** (`E088` hard error; enrich survives only because it chunks upstream).
5. **One AC weakness found (fixable):** `_resolve_overlaps` is O(m²) in match count — throughput
   decays 531K → 285K → 146K → 79K chars/s at ×1/×2/×4/×7 corpus size. A sort + active-interval
   sweep makes it O(m log m). This is a promotion-PR work item, not a blocker (even degraded,
   AC is ~10× faster than spaCy at 941KB).
6. **Behavioral delta to document:** AC deliberately emits contained/nested spans (both
   survive); spaCy's `doc.ents` keeps only the longest. Consumers that swap engines will see
   more (gated) candidates — enrich's reconciler already filters single-word alt-label hits
   below 0.60 confidence, so nested extras are absorbed by existing gates.

## The hybrid question

**The hybrid is the `ac` column — and it beats both incumbents.** "Hybrid" does not mean running
two engines (union with spaCy would add 2 matches, one engine's build cost, and a 54× slower
pass); it means **AC engine + lemma-augmented label index**. The lemma pass is index
augmentation, engine-agnostic, spaCy-at-build-time-only, and already disk-cached in enrich.

## Recommendation: keep AC, promote the lemma indexing (not the spaCy engine)

1. **Keep `folio_resolve.FOLIOEntityRuler` (Aho-Corasick) as the library's matching engine.**
   Do not promote the spaCy engine — it loses on recall (85%/73% vs 100%), speed (54×), memory
   (+452MB), and document-size ceiling, and its unique contribution to a 157KB corpus was 2
   tokenization-artifact matches.
2. **Promote folio-enrich's lemma-key index augmentation into folio-resolve** as a build-time
   helper (port of `FolioService._compute_label_lemmas` + the denylist behavior):
   `folio_resolve.lemma.augment_labels(labels, ...) -> labels` producing `lemma_preferred` /
   `lemma_alternative` entries, cached by ontology content hash.
3. **Dependency cost:** ship it behind the **existing optional extra `folio-resolve[spacy]`**
   (spaCy is already declared as an optional extra in `pyproject.toml`). The core library stays
   zero-key, zero-heavy-dep: spaCy is imported lazily, needed only when (re)building a lemma
   cache; consumers without the extra simply get no lemma keys (today's `ac-base` behavior) or
   can load a pre-built lemma cache computed elsewhere. Runtime matching remains pure-Python.
4. **Include the `_resolve_overlaps` O(m log m) fix** in the same promotion PR.

### What the promotion PR entails

- `src/folio_resolve/lemma.py` — lemma-map computation (spaCy tagger + attribute_ruler guard,
  per-ontology denylist, single-word >3-char rule, lemma ≠ original) + `augment_labels()`;
  lazy spaCy import with a clear error naming the `[spacy]` extra; JSON/pickle cache keyed by
  ontology content hash + lemma-rule version (port of enrich's `LEMMA_VERSION` discipline).
- `_resolve_overlaps` rewrite (sort + active-interval sweep) + a scaling regression test.
- Tests: lemma augmentation unit tests (agreement→Agreements reachability, denylist,
  no-spaCy degradation) + ruler parity fixtures from this benchmark's gold sets.
- Docs: README section + consumer note (enrich keeps its spaCy ruler for now per Damien's
  2026-07-16 ruling; its `FolioService` lemma logic becomes a thin wrapper over the library
  helper when it next migrates — that closes the last fork of the lemma code).
- No new required dependencies; `spacy` stays optional. Version bump to 0.2.0.

## Reproducing

```bash
cd ~/Coding\ Projects/folio-enrich/backend   # venv has spaCy, folio-python, folio-resolve
.venv/bin/python ../../folio-resolve/bench/ruler_shootout.py --all
```

Captures were produced at library 0.1.0 immediately before the folio-matching → folio-resolve
rename; the rename was a pure module rename (ruler code byte-identical), and the `ac` capture
was re-validated bit-for-bit against the renamed PyPI-installed module.
