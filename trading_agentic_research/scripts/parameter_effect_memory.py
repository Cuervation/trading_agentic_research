"""Learn empirical effects by changed parameter and mutation axis."""

from __future__ import annotations

import json
from pathlib import Path


def flatten_strategy_overrides(overrides: dict, prefix: str = "") -> list[dict]:
    """Flatten strategy_overrides into auditable parameter paths."""
    rows: list[dict] = []
    for key, value in (overrides or {}).items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            rows.extend(flatten_strategy_overrides(value, path))
        else:
            if path == "strategy_id":
                continue
            rows.append({"parameter": path, "new_value": value, "axis": classify_parameter_axis(path)})
    return rows


def classify_parameter_axis(parameter_path: str) -> str:
    if parameter_path.startswith("entry_rule.top_n"):
        return "concentration"
    if parameter_path.startswith("exit_rule.rank_threshold"):
        return "exit_threshold"
    if parameter_path.startswith("ranking."):
        return "ranking_horizon"
    if parameter_path.startswith("market_filter."):
        return "market_filter"
    if parameter_path.startswith("risk_management."):
        return "risk_management"
    return "other"


def build_parameter_effect_observations(
    *,
    hypothesis: dict,
    run_id: str,
    decision: str,
    learning_metrics: dict,
) -> list[dict]:
    """Build one observation per changed parameter."""
    changes = flatten_strategy_overrides(hypothesis.get("strategy_overrides", {}))
    observations = []
    for change in changes:
        parent_cagr_delta = float(learning_metrics.get("parent_cagr_delta_pct", 0.0))
        parent_drawdown_delta = float(learning_metrics.get("parent_drawdown_delta_pct", 0.0))
        observations.append(
            {
                "run_id": run_id,
                "hypothesis_id": hypothesis.get("hypothesis_id"),
                "family": hypothesis.get("family"),
                "parameter": change["parameter"],
                "axis": change["axis"],
                "new_value": change["new_value"],
                "decision": decision,
                "parent_cagr_delta_pct": parent_cagr_delta,
                "parent_drawdown_delta_pct": parent_drawdown_delta,
                "years_beating_parent": int(learning_metrics.get("years_beating_parent", 0)),
                "years_losing_to_parent": int(learning_metrics.get("years_losing_to_parent", 0)),
                "no_effect": abs(parent_cagr_delta) <= 0.001 and abs(parent_drawdown_delta) <= 0.001,
            }
        )
    return observations


def update_parameter_effect_memory(memory: dict, observations: list[dict]) -> dict:
    """Upsert observations and recompute aggregate parameter/axis effects."""
    updated = dict(memory or {})
    updated.setdefault("version", 1)

    existing = updated.setdefault("observations", [])
    for obs in observations:
        existing = [
            row
            for row in existing
            if not (
                row.get("run_id") == obs.get("run_id")
                and row.get("hypothesis_id") == obs.get("hypothesis_id")
                and row.get("parameter") == obs.get("parameter")
            )
        ]
        existing.append(obs)

    updated["observations"] = existing
    updated["effects_by_parameter"] = _aggregate(existing, key="parameter")
    updated["effects_by_axis"] = _aggregate(existing, key="axis")
    return updated


def score_hypothesis_axis(hypothesis: dict, memory: dict) -> float:
    """Score a hypothesis using prior empirical effects of its mutation axes."""
    changes = flatten_strategy_overrides(hypothesis.get("strategy_overrides", {}))
    if not changes:
        return 0.0
    axis_effects = (memory or {}).get("effects_by_axis", {})
    scores = []
    for change in changes:
        effect = axis_effects.get(change["axis"])
        if effect:
            scores.append(float(effect.get("score", 0.0)))
        else:
            scores.append(0.25)  # mild exploration bonus for unseen axes
    return sum(scores) / len(scores)


def load_parameter_effect_memory(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"version": 1, "effects_by_parameter": {}, "effects_by_axis": {}, "observations": []}
    return json.loads(p.read_text(encoding="utf-8-sig"))


def save_parameter_effect_memory(path: str | Path, memory: dict) -> None:
    Path(path).write_text(json.dumps(memory, indent=2, ensure_ascii=False), encoding="utf-8")


def _aggregate(observations: list[dict], key: str) -> dict:
    grouped: dict[str, list[dict]] = {}
    for obs in observations:
        grouped.setdefault(str(obs.get(key)), []).append(obs)

    out = {}
    for name, rows in grouped.items():
        cagr_values = [float(r.get("parent_cagr_delta_pct", 0.0)) for r in rows]
        dd_values = [float(r.get("parent_drawdown_delta_pct", 0.0)) for r in rows]
        promoted = sum(1 for r in rows if r.get("decision") == "promoted_candidate")
        rejected = sum(1 for r in rows if r.get("decision") == "rejected")
        no_effect = sum(1 for r in rows if r.get("no_effect"))
        count = len(rows)
        avg_cagr = sum(cagr_values) / count if count else 0.0
        avg_dd = sum(dd_values) / count if count else 0.0
        # Positive CAGR and drawdown deltas are good; rejections/no-op reduce priority.
        score = avg_cagr + (0.5 * avg_dd) + promoted - rejected - (0.5 * no_effect)
        out[name] = {
            "count": count,
            "avg_parent_cagr_delta_pct": avg_cagr,
            "avg_parent_drawdown_delta_pct": avg_dd,
            "promoted_candidates": promoted,
            "rejections": rejected,
            "no_effects": no_effect,
            "score": score,
        }
    return out

