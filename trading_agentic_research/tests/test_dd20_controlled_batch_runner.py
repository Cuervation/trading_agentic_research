import json
from pathlib import Path

from scripts.run.run_dd20_controlled_batch import (
    build_effective_config_audit,
    filter_rankable_rows,
    restore_audit_json,
    detect_translation_collapse,
    translate_hypothesis_for_execution,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_dd20_family_translation_changes_config():
    parent_cfg = {
        "strategy_id": "PARENT",
        "entry_rule": {"type": "top_n", "top_n": 8, "by": "ret_52w_pct"},
        "market_filter": {"benchmark": "SPY", "require_positive_trend": True},
        "risk_management": {
            "max_gross_exposure_pct": 50,
            "equity_drawdown_guard": {"enabled": True, "stop_new_entries_drawdown_pct": -18, "resume_drawdown_pct": -10},
        },
        "costs": {"entry_cost_pct": 0.24, "exit_cost_pct": 0.24},
    }
    hypothesis_cfg = {
        "strategy_id": "HYP_TOPN",
        "strategy_overrides": {
            "entry_rule": {"type": "top_n_dynamic", "top_n_strong_regime": 16, "top_n_weak_regime": 8},
            "market_filter": {"benchmark": "SPY", "require_positive_trend": True},
        },
    }
    translated = translate_hypothesis_for_execution(hypothesis_cfg, parent_cfg, "topn_dynamic")
    cfg = translated["executable_config"]
    assert cfg is not None
    assert cfg["entry_rule"]["type"] == "top_n"
    assert cfg["entry_rule"]["top_n"] == 16
    assert cfg["market_filter"]["soft_weak_regime_top_n"] == 8
    assert cfg["entry_rule"]["top_n"] != parent_cfg["entry_rule"]["top_n"]


def test_dd20_unsupported_controls_are_preflight_blocked():
    translated = translate_hypothesis_for_execution(
        {"strategy_id": "HYP_SPY_FB", "strategy_overrides": {}},
        {"strategy_id": "PARENT"},
        "spy_fallback_partial",
    )
    assert translated["executable_config"] is None
    assert translated["support_issue"]
    assert "spy_fallback_partial_pct" in translated["support_issue"]


def test_dd20_batch_detects_translation_collapse():
    rows = [
        {
            "strategy_id": "A",
            "status": "rejected",
            "candidate_cagr": 12.58,
            "candidate_max_drawdown_pct": -47.08,
            "candidate_years_won_vs_spy": 16,
            "candidate_trades": 1537,
            "effect_signature": "same-signature",
        },
        {
            "strategy_id": "B",
            "status": "rejected",
            "candidate_cagr": 12.579,
            "candidate_max_drawdown_pct": -47.079,
            "candidate_years_won_vs_spy": 16,
            "candidate_trades": 1537,
            "effect_signature": "same-signature",
        },
    ]
    collapsed, groups = detect_translation_collapse(rows)
    assert collapsed is True
    assert any(len(v) == 2 for v in groups.values())


def test_audit_json_is_emitted_for_batch_candidates(tmp_path, monkeypatch):
    from scripts.run import run_dd20_controlled_batch as runner

    runs_dir = tmp_path / "runs"
    run_id = "HYP_TEST_AUDIT"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        run_dir / "metrics.json",
        {
            "strategy": {"cagr_pct": 11.0, "total_return_pct": 100.0, "max_drawdown_pct": -19.0},
            "spy": {"cagr_pct": 7.0, "total_return_pct": 50.0, "max_drawdown_pct": -56.0},
            "diagnostics": {"number_of_trades": 1200, "number_of_rebalances": 200},
        },
    )
    _write_json(
        run_dir / "spy_comparison_summary.json",
        {
            "strategy_cagr_pct": 11.0,
            "spy_cagr_pct": 7.0,
            "years_beating_spy": 15,
            "months_beating_spy": 160,
            "recommendation_hint": "candidate",
        },
    )
    (run_dir / "spy_comparison_yearly.csv").write_text("year,strategy_return_pct,spy_return_pct,excess_return_pct,winner\n2025,10,5,5,strategy\n", encoding="utf-8")
    (run_dir / "spy_comparison_monthly.csv").write_text("year,month,strategy_return_pct,spy_return_pct,excess_return_pct,winner\n2025,1,1,0.5,0.5,strategy\n", encoding="utf-8")
    (run_dir / "spy_comparison_daily.csv").write_text("date,strategy_equity,spy_equity\n2025-01-01,10000,10000\n", encoding="utf-8")
    (run_dir / "summary.md").write_text("# summary\n", encoding="utf-8")

    monkeypatch.setattr(runner, "RUNS_DIR", runs_dir)
    payload = restore_audit_json(
        run_id=run_id,
        family="guardrail_dynamic",
        status="rejected",
        decision_reason="test reason",
        support_status="supported",
        support_issue="",
        effective_audit={"conclusion": "translated_controls_applied"},
    )
    assert (run_dir / "audit.json").exists()
    assert payload["promoted_to_baseline"] is False
    assert "decision_reason" in payload


def test_requires_engine_support_not_ranked():
    rows = [
        {"strategy_id": "A", "status": "requires_engine_support"},
        {"strategy_id": "B", "status": "run_failed"},
        {"strategy_id": "C", "status": "rejected"},
    ]
    rankable = filter_rankable_rows(rows)
    assert [r["strategy_id"] for r in rankable] == ["C"]


def test_declared_controls_are_all_accounted_for():
    parent_cfg = {
        "strategy_id": "PARENT",
        "risk_management": {
            "max_gross_exposure_pct": 50,
            "equity_drawdown_guard": {"enabled": True, "stop_new_entries_drawdown_pct": -18, "resume_drawdown_pct": -10},
        },
        "strategy_overrides": {
            "market_filter": {"benchmark": "SPY", "require_positive_trend": True},
            "ranking": {"field": "close_vs_sma52w_pct", "order": "desc"},
            "risk_filters": {"require_non_null_fields": ["ret_52w_pct", "close"]},
        },
        "market_filter": {"benchmark": "SPY", "require_positive_trend": True},
        "ranking": {"field": "close_vs_sma52w_pct", "order": "desc"},
        "risk_filters": {"require_non_null_fields": ["ret_52w_pct", "close"]},
    }
    hypothesis_cfg = {
        "strategy_id": "HYP_GUARD",
        "strategy_overrides": {
            "risk_management": {
                "max_gross_exposure_pct": 50,
                "equity_drawdown_guard": {
                    "enabled": True,
                    "stop_new_entries_drawdown_pct": -18,
                    "resume_drawdown_pct": -12,
                    "reduced_exposure_pct_when_active": 20,
                },
            }
        },
    }
    translation = translate_hypothesis_for_execution(hypothesis_cfg, parent_cfg, "guardrail_dynamic")
    audit = build_effective_config_audit(
        run_id="HYP_GUARD",
        hypothesis_id="HYP_GUARD",
        family="guardrail_dynamic",
        parent_cfg=parent_cfg,
        candidate_cfg=translation["executable_config"],
        hypothesis_cfg=hypothesis_cfg,
        translation=translation,
    )
    assert audit["missing_declared_controls"] == []
    assert audit["conclusion"] == "translated_controls_applied"
    assert audit["materialized_parent_strategy_overrides"]["strategy_overrides.market_filter"]["status"] == "preserved"
    assert audit["materialized_parent_strategy_overrides"]["strategy_overrides.ranking"]["status"] == "preserved"
    assert audit["materialized_parent_strategy_overrides"]["strategy_overrides.risk_filters"]["status"] == "preserved"


def test_max_gross_exposure_pct_is_applied_or_marked_unsupported():
    parent_cfg = {
        "strategy_id": "PARENT",
        "risk_management": {
            "max_gross_exposure_pct": 50,
            "equity_drawdown_guard": {"enabled": True, "stop_new_entries_drawdown_pct": -18, "resume_drawdown_pct": -10},
        },
    }
    hypothesis_cfg = {
        "strategy_id": "HYP_GUARD",
        "strategy_overrides": {
            "risk_management": {
                "max_gross_exposure_pct": 50,
                "equity_drawdown_guard": {"resume_drawdown_pct": -12},
            }
        },
    }
    translation = translate_hypothesis_for_execution(hypothesis_cfg, parent_cfg, "guardrail_dynamic")
    assert (
        "risk_management.max_gross_exposure_pct" in translation["translated_controls"]
        or "risk_management.max_gross_exposure_pct" in translation["unsupported_controls"]
    )
    assert "risk_management.max_gross_exposure_pct" in translation["risk_control_fields_applied"]
