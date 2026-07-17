# Bring Your Own Key (BYOK)

`folio-resolve` is **key-agnostic**. The library never reads an environment variable, never
instantiates a provider SDK, and never makes a network call on its own. Everything that needs an
LLM or an embedding model is a **`typing.Protocol` seam** you fill with an object you construct —
so *you* own the key, the vendor choice, the spend, and the ret/o retry policy.

This document is for **admin users deploying a consumer app** on top of `folio-resolve`: it explains
what runs with no key at all, which stages want a provider, how to wire OpenAI / Gemini / Anthropic /
a local model, how the system degrades when no key is present, and roughly what a real run costs.

---

## 1. The zero-key deterministic core

The **entire core is pure-Python and needs no API key, no model download, and no network.** Install
`folio-resolve` with no extras and every capability in this table works offline:

| Capability | Module | What it does with no key |
|---|---|---|
| Word-order-invariant relevance scoring | `scoring` | `compute_relevance_score`, `word_overlap`, legal-term expansions |
| Multi-strategy label search | `scoring`, `pipeline` | term generation + label matching over the ontology |
| Aho-Corasick entity ruler | `entity_ruler`, `matching` | exact-label span matching (pure-Python, no spaCy/C deps) |
| Candidate reconciliation | `reconciler` | merge ruler + LLM-supplied + semantic candidates with provenance |
| **Span decomposition** | `decompose` | conjunction split + shared-head ("X and Y Law" → both) |
| **Place-name / short-label gates** | `gates` | demote pathological fuzzy place/short-label hits |
| **Alias/homonym blocklist** | `blocklist` | deterministic Action ≠ Auction guard |
| **Metadata/front-matter exclusion** | `sources` | never tag a copyright page or YAML front-matter |
| **Score calibration** | `calibration` | verdict-labelled score → P(correct) recalibration |
| **Domain-prior data model** | `domain_prior` | hold/validate/add corpus subject tags (the suggester wants an ontology) |
| Annotate primitives | `annotate` | per-tag verdicts, notes, reject/restore, feedback store |

The 4-stage `MatchPipeline` (`filter → expand → rank → judge`) runs with **only the first three
stages** when no judge is supplied — you still get ruler + label-search + decomposition + semantic
(if an embedding provider is wired) candidates, gated, blocklisted, and calibrated. The judge stage is
simply skipped.

```python
from folio_resolve import InMemoryOntology, Concept, MatchPipeline

ontology = InMemoryOntology([
    Concept(iri="R-arb", label="Arbitration Rules", branch="Service"),
    Concept(iri="R-def", label="Litigation Defenses", branch="Objectives"),
])
pipe = MatchPipeline(ontology=ontology)          # no judge, no embeddings, no key
pipe.match("rules of arbitration")               # -> Arbitration Rules  (deterministic)
```

Deterministic output is fully reproducible and free. For many admin deployments the zero-key core is
enough; add a provider only where it measurably improves recall or disambiguation.

---

## 2. Which stages want a provider

Three seams accept an optional provider. Each is a `Protocol` — any object with the right method(s)
satisfies it; there is no base class to import and no vendor lock-in.

| Seam | Protocol | Method(s) | What it buys you | Skipped when absent |
|---|---|---|---|---|
| **Judge** | `folio_resolve.judge.Judge` | `complete(system: str, user: str) -> str` | context-aware disambiguation + verdict enforcement (Defenses → *Litigation* Defenses) | candidates pass through unjudged |
| **Embeddings** | `folio_resolve.embedding.EmbeddingProvider` | `embed`, `embed_batch`, `dimension` | semantic recall for "no shared label token" maps (Presumptions → Burdens of Proof) | semantic path contributes nothing; a pure-Python hashing default keeps it *exercisable* but not production-grade |
| **Domain-prior suggestions** | `folio_resolve.domain_prior.DomainPriorSuggester` | (constructed with an `OntologyProvider`) | auto-suggest corpus subject tags for human validation | you supply subject tags manually (or omit them) |

The `Ontology` itself is also a `Protocol` (`OntologyProvider`): `InMemoryOntology` needs no key;
`FolioPythonProvider` (the `[folio]` extra) loads the live 18k-concept FOLIO ontology locally — still
no API key, just a heavier dependency.

### The Judge seam in detail

The library ships the **prompt builders and the deterministic verdict enforcement** — the parts that
must be identical across every consumer — and leaves only the raw model call to you:

```python
from folio_resolve import build_judge_prompt, parse_judge_json, enforce_verdict

# candidates: list of {"iri_hash", "score", ...}; ranked_by_iri maps iri_hash -> original score
system, user = build_judge_prompt(text, candidates, document_type="litigation treatise")
raw = my_judge.complete(system, user)              # <-- the ONLY vendor-specific line
judged = parse_judge_json(raw, ranked_by_iri)      # -> list[JudgedCandidate]

for jc in judged:
    final = enforce_verdict(ranked_by_iri[jc.iri], jc.adjusted_score, jc.verdict)
    # `final` is the guardrailed score for this candidate
```

`build_judge_prompt` threads the document-level **domain prior** (`document_type`) into the prompt so
"Defenses" disambiguates correctly in a litigation corpus. `parse_judge_json` turns the model's raw JSON
into structured `JudgedCandidate`s, and `enforce_verdict(original, adjusted, verdict)` clamps each one to
the calibration rules (rejected → 0, confirmed within ±5, boost capped) **deterministically** — so a
misbehaving or prompt-injected judge cannot inflate a score past the guardrail.

---

## 3. Wiring a provider — one minimal example per vendor

A `Judge` is *any object with `complete(system, user) -> str`*. Construct it with your key and pass it
in. Below is the same seam filled four ways. Install only the SDK you use.

### OpenAI

```python
import os
from openai import OpenAI

class OpenAIJudge:
    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self._client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self._model = model

    def complete(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content or ""
```

### Google Gemini (the measured reference — see §5)

```python
import os
from google import genai

class GeminiJudge:
    def __init__(self, model: str = "gemini-2.5-flash-lite") -> None:
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self._model = model

    def complete(self, system: str, user: str) -> str:
        resp = self._client.models.generate_content(
            model=self._model,
            contents=f"{system}\n\n{user}",
            config={"temperature": 0},
        )
        return resp.text or ""
```

### Anthropic (Claude)

```python
import os
import anthropic

class AnthropicJudge:
    def __init__(self, model: str = "claude-opus-4-8") -> None:
        self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self._model = model

    def complete(self, system: str, user: str) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")
```

### Local / self-hosted (Ollama, vLLM, or any OpenAI-compatible endpoint)

```python
import os
from openai import OpenAI

class LocalJudge:
    """Points the OpenAI client at a local server; no cloud key leaves the box."""
    def __init__(self, model: str = "llama3.1") -> None:
        self._client = OpenAI(
            base_url=os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1"),
            api_key=os.environ.get("LOCAL_LLM_API_KEY", "not-needed"),
        )
        self._model = model

    def complete(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content or ""
```

### Embeddings

The embedding seam is analogous. `folio-resolve[embedding]` ships `LocalEmbeddingProvider`
(`all-MiniLM-L6-v2`, runs locally, no API key) — recommended for most deployments. To use a hosted
embedding vendor, implement the three-method `EmbeddingProvider` Protocol against its API the same way.

```python
from folio_resolve.embedding import LocalEmbeddingProvider, BruteForceIndex
index = BruteForceIndex(LocalEmbeddingProvider())   # local model, no key
```

---

## 4. Env-var conventions & graceful degradation

### Recommended env-var conventions

The library reads **nothing** from the environment — these names are a *convention for your app*, chosen
to match what a `folio-resolve` consumer (e.g. `folio-insights`) already uses so operators see one
scheme across repos:

| Variable | Meaning |
|---|---|
| `<VENDOR>_API_KEY` | provider key, read by *your* Judge/embedding class (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`) |
| `FOLIO_MATCHING_JUDGE_PROVIDER` | which vendor your app should construct (`openai` \| `gemini` \| `anthropic` \| `local` \| `none`) |
| `FOLIO_MATCHING_JUDGE_MODEL` | model id override for the judge |
| `FOLIO_MATCHING_EMBED_PROVIDER` | `local` (default) \| `none` \| a hosted vendor |
| `LOCAL_LLM_BASE_URL` | endpoint for a self-hosted OpenAI-compatible server |

A tiny factory keeps the vendor choice in config, not in code:

```python
import os

def build_judge():
    provider = os.environ.get("FOLIO_MATCHING_JUDGE_PROVIDER", "none")
    if provider == "none":
        return None
    if provider == "openai":    return OpenAIJudge(os.environ.get("FOLIO_MATCHING_JUDGE_MODEL", "gpt-4o-mini"))
    if provider == "gemini":    return GeminiJudge(os.environ.get("FOLIO_MATCHING_JUDGE_MODEL", "gemini-2.5-flash-lite"))
    if provider == "anthropic": return AnthropicJudge(os.environ.get("FOLIO_MATCHING_JUDGE_MODEL", "claude-opus-4-8"))
    if provider == "local":     return LocalJudge(os.environ.get("FOLIO_MATCHING_JUDGE_MODEL", "llama3.1"))
    raise ValueError(f"unknown judge provider: {provider}")
```

### Graceful degradation semantics

`folio-resolve` is designed to **degrade, not crash**, when a key is absent:

- **No judge** → the pipeline runs `filter → expand → rank` and returns the survivors as-is. Nothing is
  raised. Items that *would* have been judged are simply not judged.
- **No embeddings** → the semantic recall path contributes no candidates; the pure-Python
  `HashingEmbeddingProvider` default keeps the code path exercisable (and deterministic for tests) but is
  explicitly *not* a production model.
- **No domain-prior suggester** → you pass validated subject tags in yourself, or run with none.

**Mark unjudged items rather than dropping them.** When you run without a judge, tag the output so
downstream consumers and reviewers can tell "the model declined this" from "no model ran":

```python
judge = build_judge()
for cand in ranked_candidates:
    if judge is None:
        cand.extraction_path = cand.extraction_path or "unjudged"   # provenance, not a silent gap
    # ... else run the judge seam from §2
```

The deterministic guardrails (gates, blocklist, calibration, decomposition, metadata exclusion) run in
**every** mode — so even a zero-key deployment gets the Ch02 fixes; only the context-aware
disambiguation layer is what a key adds.

---

## 5. Rough cost expectations

The reference measurement is a full extraction pass over **one book chapter** (~115 KB markdown,
464 knowledge units) run through the `folio-insights` pipeline on **`gemini-2.5-flash-lite`**:

| Metric | Value |
|---|---|
| Model | `gemini-2.5-flash-lite` |
| LLM calls | ~1,875 |
| Total tokens | ~652 K |
| **Measured cost** | **≈ $0.12 / chapter** |

Use **~$0.12/chapter on `gemini-2.5-flash-lite`** as your planning anchor. Practical implications for an
admin deployment:

- **Flash-tier models are the sweet spot** for the judge — the task is bounded per-unit disambiguation,
  not open-ended reasoning, so a small fast model is both cheap and accurate enough.
- **Cost scales with unit count**, roughly linearly — a 10-chapter book is ≈ $1.20, not a step change.
- **The zero-key core is free**, so you can run the deterministic pipeline over the whole corpus and
  spend LLM budget only on the judge pass for the units that survive gating.
- **Embeddings are free** if you use the local `all-MiniLM-L6-v2` provider — no per-call cost.
- Bigger/reasoning models (GPT-4o, Claude Opus, Gemini Pro) will raise per-chapter cost 5–50×; reach for
  them only if flash-tier disambiguation quality proves insufficient on your corpus.

---

## Summary

- **Zero key** → full deterministic pipeline (ruler, scoring, decomposition, gates, blocklist,
  calibration, metadata exclusion, annotate). Free, reproducible, offline.
- **Add a Judge key** → context-aware disambiguation with a domain prior, deterministically guardrailed.
- **Add embeddings** (local model, no key) → semantic recall for no-shared-token maps.
- Everything is a `Protocol` you fill — you own the key, the vendor, and the spend. Budget ~$0.12/chapter
  on `gemini-2.5-flash-lite` as the reference point.
