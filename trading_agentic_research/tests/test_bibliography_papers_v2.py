import json
from pathlib import Path

from scripts.research.bibliography_gap_report import build_bibliography_gap_report
from scripts.research.literature_hypothesis_miner import mine_literature_hypotheses
from scripts.research.paper_searcher import generate_paper_ideas


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_paper_searcher_offline_adds_more_than_legacy_seed_count(tmp_path):
    out = tmp_path / "bibliography" / "paper_ideas.jsonl"
    result = generate_paper_ideas(output=out, online=False)
    assert result["rows_written"] >= 9
    text = out.read_text(encoding="utf-8")
    assert "absolute_momentum_dual_momentum" in text
    assert "volatility_managed_portfolios" in text


def test_literature_miner_generates_variant_when_base_signature_exists(tmp_path):
    state = tmp_path / "state"
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    parent = tmp_path / "configs" / "parent.json"
    weekly = tmp_path / "data" / "weekly.csv"
    write_json(state / "current_parent.json", {
        "current_parent_run_id": "AUTO_002",
        "current_parent_hypothesis_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED",
    })
    write_json(parent, {"strategy_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED", "ranking": {"field": "close_vs_sma52w_pct", "order": "desc"}})
    weekly.parent.mkdir(parents=True, exist_ok=True)
    weekly.write_text("date,ticker,close,ret_52w_pct,ret_13w_pct,ret_26w_pct,channel_r2,channel_slope_pct,close_vs_sma20w_pct,close_vs_sma52w_pct,spy_close_vs_sma50_pct\n", encoding="utf-8")
    write_json(state / "data_paths_resolved.json", {"weekly_file": str(weekly)})
    bank.parent.mkdir(parents=True, exist_ok=True)
    # Existing base idea should not prevent variants with risk_filters.conditions.
    bank.write_text(json.dumps({
        "hypothesis_id": "HYP_EXISTING_BASE",
        "status": "candidate",
        "family": "paper_time_series_momentum",
        "claim": "existing",
        "bibliography_basis": [{"source_id": "x"}],
        "strategy_overrides": {"ranking": {"field": "ret_52w_pct", "order": "desc"}, "risk_filters": {"require_non_null_fields": ["ret_52w_pct", "close"]}},
    }) + "\n", encoding="utf-8")

    result = mine_literature_hypotheses(
        parent_strategy_config_path=parent,
        hypothesis_bank_path=bank,
        state_dir=state,
        max_new=5,
        paper_ideas_path=tmp_path / "bibliography" / "paper_ideas.jsonl",
    )

    assert result["generated"] >= 1
    text = bank.read_text(encoding="utf-8")
    assert "RET13_CONFIRM" in text or "QUALITY" in text or "REGIME" in text
    assert "conditions" in text


def test_literature_miner_writes_missing_feature_tasks(tmp_path):
    state = tmp_path / "state"
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    parent = tmp_path / "configs" / "parent.json"
    weekly = tmp_path / "data" / "weekly.csv"
    write_json(state / "current_parent.json", {"current_parent_run_id": "AUTO_002"})
    write_json(parent, {"strategy_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED"})
    weekly.parent.mkdir(parents=True, exist_ok=True)
    weekly.write_text("date,ticker,close,ret_52w_pct\n", encoding="utf-8")
    write_json(state / "data_paths_resolved.json", {"weekly_file": str(weekly)})
    bank.parent.mkdir(parents=True, exist_ok=True)
    bank.write_text("", encoding="utf-8")

    mine_literature_hypotheses(
        parent_strategy_config_path=parent,
        hypothesis_bank_path=bank,
        state_dir=state,
        max_new=20,
        paper_ideas_path=tmp_path / "bibliography" / "paper_ideas.jsonl",
    )

    tasks = state / "missing_feature_tasks.jsonl"
    assert tasks.exists()
    assert "atr_14w_pct" in tasks.read_text(encoding="utf-8") or "channel_r2" in tasks.read_text(encoding="utf-8")


def test_bibliography_gap_report_outputs_json_and_markdown(tmp_path):
    state = tmp_path / "state"
    reports = tmp_path / "reports"
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    parent = tmp_path / "configs" / "parent.json"
    weekly = tmp_path / "data" / "weekly.csv"
    write_json(state / "current_parent.json", {"current_parent_run_id": "AUTO_002"})
    write_json(parent, {"strategy_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED"})
    weekly.parent.mkdir(parents=True, exist_ok=True)
    weekly.write_text("date,ticker,close,ret_52w_pct,ret_13w_pct,channel_r2,channel_slope_pct,close_vs_sma20w_pct,close_vs_sma52w_pct,spy_close_vs_sma50_pct\n", encoding="utf-8")
    write_json(state / "data_paths_resolved.json", {"weekly_file": str(weekly)})
    bank.parent.mkdir(parents=True, exist_ok=True)
    bank.write_text("", encoding="utf-8")

    result = build_bibliography_gap_report(
        parent_strategy_config_path=parent,
        hypothesis_bank_path=bank,
        paper_ideas_path=tmp_path / "bibliography" / "paper_ideas.jsonl",
        state_dir=state,
        reports_dir=reports,
    )

    assert result["paper_idea_count"] >= 1
    assert (state / "bibliography_gap_report.json").exists()
    assert (reports / "bibliography_gap_report.md").exists()
    assert "Status counts" in (reports / "bibliography_gap_report.md").read_text(encoding="utf-8")
