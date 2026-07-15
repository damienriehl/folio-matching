"""Judge — verdict enforcement + domain-prior prompt threading."""

from __future__ import annotations

import json

from folio_matching import build_judge_prompt, enforce_verdict, parse_judge_json
from folio_matching.judge import SCORE_CALIBRATION, build_contextual_rerank_prompt


def test_enforce_rejected_forces_zero() -> None:
    assert enforce_verdict(80.0, 50.0, "rejected") == 0.0


def test_enforce_confirmed_clamps_within_5() -> None:
    assert enforce_verdict(80.0, 95.0, "confirmed") == 85.0


def test_enforce_boost_capped_at_25() -> None:
    assert enforce_verdict(50.0, 200.0, "boosted") == 75.0


def test_parse_drops_hallucinated_iris() -> None:
    ranked = {"R1": 80.0}
    raw = json.dumps(
        {
            "judged": [
                {"iri_hash": "R1", "adjusted_score": 82, "verdict": "confirmed", "reasoning": "ok"},
                {"iri_hash": "FAKE", "adjusted_score": 90, "verdict": "boosted", "reasoning": "halluc"},
            ]
        }
    )
    out = parse_judge_json(raw, ranked)
    assert len(out) == 1
    assert out[0].iri == "R1"


def test_parse_bad_json_returns_empty() -> None:
    assert parse_judge_json("not json", {"R1": 80.0}) == []


def test_judge_prompt_threads_domain_prior() -> None:
    _system, user = build_judge_prompt(
        "The defenses raised were meritless.",
        [{"iri_hash": "R-defenses", "label": "Litigation Defenses"}],
        document_type="Litigation / Trial Advocacy treatise",
    )
    assert "Litigation / Trial Advocacy treatise" in user
    assert "Document Type" in user


def test_calibration_block_in_prompt() -> None:
    system, _user = build_judge_prompt("x", [])
    assert SCORE_CALIBRATION in system
    assert "90+" in system


def test_contextual_rerank_prompt_injects_domain() -> None:
    prompt = build_contextual_rerank_prompt(
        "Some excerpt", [{"folio_iri": "R1", "folio_label": "X"}], document_type="Litigation"
    )
    assert "This document is: Litigation" in prompt
