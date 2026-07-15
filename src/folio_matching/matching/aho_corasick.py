"""Pure-Python Aho-Corasick multi-pattern matcher.

Reimplements folio-enrich's ``AhoCorasickMatcher`` contract (``MatchResult`` with char
offsets, word-boundary validation, containment-aware overlap resolution) **without** the
compiled ``pyahocorasick`` C extension — a lift-and-improve that removes a heavy dependency
and makes the ruler installable everywhere. The automaton is a classic goto/fail/output trie
built with a BFS failure-link pass.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class MatchResult:
    pattern: str
    start: int
    end: int  # exclusive
    value: dict[str, object]


@dataclass
class _Node:
    children: dict[str, _Node] = field(default_factory=dict)
    fail: _Node | None = None
    outputs: list[tuple[str, dict[str, object]]] = field(default_factory=list)


def _is_word_boundary(text: str, pos: int) -> bool:
    """True when ``pos`` is outside the string or holds a non-word character."""
    if pos < 0 or pos >= len(text):
        return True
    ch = text[pos]
    return not (ch.isalnum() or ch == "_")


class AhoCorasickMatcher:
    """Match many patterns against text in a single linear pass."""

    def __init__(self) -> None:
        self._root = _Node()
        self._built = False
        self._pattern_count = 0

    def add_pattern(self, pattern: str, value: dict[str, object] | None = None) -> None:
        key = pattern.lower()
        node = self._root
        for ch in key:
            node = node.children.setdefault(ch, _Node())
        node.outputs.append((pattern, value or {}))
        self._pattern_count += 1
        self._built = False

    def add_patterns(self, patterns: dict[str, dict[str, object]]) -> None:
        for pattern, value in patterns.items():
            self.add_pattern(pattern, value)

    def build(self) -> None:
        """Compute failure links via BFS. Idempotent-safe to call before searching."""
        queue: deque[_Node] = deque()
        self._root.fail = self._root
        for child in self._root.children.values():
            child.fail = self._root
            queue.append(child)
        while queue:
            current = queue.popleft()
            for ch, child in current.children.items():
                queue.append(child)
                fail = current.fail
                assert fail is not None
                while fail is not self._root and ch not in fail.children:
                    assert fail.fail is not None
                    fail = fail.fail
                child.fail = fail.children.get(ch, self._root)
                if child.fail is child:
                    child.fail = self._root
                child.outputs.extend(child.fail.outputs)
        self._built = True

    def search(self, text: str, *, case_sensitive: bool = False) -> list[MatchResult]:
        if not self._built:
            self.build()

        search_text = text if case_sensitive else text.lower()
        raw: list[MatchResult] = []
        node = self._root
        for end_idx, ch in enumerate(search_text):
            while node is not self._root and ch not in node.children:
                assert node.fail is not None
                node = node.fail
            node = node.children.get(ch, self._root)
            for pattern, value in node.outputs:
                start_idx = end_idx - len(pattern) + 1
                if not _is_word_boundary(search_text, start_idx - 1):
                    continue
                if not _is_word_boundary(search_text, end_idx + 1):
                    continue
                raw.append(
                    MatchResult(pattern=pattern, start=start_idx, end=end_idx + 1, value=value)
                )
        return self._resolve_overlaps(raw)

    def _resolve_overlaps(self, matches: list[MatchResult]) -> list[MatchResult]:
        """Contained spans both survive; partial overlaps: longer wins; duplicates deduped."""
        if not matches:
            return []

        matches.sort(key=lambda m: (m.start, -(m.end - m.start)))
        resolved: list[MatchResult] = []

        for match in matches:
            dominated = False
            for i, kept in enumerate(resolved):
                if match.start >= kept.end or match.end <= kept.start:
                    continue  # no overlap
                if match.start == kept.start and match.end == kept.end:
                    dominated = True
                    break
                if match.start >= kept.start and match.end <= kept.end:
                    continue  # contained — both survive
                if kept.start >= match.start and kept.end <= match.end:
                    continue  # contains kept — both survive
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

    @property
    def pattern_count(self) -> int:
        return self._pattern_count
