from __future__ import annotations

import json
from pathlib import Path

from scripts.research.feature_space_expansion_factory import generate_feature_space_hypotheses


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_feature_space_skips_cooldowned_confirmation_and_regime_families(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    bank = tmp_path / "hypothesis_bank.jsonl"
    parent = tmp_path / "parent.json"
    weekly = tmp_path / "weekly.csv"

    weekly.write_text(
        "date,ticker,close,ret_26w_pct,ret_52w_pct,channel_r2,channel_slope_pct,"
        "close_sma_50_slope_5d_pct,close_vs_sma20w_pct,close_vs_sma52w_pct,"
        "distance_to_channel_lower_pct\n",
        encoding="utf-8",
    )
    _write_json(state_dir / "data_paths_resolved.json", {"weekly_file": str(weekly)})
    _write_json(state_dir / "current_parent.json", {"current_parent_run_id": "AUTO_002"})
    _write_json(
        state_dir / "subspace_cooldowns.json",
        {
            "version": 1,
            "cooldowns": {
                "feature_space_composite_confirmation": {"reason": "repeated_failed_hypotheses"},
                "feature_space_regime": {"reason": "repeated_failed_hypotheses"},
            },
        },
    )
    _write_json(parent, {"ranking": {"field": "ret_13w_pct"}, "entry_rule": {"top_n": 8}, "exit_rule": {"rank_threshold": 20}})

    # Make pure ranking ids already exist, forcing the generator to consider
    # later layers. The cooldown-aware behavior should skip CONF/MKT and reach TOPN/EXIT.
    existing = []
    for field in [
        "RET_26W_PCT",
        "RET_52W_PCT",
        "CHANNEL_R2",
        "CHANNEL_SLOPE_PCT",
        "CLOSE_SMA_50_SLOPE_5D_PCT",
        "CLOSE_VS_SMA20W_PCT",
        "CLOSE_VS_SMA52W_PCT",
        "DISTANCE_TO_CHANNEL_LOWER_PCT",
    ]:
        existing.append({"hypothesis_id": f"HYP_FSPACE_AUTO_002_RANK_{field}_V1", "family": "feature_space_ranking", "status": "candidate"})
    _append_jsonl(bank, existing)

    result = generate_feature_space_hypotheses(
        parent_strategy_config_path=parent,
        hypothesis_bank_path=bank,
        state_dir=state_dir,
        max_new=3,
        reason="test",
    )

    assert result["generated"] > 0
    assert "feature_space_composite_confirmation" in result["cooldowned_families"]
    assert "feature_space_regime" in result["cooldowned_families"]
    assert all("CONF" not in hid and "MKT" not in hid for hid in result["hypotheses"])
    assert any("TOPN" in hid or "EXIT" in hid for hid in result["hypotheses"])
    assert any(row.get("reason") == "family_cooldown" for row in result["skipped"])
