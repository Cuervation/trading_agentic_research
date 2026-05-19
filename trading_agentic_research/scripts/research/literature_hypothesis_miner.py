"""Literature-to-hypothesis fallback v4.

This module converts curated paper templates and bibliography/paper_ideas.jsonl
into auditable hypothesis cards.

v4 goals:
- stay parent-lock safe: append hypotheses only; never promote or move parent;
- be cooldown-aware: avoid generating hypotheses in families already cooled down;
- use papers as a research engine, not only as a variant generator;
- create missing-feature tasks when a paper requires unavailable features;
- prioritize ideas that can open *new* research subspaces while avoiding duplicate
  override signatures.

Compatible public API:
    available_weekly_features(state_dir)
    mine_literature_hypotheses(...)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


def cooldowned_families(state_dir: str | Path = "state") -> set[str]:
    payload = read_json(Path(state_dir) / "subspace_cooldowns.json", {}) or {}
    cooldowns = payload.get("cooldowns", {}) if isinstance(payload, dict) else {}
    return {str(k) for k in cooldowns.keys()}


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
    axis: str | None = None
    priority: int = 100


def _condition(field: str, operator: str, value: float) -> dict[str, Any]:
    return {"field": field, "operator": operator, "value": value, "enabled_if_field_exists": True}


def _rank_override(field: str, *, order: str = "desc", required: list[str] | None = None) -> dict[str, Any]:
    required_fields = required or [field, "close"]
    return {"ranking": {"field": field, "order": order}, "risk_filters": {"require_non_null_fields": required_fields}}


def _rank_confirm_override(
    rank_field: str,
    confirm_field: str,
    *,
    operator: str = ">",
    value: float = 0.0,
    order: str = "desc",
) -> dict[str, Any]:
    return {
        "ranking": {"field": rank_field, "order": order},
        "risk_filters": {
            "require_non_null_fields": [rank_field, confirm_field, "close"],
            "conditions": [_condition(confirm_field, operator, value)],
        },
    }


def _market_override(*, require_positive_trend: bool, fallback_allow: bool | None = None, threshold: float | None = None) -> dict[str, Any]:
    cfg: dict[str, Any] = {"benchmark": "SPY", "require_positive_trend": bool(require_positive_trend)}
    if fallback_allow is not None:
        cfg["fallback_allow_if_missing_spy_metric"] = bool(fallback_allow)
    if threshold is not None:
        cfg["condition_any"] = [{"field": "spy_close_vs_sma50_pct", "operator": ">", "value": float(threshold), "enabled_if_field_exists": True}]
    return {"market_filter": cfg}


def _idea(
    suffix: str,
    family: str,
    source_id: str,
    title: str,
    claim: str,
    mechanism: str,
    required_features: tuple[str, ...],
    overrides: dict[str, Any],
    falsification_rule: str,
    axis: str | None = None,
    priority: int = 100,
) -> PaperIdea:
    return PaperIdea(
        suffix=suffix,
        family=family,
        source_id=source_id,
        paper_title=title,
        claim=claim,
        mechanism=mechanism,
        required_features=required_features,
        overrides=overrides,
        falsification_rule=falsification_rule,
        axis=axis or family,
        priority=priority,
    )


def built_in_literature_templates(parent: dict[str, Any]) -> list[PaperIdea]:
    """Return expanded deterministic paper-inspired hypothesis variants."""
    return [
        _idea(
            "TSMOM_RET52_RANK_V4",
            "paper_time_series_momentum",
            "moskowitz_ooi_pedersen_time_series_momentum",
            "Time Series Momentum",
            "Ranking by 52-week return retests canonical intermediate-horizon momentum.",
            "Trend persistence across intermediate horizons may continue in equities, but must beat the current champion after costs.",
            ("ret_52w_pct", "close"),
            _rank_override("ret_52w_pct"),
            "Reject if it fails to improve CAGR/drawdown or duplicates historical artifacts versus the champion.",
            "paper_tsmom_rank",
            40,
        ),
        _idea(
            "TSMOM_RET52_RET13_CONFIRM_V4",
            "paper_time_series_momentum",
            "multi_lookback_momentum_confirmation",
            "Multi-lookback momentum confirmation",
            "52-week momentum confirmed by positive 13-week return may avoid stale long-lookback winners.",
            "Short-term confirmation can filter momentum names that are already deteriorating.",
            ("ret_52w_pct", "ret_13w_pct", "close"),
            _rank_confirm_override("ret_52w_pct", "ret_13w_pct", value=0.0),
            "Reject if confirmation reduces CAGR without improving drawdown or yearly SPY comparison.",
            "paper_tsmom_confirm",
            35,
        ),
        _idea(
            "TSMOM_RET26_SMA20_CONFIRM_V4",
            "paper_time_series_momentum",
            "multi_lookback_momentum_confirmation",
            "Intermediate momentum with fast confirmation",
            "26-week momentum confirmed by positive 20-week SMA distance may reduce weak trend exposure.",
            "Combining an intermediate lookback with a fast trend gate may improve stability.",
            ("ret_26w_pct", "close_vs_sma20w_pct", "close"),
            _rank_confirm_override("ret_26w_pct", "close_vs_sma20w_pct", value=0.0),
            "Reject if turnover/whipsaw reduces CAGR and drawdown does not improve.",
            "paper_tsmom_confirm",
            30,
        ),
        _idea(
            "QUALITY_R2_CHANNEL_SLOPE_CONFIRM_V4",
            "paper_quality_momentum",
            "quality_momentum_trend_stability",
            "Quality momentum with positive slope",
            "Ranking by channel_r2 while requiring positive channel_slope_pct may combine quality and direction.",
            "A clean but flat/negative trend is less useful than a clean positive trend.",
            ("channel_r2", "channel_slope_pct", "close"),
            _rank_confirm_override("channel_r2", "channel_slope_pct", value=0.0),
            "Reject if the slope confirmation does not improve drawdown-adjusted SPY-relative robustness.",
            "paper_quality_confirm",
            32,
        ),
        _idea(
            "QUALITY_SLOPE_R2_CONFIRM_V4",
            "paper_quality_momentum",
            "quality_momentum_trend_stability",
            "Trend slope with quality confirmation",
            "Ranking by channel_slope_pct while requiring channel_r2 >= 0.35 may avoid noisy slopes.",
            "A strong fitted slope is more credible when trend fit quality is acceptable.",
            ("channel_slope_pct", "channel_r2", "close"),
            _rank_confirm_override("channel_slope_pct", "channel_r2", operator=">=", value=0.35),
            "Reject if the quality confirmation does not reduce fragile momentum exposure.",
            "paper_quality_confirm",
            32,
        ),
        _idea(
            "FAST_TREND_SMA20_RET13_CONFIRM_V4",
            "paper_trend_following",
            "trend_following_fast_slow_confirmation",
            "Fast trend with near-term momentum confirmation",
            "SMA20 distance with positive 13-week return may reduce weak fast-trend artifacts.",
            "Fast trend strength is more reliable when short-term return is also positive.",
            ("close_vs_sma20w_pct", "ret_13w_pct", "close"),
            _rank_confirm_override("close_vs_sma20w_pct", "ret_13w_pct", value=0.0),
            "Reject if it reduces CAGR without improving drawdown or SPY comparison.",
            "paper_trend_fast_confirm",
            36,
        ),
        _idea(
            "REGIME_SPY_STRICT_NO_FALLBACK_V4",
            "paper_regime_filter",
            "faber_tactical_asset_allocation",
            "Tactical asset allocation / regime filter",
            "A strict SPY SMA50 gate without fallback tests whether current NaN fallback is masking regime behavior.",
            "Market trend filters reduce crash exposure, but fallback behavior can make a regime gate ineffective.",
            ("spy_close_vs_sma50_pct", "close"),
            _market_override(require_positive_trend=True, fallback_allow=False),
            "Reject if strict SPY gate reduces CAGR without a meaningful drawdown improvement.",
            "paper_regime_strict",
            90,
        ),
        _idea(
            "REGIME_DISABLED_MEASURE_OVERFILTER_V4",
            "paper_regime_filter",
            "faber_tactical_asset_allocation",
            "Market regime ablation",
            "Disabling positive SPY trend requirement tests whether the parent is over-filtering entries.",
            "Ablation can identify whether the regime rule adds value or simply removes profitable recoveries.",
            ("close",),
            _market_override(require_positive_trend=False),
            "Reject if drawdown worsens materially or yearly SPY-relative robustness deteriorates.",
            "paper_regime_ablation",
            95,
        ),
        _idea(
            "VOL_FILTER_ATR14_RET52_V4",
            "paper_low_vol_momentum",
            "low_volatility_anomaly_bab",
            "Low volatility anomaly / Betting Against Beta",
            "Momentum filtered for available volatility proxy may improve drawdown profile.",
            "High volatility momentum can carry crash risk; requiring ATR availability enables volatility-aware refinement.",
            ("atr_14w_pct", "ret_52w_pct", "close"),
            _rank_override("ret_52w_pct", required=["atr_14w_pct", "ret_52w_pct", "close"]),
            "Reject if drawdown does not improve or CAGR falls more than the defensive threshold.",
            "paper_low_volatility",
            55,
        ),
        _idea(
            "VOL_MANAGED_RET26_REALIZED_VOL13_V4",
            "paper_low_vol_momentum",
            "volatility_managed_portfolios",
            "Volatility managed portfolios",
            "26-week momentum with realized-volatility availability may support volatility-managed follow-up experiments.",
            "Volatility scaling/filters can reduce crash risk in momentum strategies.",
            ("realized_vol_13w_pct", "ret_26w_pct", "close"),
            _rank_override("ret_26w_pct", required=["realized_vol_13w_pct", "ret_26w_pct", "close"]),
            "Reject if volatility-aware variant does not improve drawdown or stability.",
            "paper_low_volatility",
            20,
        ),
        _idea(
            "RESIDUAL_MOMENTUM_RET26_V4",
            "paper_residual_momentum",
            "idiosyncratic_momentum_residual_returns",
            "Residual / idiosyncratic momentum",
            "Ranking by residual_ret_26w_pct may isolate stock-specific momentum after broad/sector effects.",
            "Residual momentum can reduce hidden exposure to market or sector moves.",
            ("residual_ret_26w_pct", "close"),
            _rank_override("residual_ret_26w_pct"),
            "Reject if residual momentum does not improve yearly SPY comparison or duplicates prior artifacts.",
            "paper_residual_momentum",
            15,
        ),
        _idea(
            "SECTOR_REL_STRENGTH_RET26_V4",
            "paper_sector_momentum",
            "sector_industry_relative_momentum",
            "Sector and industry relative strength",
            "Ranking by ret_vs_sector_26w_pct may favor stocks outperforming their own sector.",
            "Sector-relative momentum can separate true stock leadership from sector beta.",
            ("ret_vs_sector_26w_pct", "close"),
            _rank_override("ret_vs_sector_26w_pct"),
            "Reject if sector-relative ranking fails to improve robustness or is too sparse.",
            "paper_sector_relative_strength",
            15,
        ),
        _idea(
            "DRAWDOWN_AWARE_RET52_MAXDD26_V4",
            "paper_downside_risk_momentum",
            "drawdown_aware_momentum",
            "Drawdown-aware momentum",
            "52-week momentum requiring max_drawdown_26w_pct availability opens a drawdown-control research axis.",
            "Recent severe drawdowns can indicate fragile momentum despite high trailing return.",
            ("max_drawdown_26w_pct", "ret_52w_pct", "close"),
            _rank_override("ret_52w_pct", required=["max_drawdown_26w_pct", "ret_52w_pct", "close"]),
            "Reject if drawdown-aware variant does not reduce downside or harms SPY-relative CAGR too much.",
            "paper_downside_risk_momentum",
            18,
        ),
        _idea(
            "BREADTH_REGIME_RET52_V4",
            "paper_breadth_regime",
            "market_breadth_momentum_regime",
            "Market breadth as momentum regime filter",
            "52-week momentum with market-breadth availability opens a breadth-aware regime axis.",
            "Broad participation can distinguish healthy trends from narrow leadership.",
            ("market_breadth_above_sma50_pct", "ret_52w_pct", "close"),
            _rank_override("ret_52w_pct", required=["market_breadth_above_sma50_pct", "ret_52w_pct", "close"]),
            "Reject if breadth-aware variant does not improve drawdown/yearly SPY comparison.",
            "paper_breadth_regime",
            18,
        ),
    ]


def _slug(text: str, max_len: int = 44) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", text.upper()).strip("_")
    return (text or "PAPER_IDEA")[:max_len]


def _variants_from_external_paper(row: dict[str, Any], idx: int) -> list[PaperIdea]:
    if row.get("mode") == "online_search_error":
        return []
    title = str(row.get("title") or row.get("query") or f"paper idea {idx}")
    source_id = str(row.get("source_id") or f"paper_idea_{idx}")
    claim = str(row.get("claim_seed") or row.get("abstract") or title)
    families = [str(x) for x in row.get("families", [])] or []
    text = " ".join([title, claim, str(row.get("query") or row.get("query_seed") or ""), " ".join(families)]).lower()
    stem = _slug(title, 32)

    if "residual" in text or "idiosyncratic" in text:
        return [_idea(
            f"PAPER_{stem}_RESIDUAL_RET26_V4",
            "paper_residual_momentum",
            source_id,
            title,
            claim,
            "Paper idea suggests residual returns may isolate stock-specific momentum.",
            ("residual_ret_26w_pct", "close"),
            _rank_override("residual_ret_26w_pct"),
            "Reject if residual momentum fails to improve robustness or is unavailable.",
            "paper_residual_momentum",
            15,
        )]

    if "sector" in text or "industry" in text:
        return [_idea(
            f"PAPER_{stem}_SECTOR_REL_RET26_V4",
            "paper_sector_momentum",
            source_id,
            title,
            claim,
            "Paper idea suggests sector-relative leadership may be more robust than raw momentum.",
            ("ret_vs_sector_26w_pct", "close"),
            _rank_override("ret_vs_sector_26w_pct"),
            "Reject if sector-relative momentum fails to improve SPY-relative robustness.",
            "paper_sector_relative_strength",
            15,
        )]

    if "breadth" in text:
        return [_idea(
            f"PAPER_{stem}_BREADTH_REGIME_V4",
            "paper_breadth_regime",
            source_id,
            title,
            claim,
            "Paper idea suggests market breadth may be useful for regime confirmation.",
            ("market_breadth_above_sma50_pct", "ret_52w_pct", "close"),
            _rank_override("ret_52w_pct", required=["market_breadth_above_sma50_pct", "ret_52w_pct", "close"]),
            "Reject if breadth-aware momentum fails to improve drawdown or yearly SPY comparison.",
            "paper_breadth_regime",
            18,
        )]

    if "quality" in text or "stability" in text or "channel" in text:
        return [
            _idea(
                f"PAPER_{stem}_QUALITY_R2_RANK_V4",
                "paper_quality_momentum",
                source_id,
                title,
                claim,
                "Paper idea suggests improving raw momentum with trend quality/stability confirmation.",
                ("channel_r2", "close"),
                _rank_override("channel_r2"),
                "Reject if trend-quality ranking does not improve drawdown-adjusted SPY-relative robustness.",
                "paper_quality_rank",
                40,
            ),
            _idea(
                f"PAPER_{stem}_QUALITY_R2_SLOPE_CONFIRM_V4",
                "paper_quality_momentum",
                source_id,
                title,
                claim,
                "Paper idea suggests trend quality should be paired with positive trend direction.",
                ("channel_r2", "channel_slope_pct", "close"),
                _rank_confirm_override("channel_r2", "channel_slope_pct", value=0.0),
                "Reject if confirmation fails to improve stability versus the champion.",
                "paper_quality_confirm",
                35,
            ),
        ]

    if "vol" in text or "beta" in text or "drawdown" in text or "crash" in text:
        return [
            _idea(
                f"PAPER_{stem}_VOL_ATR14_RET52_V4",
                "paper_low_vol_momentum",
                source_id,
                title,
                claim,
                "Paper idea suggests volatility-aware momentum may reduce crash/drawdown risk.",
                ("atr_14w_pct", "ret_52w_pct", "close"),
                _rank_override("ret_52w_pct", required=["atr_14w_pct", "ret_52w_pct", "close"]),
                "Reject if volatility-aware filter fails to improve drawdown or materially reduces CAGR.",
                "paper_low_volatility",
                45,
            ),
            _idea(
                f"PAPER_{stem}_DOWNSIDE_VOL13_RET26_V4",
                "paper_downside_risk_momentum",
                source_id,
                title,
                claim,
                "Paper idea suggests downside-risk filters may reduce fragile momentum.",
                ("downside_vol_13w_pct", "ret_26w_pct", "close"),
                _rank_override("ret_26w_pct", required=["downside_vol_13w_pct", "ret_26w_pct", "close"]),
                "Reject if downside-risk variant does not improve drawdown or stability.",
                "paper_downside_risk_momentum",
                18,
            ),
        ]

    if "regime" in text or "tactical" in text or "asset allocation" in text or "sma" in text:
        return [
            _idea(
                f"PAPER_{stem}_REGIME_STRICT_V4",
                "paper_regime_filter",
                source_id,
                title,
                claim,
                "Paper idea suggests regime filters can reduce market-direction risk.",
                ("spy_close_vs_sma50_pct", "close"),
                _market_override(require_positive_trend=True, fallback_allow=False),
                "Reject if strict regime gate worsens CAGR without improving drawdown.",
                "paper_regime_strict",
                90,
            ),
            _idea(
                f"PAPER_{stem}_REGIME_RELAXED_V4",
                "paper_regime_filter",
                source_id,
                title,
                claim,
                "Paper idea suggests regime filters may be useful but over-strict gates can miss recoveries.",
                ("spy_close_vs_sma50_pct", "close"),
                _market_override(require_positive_trend=False, threshold=-2.5),
                "Reject if relaxed regime gate worsens drawdown/yearly SPY comparison.",
                "paper_regime_relaxed",
                90,
            ),
        ]

    return [
        _idea(
            f"PAPER_{stem}_RET52_RANK_V4",
            "paper_time_series_momentum",
            source_id,
            title,
            claim,
            "Paper idea suggests intermediate-horizon trend persistence may improve selection.",
            ("ret_52w_pct", "close"),
            _rank_override("ret_52w_pct"),
            "Reject if paper-derived 52w momentum idea fails to beat champion or duplicates historical artifacts.",
            "paper_tsmom_rank",
            40,
        ),
        _idea(
            f"PAPER_{stem}_RET52_RET13_CONFIRM_V4",
            "paper_time_series_momentum",
            source_id,
            title,
            claim,
            "Paper idea suggests trend persistence may improve when confirmed by shorter-term momentum.",
            ("ret_52w_pct", "ret_13w_pct", "close"),
            _rank_confirm_override("ret_52w_pct", "ret_13w_pct", value=0.0),
            "Reject if confirmation fails to improve robustness versus the champion.",
            "paper_tsmom_confirm",
            35,
        ),
    ]


def ideas_from_paper_ideas(path: str | Path = "bibliography/paper_ideas.jsonl") -> list[PaperIdea]:
    rows = read_jsonl(path)
    ideas: list[PaperIdea] = []
    for idx, row in enumerate(rows, start=1):
        ideas.extend(_variants_from_external_paper(row, idx))
    return ideas


def _supported(idea: PaperIdea, features: set[str]) -> bool:
    return bool(features) and set(idea.required_features).issubset(features)


def _missing_task(parent_run_id: str, parent_hypothesis_id: str | None, idea: PaperIdea, features: set[str]) -> dict[str, Any]:
    missing = sorted(set(idea.required_features).difference(features))
    suggested = []
    for feature in missing:
        if feature == "atr_14w_pct":
            suggested.append({
                "feature": feature,
                "suggested_implementation": "rolling 14-week average true range percentage using weekly high/low/close or daily OHLC resampled to weekly",
                "priority": "high",
            })
        elif feature == "realized_vol_13w_pct":
            suggested.append({
                "feature": feature,
                "suggested_implementation": "rolling 13-week standard deviation of weekly returns",
                "priority": "high",
            })
        elif feature == "downside_vol_13w_pct":
            suggested.append({
                "feature": feature,
                "suggested_implementation": "rolling 13-week standard deviation of negative weekly returns only",
                "priority": "high",
            })
        elif feature == "max_drawdown_26w_pct":
            suggested.append({
                "feature": feature,
                "suggested_implementation": "rolling 26-week maximum drawdown percentage from weekly closes",
                "priority": "high",
            })
        elif feature == "residual_ret_26w_pct":
            suggested.append({
                "feature": feature,
                "suggested_implementation": "26-week return residualized against SPY and/or sector return using rolling regression or simple subtraction baseline",
                "priority": "medium",
            })
        elif feature in {"sector_ret_26w_pct", "ret_vs_sector_26w_pct"}:
            suggested.append({
                "feature": feature,
                "suggested_implementation": "add sector metadata and compute sector 26-week return plus stock minus sector relative return",
                "priority": "medium",
            })
        elif feature == "market_breadth_above_sma50_pct":
            suggested.append({
                "feature": feature,
                "suggested_implementation": "weekly percentage of universe constituents trading above 50-day/10-week SMA",
                "priority": "medium",
            })
        else:
            suggested.append({
                "feature": feature,
                "suggested_implementation": "add to feature store if source data supports it",
                "priority": "medium",
            })
    return {
        "created_at": now_iso(),
        "parent_run_id": parent_run_id,
        "parent_hypothesis_id": parent_hypothesis_id,
        "source_id": idea.source_id,
        "paper_title": idea.paper_title,
        "candidate_suffix": idea.suffix,
        "family": idea.family,
        "axis": idea.axis,
        "reason": "missing_required_features_for_literature_hypothesis",
        "missing_features": missing,
        "suggested_feature_tasks": suggested,
        "claim": idea.claim,
        "next_action": "add_features_to_feature_store_or_skip_this_paper_axis",
    }


def _missing_task_key(task: dict[str, Any]) -> str:
    return "|".join([
        str(task.get("parent_run_id") or ""),
        str(task.get("parent_hypothesis_id") or ""),
        str(task.get("source_id") or ""),
        str(task.get("candidate_suffix") or ""),
        ",".join(sorted(str(x) for x in task.get("missing_features", []) or [])),
    ])


def append_missing_tasks_dedup(path: str | Path, tasks: list[dict[str, Any]]) -> int:
    if not tasks:
        return 0
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = read_jsonl(p)
    keys = {_missing_task_key(row) for row in existing}
    written = 0
    with p.open("a", encoding="utf-8") as f:
        for task in tasks:
            key = _missing_task_key(task)
            if key in keys:
                continue
            keys.add(key)
            f.write(json.dumps(task, ensure_ascii=False, separators=(",", ":")) + "\n")
            written += 1
    return written


def _all_ideas(parent: dict[str, Any], paper_ideas_path: str | Path) -> list[PaperIdea]:
    ideas = [*ideas_from_paper_ideas(paper_ideas_path), *built_in_literature_templates(parent)]
    seen: set[tuple[str, str]] = set()
    out: list[PaperIdea] = []
    for idea in ideas:
        key = (idea.source_id, idea.suffix)
        if key in seen:
            continue
        seen.add(key)
        out.append(idea)
    out.sort(key=lambda x: x.priority)
    return out


def mine_literature_hypotheses(
    *,
    parent_strategy_config_path: str | Path,
    hypothesis_bank_path: str | Path = "bibliography/hypothesis_bank.jsonl",
    state_dir: str | Path = "state",
    max_new: int = 8,
    paper_ideas_path: str | Path = "bibliography/paper_ideas.jsonl",
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
    cooldowns = cooldowned_families(state_dir)

    rows: list[dict[str, Any]] = []
    missing_tasks: list[dict[str, Any]] = []
    skipped_existing = 0
    skipped_duplicate_signature = 0
    skipped_family_cooldown = 0
    ideas_seen = 0
    supported_seen = 0
    missing_seen = 0

    for idea in _all_ideas(parent, paper_ideas_path):
        ideas_seen += 1
        if len(rows) >= max_new:
            break

        if idea.family in cooldowns:
            skipped_family_cooldown += 1
            # Still record missing feature tasks for new feature discovery if the
            # feature axis is unavailable; this keeps papers useful even when a
            # family is temporarily cooled down.
            if not _supported(idea, features):
                missing_tasks.append(_missing_task(str(parent_run_id), parent_hypothesis_id, idea, features))
                missing_seen += 1
            continue

        hypothesis_id = f"HYP_LIT_{parent_run_id}_{idea.suffix}"
        if hypothesis_id in ids:
            skipped_existing += 1
            continue

        if not _supported(idea, features):
            missing_tasks.append(_missing_task(str(parent_run_id), parent_hypothesis_id, idea, features))
            missing_seen += 1
            continue

        supported_seen += 1
        overrides = json.loads(json.dumps(idea.overrides, ensure_ascii=False))
        overrides["strategy_id"] = hypothesis_id
        overrides.setdefault("strategy_family", idea.family)
        overrides.setdefault("changed_parameters", sorted(overrides.keys()))
        overrides.setdefault("expected_effect", "Paper-derived causal variant to improve SPY-relative robustness.")
        overrides.setdefault("autonomy_reason", "literature_hypothesis_miner_v4")

        sig = real_override_signature(overrides)
        if sig in sigs:
            skipped_duplicate_signature += 1
            continue

        rows.append(
            {
                "hypothesis_id": hypothesis_id,
                "family": idea.family,
                "claim": idea.claim,
                "causal_mechanism": idea.mechanism,
                "bibliography_basis": [{"source_id": idea.source_id, "title": idea.paper_title}],
                "empirical_basis": [
                    {
                        "run_id": parent_run_id,
                        "hypothesis_id": parent_hypothesis_id,
                        "reason": "Generated by literature_hypothesis_miner v4 after local/feature-space exhaustion or paper fallback.",
                    }
                ],
                "features_required": list(idea.required_features),
                "status": "candidate",
                "required_spy_comparison": "monthly_and_yearly",
                "axis": idea.axis or idea.family,
                "falsification_rule": idea.falsification_rule,
                "strategy_overrides": overrides,
            }
        )
        ids.add(hypothesis_id)
        sigs.add(sig)

    if rows:
        append_jsonl(hypothesis_bank_path, rows)
    missing_written = append_missing_tasks_dedup(Path(state_dir) / "missing_feature_tasks.jsonl", missing_tasks)

    return {
        "generated": len(rows),
        "reason": "literature_hypotheses_generated" if rows else "no_supported_literature_hypotheses",
        "hypotheses": [row["hypothesis_id"] for row in rows],
        "missing_feature_tasks": missing_written,
        "missing_feature_tasks_seen": len(missing_tasks),
        "missing_feature_axes_seen": missing_seen,
        "available_feature_count": len(features),
        "cooldowned_families": sorted(cooldowns),
        "skipped_existing": skipped_existing,
        "skipped_duplicate_signature": skipped_duplicate_signature,
        "skipped_family_cooldown": skipped_family_cooldown,
        "ideas_seen": ideas_seen,
        "supported_seen": supported_seen,
        "paper_ideas_path": str(paper_ideas_path),
        "parent_run_id": parent_run_id,
        "version": "v4",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--parent-strategy-config", required=True)
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--max-new", type=int, default=8)
    p.add_argument("--paper-ideas", default="bibliography/paper_ideas.jsonl")
    args = p.parse_args()
    print(
        json.dumps(
            mine_literature_hypotheses(
                parent_strategy_config_path=args.parent_strategy_config,
                hypothesis_bank_path=args.hypothesis_bank,
                state_dir=args.state_dir,
                max_new=args.max_new,
                paper_ideas_path=args.paper_ideas,
            ),
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
