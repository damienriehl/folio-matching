"""Alias / homonym blocklist.

Ch02 unit ``4b06a90c``: *"Action != Auction. Awful."* — a deterministic homonym the LLM judge
should never have to catch. folio-mapper and folio-enrich both lack a deterministic homonym
guard. This module is that guard: a versioned set of ``(surface_term, blocked_iri, domain)``
triples. A ``wrong`` per-tag verdict on a homonym appends a triple here, and the matcher consults
it to drop the bad candidate before it ever reaches a judge.

The blocklist is domain-scoped: ``domain=None`` blocks the pairing everywhere; a specific domain
(e.g. ``"litigation"``) blocks it only when that domain prior is active, so an alias that is wrong
in one practice area can remain valid in another.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

logger = logging.getLogger(__name__)

# The shipped seed lives as package data so every consumer loads the same recorded verdicts.
SEED_RESOURCE = ("folio_resolve.data", "alias_blocklist.json")


@dataclass(frozen=True)
class BlockedAlias:
    surface_term: str
    blocked_iri: str
    domain: str | None = None
    reason: str = ""

    def key(self) -> tuple[str, str, str]:
        return (self.surface_term.lower(), self.blocked_iri, (self.domain or "").lower())


class AliasBlocklist:
    """A set of blocked ``(surface_term, iri, domain)`` pairings the matcher consults."""

    def __init__(self, entries: Iterable[BlockedAlias] | None = None) -> None:
        self._entries: dict[tuple[str, str, str], BlockedAlias] = {}
        for entry in entries or []:
            self.add(entry)

    def add(self, entry: BlockedAlias) -> None:
        self._entries[entry.key()] = entry

    def block(
        self, surface_term: str, blocked_iri: str, domain: str | None = None, reason: str = ""
    ) -> None:
        self.add(BlockedAlias(surface_term, blocked_iri, domain, reason))

    def is_blocked(self, surface_term: str, iri: str, *, domains: Iterable[str] | None = None) -> bool:
        """True if this surface_term→iri pairing is blocked globally or in any active domain."""
        term = surface_term.lower()
        # Global block (domain unset) applies everywhere.
        if (term, iri, "") in self._entries:
            return True
        return any((term, iri, domain.lower()) in self._entries for domain in domains or [])

    def filter_candidates(
        self,
        surface_term: str,
        candidates: Iterable[tuple[str, float]],
        *,
        domains: Iterable[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Drop ``(iri, score)`` candidates blocked for this surface term."""
        domain_list = list(domains or [])
        return [
            (iri, score)
            for iri, score in candidates
            if not self.is_blocked(surface_term, iri, domains=domain_list)
        ]

    def __len__(self) -> int:
        return len(self._entries)

    def is_empty(self) -> bool:
        return not self._entries

    def entries(self) -> list[BlockedAlias]:
        return list(self._entries.values())

    # -- persistence -------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> AliasBlocklist:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            BlockedAlias(
                surface_term=row["surface_term"],
                blocked_iri=row["blocked_iri"],
                domain=row.get("domain"),
                reason=row.get("reason", ""),
            )
            for row in data.get("blocked_aliases", [])
        )

    @classmethod
    def from_seed(cls) -> AliasBlocklist:
        """Load the blocklist shipped as package data (the recorded Ch01/Ch02 verdicts).

        Returns an empty blocklist (never raises) if the seed resource is missing, so a consumer
        degrades to "no homonym vetoes" rather than crashing the tagger.
        """
        pkg, name = SEED_RESOURCE
        try:
            data = (resources.files(pkg) / name).read_text(encoding="utf-8")
        except (FileNotFoundError, ModuleNotFoundError, OSError):
            logger.warning("Alias blocklist seed %s/%s not found; using empty blocklist", pkg, name)
            return cls()
        rows = json.loads(data).get("blocked_aliases", [])
        return cls(
            BlockedAlias(
                surface_term=row["surface_term"],
                blocked_iri=row["blocked_iri"],
                domain=row.get("domain"),
                reason=row.get("reason", ""),
            )
            for row in rows
        )

    def save(self, path: str | Path) -> None:
        payload = {
            "version": 1,
            "blocked_aliases": [
                {
                    "surface_term": e.surface_term,
                    "blocked_iri": e.blocked_iri,
                    "domain": e.domain,
                    "reason": e.reason,
                }
                for e in self._entries.values()
            ],
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_seed_blocklist() -> AliasBlocklist:
    """Module-level convenience: the shipped seed blocklist (recorded Ch01/Ch02 verdicts)."""
    return AliasBlocklist.from_seed()
