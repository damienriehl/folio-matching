#!/usr/bin/env python3
"""Ruler shootout: folio-enrich's spaCy FOLIOEntityRuler vs folio-resolve's Aho-Corasick ruler.

Damien's question (2026-07-16): which entity ruler should be promoted into folio-resolve so
every consumer gets it — enrich's spaCy engine, the library's pure-Python Aho-Corasick, or a
hybrid? (The library was named folio-matching when the captures were produced; the rename to
folio-resolve at 0.1.0 was a pure module rename — ruler code byte-identical — so they remain
valid.)

Architectural fact this benchmark is built around: **both rulers consume the identical
``labels`` dict** from folio-enrich's ``FolioService.get_all_labels()``. The lemma keys
("agreement" -> Agreements) and multi-branch expansion that make enrich's ruler look smarter
live UPSTREAM in that index (spaCy is used only at index-build time, disk-cached by owl hash) —
not in the spaCy matching engine. So the fair comparison is three variants:

* ``spacy``    — enrich's spaCy engine + lemma-augmented index   (enrich today)
* ``ac``       — library AC engine    + lemma-augmented index    (the hybrid candidate)
* ``ac-base``  — library AC engine    + index WITHOUT lemma keys (the library alone today)

Measurements (all deterministic, $0 LLM):
1. Build time + peak RSS (each engine benchmarked in its own subprocess).
2. Throughput on the folio-enrich synthetic demo corpus (~157KB) and a ~1MB stress concat.
3. Match quality:
   - gold recall: stratified deterministic sample of label keys (preferred / alternative /
     lemma_preferred / lemma_alternative) embedded in sentences; hit = span+IRI recovered.
   - punctuated multi-word labels ("license (agreement)", hyphenated forms) — the spaCy
     token-pattern builder splits on whitespace, so punctuation-attached tokens can never
     match the tokenizer's output; AC is char-based.
   - whitespace robustness: labels split across a newline / double space (spaCy tokens ignore
     whitespace; AC requires the exact single-space surface).
   - homonym-trap false positives: sentences using trap words in non-legal senses; every
     ruler match on the trap word is a false positive.
   - full-corpus match-set diff: (start, end, iri) sets per engine, engine-only counts.

Run (uses folio-enrich's venv — it has spaCy, folio-python, and folio-resolve from PyPI):

    cd ~/Coding\ Projects/folio-enrich/backend
    .venv/bin/python ../../folio-resolve/bench/ruler_shootout.py --all

Writes bench/results/*.json (one per engine + summary). See bench/RESULTS.md for the verdict.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import resource
import subprocess
import sys
import time
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BENCH_DIR / "results"
SEED = 42

# folio-enrich backend (for FolioService + the spaCy ruler). Read-only import.
ENRICH_BACKEND = (BENCH_DIR / ".." / ".." / "folio-enrich" / "backend").resolve()
DEMOS_DIR = ENRICH_BACKEND.parent / "frontend" / "demos"

GOLD_SAMPLE = {
    "preferred": 300,
    "alternative": 200,
    "lemma_preferred": 150,
    "lemma_alternative": 50,
}
PUNCT_SAMPLE = 150
LEMMA_TYPES = ("lemma_preferred", "lemma_alternative")

# Homonym-trap sentences: the trap word is used in a plainly non-legal sense, so any ruler
# match on it is a false positive. Trap words chosen from known single-word alt-label keys.
TRAP_SENTENCES = [
    ("action", "The camera's fast action shots impressed the wedding photographer."),
    ("state", "He will state his name clearly before the microphone check."),
    ("tax", "Climbing the hill was a real tax on her stamina during vacation."),
    ("charge", "She left the phone on charge overnight in the kitchen."),
    ("trial", "The bakery ran a free trial of its sourdough subscription."),
    ("justice", "The chef did justice to the family recipe at the reunion dinner."),
    ("will", "They will meet at the lake house on Saturday morning."),
    ("grant", "The soil here can grant a bumper crop of tomatoes each summer."),
    ("motion", "The ocean's gentle motion rocked the small fishing boat."),
    ("brief", "After a brief pause, the orchestra resumed the symphony."),
    ("party", "The birthday party ended with fireworks over the garden."),
    ("court", "The tennis court was resurfaced before the summer season."),
    ("order", "She placed an order for two lattes and a croissant."),
    ("title", "The title of the novel changed twice before publication."),
    ("claim", "Prospectors would claim a stretch of the riverbed at dawn."),
]

WS_TEMPLATES = ("newline", "double_space")


def _now() -> float:
    return time.perf_counter()


def _rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def _load_demo_corpus() -> str:
    texts: list[str] = []
    for f in sorted(DEMOS_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        t = (d.get("cache") or {}).get("normalizedText") or (d.get("cache") or {}).get("docInput") or ""
        if isinstance(t, str) and len(t) > 500:
            texts.append(t)
    return "\n\n".join(texts)


def _load_labels(include_lemma: bool):
    sys.path.insert(0, str(ENRICH_BACKEND))
    from app.services.folio.folio_service import FolioService

    labels = FolioService.get_instance().get_all_labels()
    if include_lemma:
        return labels
    return {k: v for k, v in labels.items() if v.label_type not in LEMMA_TYPES}


def _build_engine(engine: str, labels):
    """Return (ruler, build_seconds). Both expose load_patterns + find_matches."""
    if engine == "spacy":
        sys.path.insert(0, str(ENRICH_BACKEND))
        from app.services.entity_ruler.ruler import FOLIOEntityRuler as SpacyRuler

        ruler = SpacyRuler()
        t0 = _now()
        ruler.load_patterns(labels)
        return ruler, _now() - t0
    else:
        from folio_resolve import FOLIOEntityRuler as ACRuler

        ruler = ACRuler()
        t0 = _now()
        ruler.load_patterns(labels)
        return ruler, _now() - t0


def _matches(ruler, text: str) -> list[tuple[int, int, str, str]]:
    """Normalize both engines' output to (start, end, iri, surface)."""
    out = []
    for m in ruler.find_matches(text):
        out.append((m.start_char, m.end_char, m.entity_id, m.text))
    return out


def _eligible_key(key: str) -> bool:
    return 4 <= len(key) <= 60 and key.isprintable() and not key.startswith(("-", "'"))


def _gold_samples(labels) -> dict[str, list[tuple[str, str]]]:
    """Stratified deterministic samples: label_type -> [(key, expected_iri)]."""
    rng = random.Random(SEED)
    by_type: dict[str, list[tuple[str, str]]] = {t: [] for t in GOLD_SAMPLE}
    punct: list[tuple[str, str]] = []
    for key in sorted(labels):
        info = labels[key]
        if not _eligible_key(key):
            continue
        pair = (key, info.concept.iri)
        if " " in key and re.search(r"[^\w\s]", key):
            punct.append(pair)
        if info.label_type in by_type:
            by_type[info.label_type].append(pair)
    samples = {
        t: rng.sample(pool, min(GOLD_SAMPLE[t], len(pool))) for t, pool in by_type.items()
    }
    samples["punct_multiword"] = rng.sample(punct, min(PUNCT_SAMPLE, len(punct)))
    return samples


def _gold_recall(ruler, samples) -> dict:
    out: dict = {}
    for label_type, pairs in samples.items():
        hits = 0
        misses: list[str] = []
        for key, iri in pairs:
            sentence = f"The filing addresses {key} in this matter."
            found = any(
                iri == m_iri and surface.lower() == key
                for (_s, _e, m_iri, surface) in _matches(ruler, sentence)
            )
            if found:
                hits += 1
            elif len(misses) < 12:
                misses.append(key)
        out[label_type] = {"n": len(pairs), "hits": hits, "miss_examples": misses}
    return out


def _whitespace_robustness(ruler, labels) -> dict:
    """Multi-word PREFERRED labels rendered with a newline / double space inside."""
    rng = random.Random(SEED)
    pool = [
        (k, v.concept.iri)
        for k, v in sorted(labels.items())
        if v.label_type == "preferred" and k.count(" ") >= 1 and _eligible_key(k)
        and not re.search(r"[^\w\s]", k)
    ]
    sample = rng.sample(pool, min(100, len(pool)))
    out = {}
    for mode in WS_TEMPLATES:
        hits = 0
        for key, iri in sample:
            mangled = key.replace(" ", "\n", 1) if mode == "newline" else key.replace(" ", "  ", 1)
            sentence = f"The filing addresses {mangled} in this matter."
            if any(iri == m_iri for (_s, _e, m_iri, _t) in _matches(ruler, sentence)):
                hits += 1
        out[mode] = {"n": len(sample), "hits": hits}
    return out


def _trap_fps(ruler) -> dict:
    total = 0
    detail = []
    for trap_word, sentence in TRAP_SENTENCES:
        fp = [
            {"surface": surface, "iri": iri.rsplit("/", 1)[-1]}
            for (_s, _e, iri, surface) in _matches(ruler, sentence)
            if surface.lower() == trap_word
        ]
        total += len(fp)
        detail.append({"trap": trap_word, "fp_matches": len(fp)})
    return {"total_fp": total, "per_trap": detail}


def _throughput(ruler, corpus: str) -> dict:
    def best_of(text: str, runs: int) -> tuple[float, int]:
        best = float("inf")
        n = 0
        for _ in range(runs):
            t0 = _now()
            n = len(ruler.find_matches(text))
            best = min(best, _now() - t0)
        return best, n

    demo_s, demo_matches = best_of(corpus, 3)
    # x6 keeps the stress doc under spaCy's hard nlp.max_length cap of 1,000,000 chars —
    # at x7 (1.10M chars) the spaCy engine raises E088 and cannot process the doc AT ALL,
    # while the AC engine has no document-size cap. Recorded as a finding in RESULTS.md.
    stress = "\n\n".join([corpus] * 6)
    try:
        stress_s, _ = best_of(stress, 1)
        stress_err = None
    except Exception as exc:  # e.g. spaCy E088 on oversized docs
        stress_s, stress_err = None, f"{type(exc).__name__}: {exc}"[:200]
    return {
        "demo_chars": len(corpus),
        "demo_best_s": round(demo_s, 3),
        "demo_chars_per_s": int(len(corpus) / demo_s) if demo_s else None,
        "demo_matches": demo_matches,
        "stress_chars": len(stress),
        "stress_s": round(stress_s, 3) if stress_s else None,
        "stress_chars_per_s": int(len(stress) / stress_s) if stress_s else None,
        "stress_error": stress_err,
    }


def run_engine(engine: str) -> dict:
    include_lemma = engine != "ac-base"
    labels = _load_labels(include_lemma)
    corpus = _load_demo_corpus()

    rss_before = _rss_mb()
    ruler, build_s = _build_engine(engine, labels)
    rss_after_build = _rss_mb()

    samples = _gold_samples(_load_labels(True))  # gold set fixed across engines (incl. lemma keys)
    result = {
        "engine": engine,
        "index_labels": len(labels),
        "lemma_keys_in_index": sum(1 for v in labels.values() if v.label_type in LEMMA_TYPES),
        "build_s": round(build_s, 2),
        "rss_before_mb": round(rss_before, 1),
        "rss_after_build_mb": round(rss_after_build, 1),
        "gold": _gold_recall(ruler, samples),
        "whitespace": _whitespace_robustness(ruler, labels),
        "traps": _trap_fps(ruler),
        "throughput": _throughput(ruler, corpus),
    }
    # Full-corpus match set for the cross-engine diff (surface kept for examples).
    result["corpus_matches"] = [
        [s, e, iri, surface] for (s, e, iri, surface) in _matches(ruler, corpus)
    ]
    return result


def summarize(engines: list[str]) -> dict:
    data = {e: json.loads((RESULTS_DIR / f"{e}.json").read_text()) for e in engines}
    sets = {
        e: {(s, ee, iri) for s, ee, iri, _t in d["corpus_matches"]} for e, d in data.items()
    }
    diff = {}
    if "spacy" in sets and "ac" in sets:
        only_spacy = sets["spacy"] - sets["ac"]
        only_ac = sets["ac"] - sets["spacy"]
        surfaces = {(s, e, iri): t for s, e, iri, t in data["spacy"]["corpus_matches"]}
        surfaces.update({(s, e, iri): t for s, e, iri, t in data["ac"]["corpus_matches"]})
        diff = {
            "spacy_total": len(sets["spacy"]),
            "ac_total": len(sets["ac"]),
            "both": len(sets["spacy"] & sets["ac"]),
            "spacy_only": len(only_spacy),
            "ac_only": len(only_ac),
            "spacy_only_examples": sorted({surfaces[k] for k in list(only_spacy)[:400]})[:25],
            "ac_only_examples": sorted({surfaces[k] for k in list(only_ac)[:400]})[:25],
        }
        if "ac-base" in sets:
            diff["ac_base_total"] = len(sets["ac-base"])
            diff["ac_vs_ac_base_gained"] = len(sets["ac"] - sets["ac-base"])
    summary = {
        "engines": {
            e: {k: v for k, v in d.items() if k != "corpus_matches"} for e, d in data.items()
        },
        "corpus_diff": diff,
    }
    (RESULTS_DIR / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["spacy", "ac", "ac-base"])
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    RESULTS_DIR.mkdir(exist_ok=True)

    if args.engine:
        result = run_engine(args.engine)
        (RESULTS_DIR / f"{args.engine}.json").write_text(json.dumps(result) + "\n")
        printable = {k: v for k, v in result.items() if k != "corpus_matches"}
        print(json.dumps(printable, indent=2))
        return 0

    if args.all:
        engines = ["spacy", "ac", "ac-base"]
        for e in engines:
            print(f"=== running engine: {e} (subprocess) ===", flush=True)
            proc = subprocess.run(
                [sys.executable, str(__file__), "--engine", e],
                cwd=str(ENRICH_BACKEND),
                capture_output=True,
                text=True,
                timeout=1800,
            )
            if proc.returncode != 0:
                print(proc.stdout[-3000:])
                print(proc.stderr[-3000:])
                return proc.returncode
        summary = summarize(engines)
        print(json.dumps(summary, indent=2))
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
