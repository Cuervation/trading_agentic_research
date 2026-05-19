from pathlib import Path

from scripts.research.generation_selection_feedback import diagnose_generated_hypotheses


def test_diagnose_generated_hypotheses_reports_selectable(tmp_path):
    state = tmp_path / "state"
    bank = tmp_path / "hypothesis_bank.jsonl"
    state.mkdir()
    bank.write_text(
        '{"hypothesis_id":"HYP_NEW","family":"feature_space_composite_confirmation","status":"candidate","claim":"x","causal_mechanism":"x","bibliography_basis":[{"source_id":"x","title":"x"}],"strategy_overrides":{"ranking":{"field":"channel_r2","order":"desc"}}}\n',
        encoding="utf-8",
    )

    result = diagnose_generated_hypotheses(
        hypothesis_bank_path=bank,
        state_dir=state,
        hypothesis_ids=["HYP_NEW"],
    )

    assert result["selectable"] == ["HYP_NEW"]
    assert result["selectable_count"] == 1
    assert result["blocked_count"] == 0


def test_diagnose_generated_hypotheses_reports_consumed(tmp_path):
    state = tmp_path / "state"
    bank = tmp_path / "hypothesis_bank.jsonl"
    state.mkdir()
    bank.write_text(
        '{"hypothesis_id":"HYP_NEW","family":"feature_space_composite_confirmation","status":"candidate","claim":"x","causal_mechanism":"x","bibliography_basis":[{"source_id":"x","title":"x"}],"strategy_overrides":{"ranking":{"field":"channel_r2","order":"desc"}}}\n',
        encoding="utf-8",
    )
    (state / "consumed_hypotheses.jsonl").write_text('{"hypothesis_id":"HYP_NEW","run_id":"EXP_001"}\n', encoding="utf-8")

    result = diagnose_generated_hypotheses(
        hypothesis_bank_path=bank,
        state_dir=state,
        hypothesis_ids=["HYP_NEW"],
    )

    assert result["selectable_count"] == 0
    assert result["summary_by_reason"] == {"consumed": 1}


def test_diagnose_generated_hypotheses_reports_duplicate_signature(tmp_path):
    state = tmp_path / "state"
    bank = tmp_path / "hypothesis_bank.jsonl"
    state.mkdir()
    bank.write_text(
        '\n'.join([
            '{"hypothesis_id":"HYP_OLD","family":"feature_space_composite_confirmation","status":"candidate","claim":"x","causal_mechanism":"x","bibliography_basis":[{"source_id":"x","title":"x"}],"strategy_overrides":{"ranking":{"field":"channel_r2","order":"desc"}}}',
            '{"hypothesis_id":"HYP_NEW","family":"feature_space_composite_confirmation","status":"candidate","claim":"x","causal_mechanism":"x","bibliography_basis":[{"source_id":"x","title":"x"}],"strategy_overrides":{"ranking":{"field":"channel_r2","order":"desc"}}}',
            '',
        ]),
        encoding="utf-8",
    )
    (state / "rejected_hypotheses.jsonl").write_text('{"hypothesis_id":"HYP_OLD"}\n', encoding="utf-8")

    result = diagnose_generated_hypotheses(
        hypothesis_bank_path=bank,
        state_dir=state,
        hypothesis_ids=["HYP_NEW"],
    )

    assert result["selectable_count"] == 0
    assert result["summary_by_reason"] == {"duplicate_signature_blocked": 1}
