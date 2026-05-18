"""Final autonomous fallback: feature-space hypothesis expansion v2.

Used after candidate-review, value, literature and paper fallbacks fail to
produce eligible work. Version 2 keeps the same safety goals as v1, but it is
less sterile when simple one-axis ranking hypotheses are exhausted:

- first tries pure ranking hypotheses;
- then generates *real* composite hypotheses supported by the backtester:
  ranking + row-level confirmation filters, ranking + market-filter variants,
  ranking + mild top_n/exit changes;
- avoids duplicate real override signatures;
- stays deterministic, auditable, and parent-lock safe.

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


@dataclass(frozen=True)
class ConfirmSpec:
    field: str
    operator: str
    value: float
    suffix: str
    claim_fragment: str
    mechanism_fragment: str


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text.upper()).strip("_")[:56] or "FEATURE"


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
        for row in rows[-120:]:
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


def _confirm_specs() -> list[ConfirmSpec]:
    return [
        ConfirmSpec("close_vs_sma20w_pct", ">", 0.0, "SMA20_POS", "20-week trend must be positive", "fast trend confirmation reduces late/weak momentum entries"),
        ConfirmSpec("close_vs_sma52w_pct", ">", 0.0, "SMA52_POS", "52-week trend must be positive", "long trend confirmation filters structurally weak names"),
        ConfirmSpec("close_sma_50_slope_5d_pct", ">", 0.0, "SMA50_SLOPE_POS", "short SMA slope must be positive", "recent slope confirmation avoids deteriorating trends"),
        ConfirmSpec("channel_slope_pct", ">", 0.0, "CHANNEL_SLOPE_POS", "channel slope must be positive", "positive fitted trend reduces noisy counter-trend selections"),
        ConfirmSpec("channel_r2", ">=", 0.35, "CHANNEL_R2_035", "trend quality must clear a minimum R2", "trend quality confirmation reduces fragile momentum exposure"),
        ConfirmSpec("ret_13w_pct", ">", 0.0, "RET13_POS", "13-week return must be positive", "near-term confirmation avoids stale long-lookback winners"),
    ]


def _existing_feature_mentions(state_dir: str | Path) -> set[str]:
    text = _recent_text(state_dir)
    names = {spec.field for spec in _feature_specs()}
    names.update({spec.field for spec in _confirm_specs()})
    return {name for name in names if name.lower() in text}


def _row_family_for_combo(rank_spec: FeatureSpec, suffix: str) -> str:
    if "CONF" in suffix or "FILTER" in suffix:
        return "feature_space_composite_confirmation"
    if "MKT" in suffix or "SPY" in suffix:
        return "feature_space_regime"
    if "TOPN" in suffix:
        return "feature_space_composite_concentration"
    if "EXIT" in suffix:
        return "feature_space_composite_exit"
    return rank_spec.family


def _build_row(
    *,
    hypothesis_id: str,
    spec: FeatureSpec,
    parent_run_id: str,
    parent_hypothesis_id: str | None,
    overrides: dict[str, Any],
    claim: str | None = None,
    mechanism: str | None = None,
    family: str | None = None,
    axis: str | None = None,
    features_required: list[str] | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    required = sorted(set(features_required or [spec.field, "close"]))
    return {
        "hypothesis_id": hypothesis_id,
        "family": family or spec.family,
        "claim": claim or spec.claim,
        "causal_mechanism": mechanism or spec.mechanism,
        "bibliography_basis": [{"source_id": source_id or spec.source_id, "title": "Autonomous feature-space expansion after local/literature exhaustion"}],
        "empirical_basis": [{"run_id": parent_run_id, "hypothesis_id": parent_hypothesis_id, "reason": "Generated only after candidate/value/literature/paper fallbacks produced no eligible hypotheses."}],
        "features_required": required,
        "status": "candidate",
        "required_spy_comparison": "monthly_and_yearly",
        "axis": axis or spec.axis,
        "falsification_rule": "Reject if it fails to improve CAGR/drawdown/SPY-relative robustness versus AUTO_002 or if it creates duplicate/no-effect artifacts.",
        "strategy_overrides": overrides,
    }


def _condition(field: str, operator: str, value: float) -> dict[str, Any]:
    return {"field": field, "operator": operator, "value": value, "enabled_if_field_exists": True}


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
    layers: list[str] = []

    available_specs = [s for s in _feature_specs() if s.field in features and s.field != parent_ranking]
    available_specs.sort(key=lambda s: (s.field in recently_used_features, s.field))
    confirm_specs = [c for c in _confirm_specs() if c.field in features]
    confirm_specs.sort(key=lambda c: (c.field in recently_used_features, c.field, c.suffix))

    def add(
        spec: FeatureSpec,
        suffix: str,
        overrides: dict[str, Any],
        *,
        layer: str,
        claim: str | None = None,
        mechanism: str | None = None,
        family: str | None = None,
        axis: str | None = None,
        features_required: list[str] | None = None,
        source_id: str | None = None,
        respect_axis_exhaustion: bool = True,
    ) -> None:
        if len(rows) >= max_new:
            return
        effective_axis = axis or spec.axis
        if respect_axis_exhaustion and effective_axis in exhausted_axes:
            skipped.append({"field": spec.field, "reason": "axis_exhausted", "axis": effective_axis, "layer": layer})
            return
        hypothesis_id = f"HYP_FSPACE_{safe_parent}_{suffix}_V1"
        if hypothesis_id in ids:
            skipped.append({"field": spec.field, "reason": "id_exists", "hypothesis_id": hypothesis_id, "layer": layer})
            return
        overrides = dict(overrides)
        overrides["strategy_id"] = hypothesis_id
        overrides.setdefault("strategy_family", family or _row_family_for_combo(spec, suffix))
        sig = real_override_signature(overrides)
        if sig in sigs:
            skipped.append({"field": spec.field, "reason": "duplicate_override_signature", "hypothesis_id": hypothesis_id, "layer": layer})
            return
        rows.append(_build_row(
            hypothesis_id=hypothesis_id,
            spec=spec,
            parent_run_id=parent_run_id,
            parent_hypothesis_id=parent_hypothesis_id,
            overrides=overrides,
            claim=claim,
            mechanism=mechanism,
            family=family or _row_family_for_combo(spec, suffix),
            axis=effective_axis,
            features_required=features_required,
            source_id=source_id,
        ))
        ids.add(hypothesis_id)
        sigs.add(sig)
        layers.append(layer)

    # Layer 1: pure ranking, same as v1. It is cheap and still useful when new
    # feature columns appear.
    for spec in available_specs:
        overrides = {
            "ranking": {"field": spec.field, "order": spec.order},
            "risk_filters": {"require_non_null_fields": [spec.field, "close"]},
            "changed_parameters": ["ranking.field", "ranking.order", "risk_filters.require_non_null_fields"],
            "expected_effect": "Discover a non-consumed feature dimension while preserving parent governance and SPY comparison.",
            "autonomy_reason": reason,
        }
        add(spec, f"RANK_{_slug(spec.field)}", overrides, layer="pure_ranking")

    # Layer 2: ranking + confirmation filter. These are real because
    # backtester.signal_builder now enforces risk_filters.conditions.
    if len(rows) < max_new:
        for spec in available_specs:
            for confirm in confirm_specs:
                if confirm.field == spec.field:
                    continue
                required = [spec.field, confirm.field, "close"]
                overrides = {
                    "ranking": {"field": spec.field, "order": spec.order},
                    "risk_filters": {
                        "require_non_null_fields": required,
                        "conditions": [_condition(confirm.field, confirm.operator, confirm.value)],
                    },
                    "changed_parameters": ["ranking.field", "ranking.order", "risk_filters.conditions"],
                    "expected_effect": "Test ranking signal only when an independent trend/quality confirmation is present.",
                    "autonomy_reason": reason,
                }
                claim = f"Ranking by {spec.field} plus confirmation that {confirm.claim_fragment} may reduce duplicate/noisy momentum exposure."
                mechanism = f"{spec.mechanism} The confirmation layer adds an independent condition: {confirm.mechanism_fragment}."
                add(
                    spec,
                    f"RANK_{_slug(spec.field)}_CONF_{confirm.suffix}",
                    overrides,
                    layer="rank_confirmation",
                    claim=claim,
                    mechanism=mechanism,
                    family="feature_space_composite_confirmation",
                    axis="feature_space_rank_confirm",
                    features_required=required,
                    source_id=f"{spec.source_id}__{confirm.suffix.lower()}",
                    respect_axis_exhaustion=False,
                )
                if len(rows) >= max_new:
                    break
            if len(rows) >= max_new:
                break

    # Layer 3: ranking + real market-filter variants. These are useful because
    # the logs show repeated SPY NaN fallback warnings.
    if len(rows) < max_new:
        for spec in available_specs:
            variants = [
                ("MKT_STRICT_SPY", {"require_positive_trend": True, "fallback_allow_if_missing_spy_metric": False}, "strict SPY trend filter without NaN fallback"),
                ("MKT_RELAXED", {"require_positive_trend": False}, "relaxed market filter to measure over-filtering"),
            ]
            for suffix, market_filter, label in variants:
                overrides = {
                    "ranking": {"field": spec.field, "order": spec.order},
                    "market_filter": market_filter,
                    "risk_filters": {"require_non_null_fields": [spec.field, "close"]},
                    "changed_parameters": ["ranking.field", "ranking.order", "market_filter"],
                    "expected_effect": f"Test whether {label} changes robustness versus AUTO_002.",
                    "autonomy_reason": reason,
                }
                add(
                    spec,
                    f"RANK_{_slug(spec.field)}_{suffix}",
                    overrides,
                    layer="rank_market_filter",
                    claim=f"Ranking by {spec.field} with {label} may reveal whether regime gating is helping or over-filtering.",
                    mechanism=f"{spec.mechanism} The market regime variant directly changes the live gate used by signal_builder.",
                    family="feature_space_regime",
                    axis="feature_space_market_filter",
                    features_required=[spec.field, "close"],
                    source_id=f"{spec.source_id}__{suffix.lower()}",
                    respect_axis_exhaustion=False,
                )
                if len(rows) >= max_new:
                    break
            if len(rows) >= max_new:
                break

    # Layer 4: composite concentration. Even when the coarse concentration axis
    # is exhausted for old families, rank+top_n can be causal for a new feature.
    if len(rows) < max_new:
        for spec in available_specs:
            for top_n in sorted({max(3, parent_top_n - 3), max(3, parent_top_n - 1), parent_top_n + 2, parent_top_n + 4, 5, 7, 9, 11}):
                if top_n == parent_top_n:
                    continue
                overrides = {
                    "ranking": {"field": spec.field, "order": spec.order},
                    "entry_rule": {"top_n": int(top_n)},
                    "risk_filters": {"require_non_null_fields": [spec.field, "close"]},
                    "changed_parameters": ["ranking.field", "ranking.order", "entry_rule.top_n"],
                    "expected_effect": "Test a feature-specific concentration level without changing official parent governance.",
                    "autonomy_reason": reason,
                }
                add(
                    spec,
                    f"RANK_{_slug(spec.field)}_TOPN_{top_n}",
                    overrides,
                    layer="rank_topn",
                    claim=f"Ranking by {spec.field} with top_n={top_n} may improve the concentration/diversification trade-off for this feature.",
                    mechanism=f"{spec.mechanism} A feature-specific top_n can change turnover and concentration without changing parent.",
                    family="feature_space_composite_concentration",
                    axis="feature_space_rank_topn",
                    features_required=[spec.field, "close"],
                    source_id=f"{spec.source_id}__topn",
                    respect_axis_exhaustion=False,
                )
                if len(rows) >= max_new:
                    break
            if len(rows) >= max_new:
                break

    # Layer 5: composite exit threshold. Same idea: rank-specific exit behavior
    # may be different even if generic exit experiments were exhausted.
    if len(rows) < max_new:
        for spec in available_specs:
            for threshold in sorted({max(3, parent_exit - 6), max(3, parent_exit - 3), parent_exit + 3, parent_exit + 6, 14, 18, 24, 28}):
                if threshold == parent_exit:
                    continue
                overrides = {
                    "ranking": {"field": spec.field, "order": spec.order},
                    "exit_rule": {"rank_threshold": int(threshold)},
                    "risk_filters": {"require_non_null_fields": [spec.field, "close"]},
                    "changed_parameters": ["ranking.field", "ranking.order", "exit_rule.rank_threshold"],
                    "expected_effect": "Test whether this feature needs a tighter/looser exit rank threshold.",
                    "autonomy_reason": reason,
                }
                add(
                    spec,
                    f"RANK_{_slug(spec.field)}_EXIT_{threshold}",
                    overrides,
                    layer="rank_exit",
                    claim=f"Ranking by {spec.field} with exit threshold={threshold} may cut deterioration differently than the parent.",
                    mechanism=f"{spec.mechanism} The exit threshold controls when ranked names leave the hold universe.",
                    family="feature_space_composite_exit",
                    axis="feature_space_rank_exit",
                    features_required=[spec.field, "close"],
                    source_id=f"{spec.source_id}__exit",
                    respect_axis_exhaustion=False,
                )
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
        "available_confirmations": [c.field for c in confirm_specs],
        "recently_used_features": sorted(recently_used_features),
        "generation_layers": layers,
        "skipped": skipped[:60],
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
