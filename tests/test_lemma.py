"""Tests for lemma-key label-index augmentation (folio_resolve.lemma).

Fixtures mirror the 2026-07-16 ruler-shootout gold sets (bench/RESULTS.md): lemma keys are
index augmentation, engine-agnostic, and must degrade gracefully without the ``[spacy]`` extra.
All tests inject a fake lemmatizer so the suite never needs spaCy or a model download.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from folio_resolve import (
    Concept,
    FOLIOEntityRuler,
    LabelInfo,
    SpacyNotInstalledError,
    augment_labels,
    compute_label_lemmas,
    load_lemma_cache,
    save_lemma_cache,
)
from folio_resolve.lemma import LEMMA_VERSION

# A tiny deterministic "lemmatizer": strip a trailing s (the shootout's agreement/Agreements
# reachability case) — plus identity for everything else.
_FAKE_LEMMAS = {
    "agreements": "agreement",
    "motions": "motion",
    "damages": "damage",  # denylisted surface — must never produce a key
    "auctions": "auction",
}


def fake_lemmatize(words: list[str]) -> list[str]:
    return [_FAKE_LEMMAS.get(w, w) for w in words]


@pytest.fixture
def labels() -> dict[str, LabelInfo]:
    agreements = Concept(iri="R-agreements", label="Agreements", branch="Document Artifacts")
    license_ = Concept(iri="R-license", label="License (Agreement)", branch="Document Artifacts")
    motions = Concept(iri="R-motions", label="Motions", branch="Document Artifacts")
    damages = Concept(iri="R-damages", label="Damages", branch="Objectives")
    auction = Concept(iri="R-auction", label="Auctions", branch="Events")
    return {
        "agreements": LabelInfo(concept=agreements, label_type="preferred"),
        # The same surface "agreement" is ALSO another concept's exact alternative label —
        # the shootout's License (Agreement) collision. lemma_preferred must win the slot.
        "agreement": LabelInfo(concept=license_, label_type="alternative"),
        "motions": LabelInfo(concept=motions, label_type="preferred"),
        "damages": LabelInfo(concept=damages, label_type="preferred"),  # denylisted
        "auctions": LabelInfo(concept=auction, label_type="alternative"),
        "multi word label": LabelInfo(concept=motions, label_type="preferred"),
        "abc": LabelInfo(concept=motions, label_type="preferred"),  # too short (<=3)
    }


class TestComputeLabelLemmas:
    def test_basic_map(self, labels: dict[str, LabelInfo]) -> None:
        m = compute_label_lemmas(labels, lemmatize=fake_lemmatize)
        assert m["agreements"] == "agreement"
        assert m["motions"] == "motion"
        assert m["auctions"] == "auction"

    def test_denylist_blocks_surface(self, labels: dict[str, LabelInfo]) -> None:
        m = compute_label_lemmas(labels, lemmatize=fake_lemmatize)
        assert "damages" not in m  # pluralia-tantum denylist (spec.behavior.lemma_denylist)

    def test_multiword_and_short_keys_skipped(self, labels: dict[str, LabelInfo]) -> None:
        m = compute_label_lemmas(labels, lemmatize=fake_lemmatize)
        assert "multi word label" not in m
        assert "abc" not in m

    def test_identity_lemmas_dropped(self, labels: dict[str, LabelInfo]) -> None:
        m = compute_label_lemmas(labels, lemmatize=fake_lemmatize)
        assert "agreement" not in m  # its fake lemma equals the surface

    def test_denylisted_lemma_target_dropped(self) -> None:
        c = Concept(iri="R-x", label="Wills", branch="Estates")
        labels = {"wills": LabelInfo(concept=c, label_type="preferred")}
        m = compute_label_lemmas(labels, lemmatize=lambda ws: ["will" for _ in ws])
        assert m == {}  # "will" is on the FOLIO denylist


class TestAugmentLabels:
    def test_lemma_reachability(self, labels: dict[str, LabelInfo]) -> None:
        out = augment_labels(labels, lemmatize=fake_lemmatize)
        # agreement -> Agreements as lemma_preferred, OUTRANKING the exact alternative
        # (License) that previously owned the slot — the shootout's collision semantics.
        assert out["agreement"].concept.iri == "R-agreements"
        assert out["agreement"].label_type == "lemma_preferred"
        # motion (new key) -> Motions
        assert out["motion"].concept.iri == "R-motions"
        assert out["motion"].label_type == "lemma_preferred"
        # lemma of an alternative label gets the alternative-grade lemma tier
        assert out["auction"].label_type == "lemma_alternative"

    def test_never_overwrites_equal_or_higher_tier(self, labels: dict[str, LabelInfo]) -> None:
        other = Concept(iri="R-other", label="Motion", branch="Document Artifacts")
        labels = dict(labels)
        labels["motion"] = LabelInfo(concept=other, label_type="preferred")
        out = augment_labels(labels, lemmatize=fake_lemmatize)
        assert out["motion"].concept.iri == "R-other"  # exact preferred beats lemma_preferred
        assert out["motion"].label_type == "preferred"

    def test_originals_untouched_except_outranked_slots(
        self, labels: dict[str, LabelInfo]
    ) -> None:
        out = augment_labels(labels, lemmatize=fake_lemmatize)
        for key, info in labels.items():
            if key == "agreement":
                continue  # legitimately outranked by lemma_preferred (collision semantics)
            assert out[key] is info
        # The INPUT mapping is never mutated — the outranking happens on the copy.
        assert labels["agreement"].concept.iri == "R-license"
        assert labels["agreement"].label_type == "alternative"

    def test_explicit_lemma_map_skips_computation(self, labels: dict[str, LabelInfo]) -> None:
        out = augment_labels(labels, lemma_map={"motions": "motion"})  # no lemmatizer at all
        assert out["motion"].concept.iri == "R-motions"
        assert "agreement" in out and out["agreement"].concept.iri == "R-license"

    def test_invalid_on_missing_spacy_value(self, labels: dict[str, LabelInfo]) -> None:
        with pytest.raises(ValueError, match="on_missing_spacy"):
            augment_labels(labels, lemmatize=fake_lemmatize, on_missing_spacy="explode")


class TestDegradationWithoutSpacy:
    """Without the [spacy] extra: clear error by default, no-op with on_missing_spacy='skip'."""

    @pytest.fixture(autouse=True)
    def _no_spacy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise() -> object:
            raise SpacyNotInstalledError('install "folio-resolve[spacy]"')

        monkeypatch.setattr("folio_resolve.lemma.spacy_lemmatizer", lambda *a, **k: _raise())

    def test_default_raises_named_extra(self, labels: dict[str, LabelInfo]) -> None:
        with pytest.raises(SpacyNotInstalledError, match=r"folio-resolve\[spacy\]"):
            augment_labels(labels)

    def test_skip_returns_index_unchanged(self, labels: dict[str, LabelInfo]) -> None:
        out = augment_labels(labels, on_missing_spacy="skip")
        assert out == dict(labels)  # exactly the shootout's ac-base behavior


class TestLemmaCache:
    def test_roundtrip_and_version_keying(self, tmp_path: Path) -> None:
        save_lemma_cache(tmp_path, "hash123", {"agreements": "agreement"})
        assert load_lemma_cache(tmp_path, "hash123") == {"agreements": "agreement"}
        assert load_lemma_cache(tmp_path, "otherhash") is None
        assert (tmp_path / f"lemmas_hash123_v{LEMMA_VERSION}.json").exists()

    def test_corrupt_cache_is_a_miss(self, tmp_path: Path) -> None:
        (tmp_path / f"lemmas_h_v{LEMMA_VERSION}.json").write_text("{not json", encoding="utf-8")
        assert load_lemma_cache(tmp_path, "h") is None

    def test_augment_writes_then_reads_cache(
        self, labels: dict[str, LabelInfo], tmp_path: Path
    ) -> None:
        out1 = augment_labels(
            labels, lemmatize=fake_lemmatize, cache_dir=tmp_path, ontology_hash="owl1"
        )
        assert load_lemma_cache(tmp_path, "owl1") is not None
        # Second call: no lemmatizer needed — cache satisfies it (steady-state, spaCy-free).
        calls: list[int] = []

        def exploding(words: list[str]) -> list[str]:
            calls.append(1)
            raise AssertionError("cache should have been used")

        out2 = augment_labels(
            labels, lemmatize=exploding, cache_dir=tmp_path, ontology_hash="owl1"
        )
        assert calls == []
        assert {k: (v.concept.iri, v.label_type) for k, v in out1.items()} == {
            k: (v.concept.iri, v.label_type) for k, v in out2.items()
        }


class TestRulerConsumesLemmaKeys:
    """End-to-end: the AC ruler matches lemma-augmented keys with preferred-tier confidence."""

    def test_agreement_reaches_agreements(self, labels: dict[str, LabelInfo]) -> None:
        augmented = augment_labels(labels, lemmatize=fake_lemmatize)
        ruler = FOLIOEntityRuler()
        ruler.load_patterns(augmented)
        matches = ruler.find_matches("The parties signed the motion and agreement today.")
        by_surface = {m.text.lower(): m for m in matches}
        assert by_surface["agreement"].entity_id == "R-agreements"
        assert by_surface["agreement"].match_type == "lemma_preferred"
        assert by_surface["agreement"].confidence == pytest.approx(0.72)  # preferred tier
        assert by_surface["motion"].entity_id == "R-motions"
