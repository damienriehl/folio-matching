"""Regression tests for the _resolve_overlaps active-interval sweep.

The 2026-07-16 ruler shootout (bench/RESULTS.md, finding 5) measured the previous
full-rescan implementation as O(m^2) in match count: throughput decayed 531K -> 285K ->
146K -> 79K chars/s as the corpus grew x1 -> x2 -> x4 -> x7. The sweep must (a) make
byte-identical decisions — pinned here by fuzzing against a verbatim copy of the old
implementation — and (b) scale near-linearly on disjoint-region inputs, pinned by a
generous wall-clock bound that the quadratic version misses by more than an order of
magnitude.
"""

from __future__ import annotations

import random
import time

from folio_resolve.matching.aho_corasick import AhoCorasickMatcher, MatchResult


def _reference_resolve(matches: list[MatchResult]) -> list[MatchResult]:
    """Verbatim copy of the pre-0.2.0 quadratic implementation (the semantics oracle)."""
    if not matches:
        return []
    matches.sort(key=lambda m: (m.start, -(m.end - m.start)))
    resolved: list[MatchResult] = []
    for match in matches:
        dominated = False
        for i, kept in enumerate(resolved):
            if match.start >= kept.end or match.end <= kept.start:
                continue
            if match.start == kept.start and match.end == kept.end:
                dominated = True
                break
            if match.start >= kept.start and match.end <= kept.end:
                continue
            if kept.start >= match.start and kept.end <= match.end:
                continue
            match_len = match.end - match.start
            kept_len = kept.end - kept.start
            if match_len > kept_len:
                resolved[i] = match
            dominated = True
            break
        if not dominated:
            resolved.append(match)
    resolved.sort(key=lambda m: (m.start, -(m.end - m.start)))
    return resolved


def _mk(start: int, end: int, tag: str = "") -> MatchResult:
    return MatchResult(pattern=tag or f"p{start}-{end}", start=start, end=end, value={})


def _as_tuples(matches: list[MatchResult]) -> list[tuple[int, int, str]]:
    return [(m.start, m.end, m.pattern) for m in matches]


class TestSweepEquivalence:
    def test_fuzz_matches_reference_semantics(self) -> None:
        """10k random cases: sweep output == old quadratic output, span for span."""
        matcher = AhoCorasickMatcher()
        rng = random.Random(42)
        for _ in range(10_000):
            n = rng.randint(0, 12)
            case = []
            for j in range(n):
                start = rng.randint(0, 30)
                end = start + rng.randint(1, 12)
                case.append(_mk(start, end, tag=f"t{j}"))
            expected = _as_tuples(_reference_resolve([_mk(m.start, m.end, m.pattern) for m in case]))
            actual = _as_tuples(matcher._resolve_overlaps(list(case)))
            assert actual == expected, f"divergence on case {_as_tuples(case)}"

    def test_known_semantics_pinned(self) -> None:
        matcher = AhoCorasickMatcher()
        # duplicate span deduped
        out = matcher._resolve_overlaps([_mk(0, 5, "a"), _mk(0, 5, "b")])
        assert _as_tuples(out) == [(0, 5, "a")]
        # contained spans both survive
        out = matcher._resolve_overlaps([_mk(0, 10, "outer"), _mk(2, 6, "inner")])
        assert _as_tuples(out) == [(0, 10, "outer"), (2, 6, "inner")]
        # partial overlap: longer wins
        out = matcher._resolve_overlaps([_mk(0, 6, "short"), _mk(3, 12, "longer")])
        assert _as_tuples(out) == [(3, 12, "longer")]
        # disjoint spans untouched
        out = matcher._resolve_overlaps([_mk(10, 15, "b"), _mk(0, 5, "a")])
        assert _as_tuples(out) == [(0, 5, "a"), (10, 15, "b")]

    def test_end_to_end_search_unchanged(self) -> None:
        """The public search() output is identical through the sweep (nested + overlaps)."""
        matcher = AhoCorasickMatcher()
        matcher.add_patterns(
            {
                "summary judgment": {"id": "1"},
                "judgment": {"id": "2"},
                "motion for summary judgment": {"id": "3"},
            }
        )
        matcher.build()
        got = [(m.pattern, m.start, m.end) for m in matcher.search("The Motion for Summary Judgment was denied.")]
        assert got == [
            ("motion for summary judgment", 4, 31),
            ("summary judgment", 15, 31),
            ("judgment", 23, 31),
        ]


class TestSweepScaling:
    def test_disjoint_regions_scale_near_linearly(self) -> None:
        """40k matches over disjoint regions (the repeated-document shape from the shootout).

        The quadratic implementation needs ~800M span comparisons here (minutes); the sweep
        retires each region as the scan passes it and finishes in well under the bound. The
        bound is deliberately generous (CI-safe) — it exists to catch a reintroduced O(m^2)
        rescan, which overshoots it by more than an order of magnitude.
        """
        matcher = AhoCorasickMatcher()
        matches = []
        for region in range(10_000):
            base = region * 50  # disjoint 50-char regions, 4 nested/overlapping spans each
            matches.append(_mk(base, base + 30))
            matches.append(_mk(base + 2, base + 12))
            matches.append(_mk(base + 4, base + 8))
            matches.append(_mk(base + 20, base + 40))
        t0 = time.perf_counter()
        out = matcher._resolve_overlaps(matches)
        elapsed = time.perf_counter() - t0
        assert len(out) == 30_000  # per region: 30-span keeps its 2 nested; 20-40 overlap loses
        assert elapsed < 5.0, f"overlap resolution took {elapsed:.1f}s — quadratic regression?"
