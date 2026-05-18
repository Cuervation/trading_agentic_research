import json
from pathlib import Path

from scripts.research.generation_selection_feedback import diagnose_generated_hypotheses, record_generation_selection_feedback
from scripts.research.feature_space_expansion_factory import generate_feature_space_hypotheses


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def hypothesis(hid: str, family: str = "feature_space_composite_confirmation") -> dict:
    return {
        "hypothesis_id": hid,
        "family": family,
        "claim": "test",
        "causal_mechanism": "test",
        "bibliography_basis": [{"source_id": "test", "title": "test"}],
        "empirical_basis": [{"run_id": "AUTO_002", "reason": "test"}],
        "features_required": ["channel_r2", "close"],
        "status": "candidate",
        "required_spy_comparison": "monthly_and_yearly",
        "axis": "feature_space_rank_confirm",
        "falsification_rule": "reject duplicates",
        "strategy_overrides": {
            "ranking": {"field": "channel_r2", "order": "desc"},
            "risk_filters": {"require_non_null_fields": ["channel_r2", "close"]},
        },
    }


def test_diagnostics_marks_selectable_generated_id(tmp_path):
    state = tmp_path / "state"
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    hid = "HYP_FSPACE_AUTO_002_TEST_V1"
    write_json(state / "current_parent.json", {"current_parent_hypothesis_id": "HYP_PARENT"})
    write_json(state / "candidate_under_review.json", {"status": "review_exhausted", "candidate_run_id": "EXP_054"})
    append_jsonl(bank, [hypothesis(hid)])

    result = diagnose_generated_hypotheses(generated_ids=[hid], hypothesis_bank=bank, state_dir=state)

    assert result["selectable_ids"] == [hid]
    assert result["counts"]["blocked"] == 0


def test_diagnostics_blocks_duplicate_signature(tmp_path):
    state = tmp_path / "state"
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    old = hypothesis("HYP_OLD")
    new = hypothesis("HYP_NEW")
    write_json(state / "current_parent.json", {"current_parent_hypothesis_id": "HYP_PARENT"})
    write_json(state / "candidate_under_review.json", {"status": "review_exhausted", "candidate_run_id": "EXP_054"})
    append_jsonl(bank, [old, new])
    append_jsonl(state / "consumed_hypotheses.jsonl", [{"hypothesis_id": "HYP_OLD", "run_id": "EXP_001"}])

    result = diagnose_generated_hypotheses(generated_ids=["HYP_NEW"], hypothesis_bank=bank, state_dir=state)

    assert result["selectable_ids"] == []
    assert result["blocked"][0]["reason"] == "duplicate_signature_blocked"


def test_record_generation_selection_feedback_writes_files(tmp_path):
    diagnostics = {
        "selectable_ids": [],
        "blocked": [{"hypothesis_id": "HYP_X", "reason": "family_cooldown"}],
        "counts": {"generated": 1, "selectable": 0, "blocked": 1},
        "reason_counts": {"family_cooldown": 1},
    }

    event = record_generation_selection_feedback(
        state_dir=tmp_path / "state",
        reports_dir=tmp_path / "reports",
        phase="feature_space_expansion",
        generation_result={"generated": 1, "hypotheses": ["HYP_X"], "reason": "test"},
        diagnostics=diagnostics,
    )

    assert event["warning"] == "generated_but_none_selectable"
    assert (tmp_path / "state" / "generation_selection_feedback.json").exists()
    assert (tmp_path / "reports" / "generation_selection_feedback.md").exists()


def test_feature_space_generator_skips_family_in_cooldown_and_generates_other_layer(tmp_path):
    state = tmp_path / "state"
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    parent = tmp_path / "configs" / "parent.json"
    weekly = tmp_path / "data" / "weekly.csv"

    write_json(state / "current_parent.json", {"current_parent_run_id": "AUTO_002", "current_parent_hypothesis_id": "HYP_PARENT"})
    write_json(state / "subspace_cooldowns.json", {
        "version": 1,
        "cooldowns": {
            "feature_space_composite_confirmation": {"reason": "test_cooldown"}
        },
    })
    write_json(parent, {
        "strategy_id": "HYP_PARENT",
        "ranking": {"field": "close_vs_sma52w_pct", "order": "desc"},
        "entry_rule": {"top_n": 8},
        "exit_rule": {"rank_threshold": 20},
    })
    weekly.parent.mkdir(parents=True, exist_ok=True)
    weekly.write_text(
        "date,ticker,close,channel_r2,channel_slope_pct,close_vs_sma20w_pct,close_vs_sma52w_pct,ret_26w_pct\n",
        encoding="utf-8",
    )
    write_json(state / "data_paths_resolved.json", {"weekly_file": str(weekly)})
    bank.parent.mkdir(parents=True, exist_ok=True)
    bank.write_text("", encoding="utf-8")

    # Pre-create pure ranking rows so the generator must try composite layers.
    existing = []
    for field in ["channel_r2", "channel_slope_pct", "close_vs_sma20w_pct", "ret_26w_pct"]:
        existing.append({
            "hypothesis_id": f"HYP_FSPACE_AUTO_002_RANK_{field.upper()}_V1",
            "family": "feature_space_quality_momentum",
            "claim": "existing",
            "causal_mechanism": "existing",
            "bibliography_basis": [{"source_id": "test"}],
            "empirical_basis": [{"run_id": "AUTO_002"}],
            "features_required": [field, "close"],
            "status": "candidate",
            "required_spy_comparison": "monthly_and_yearly",
            "axis": "feature_space_ranking",
            "falsification_rule": "test",
            "strategy_overrides": {"ranking": {"field": field, "order": "desc"}, "risk_filters": {"require_non_null_fields": [field, "close"]}},
        })
    append_jsonl(bank, existing)

    result = generate_feature_space_hypotheses(
        parent_strategy_config_path=parent,
        hypothesis_bank_path=bank,
        state_dir=state,
        max_new=2,
    )

    assert result["generated"] >= 1
    assert all("CONF_" not in hid for hid in result["hypotheses"])
