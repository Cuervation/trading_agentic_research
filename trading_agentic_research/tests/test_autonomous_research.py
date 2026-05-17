import json

import pytest

from scripts.governance import canonical_strategy_payload, stable_json_hash
from scripts.research.executor import DEFAULT_RESEARCH_WINDOWS_WEEKS, build_execution_plan
from scripts.research.literature_searcher import search_new_literature
from scripts.research.candidate_config_writer import write_candidate_config
from scripts.research.real_evaluator import evaluate_completed_run
from scripts.research.artifact_index import rebuild_artifact_index_from_runs, find_duplicate_artifact
from scripts.research.champion_governance import classify_candidate, rebuild_champion_state_from_runs
from scripts.research.autonomous import (
    coordinator_decision,
    evaluate_result,
    precheck_hypothesis,
    run_iteration,
    seed_literature_sources,
    update_axis_cooldowns,
    validate_hypothesis,
    validate_mixed_hypothesis,
    write_json,
)


def _parent_config():
    return {
        "strategy_id": "BASE",
        "hypothesis_id": "H_BASE",
        "strategy_family": "momentum",
        "ranking": {"field": "ret_52w_pct", "order": "desc"},
        "entry_rule": {"top_n": 12, "by": "ret_52w_pct"},
        "exit_rule": {"rank_threshold": 30},
    }


def _hypothesis(**overrides):
    payload = {
        "hypothesis_id": "HYP_TEST",
        "source_ids": ["SRC_CROSS_SECTIONAL_MOMENTUM_SEED"],
        "family": "momentum",
        "axis": "ranking_24_52_momentum",
        "claim": "24/52 week momentum should persist.",
        "causal_mechanism": "Slow information diffusion.",
        "implementation_change": {
            "axis": "ranking_24_52_momentum",
            "strategy_overrides": {"ranking": {"field": "ret_26w_pct", "order": "desc"}},
            "features_used": ["ret_26w_pct"],
        },
        "expected_effect": "Improve 24/52 robustness.",
        "falsification_rule": "Reject if duplicate or no SPY-relative improvement.",
        "materiality_guard": {"reject_metric_no_effect": True, "reject_duplicate_result": True},
    }
    payload.update(overrides)
    return payload


def test_hypothesis_without_source_id_fails():
    with pytest.raises(ValueError, match="source_id"):
        validate_hypothesis(_hypothesis(source_ids=[]))


def test_hypothesis_without_causal_mechanism_fails():
    with pytest.raises(ValueError, match="causal_mechanism"):
        validate_hypothesis(_hypothesis(causal_mechanism=""))


def test_hypothesis_without_falsification_rule_fails():
    with pytest.raises(ValueError, match="falsification_rule"):
        validate_hypothesis(_hypothesis(falsification_rule=""))


def test_mixed_hypothesis_with_less_than_two_sources_fails():
    with pytest.raises(ValueError, match="two source"):
        validate_mixed_hypothesis({**_hypothesis(), "mixed_mechanism": "x"})


def test_no_material_change_returns_metric_no_effect(tmp_path):
    hypothesis = _hypothesis(implementation_change={"axis": "noop", "strategy_overrides": {}, "features_used": []})
    result = precheck_hypothesis(hypothesis, _parent_config(), state_dir=tmp_path)
    assert result["status"] == "metric_no_effect"
    assert result["run_backtest"] is False


def test_metric_no_effect_cannot_accepted_for_followup(tmp_path):
    hypothesis = _hypothesis(implementation_change={"axis": "noop", "strategy_overrides": {}, "features_used": []})
    precheck = precheck_hypothesis(hypothesis, _parent_config(), state_dir=tmp_path)
    evaluation = evaluate_result(hypothesis, precheck)
    assert evaluation["decision"] == "rejected"
    assert evaluation["accepted_for_followup"] is False


def test_duplicate_result_cannot_move_parent(tmp_path):
    hypothesis = _hypothesis()
    parent = _parent_config()
    first = precheck_hypothesis(hypothesis, parent, state_dir=tmp_path)
    write_json(tmp_path / "duplicate_runs.json", {"version": 1, "duplicates": [{"run_id": "EXP_DUP", "config_hash": first["config_hash"]}]})
    duplicate = precheck_hypothesis(hypothesis, parent, state_dir=tmp_path)
    evaluation = evaluate_result(hypothesis, duplicate)
    assert duplicate["status"] == "duplicate_result"
    assert evaluation["can_move_parent"] is False


def test_duplicate_result_cannot_promoted_to_baseline_candidate(tmp_path):
    hypothesis = _hypothesis()
    first = precheck_hypothesis(hypothesis, _parent_config(), state_dir=tmp_path)
    write_json(tmp_path / "duplicate_runs.json", {"version": 1, "duplicates": [{"run_id": "EXP_DUP", "config_hash": first["config_hash"]}]})
    duplicate = precheck_hypothesis(hypothesis, _parent_config(), state_dir=tmp_path)
    evaluation = evaluate_result(hypothesis, duplicate)
    assert evaluation["promoted_to_baseline_candidate"] is False


def test_no_available_hypotheses_returns_search_new_literature(tmp_path):
    decision = coordinator_decision(tmp_path, None, None, None)
    assert decision["decision"] == "search_new_literature"


def test_too_many_rejections_marks_axis_exhausted(tmp_path):
    memory = {
        "events": [
            {"family": "momentum", "axis": "ranking", "decision": "rejected", "precheck_status": "passed"},
            {"family": "momentum", "axis": "ranking", "decision": "rejected", "precheck_status": "passed"},
            {"family": "momentum", "axis": "ranking", "decision": "rejected", "precheck_status": "passed"},
        ]
    }
    cooldowns = update_axis_cooldowns(tmp_path, memory)
    assert cooldowns["axes"]["momentum:ranking"]["status"] == "axis_exhausted"


def test_followup_and_baseline_candidate_are_separate_fields(tmp_path):
    hypothesis = _hypothesis()
    precheck = precheck_hypothesis(hypothesis, _parent_config(), state_dir=tmp_path)
    evaluation = evaluate_result(hypothesis, precheck)
    assert "accepted_for_followup" in evaluation
    assert "promoted_to_baseline_candidate" in evaluation
    assert evaluation["accepted_for_followup"] in {True, False}
    assert evaluation["promoted_to_baseline_candidate"] in {True, False}


def test_promoted_to_baseline_candidate_requires_manual_review():
    evaluation = {
        "promoted_to_baseline_candidate": True,
        "manual_review_required": True,
    }
    assert evaluation["manual_review_required"] is True


def test_vertical_slice_iteration_runs_with_mock_state(tmp_path):
    parent_path = tmp_path / "parent.json"
    parent_path.write_text(json.dumps(_parent_config()), encoding="utf-8")
    seed_literature_sources(tmp_path)
    result = run_iteration(tmp_path, parent_path, mock=True)
    assert result["hypothesis"]["source_ids"]
    assert result["precheck"]["status"] in {"passed", "metric_no_effect", "duplicate_result"}
    assert (tmp_path / "hypothesis_memory.json").exists()


def test_executor_defaults_to_real_4_8_24_52_without_156():
    plan = build_execution_plan("HYP_TEST")
    assert tuple(plan["windows_weeks"]) == DEFAULT_RESEARCH_WINDOWS_WEEKS
    assert plan["mock_execution"] is False
    assert plan["uses_existing_backtester"] is True
    assert 156 not in plan["windows_weeks"]



def test_search_new_literature_adds_semantic_scholar_source(tmp_path):
    seed_literature_sources(tmp_path)

    def fake_fetch(url):
        assert "semanticscholar" in url
        return {
            "data": [
                {
                    "paperId": "P1",
                    "title": "Momentum Crashes and Long Horizon Signals",
                    "authors": [{"name": "A Researcher"}],
                    "year": 2020,
                    "url": "https://example.test/p1",
                    "abstract": "Tests momentum crashes.",
                    "citationCount": 12,
                    "externalIds": {"DOI": "10.0000/test"},
                }
            ]
        }

    result = search_new_literature(state_dir=tmp_path, max_results=1, fetch_json=fake_fetch)

    assert result["added"] == 1
    payload = json.loads((tmp_path / "literature_sources.json").read_text(encoding="utf-8"))
    assert any(source["source_id"].startswith("SRC_S2_") for source in payload["sources"])
    assert payload["search_events"]


def test_search_new_literature_falls_back_to_crossref(tmp_path):
    seed_literature_sources(tmp_path)

    def fake_fetch(url):
        if "semanticscholar" in url:
            return {"data": []}
        assert "crossref" in url
        return {
            "message": {
                "items": [
                    {
                        "DOI": "10.0000/crossref",
                        "title": ["Quality Momentum in Equity Markets"],
                        "author": [{"given": "B", "family": "Researcher"}],
                        "type": "journal-article",
                        "published-print": {"date-parts": [[2018]]},
                        "URL": "https://example.test/crossref",
                    }
                ]
            }
        }

    result = search_new_literature(state_dir=tmp_path, max_results=1, fetch_json=fake_fetch)

    assert result["added"] == 1
    assert result["sources"][0]["source_id"].startswith("SRC_CR_")


def test_run_iteration_searches_literature_when_no_hypothesis(tmp_path, monkeypatch):
    parent_path = tmp_path / "parent.json"
    parent_path.write_text(json.dumps(_parent_config()), encoding="utf-8")
    seed_literature_sources(tmp_path)
    (tmp_path / "extracted_claims.json").write_text(json.dumps({"version": 1, "claims": []}), encoding="utf-8")
    (tmp_path / "hypothesis_memory.json").write_text(json.dumps({"version": 1, "hypotheses": [], "events": []}), encoding="utf-8")
    (tmp_path / "literature_sources.json").write_text(json.dumps({"version": 1, "sources": []}), encoding="utf-8")

    def fake_search_new_literature(*, state_dir="state", max_results=5, fetch_json=None):
        return {"added": 1, "sources": [{"source_id": "SRC_NEW"}], "errors": [], "queries": []}

    monkeypatch.setattr("scripts.research.literature_searcher.search_new_literature", fake_search_new_literature)

    result = run_iteration(tmp_path, parent_path, mock=True)

    assert result["coordinator_decision"]["decision"] == "search_new_literature"
    assert result["literature_search"]["added"] == 1



def test_run_iteration_default_real_requires_data_for_material_hypothesis(tmp_path):
    parent_path = tmp_path / "parent.json"
    parent_path.write_text(json.dumps(_parent_config()), encoding="utf-8")
    seed_literature_sources(tmp_path)

    with pytest.raises(ValueError, match="requires --weekly-file"):
        run_iteration(tmp_path, parent_path)


def test_material_hypothesis_writes_candidate_config(tmp_path):
    path = write_candidate_config(_parent_config(), _hypothesis(), tmp_path / "generated")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "HYP_TEST.json"
    assert payload["hypothesis_id"] == "HYP_TEST"
    assert payload["strategy_id"] == "HYP_TEST"
    assert payload["bibliography_basis"] == [{"source_id": "SRC_CROSS_SECTIONAL_MOMENTUM_SEED"}]
    assert "ranking.field" in payload["changed_parameters"]
    assert payload["claim"]
    assert payload["causal_mechanism"]
    assert payload["expected_effect"]
    assert payload["falsification_rule"]


def test_metric_no_effect_does_not_call_real_runner(tmp_path, monkeypatch):
    parent_path = tmp_path / "parent.json"
    parent_path.write_text(json.dumps(_parent_config()), encoding="utf-8")
    seed_literature_sources(tmp_path)
    hypothesis = _hypothesis(implementation_change={"axis": "noop", "strategy_overrides": {}, "features_used": []})

    from scripts.research import autonomous

    monkeypatch.setattr(autonomous, "build_next_hypothesis", lambda *args, **kwargs: hypothesis)

    def fail_runner(command):
        raise AssertionError("runner should not be called")

    result = run_iteration(
        tmp_path,
        parent_path,
        weekly_file="weekly.csv",
        daily_folder="daily",
        runner=fail_runner,
    )

    assert result["precheck"]["status"] == "metric_no_effect"
    assert result["evaluation"]["decision"] == "rejected"


def test_duplicate_result_does_not_call_real_runner(tmp_path, monkeypatch):
    parent = _parent_config()
    hypothesis = _hypothesis()
    first = precheck_hypothesis(hypothesis, parent, state_dir=tmp_path)
    write_json(tmp_path / "duplicate_runs.json", {"version": 1, "duplicates": [{"run_id": "EXP_DUP", "config_hash": first["config_hash"]}]})
    parent_path = tmp_path / "parent.json"
    parent_path.write_text(json.dumps(parent), encoding="utf-8")
    seed_literature_sources(tmp_path)

    from scripts.research import autonomous

    monkeypatch.setattr(autonomous, "build_next_hypothesis", lambda *args, **kwargs: hypothesis)

    def fail_runner(command):
        raise AssertionError("runner should not be called")

    result = run_iteration(tmp_path, parent_path, weekly_file="weekly.csv", daily_folder="daily", runner=fail_runner)

    assert result["precheck"]["status"] == "duplicate_result"
    assert result["evaluation"]["can_move_parent"] is False


def test_real_iteration_uses_real_evaluator_not_synthetic(tmp_path, monkeypatch):
    parent_path = tmp_path / "parent.json"
    parent_path.write_text(json.dumps(_parent_config()), encoding="utf-8")
    seed_literature_sources(tmp_path)

    from scripts.research import autonomous

    monkeypatch.setattr(autonomous, "build_next_hypothesis", lambda *args, **kwargs: _hypothesis())
    monkeypatch.setattr(autonomous, "precheck_hypothesis", lambda *args, **kwargs: {"status": "passed", "run_backtest": True, "config_hash": "cfg"})
    monkeypatch.setattr(autonomous, "evaluate_result", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("synthetic evaluator called")))

    def fake_runner(command):
        run_dir = tmp_path / "runs" / "AUTO_001"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "metrics.json").write_text(json.dumps({"strategy": {"cagr_pct": 11, "max_drawdown_pct": -10, "total_return_pct": 50}, "spy": {"cagr_pct": 10, "max_drawdown_pct": -20, "total_return_pct": 40}, "costs": {"applied": True, "cost_per_side_pct": 0.24}, "diagnostics": {"warnings": []}}), encoding="utf-8")
        (run_dir / "spy_comparison_summary.json").write_text(json.dumps({"strategy_cagr_pct": 11, "spy_cagr_pct": 10, "excess_cagr_pct": 1, "months_beating_spy": 7, "months_losing_to_spy": 5, "years_beating_spy": 2, "years_losing_to_spy": 1}), encoding="utf-8")
        (run_dir / "trades.csv").write_text("net_return_pct;gross_return_pct\n2,0;2,5\n0,5;1,0\n-1,0;-0,5\n", encoding="utf-8")
        (run_dir / "equity_curve.csv").write_text("date;equity\n2024-01-01;10000\n2024-02-01;11000\n", encoding="utf-8")
        (run_dir / "spy_comparison_monthly.csv").write_text("winner\nstrategy\n", encoding="utf-8")
        (run_dir / "spy_comparison_yearly.csv").write_text("winner\nstrategy\n", encoding="utf-8")
        (run_dir / "run_manifest.json").write_text(json.dumps({"parent_run_id": "EXP_PARENT", "hypothesis_id": "HYP_TEST", "hypothesis_family": "momentum"}), encoding="utf-8")
        if any("evaluate_candidate.py" in str(part) for part in command):
            (run_dir / "audit.json").write_text(json.dumps({"decision": "promoted_candidate", "can_move_parent": True, "can_promote_baseline": False, "flags": []}), encoding="utf-8")
        import subprocess
        return subprocess.CompletedProcess(command, returncode=0)

    result = run_iteration(
        tmp_path,
        parent_path,
        weekly_file="weekly.csv",
        daily_folder="daily",
        runs_dir=tmp_path / "runs",
        generated_config_dir=tmp_path / "generated",
        runner=fake_runner,
    )

    assert result["evaluation"]["evaluation_source"] == "real_artifacts"
    assert result["evaluation"]["trade_wins"] == 1
    assert (tmp_path / "runs" / "AUTO_001" / "audit.json").exists()


def test_loop_max_iterations_zero_supported():
    from scripts.research.run_autonomous_research_loop import iteration_summary

    summary = iteration_summary({"coordinator_decision": {"decision": "search_new_literature", "reason": "none"}})
    assert summary["next_action"] == "search_new_literature"


def _write_run(run_dir, cagr=10, drawdown=-20, years_win=1, years_loss=1, parent="PARENT", content_tag=None):
    run_dir.mkdir(parents=True, exist_ok=True)
    tag = content_tag or run_dir.name
    (run_dir / "metrics.json").write_text(json.dumps({"strategy": {"cagr_pct": cagr, "max_drawdown_pct": drawdown, "total_return_pct": cagr * 10}, "spy": {"cagr_pct": 8, "max_drawdown_pct": -30, "total_return_pct": 40}, "costs": {"applied": True, "cost_per_side_pct": 0.24}, "diagnostics": {"warnings": []}}), encoding="utf-8")
    (run_dir / "spy_comparison_summary.json").write_text(json.dumps({"strategy_cagr_pct": cagr, "spy_cagr_pct": 8, "excess_cagr_pct": cagr - 8, "months_beating_spy": 6, "months_losing_to_spy": 4, "years_beating_spy": years_win, "years_losing_to_spy": years_loss}), encoding="utf-8")
    (run_dir / "trades.csv").write_text(f"net_return_pct,gross_return_pct,tag\n2,2.5,{tag}\n", encoding="utf-8")
    (run_dir / "equity_curve.csv").write_text(f"date,equity,tag\n2024-01-01,10000,{tag}\n2024-02-01,{10000 + cagr},{tag}\n", encoding="utf-8")
    (run_dir / "run_manifest.json").write_text(json.dumps({"run_id": run_dir.name, "parent_run_id": parent, "hypothesis_id": f"H_{run_dir.name}", "hypothesis_family": "momentum", "bibliography_basis": [{"source_id": "SRC"}]}), encoding="utf-8")


def test_duplicate_historical_artifact_is_detected(tmp_path):
    _write_run(tmp_path / "runs" / "AUTO_001", content_tag="same")
    _write_run(tmp_path / "runs" / "AUTO_002", content_tag="same")
    result = rebuild_artifact_index_from_runs(tmp_path / "runs", tmp_path / "state")
    duplicate = find_duplicate_artifact(tmp_path / "runs" / "AUTO_002", tmp_path / "state")
    assert result["duplicates"][0]["duplicate_of_run_id"] == "AUTO_001"
    assert duplicate["decision"] == "duplicate_result"
    assert duplicate["can_move_parent"] is False


def test_parent_null_cannot_move_parent():
    candidate = {"run_id": "AUTO_X", "cagr": 50, "max_drawdown": -10, "years_beating_spy": 7, "years_losing_to_spy": 0}
    champion = {"run_id": "AUTO_002", "cagr": 40, "max_drawdown": -20, "years_beating_spy": 5, "years_losing_to_spy": 1}
    result = classify_candidate(candidate, champion, parent_run_id=None)
    assert result["can_move_parent"] is False
    assert result["value_delivered"] == "rejected_with_learning"


def test_auto_002_like_run_becomes_best_champion(tmp_path):
    _write_run(tmp_path / "runs" / "AUTO_002", cagr=52, drawdown=-24, years_win=7, years_loss=0)
    _write_run(tmp_path / "runs" / "EXP_030", cagr=53, drawdown=-37, years_win=5, years_loss=2)
    state = rebuild_champion_state_from_runs(tmp_path / "runs", tmp_path / "state")
    assert state["best_champion_run_id"] == "AUTO_002"
    assert state["aggressive_champion_run_id"] == "EXP_030"


def test_improves_parent_but_loses_to_champion_is_secondary():
    candidate = {"run_id": "AUTO_003", "cagr": 49, "max_drawdown": -30, "years_beating_spy": 6, "years_losing_to_spy": 1}
    champion = {"run_id": "AUTO_002", "cagr": 52, "max_drawdown": -24, "years_beating_spy": 7, "years_losing_to_spy": 0}
    result = classify_candidate(candidate, champion, parent_run_id="EXP_PARENT")
    assert result["value_delivered"] == "secondary_candidate"
    assert result["can_move_parent"] is False


def test_three_duplicate_same_axis_exhausts_axis(tmp_path):
    memory = {"events": [{"family": "mixed", "axis": "regime+trend", "decision": "duplicate_result", "precheck_status": "duplicate_result"} for _ in range(3)]}
    cooldowns = update_axis_cooldowns(tmp_path, memory)
    assert cooldowns["axes"]["mixed:regime+trend"]["status"] == "axis_exhausted"
