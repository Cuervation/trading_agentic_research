import json
from pathlib import Path

import pytest

from scripts.select_next_hypothesis import choose_next_hypothesis, load_hypothesis_bank


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_load_hypothesis_bank_validates_basis(tmp_path):
    bank_path = tmp_path / "bank.jsonl"
    _write_jsonl(
        bank_path,
        [
            {
                "hypothesis_id": "H1",
                "family": "academic_momentum",
                "claim": "x",
                "bibliography_basis": [{"source_id": "s1"}],
                "empirical_basis": [],
                "status": "candidate",
                "required_spy_comparison": "monthly_and_yearly",
            }
        ],
    )

    bank = load_hypothesis_bank(bank_path)

    assert bank[0]["hypothesis_id"] == "H1"


def test_choose_next_hypothesis_skips_rejected_and_cooldown():
    bank = [
        {
            "hypothesis_id": "H_REJ",
            "family": "risk_management",
            "claim": "x",
            "bibliography_basis": [{"source_id": "s1"}],
            "empirical_basis": [],
            "status": "candidate",
            "required_spy_comparison": "monthly_and_yearly",
        },
        {
            "hypothesis_id": "H_OK",
            "family": "academic_momentum",
            "claim": "y",
            "bibliography_basis": [{"source_id": "s2"}],
            "empirical_basis": [],
            "status": "candidate",
            "required_spy_comparison": "monthly_and_yearly",
        },
    ]

    learning_memory = {"family_summaries": {"academic_momentum": {"rejections": 0, "acceptances": 0}}}
    cooldowns = {"cooldowns": {"risk_management": {"reason": "repeated_failed_hypotheses"}}}

    selected = choose_next_hypothesis(
        hypothesis_bank=bank,
        learning_memory=learning_memory,
        cooldowns=cooldowns,
        rejected_ids={"H_REJ"},
        accepted_ids=set(),
        prefer_unseen=True,
    )

    assert selected["hypothesis_id"] == "H_OK"


def test_choose_next_hypothesis_prefers_unseen_when_enabled():
    bank = [
        {
            "hypothesis_id": "H_SEEN",
            "family": "academic_momentum",
            "claim": "x",
            "bibliography_basis": [{"source_id": "s1"}],
            "empirical_basis": [{"run_id": "EXP_1"}],
            "status": "candidate",
            "required_spy_comparison": "monthly_and_yearly",
        },
        {
            "hypothesis_id": "H_UNSEEN",
            "family": "academic_momentum",
            "claim": "y",
            "bibliography_basis": [{"source_id": "s2"}],
            "empirical_basis": [],
            "status": "candidate",
            "required_spy_comparison": "monthly_and_yearly",
        },
    ]

    learning_memory = {"family_summaries": {"academic_momentum": {"rejections": 0, "acceptances": 0}}}
    cooldowns = {"cooldowns": {}}

    selected = choose_next_hypothesis(
        hypothesis_bank=bank,
        learning_memory=learning_memory,
        cooldowns=cooldowns,
        rejected_ids=set(),
        accepted_ids={"H_SEEN"},
        prefer_unseen=True,
    )

    assert selected["hypothesis_id"] == "H_UNSEEN"


def test_choose_next_hypothesis_prefers_better_axis_score_when_seen_equal():
    bank = [
        {
            "hypothesis_id": "H_EXIT",
            "family": "academic_momentum",
            "claim": "x",
            "bibliography_basis": [{"source_id": "s1"}],
            "empirical_basis": [],
            "status": "candidate",
            "required_spy_comparison": "monthly_and_yearly",
            "strategy_overrides": {"exit_rule": {"rank_threshold": 15}},
        },
        {
            "hypothesis_id": "H_TOPN",
            "family": "academic_momentum",
            "claim": "y",
            "bibliography_basis": [{"source_id": "s2"}],
            "empirical_basis": [],
            "status": "candidate",
            "required_spy_comparison": "monthly_and_yearly",
            "strategy_overrides": {"entry_rule": {"top_n": 8}},
        },
    ]
    memory = {"family_summaries": {"academic_momentum": {"rejections": 0, "acceptances": 0}}}
    parameter_effect_memory = {
        "effects_by_axis": {"concentration": {"score": 2.0}, "exit_threshold": {"score": -1.0}}
    }

    selected = choose_next_hypothesis(
        hypothesis_bank=bank,
        learning_memory=memory,
        cooldowns={"cooldowns": {}},
        rejected_ids=set(),
        accepted_ids=set(),
        parameter_effect_memory=parameter_effect_memory,
        prefer_unseen=True,
    )

    assert selected["hypothesis_id"] == "H_TOPN"


def test_choose_next_hypothesis_raises_when_none_eligible():
    bank = [
        {
            "hypothesis_id": "H_BAD",
            "family": "risk_management",
            "claim": "x",
            "bibliography_basis": [{"source_id": "s1"}],
            "empirical_basis": [],
            "status": "candidate",
            "required_spy_comparison": "monthly_and_yearly",
        }
    ]

    learning_memory = {"family_summaries": {}}
    cooldowns = {"cooldowns": {"risk_management": {"reason": "repeated_failed_hypotheses"}}}

    with pytest.raises(ValueError):
        choose_next_hypothesis(
            hypothesis_bank=bank,
            learning_memory=learning_memory,
            cooldowns=cooldowns,
            rejected_ids=set(),
            accepted_ids=set(),
        )
