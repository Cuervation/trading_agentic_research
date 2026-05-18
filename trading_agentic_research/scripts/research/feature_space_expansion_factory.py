"""Final autonomous fallback: conservative feature-space hypothesis expansion.

This factory is used only after candidate-review, value, literature and paper
fallbacks fail to produce any eligible work. It is intentionally small,
deterministic and auditable: it creates a few new one-axis or lightly-combined
hypotheses from features that actually exist in the weekly feature store.

It does not move the parent and does not promote candidates. It only appends new
hypothesis cards to the hypothesis bank for the normal selector/backtester.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.research.autonomous_hypothesis_factory import (
    append_jsonl,
    exhausted_axes_from_ledger,
    existing_ids,
    existing_override_sigs,
    read_json,
    read_jsonl,
    real_override_signature,
)
from scripts.research.literature_hypothesis_miner import available_weekly_features


@dataclass(frozen=True)
class FeatureSpec:
    field: str
    family: str
    axis: str
    order: str
    claim: str
    mechanism: str
    source_id: str


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text.upper()).strip("_")[:48] or "FEATURE"


def _safe_run_id(value: Any) -> str:
    return _slug(str(value or "PARENT"))


def _deep_get(d: dict[str, Any], path: tuple[str, ...], default: Any = None) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _recent_text(state_dir: str | Path) -> str:
    pieces: list[str] = []
    for name in ["research_ledger.jsonl", "rejected_hypotheses.jsonl", "accepted_hypotheses.jsonl", "consumed_hypotheses.jsonl"]:
        rows = read_jsonl(Path(state_dir) / name)
        for row in rows[-80:]:
            pieces.append(json.dumps(row, sort_keys=True, ensure_ascii=False))
    return "\n".join(pieces).lower()


def _feature_specs() -> list[FeatureSpec]:
    return [
        FeatureSpec("ret_13w_pct", "feature_space_momentum", "feature_space_ranking", "desc", "A 13-week momentum ranking may catch earlier leadership rotation than the official parent.", "Shorter momentum horizons can adapt faster, but must prove SPY-relative robustness after costs.", "feature_space_local_momentum_13w"),
        FeatureSpec("ret_26w_pct", "feature_space_momentum", "feature_space_ranking", "desc", "A 26-week momentum ranking may balance responsiveness and trend persistence.", "Intermediate momentum may avoid very late entries while preserving trend continuation.", "feature_space_local_momentum_26w"),
        FeatureSpec("ret_52w_pct", "feature_space_momentum", "feature_space_ranking", "desc", "A direct 52-week return ranking retests canonical time-series/cross-sectional momentum on available features.", "The parent uses trend information; direct 52-week return can validate whether the proxy choice matters.", "feature_space_local_momentum_52w"),
        FeatureSpec("close_vs_sma20w_pct", "feature_space_trend_following", "feature_space_ranking", "desc", "Distance above the 20-week SMA may capture faster trend confirmation.", "Fast trend strength can improve entry timing but risks whipsaw, so it needs strict falsification.", "feature_space_fast_trend_sma20"),
        FeatureSpec("close_vs_sma52w_pct", "feature_space_trend_following", "feature_space_ranking", "desc", "Distance above the 52-week SMA may favor structurally persistent leaders.", "Long trend distance can capture durable leadership while staying close to the official parent mechanism.", "feature_space_slow_trend_sma52"),
        FeatureSpec("channel_r2", "feature_space_quality_momentum", "feature_space_ranking", "desc", "Ranking by channel_r2 may prefer cleaner trends over noisy winners.", "Trend quality can reduce fragile momentum exposure and improve drawdown-adjusted robustness.", "feature_space_channel_quality"),
        FeatureSpec("channel_slope_pct", "feature_space_quality_momentum", "feature_space_ranking", "desc", "Ranking by channel_slope_pct may prefer stronger fitted trend slopes.", "Slope captures directional persistence differently than raw returns and may diversify hypothesis search.", "feature_space_channel_slope"),
        FeatureSpec("distance_to_channel_lower_pct", "feature_space_pullback", "feature_space_ranking", "asc", "Distance to the lower channel may test controlled pullback entries within trend context.", "Buying closer to support can reduce downside, but must not become a falling-knife artifact.", "feature_space_channel_pullback"),
        FeatureSpec("close_sma_50_slope_5d_pct", "feature_space_trend_following", "feature_space_ranking", "desc", "A positive short SMA slope may confirm improving local trend before entry.", "Recent slope can filter deteriorating trends that still look strong on long lookbacks.", "feature_space_local_sma_slope"),
    ]


def _existing_feature_mentions(state_dir: str | Path) -> set[str]:
    text = _recent_text(state_dir)
    return {spec.field for spec in _feature_specs() if spec.field.lower() in text}


def _build_row(
    *,
    hypothesis_id: str,
    spec: FeatureSpec,
    parent_run_id: str,
    parent_hypothesis_id: str | None,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    required = [spec.field, "close"]
    return {
        "hypothesis_id": hypothesis_id,
        "family": spec.family,
        "claim": spec.claim,
        "causal_mechanism": spec.mechanism,
        "bibliography_basis": [{"source_id": spec.source_id, "title": "Autonomous feature-space expansion after local/literature exhaustion"}],
        "empirical_basis": [{"run_id": parent_run_id, "hypothesis_id": parent_hypothesis_id, "reason": "Generated only after candidate/value/literature/paper fallbacks produced no eligible hypotheses."}],
        "features_required": required,
        "status": "candidate",
        "required_spy_comparison": "monthly_and_yearly",
        "axis": spec.axis,
        "falsification_rule": "Reject if it fails to improve CAGR/drawdown/SPY-relative robustness versus AUTO_002 or if it creates duplicate/no-effect artifacts.",
        "strategy_overrides": overrides,
    }


def generate_feature_space_hypotheses(
    *,
    parent_strategy_config_path: str | Path,
    hypothesis_bank_path: str | Path = "bibliography/hypothesis_bank.jsonl",
    state_dir: str | Path = "state",
    max_new: int = 5,
    reason: str = "all_fallbacks_exhausted",
) -> dict[str, Any]:
    parent = read_json(parent_strategy_config_path, {}) or {}
    if not parent:
        return {"generated": 0, "reason": "missing_parent_config", "parent_strategy_config": str(parent_strategy_config_path)}

    features = available_weekly_features(state_dir)
    if not features:
        return {"generated": 0, "reason": "missing_weekly_feature_header", "parent_strategy_config": str(parent_strategy_config_path)}

    bank = read_jsonl(hypothesis_bank_path)
    ids = existing_ids(bank)
    sigs = existing_override_sigs(bank)
    current = read_json(Path(state_dir) / "current_parent.json", {}) or {}
    parent_run_id = str(current.get("current_parent_run_id") or "PARENT")
    parent_hypothesis_id = current.get("current_parent_hypothesis_id") or current.get("current_parent_strategy_id")
    safe_parent = _safe_run_id(parent_run_id)
    parent_ranking = str(_deep_get(parent, ("ranking", "field"), "") or "")
    parent_top_n = int(_deep_get(parent, ("entry_rule", "top_n"), 8) or 8)
    parent_exit = int(_deep_get(parent, ("exit_rule", "rank_threshold"), 20) or 20)

    exhausted_axes = exhausted_axes_from_ledger(state_dir)
    recently_used_features = _existing_feature_mentions(state_dir)
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    def add(spec: FeatureSpec, suffix: str, overrides: dict[str, Any]) -> None:
        if len(rows) >= max_new:
            return
        if spec.axis in exhausted_axes:
            skipped.append({"field": spec.field, "reason": "axis_exhausted", "axis": spec.axis})
            return
        hypothesis_id = f"HYP_FSPACE_{safe_parent}_{suffix}_V1"
        if hypothesis_id in ids:
            skipped.append({"field": spec.field, "reason": "id_exists", "hypothesis_id": hypothesis_id})
            return
        overrides = dict(overrides)
        overrides["strategy_id"] = hypothesis_id
        overrides.setdefault("strategy_family", spec.family)
        sig = real_override_signature(overrides)
        if sig in sigs:
            skipped.append({"field": spec.field, "reason": "duplicate_override_signature", "hypothesis_id": hypothesis_id})
            return
        rows.append(_build_row(
            hypothesis_id=hypothesis_id,
            spec=spec,
            parent_run_id=parent_run_id,
            parent_hypothesis_id=parent_hypothesis_id,
            overrides=overrides,
        ))
        ids.add(hypothesis_id)
        sigs.add(sig)

    # Prefer unused feature dimensions first; then allow lightly-used dimensions
    # with a different structural combination.
    available_specs = [s for s in _feature_specs() if s.field in features and s.field != parent_ranking]
    available_specs.sort(key=lambda s: (s.field in recently_used_features, s.field))

    for spec in available_specs:
        overrides = {
            "ranking": {"field": spec.field, "order": spec.order},
            "risk_filters": {"require_non_null_fields": [spec.field, "close"]},
            "changed_parameters": ["ranking.field", "risk_filters.require_non_null_fields"],
            "expected_effect": "Discover a non-consumed feature dimension while preserving parent governance and SPY comparison.",
            "autonomy_reason": reason,
        }
        add(spec, f"RANK_{_slug(spec.field)}", overrides)

    # If pure ranking features are exhausted/duplicated, try a small combined
    # structure only when the corresponding coarse axis was not exhausted.
    if len(rows) < max_new and "concentration" not in exhausted_axes:
        for spec in available_specs:
            for top_n in sorted({max(3, parent_top_n - 2), parent_top_n + 2, 7, 9}):
                if top_n == parent_top_n:
                    continue
                overrides = {
                    "ranking": {"field": spec.field, "order": spec.order},
                    "entry_rule": {"top_n": int(top_n)},
                    "risk_filters": {"require_non_null_fields": [spec.field, "close"]},
                    "changed_parameters": ["ranking.field", "entry_rule.top_n"],
                    "expected_effect": "Test a new ranking feature with a mild concentration adjustment, without changing parent.",
                    "autonomy_reason": reason,
                }
                add(spec, f"RANK_{_slug(spec.field)}_TOPN_{top_n}", overrides)
                if len(rows) >= max_new:
                    break
            if len(rows) >= max_new:
                break

    if len(rows) < max_new and "exit_threshold" not in exhausted_axes:
        for spec in available_specs:
            for threshold in sorted({max(3, parent_exit - 4), parent_exit + 4}):
                if threshold == parent_exit:
                    continue
                overrides = {
                    "ranking": {"field": spec.field, "order": spec.order},
                    "exit_rule": {"rank_threshold": int(threshold)},
                    "risk_filters": {"require_non_null_fields": [spec.field, "close"]},
                    "changed_parameters": ["ranking.field", "exit_rule.rank_threshold"],
                    "expected_effect": "Test a new ranking feature with a mild exit adjustment, without changing parent.",
                    "autonomy_reason": reason,
                }
                add(spec, f"RANK_{_slug(spec.field)}_EXIT_{threshold}", overrides)
                if len(rows) >= max_new:
                    break
            if len(rows) >= max_new:
                break

    if rows:
        append_jsonl(hypothesis_bank_path, rows)

    return {
        "generated": len(rows),
        "reason": "feature_space_hypotheses_generated" if rows else "no_new_feature_space_hypotheses",
        "hypotheses": [row["hypothesis_id"] for row in rows],
        "parent_strategy_config": str(parent_strategy_config_path),
        "parent_run_id": parent_run_id,
        "available_feature_count": len(features),
        "available_specs": [s.field for s in available_specs],
        "recently_used_features": sorted(recently_used_features),
        "skipped": skipped[:30],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--parent-strategy-config", required=True)
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--max-new", type=int, default=5)
    p.add_argument("--reason", default="manual")
    args = p.parse_args()
    print(json.dumps(generate_feature_space_hypotheses(
        parent_strategy_config_path=args.parent_strategy_config,
        hypothesis_bank_path=args.hypothesis_bank,
        state_dir=args.state_dir,
        max_new=args.max_new,
        reason=args.reason,
    ), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
