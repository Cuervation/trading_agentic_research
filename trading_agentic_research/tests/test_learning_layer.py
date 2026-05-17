import json
from pathlib import Path

import pytest

from scripts.generate_hypotheses_from_bibliography import (
    build_hypothesis_card,
    validate_candidate_basis,
)
from scripts.score_hypothesis_against_memory import metric_no_effect_rejected
from scripts.score_hypothesis_against_memory import (
    is_cooldown_active,
    score_hypothesis_against_memory,
)
from scripts.update_evidence_memory import (
    build_learning_event,
    family_should_go_to_cooldown,
    persist_learning_from_run,
    update_subspace_cooldowns,
)

ROOT = Path(__file__).resolve().parents[1]


def _load_schema(name: str) -> dict:
    return json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8-sig"))


def test_candidate_requires_basis():
    with pytest.raises(ValueError):
        validate_candidate_basis({"hypothesis_id": "H1", "bibliography_basis": [], "empirical_basis": []})

    bibliographic = build_hypothesis_card(
        hypothesis_id="H2",
        family="academic_momentum",
        claim="Momentum should persist.",
        bibliography_basis=[{"source_id": "academic_momentum_jegadeesh_titman_1993"}],
    )
    assert bibliographic["bibliography_basis"][0]["source_id"]

    empirical = build_hypothesis_card(
        hypothesis_id="H3",
        family="risk_management",
        claim="A trailing stop may reduce drawdown.",
        empirical_basis=[{"run_id": "EXP_001"}],
    )
    assert empirical["empirical_basis"][0]["run_id"] == "EXP_001"


def test_bibliography_source_schema():
    schema = _load_schema("bibliography_source.schema.json")
    assert schema["title"] == "BibliographySource"
    assert {"source_id", "family", "title", "principle"}.issubset(set(schema["required"]))


def test_hypothesis_schema():
    schema = _load_schema("hypothesis.schema.json")
    assert schema["title"] == "Hypothesis"
    assert {"hypothesis_id", "family", "claim", "bibliography_basis", "empirical_basis", "status"}.issubset(
        set(schema["required"])
    )


def test_learning_event_schema():
    schema = _load_schema("learning_event.schema.json")
    assert schema["title"] == "LearningEvent"
    assert {"learning_id", "hypothesis_id", "family", "run_id", "decision", "flags"}.issubset(
        set(schema["required"])
    )


def test_failed_family_goes_to_cooldown():
    events = [
        {"family": "darvas_box", "decision": "rejected"},
        {"family": "darvas_box", "decision": "rejected"},
        {"family": "darvas_box", "decision": "rejected"},
    ]

    assert family_should_go_to_cooldown(events, "darvas_box", threshold=3) is True
    cooldowns = update_subspace_cooldowns({"version": 1, "cooldowns": {}}, events, threshold=3)
    assert "darvas_box" in cooldowns["cooldowns"]


def test_metric_no_effect_rejected():
    result = metric_no_effect_rejected(
        {"cagr_delta_pct": 0.0, "max_drawdown_delta_pct": 0.0, "trade_count_delta": 0.0}
    )

    assert result["decision"] == "rejected"
    assert result["reason"] == "metric_no_effect"
    assert result["can_move_parent"] is False
    assert "metric_no_effect" in result["flags"]

    changed = metric_no_effect_rejected({"cagr_delta_pct": 0.2, "max_drawdown_delta_pct": 0.0, "trade_count_delta": 0.0})
    assert changed["decision"] == "review"


def test_no_baseline_auto_promotion():
    event = build_learning_event(
        learning_id="L1",
        hypothesis_id="H1",
        family="academic_momentum",
        run_id="EXP_001",
        decision="promoted_candidate",
        metrics={"cagr_delta_pct": 10.0, "max_drawdown_delta_pct": 0.0},
    )

    assert event["decision"] == "promoted_candidate"
    assert event["can_promote_baseline"] is False
    assert event["written_to_learning_memory"] is True



def test_audit_persists_learning_and_evidence_memory(tmp_path):
    run_dir = tmp_path / "runs" / "EXP_TEST"
    state_dir = tmp_path / "state"
    run_dir.mkdir(parents=True)
    state_dir.mkdir()

    (run_dir / "metrics.json").write_text(
        json.dumps(
            {
                "strategy": {"max_drawdown_pct": -18.0},
                "spy": {"max_drawdown_pct": -20.0},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "spy_comparison_summary.json").write_text(
        json.dumps(
            {
                "excess_cagr_pct": 5.0,
                "months_beating_spy": 8,
                "months_losing_to_spy": 4,
                "years_beating_spy": 3,
                "years_losing_to_spy": 1,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "spy_comparison_yearly.csv").write_text(
        "year;strategy_return_pct;spy_return_pct;excess_return_pct;winner\n"
        "2024;20,0;10,0;10,0;strategy\n"
        "2025;12,0;8,0;4,0;strategy\n",
        encoding="utf-8",
    )
    (state_dir / "learning_memory.json").write_text(
        json.dumps({"version": 1, "family_summaries": {}, "learning_events": []}),
        encoding="utf-8",
    )
    (state_dir / "evidence_memory.json").write_text(
        json.dumps({"version": 1, "runs": {}, "hypothesis_evidence": {}}),
        encoding="utf-8",
    )
    (state_dir / "subspace_cooldowns.json").write_text(
        json.dumps({"version": 1, "cooldowns": {}, "default_failure_threshold": 3}),
        encoding="utf-8",
    )

    result = persist_learning_from_run(
        run_dir=run_dir,
        state_dir=state_dir,
        run_id="EXP_TEST",
        hypothesis_id="HYP_TEST",
        family="academic_momentum",
        audit={"decision": "promoted_candidate"},
    )

    memory = json.loads((state_dir / "learning_memory.json").read_text(encoding="utf-8"))
    evidence = json.loads((state_dir / "evidence_memory.json").read_text(encoding="utf-8"))
    accepted_lines = (state_dir / "accepted_hypotheses.jsonl").read_text(encoding="utf-8").splitlines()

    assert result["learning_event"]["learning_id"] == "LEARN_EXP_TEST"
    assert memory["learning_events"][0]["run_id"] == "EXP_TEST"
    assert evidence["runs"]["EXP_TEST"]["hypothesis_id"] == "HYP_TEST"
    assert evidence["runs"]["EXP_TEST"]["can_promote_baseline"] is False
    assert len(accepted_lines) == 1


def test_learning_event_is_idempotent_and_keeps_parent_deltas(tmp_path):
    run_dir = tmp_path / "runs" / "EXP_PARENT_CHECK"
    state_dir = tmp_path / "state"
    run_dir.mkdir(parents=True)
    state_dir.mkdir()

    (run_dir / "metrics.json").write_text(
        json.dumps(
            {
                "strategy": {"max_drawdown_pct": -30.0},
                "spy": {"max_drawdown_pct": -35.0},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "spy_comparison_summary.json").write_text(
        json.dumps(
            {
                "excess_cagr_pct": 10.0,
                "months_beating_spy": 8,
                "months_losing_to_spy": 4,
                "years_beating_spy": 3,
                "years_losing_to_spy": 1,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "spy_comparison_yearly.csv").write_text(
        "year;strategy_return_pct;spy_return_pct;excess_return_pct;winner\n"
        "2025;12,0;8,0;4,0;strategy\n",
        encoding="utf-8",
    )

    audit = {
        "decision": "rejected",
        "parent_comparison": {
            "parent_available": True,
            "excess_cagr_vs_parent_pct": -5.0,
            "drawdown_delta_vs_parent_pct": -4.0,
            "months_beating_parent": 2,
            "months_losing_to_parent": 6,
            "years_beating_parent": 0,
            "years_losing_to_parent": 1,
        },
    }

    for _ in range(2):
        persist_learning_from_run(
            run_dir=run_dir,
            state_dir=state_dir,
            run_id="EXP_PARENT_CHECK",
            hypothesis_id="HYP_PARENT_CHECK",
            family="risk_management",
            audit=audit,
        )

    memory = json.loads((state_dir / "learning_memory.json").read_text(encoding="utf-8"))
    evidence = json.loads((state_dir / "evidence_memory.json").read_text(encoding="utf-8"))
    rejected_lines = (state_dir / "rejected_hypotheses.jsonl").read_text(encoding="utf-8").splitlines()

    assert len(memory["learning_events"]) == 1
    assert memory["family_summaries"]["risk_management"]["rejections"] == 1
    assert evidence["runs"]["EXP_PARENT_CHECK"]["metrics"]["parent_cagr_delta_pct"] == -5.0
    assert evidence["hypothesis_evidence"]["HYP_PARENT_CHECK"] == ["EXP_PARENT_CHECK"]
    assert len(rejected_lines) == 1
    assert "parent_underperformance" in memory["learning_events"][0]["flags"]


def test_score_hypothesis_blocked_by_active_cooldown():
    hypothesis = {"hypothesis_id": "HYP_1", "family": "darvas_box"}
    learning_memory = {"family_summaries": {"darvas_box": {"rejections": 4, "acceptances": 0}}}
    cooldowns = {
        "cooldowns": {
            "darvas_box": {
                "reason": "repeated_failed_hypotheses",
            }
        }
    }

    result = score_hypothesis_against_memory(hypothesis, learning_memory, cooldowns)

    assert is_cooldown_active(cooldowns, "darvas_box") is True
    assert result["decision"] == "rejected"
    assert result["reason"] == "repeated_failed_hypotheses"
    assert result["can_generate_candidate"] is False


def test_score_hypothesis_rejects_metric_no_effect_candidate():
    hypothesis = {
        "hypothesis_id": "HYP_2",
        "family": "academic_momentum",
        "metric_deltas": {
            "cagr_delta_pct": 0.0,
            "max_drawdown_delta_pct": 0.0004,
            "trade_count_delta": 0.0,
        },
    }
    learning_memory = {"family_summaries": {"academic_momentum": {"rejections": 1, "acceptances": 2}}}

    result = score_hypothesis_against_memory(hypothesis, learning_memory, cooldowns={"cooldowns": {}})

    assert result["decision"] == "rejected"
    assert result["reason"] == "metric_no_effect"
    assert result["can_generate_candidate"] is False
