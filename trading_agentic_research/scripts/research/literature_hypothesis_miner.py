"""Offline literature-to-hypothesis fallback.

This is intentionally lightweight and deterministic. It does not claim to read
new papers online; instead it turns a curated bibliography template library into
new auditable hypothesis cards when the local mutation factory is exhausted.

The miner is designed for autonomous operation:
- It reads available weekly features from state/data_paths_resolved.json.
- It emits only hypotheses whose required features appear to exist.
- It records unsupported but promising paper ideas in state/missing_feature_tasks.jsonl.
- It deduplicates by real strategy override signature, ignoring metadata.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.research.autonomous_hypothesis_factory import (
    append_jsonl,
    deep_set,
    existing_ids,
    existing_override_sigs,
    read_json,
    read_jsonl,
    real_override_signature,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _header(path: str | Path | None) -> set[str]:
    if not path:
        return set()
    p = Path(path)
    if not p.exists() or not p.is_file():
        return set()
    try:
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            first = f.readline()
            delim = ";" if ";" in first else ","
            f.seek(0)
            return {x.strip() for x in next(csv.reader(f, delimiter=delim), [])}
    except Exception:
        return set()


def available_weekly_features(state_dir: str | Path = "state") -> set[str]:
    resolved = read_json(Path(state_dir) / "data_paths_resolved.json", {}) or {}
    return _header(resolved.get("weekly_file"))


@dataclass(frozen=True)
class PaperIdea:
    suffix: str
    family: str
    source_id: str
    paper_title: str
    claim: str
    mechanism: str
    required_features: tuple[str, ...]
    overrides: dict[str, Any]
    falsification_rule: str


def literature_templates(parent: dict[str, Any]) -> list[PaperIdea]:
    # Keep overrides simple because the current backtester supports simple ranking/entry/exit/filter configs.
    return [
        PaperIdea(
            suffix="TSMOM_RET52_RANK_V1",
            family="paper_time_series_momentum",
            source_id="moskowitz_ooi_pedersen_time_series_momentum",
            paper_title="Time Series Momentum",
            claim="Ranking by 52-week return can preserve time-series trend persistence while staying close to the AUTO_002 champion mechanism.",
            mechanism="Trend persistence across intermediate horizons may continue in equities, but must beat the current champion after costs.",
            required_features=("ret_52w_pct", "close"),
            overrides={"ranking": {"field": "ret_52w_pct", "order": "desc"}, "risk_filters": {"require_non_null_fields": ["ret_52w_pct", "close"]}},
            falsification_rule="Reject if it fails to improve CAGR/drawdown or duplicates historical artifacts versus AUTO_002.",
        ),
        PaperIdea(
            suffix="TSMOM_RET26_CONFIRM_V1",
            family="paper_time_series_momentum",
            source_id="multi_lookback_momentum_confirmation",
            paper_title="Multi-lookback momentum confirmation",
            claim="A shorter 26-week lookback may react faster than the current 52-week trend while retaining trend persistence.",
            mechanism="Intermediate momentum can decay; shorter confirmation may reduce late entries after trend exhaustion.",
            required_features=("ret_26w_pct", "close"),
            overrides={"ranking": {"field": "ret_26w_pct", "order": "desc"}, "risk_filters": {"require_non_null_fields": ["ret_26w_pct", "close"]}},
            falsification_rule="Reject if monthly/yearly SPY-relative robustness does not improve or artifact signature duplicates prior runs.",
        ),
        PaperIdea(
            suffix="QUALITY_CHANNEL_R2_V1",
            family="paper_quality_momentum",
            source_id="quality_momentum_trend_stability",
            paper_title="Quality momentum / trend stability proxy",
            claim="Momentum with a trend-quality proxy may reduce fragile momentum exposure.",
            mechanism="Persistent and well-fit trends may be less prone to reversal than noisy momentum winners.",
            required_features=("channel_r2", "close"),
            overrides={"ranking": {"field": "channel_r2", "order": "desc"}, "risk_filters": {"require_non_null_fields": ["channel_r2", "close"]}},
            falsification_rule="Reject if CAGR deteriorates materially without a compensating drawdown improvement versus AUTO_002.",
        ),
        PaperIdea(
            suffix="SMA20_TREND_FAST_CONFIRM_V1",
            family="paper_trend_following",
            source_id="trend_following_fast_slow_confirmation",
            paper_title="Trend following fast/slow confirmation",
            claim="Ranking by distance to the 20-week SMA can capture faster trend confirmation than the current 52-week SMA distance.",
            mechanism="Shorter trend signals may cut deteriorating names faster but risk more churn.",
            required_features=("close_vs_sma20w_pct", "close"),
            overrides={"ranking": {"field": "close_vs_sma20w_pct", "order": "desc"}, "risk_filters": {"require_non_null_fields": ["close_vs_sma20w_pct", "close"]}},
            falsification_rule="Reject if turnover/whipsaw reduces CAGR and does not improve drawdown/years versus SPY.",
        ),
        PaperIdea(
            suffix="VOL_FILTER_ATR14_V1",
            family="paper_low_vol_momentum",
            source_id="low_volatility_anomaly_bab",
            paper_title="Low volatility anomaly / Betting Against Beta",
            claim="Momentum filtered for available volatility proxy may improve drawdown profile.",
            mechanism="High volatility momentum can carry crash risk; requiring ATR availability enables later volatility-aware refinement.",
            required_features=("atr_14w_pct", "ret_52w_pct", "close"),
            overrides={"ranking": {"field": "ret_52w_pct", "order": "desc"}, "risk_filters": {"require_non_null_fields": ["atr_14w_pct", "ret_52w_pct", "close"]}},
            falsification_rule="Reject if drawdown does not improve or CAGR falls more than the defensive threshold.",
        ),
        PaperIdea(
            suffix="SPY_REGIME_RELAXED_V1",
            family="paper_regime_filter",
            source_id="faber_tactical_asset_allocation",
            paper_title="Tactical asset allocation / market regime filter",
            claim="A slightly relaxed SPY SMA50 regime gate may avoid over-filtering while preserving market-direction discipline.",
            mechanism="Market trend filters reduce crash exposure, but over-strict gates can miss recoveries.",
            required_features=("spy_close_vs_sma50_pct", "close"),
            overrides={"market_filter": {"benchmark": "SPY", "condition_any": [{"field": "spy_close_vs_sma50_pct", "operator": ">", "value": -2.5, "enabled_if_field_exists": True}], "require_positive_trend": False}},
            falsification_rule="Reject if it increases drawdown or worsens yearly SPY comparison versus AUTO_002.",
        ),
    ]


def _supported(idea: PaperIdea, features: set[str]) -> bool:
    if not features:
        # If we cannot inspect features, do not generate feature-sensitive ideas blindly.
        return False
    return set(idea.required_features).issubset(features)


def _missing_task(parent_run_id: str, parent_hypothesis_id: str | None, idea: PaperIdea, features: set[str]) -> dict[str, Any]:
    missing = sorted(set(idea.required_features).difference(features))
    return {
        "created_at": now_iso(),
        "parent_run_id": parent_run_id,
        "parent_hypothesis_id": parent_hypothesis_id,
        "source_id": idea.source_id,
        "paper_title": idea.paper_title,
        "candidate_suffix": idea.suffix,
        "reason": "missing_required_features_for_literature_hypothesis",
        "missing_features": missing,
        "claim": idea.claim,
        "next_action": "add_features_to_feature_store_or_skip_this_paper_axis",
    }


def mine_literature_hypotheses(
    *,
    parent_strategy_config_path: str | Path,
    hypothesis_bank_path: str | Path = "bibliography/hypothesis_bank.jsonl",
    state_dir: str | Path = "state",
    max_new: int = 8,
) -> dict[str, Any]:
    parent = read_json(parent_strategy_config_path, {}) or {}
    if not parent:
        return {"generated": 0, "reason": "missing_parent_config", "parent_strategy_config": str(parent_strategy_config_path)}

    features = available_weekly_features(state_dir)
    bank = read_jsonl(hypothesis_bank_path)
    ids = existing_ids(bank)
    sigs = existing_override_sigs(bank)
    current = read_json(Path(state_dir) / "current_parent.json", {}) or {}
    parent_run_id = current.get("current_parent_run_id") or "PARENT"
    parent_hypothesis_id = current.get("current_parent_hypothesis_id") or current.get("current_parent_strategy_id")

    rows: list[dict[str, Any]] = []
    missing_tasks: list[dict[str, Any]] = []
    skipped_existing = 0

    for idea in literature_templates(parent):
        if len(rows) >= max_new:
            break
        hypothesis_id = f"HYP_LIT_{parent_run_id}_{idea.suffix}"
        if hypothesis_id in ids:
            skipped_existing += 1
            continue
        if not _supported(idea, features):
            missing_tasks.append(_missing_task(str(parent_run_id), parent_hypothesis_id, idea, features))
            continue
        overrides = dict(idea.overrides)
        overrides["strategy_id"] = hypothesis_id
        overrides.setdefault("strategy_family", idea.family)
        sig = real_override_signature(overrides)
        if sig in sigs:
            skipped_existing += 1
            continue
        rows.append({
            "hypothesis_id": hypothesis_id,
            "family": idea.family,
            "claim": idea.claim,
            "causal_mechanism": idea.mechanism,
            "bibliography_basis": [{"source_id": idea.source_id, "title": idea.paper_title}],
            "empirical_basis": [{"run_id": parent_run_id, "hypothesis_id": parent_hypothesis_id, "reason": "Generated by literature_hypothesis_miner after local factory exhaustion."}],
            "features_required": list(idea.required_features),
            "status": "candidate",
            "required_spy_comparison": "monthly_and_yearly",
            "axis": idea.family,
            "falsification_rule": idea.falsification_rule,
            "strategy_overrides": overrides,
        })
        ids.add(hypothesis_id)
        sigs.add(sig)

    if rows:
        append_jsonl(hypothesis_bank_path, rows)
    if missing_tasks:
        append_jsonl(Path(state_dir) / "missing_feature_tasks.jsonl", missing_tasks)

    return {
        "generated": len(rows),
        "reason": "literature_hypotheses_generated" if rows else "no_supported_literature_hypotheses",
        "hypotheses": [row["hypothesis_id"] for row in rows],
        "missing_feature_tasks": len(missing_tasks),
        "available_feature_count": len(features),
        "skipped_existing": skipped_existing,
        "parent_run_id": parent_run_id,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--parent-strategy-config", required=True)
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--max-new", type=int, default=8)
    args = p.parse_args()
    print(json.dumps(mine_literature_hypotheses(
        parent_strategy_config_path=args.parent_strategy_config,
        hypothesis_bank_path=args.hypothesis_bank,
        state_dir=args.state_dir,
        max_new=args.max_new,
    ), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
