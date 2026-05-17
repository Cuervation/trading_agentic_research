from scripts.parameter_effect_memory import (
    build_parameter_effect_observations,
    classify_parameter_axis,
    flatten_strategy_overrides,
    score_hypothesis_axis,
    update_parameter_effect_memory,
)


def test_flatten_strategy_overrides_and_axis_classification():
    changes = flatten_strategy_overrides(
        {"strategy_id": "S1", "entry_rule": {"top_n": 8}, "exit_rule": {"rank_threshold": 20}}
    )

    assert {"parameter": "entry_rule.top_n", "new_value": 8, "axis": "concentration"} in changes
    assert {"parameter": "exit_rule.rank_threshold", "new_value": 20, "axis": "exit_threshold"} in changes
    assert classify_parameter_axis("ranking.field") == "ranking_horizon"


def test_update_parameter_effect_memory_aggregates_scores():
    hypothesis = {
        "hypothesis_id": "H1",
        "family": "cross_sectional_momentum",
        "strategy_overrides": {"entry_rule": {"top_n": 8}},
    }
    observations = build_parameter_effect_observations(
        hypothesis=hypothesis,
        run_id="EXP_100",
        decision="promoted_candidate",
        learning_metrics={
            "parent_cagr_delta_pct": 5.0,
            "parent_drawdown_delta_pct": 2.0,
            "years_beating_parent": 4,
            "years_losing_to_parent": 1,
        },
    )
    memory = update_parameter_effect_memory({"version": 1, "observations": []}, observations)

    effect = memory["effects_by_parameter"]["entry_rule.top_n"]
    assert effect["count"] == 1
    assert effect["avg_parent_cagr_delta_pct"] == 5.0
    assert memory["effects_by_axis"]["concentration"]["score"] > 0


def test_score_hypothesis_axis_prefers_positive_axis():
    memory = {
        "effects_by_axis": {
            "concentration": {"score": 3.0},
            "exit_threshold": {"score": -2.0},
        }
    }

    good = {"strategy_overrides": {"entry_rule": {"top_n": 8}}}
    bad = {"strategy_overrides": {"exit_rule": {"rank_threshold": 15}}}

    assert score_hypothesis_axis(good, memory) > score_hypothesis_axis(bad, memory)

