"""Literature-to-hypothesis fallback.

Converts curated paper templates and bibliography/paper_ideas.jsonl into new
auditable hypothesis cards.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.research.autonomous_hypothesis_factory import (
    append_jsonl,
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


def built_in_literature_templates(parent: dict[str, Any]) -> list[PaperIdea]:
    return [
        PaperIdea("TSMOM_RET52_RANK_V1", "paper_time_series_momentum", "moskowitz_ooi_pedersen_time_series_momentum", "Time Series Momentum", "Ranking by 52-week return can preserve time-series trend persistence while staying close to the champion mechanism.", "Trend persistence across intermediate horizons may continue in equities, but must beat the current champion after costs.", ("ret_52w_pct", "close"), {"ranking": {"field": "ret_52w_pct", "order": "desc"}, "risk_filters": {"require_non_null_fields": ["ret_52w_pct", "close"]}}, "Reject if it fails to improve CAGR/drawdown or duplicates historical artifacts versus the champion."),
        PaperIdea("TSMOM_RET26_CONFIRM_V1", "paper_time_series_momentum", "multi_lookback_momentum_confirmation", "Multi-lookback momentum confirmation", "A shorter 26-week lookback may react faster than the current 52-week trend while retaining trend persistence.", "Intermediate momentum can decay; shorter confirmation may reduce late entries after trend exhaustion.", ("ret_26w_pct", "close"), {"ranking": {"field": "ret_26w_pct", "order": "desc"}, "risk_filters": {"require_non_null_fields": ["ret_26w_pct", "close"]}}, "Reject if monthly/yearly SPY-relative robustness does not improve or artifact signature duplicates prior runs."),
        PaperIdea("QUALITY_CHANNEL_R2_V1", "paper_quality_momentum", "quality_momentum_trend_stability", "Quality momentum / trend stability proxy", "Momentum with a trend-quality proxy may reduce fragile momentum exposure.", "Persistent and well-fit trends may be less prone to reversal than noisy momentum winners.", ("channel_r2", "close"), {"ranking": {"field": "channel_r2", "order": "desc"}, "risk_filters": {"require_non_null_fields": ["channel_r2", "close"]}}, "Reject if CAGR deteriorates materially without a compensating drawdown improvement versus the champion."),
        PaperIdea("SMA20_TREND_FAST_CONFIRM_V1", "paper_trend_following", "trend_following_fast_slow_confirmation", "Trend following fast/slow confirmation", "Ranking by distance to the 20-week SMA can capture faster trend confirmation than the current long-term trend distance.", "Shorter trend signals may cut deteriorating names faster but risk more churn.", ("close_vs_sma20w_pct", "close"), {"ranking": {"field": "close_vs_sma20w_pct", "order": "desc"}, "risk_filters": {"require_non_null_fields": ["close_vs_sma20w_pct", "close"]}}, "Reject if turnover/whipsaw reduces CAGR and does not improve drawdown/years versus SPY."),
        PaperIdea("VOL_FILTER_ATR14_V1", "paper_low_vol_momentum", "low_volatility_anomaly_bab", "Low volatility anomaly / Betting Against Beta", "Momentum filtered for an available volatility proxy may improve drawdown profile.", "High volatility momentum can carry crash risk; requiring ATR availability enables volatility-aware refinement.", ("atr_14w_pct", "ret_52w_pct", "close"), {"ranking": {"field": "ret_52w_pct", "order": "desc"}, "risk_filters": {"require_non_null_fields": ["atr_14w_pct", "ret_52w_pct", "close"]}}, "Reject if drawdown does not improve or CAGR falls more than the defensive threshold."),
        PaperIdea("SPY_REGIME_RELAXED_V1", "paper_regime_filter", "faber_tactical_asset_allocation", "Tactical asset allocation / market regime filter", "A slightly relaxed SPY SMA50 regime gate may avoid over-filtering while preserving market-direction discipline.", "Market trend filters reduce crash exposure, but over-strict gates can miss recoveries.", ("spy_close_vs_sma50_pct", "close"), {"market_filter": {"benchmark": "SPY", "condition_any": [{"field": "spy_close_vs_sma50_pct", "operator": ">", "value": -2.5, "enabled_if_field_exists": True}], "require_positive_trend": False}}, "Reject if it increases drawdown or worsens yearly SPY comparison versus the champion."),
    ]


def _slug(text: str, max_len: int = 44) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", text.upper()).strip("_")
    return (text or "PAPER_IDEA")[:max_len]


def ideas_from_paper_ideas(path: str | Path = "bibliography/paper_ideas.jsonl") -> list[PaperIdea]:
    rows = read_jsonl(path)
    ideas: list[PaperIdea] = []
    for idx, row in enumerate(rows, start=1):
        if row.get("mode") == "online_search_error":
            continue
        title = str(row.get("title") or row.get("query") or f"paper idea {idx}")
        source_id = str(row.get("source_id") or f"paper_idea_{idx}")
        claim = str(row.get("claim_seed") or row.get("abstract") or title)
        families = [str(x) for x in row.get("families", [])] or []
        text = " ".join([title, claim, str(row.get("query") or row.get("query_seed") or ""), " ".join(families)]).lower()
        if "quality" in text or "stability" in text or "channel" in text:
            ideas.append(PaperIdea(f"PAPER_{_slug(title)}_QUALITY_R2_V1", "paper_quality_momentum", source_id, title, claim, "Paper idea suggests improving raw momentum with trend quality/stability confirmation.", ("channel_r2", "close"), {"ranking": {"field": "channel_r2", "order": "desc"}, "risk_filters": {"require_non_null_fields": ["channel_r2", "close"]}}, "Reject if trend-quality ranking does not improve drawdown-adjusted SPY-relative robustness versus champion."))
        elif "vol" in text or "beta" in text or "drawdown" in text or "crash" in text:
            ideas.append(PaperIdea(f"PAPER_{_slug(title)}_VOL_FILTER_V1", "paper_low_vol_momentum", source_id, title, claim, "Paper idea suggests volatility-aware momentum may reduce crash/drawdown risk.", ("atr_14w_pct", "ret_52w_pct", "close"), {"ranking": {"field": "ret_52w_pct", "order": "desc"}, "risk_filters": {"require_non_null_fields": ["atr_14w_pct", "ret_52w_pct", "close"]}}, "Reject if volatility-aware filter fails to improve drawdown or materially reduces CAGR."))
        elif "regime" in text or "tactical" in text or "asset allocation" in text or "sma" in text:
            ideas.append(PaperIdea(f"PAPER_{_slug(title)}_REGIME_V1", "paper_regime_filter", source_id, title, claim, "Paper idea suggests regime filters can reduce market-direction risk.", ("spy_close_vs_sma50_pct", "close"), {"market_filter": {"benchmark": "SPY", "condition_any": [{"field": "spy_close_vs_sma50_pct", "operator": ">", "value": -2.5, "enabled_if_field_exists": True}], "require_positive_trend": False}}, "Reject if relaxed regime gate worsens drawdown or yearly SPY comparison."))
        else:
            ideas.append(PaperIdea(f"PAPER_{_slug(title)}_RET52_V1", "paper_time_series_momentum", source_id, title, claim, "Paper idea suggests intermediate-horizon trend persistence may improve selection.", ("ret_52w_pct", "close"), {"ranking": {"field": "ret_52w_pct", "order": "desc"}, "risk_filters": {"require_non_null_fields": ["ret_52w_pct", "close"]}}, "Reject if paper-derived 52w momentum idea fails to beat champion or duplicates historical artifacts."))
    return ideas


def _supported(idea: PaperIdea, features: set[str]) -> bool:
    return bool(features) and set(idea.required_features).issubset(features)


def _missing_task(parent_run_id: str, parent_hypothesis_id: str | None, idea: PaperIdea, features: set[str]) -> dict[str, Any]:
    return {"created_at": now_iso(), "parent_run_id": parent_run_id, "parent_hypothesis_id": parent_hypothesis_id, "source_id": idea.source_id, "paper_title": idea.paper_title, "candidate_suffix": idea.suffix, "reason": "missing_required_features_for_literature_hypothesis", "missing_features": sorted(set(idea.required_features).difference(features)), "claim": idea.claim, "next_action": "add_features_to_feature_store_or_skip_this_paper_axis"}


def _all_ideas(parent: dict[str, Any], paper_ideas_path: str | Path) -> list[PaperIdea]:
    return [*built_in_literature_templates(parent), *ideas_from_paper_ideas(paper_ideas_path)]


def mine_literature_hypotheses(*, parent_strategy_config_path: str | Path, hypothesis_bank_path: str | Path = "bibliography/hypothesis_bank.jsonl", state_dir: str | Path = "state", max_new: int = 8, paper_ideas_path: str | Path = "bibliography/paper_ideas.jsonl") -> dict[str, Any]:
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
    ideas_seen = 0
    for idea in _all_ideas(parent, paper_ideas_path):
        ideas_seen += 1
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
        rows.append({"hypothesis_id": hypothesis_id, "family": idea.family, "claim": idea.claim, "causal_mechanism": idea.mechanism, "bibliography_basis": [{"source_id": idea.source_id, "title": idea.paper_title}], "empirical_basis": [{"run_id": parent_run_id, "hypothesis_id": parent_hypothesis_id, "reason": "Generated by literature_hypothesis_miner after local factory exhaustion."}], "features_required": list(idea.required_features), "status": "candidate", "required_spy_comparison": "monthly_and_yearly", "axis": idea.family, "falsification_rule": idea.falsification_rule, "strategy_overrides": overrides})
        ids.add(hypothesis_id)
        sigs.add(sig)
    if rows:
        append_jsonl(hypothesis_bank_path, rows)
    if missing_tasks:
        append_jsonl(Path(state_dir) / "missing_feature_tasks.jsonl", missing_tasks)
    return {"generated": len(rows), "reason": "literature_hypotheses_generated" if rows else "no_supported_literature_hypotheses", "hypotheses": [row["hypothesis_id"] for row in rows], "missing_feature_tasks": len(missing_tasks), "available_feature_count": len(features), "skipped_existing": skipped_existing, "ideas_seen": ideas_seen, "paper_ideas_path": str(paper_ideas_path), "parent_run_id": parent_run_id}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--parent-strategy-config", required=True)
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--max-new", type=int, default=8)
    p.add_argument("--paper-ideas", default="bibliography/paper_ideas.jsonl")
    args = p.parse_args()
    print(json.dumps(mine_literature_hypotheses(parent_strategy_config_path=args.parent_strategy_config, hypothesis_bank_path=args.hypothesis_bank, state_dir=args.state_dir, max_new=args.max_new, paper_ideas_path=args.paper_ideas), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
