from __future__ import annotations

import json
from pathlib import Path

from scripts.research.literature_hypothesis_miner import mine_literature_hypotheses
from scripts.research.audit_spy_regime_features import audit_spy_regime_features


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_literature_v4_skips_cooldown_family_but_records_missing_tasks(tmp_path: Path) -> None:
    state = tmp_path / "state"
    reports = tmp_path / "reports"
    bank = tmp_path / "hypothesis_bank.jsonl"
    weekly = tmp_path / "weekly.csv"
    parent = tmp_path / "parent.json"
    ideas = tmp_path / "paper_ideas.jsonl"

    weekly.write_text(
        "signal_date,ticker,close,ret_52w_pct,ret_26w_pct,ret_13w_pct,channel_r2,channel_slope_pct,close_vs_sma20w_pct,spy_close_vs_sma50_pct\n"
        "2024-01-05,SPY,100,1,1,1,0.5,2,3,4\n",
        encoding="utf-8",
    )
    _write_json(state / "data_paths_resolved.json", {"weekly_file": str(weekly)})
    _write_json(state / "current_parent.json", {"current_parent_run_id": "AUTO_002", "current_parent_hypothesis_id": "HYP_PARENT"})
    _write_json(state / "subspace_cooldowns.json", {"version": 1, "cooldowns": {"paper_regime_filter": {"reason": "test"}}})
    _write_json(parent, {"strategy_id": "parent"})

    # Adds missing-feature paper ideas too.
    ideas.write_text(
        json.dumps(
            {
                "source_id": "residual_test",
                "title": "Residual momentum test",
                "claim_seed": "Residual momentum may isolate alpha",
                "families": ["paper_residual_momentum"],
                "query": "residual momentum",
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    result = mine_literature_hypotheses(
        parent_strategy_config_path=parent,
        hypothesis_bank_path=bank,
        state_dir=state,
        max_new=8,
        paper_ideas_path=ideas,
    )

    assert result["generated"] > 0
    assert result["skipped_family_cooldown"] > 0
    rows = [json.loads(x) for x in bank.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert all(row["family"] != "paper_regime_filter" for row in rows)
    assert (state / "missing_feature_tasks.jsonl").exists()
    assert "residual_ret_26w_pct" in (state / "missing_feature_tasks.jsonl").read_text(encoding="utf-8")


def test_spy_regime_audit_reports_nan_pct(tmp_path: Path) -> None:
    state = tmp_path / "state"
    reports = tmp_path / "reports"
    weekly = tmp_path / "weekly.csv"
    weekly.write_text(
        "signal_date,ticker,close,spy_close_vs_sma50_pct,spy_channel_r2,spy_channel_slope_pct,spy_close_sma_50_slope_5d_pct\n"
        "2024-01-05,SPY,100,,0.8,1.2,0.3\n"
        "2024-01-12,SPY,101,2.5,0.7,1.0,0.2\n"
        "2024-01-12,AAPL,10,2.5,0.7,1.0,0.2\n",
        encoding="utf-8",
    )
    _write_json(state / "data_paths_resolved.json", {"weekly_file": str(weekly)})

    result = audit_spy_regime_features(weekly_file=weekly, state_dir=state, reports_dir=reports, max_warn_nan_pct=10.0)

    assert result["status"] == "warning"
    assert any("high_nan_pct_on_spy_rows:spy_close_vs_sma50_pct" in w for w in result["warnings"])
    assert (reports / "spy_regime_feature_audit.md").exists()
