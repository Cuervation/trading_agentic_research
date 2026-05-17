import json

import pytest

from scripts.governance import canonical_strategy_payload, stable_json_hash
from scripts.research.executor import DEFAULT_RESEARCH_WINDOWS_WEEKS, build_execution_plan
from scripts.research.literature_searcher import search_new_literature
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
    result = run_iteration(tmp_path, parent_path)
    assert result["hypothesis"]["source_ids"]
    assert result["precheck"]["status"] in {"passed", "metric_no_effect", "duplicate_result"}
    assert (tmp_path / "hypothesis_memory.json").exists()


def test_executor_defaults_to_4_8_24_52_without_156():
    plan = build_execution_plan("HYP_TEST")
    assert tuple(plan["windows_weeks"]) == DEFAULT_RESEARCH_WINDOWS_WEEKS
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

    result = run_iteration(tmp_path, parent_path)

    assert result["coordinator_decision"]["decision"] == "search_new_literature"
    assert result["literature_search"]["added"] == 1
