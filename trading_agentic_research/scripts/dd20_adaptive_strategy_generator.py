"""Adaptive DD20 frontier memory and strategy generation.

The generator is deterministic on purpose: it reads the current empirical
frontier, classifies the dominant constraint failure, then emits the next small
causal batch without hand-authored batch scripts.
"""

from __future__ import annotations

import csv
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd

from backtester.dd20_spy_beater import DD20_MIN_TRADES, row_from_dd20_audit_or_run

ROOT = Path(__file__).resolve().parents[1]
BASE_NEAR_VALID_SL10 = "HYP_DD20_STOP_DYN8050200_GUARD1810_SL10_V1"
BASE_DD20_CHAMPION = "HYP_DD20_EXP_SL11_TOPN8_WHEN_GUARD_V1"
BASE_NEAR_VALID_SL10_CONFIG = ROOT / "configs/generated/HYP_DD20_EXP_SL11_TOPN8_WHEN_GUARD_V1.json"
FALLBACK_BASE_CONFIG = ROOT / "configs/generated/HYP_DD20_STOP_DYN8050200_GUARD1810_SL10_V1.json"
FAMILY = "dd20_adaptive_research"
DD20_AXIS_ORDER = [
    "cagr_repair_under_dd20",
    "dd_rescue_for_high_cagr",
    "annual_consistency_repair",
    "controlled_combo",
    "trade_count_repair_around_sl10",
]
CURRENT_DD20_CHAMPION_ROW = {
    "run_id": "DD20ADAPT_005_HYP_DD20_EXP_SL11_TOPN8_WHEN_GUARD_V1",
    "strategy_id": BASE_DD20_CHAMPION,
    "cagr": 10.5412,
    "spy_cagr": 6.802475,
    "max_drawdown": -19.6588,
    "trades": 2354,
    "years_beating_spy": 16,
    "years_losing_to_spy": 12,
    "calmar": 0.536,
    "frontier_class": "valid_candidate",
}
DEFAULT_AXIS_MEMORY = {
    "cooldown_axes": [],
    "exhausted_axes": [],
    "axis_outcomes": {},
}


def build_frontier_memory(
    *,
    reports_dir: str | Path = "reports",
    runs_dir: str | Path = "runs",
    state_dir: str | Path = "state",
    parent_run_id: str = "",
    min_trades: int = DD20_MIN_TRADES,
) -> dict[str, Any]:
    """Read reports/runs and persist the current DD20 empirical frontier."""
    reports_path = Path(reports_dir)
    runs_path = Path(runs_dir)
    parent_run_dir = runs_path / parent_run_id if parent_run_id else None
    rows = _dedupe_latest_rows(
        _read_report_rows(reports_path / "dd20_spy_beater_summary.csv")
        + _read_report_rows(reports_path / "dd20_spy_consistency_repair_summary.csv")
        + _read_report_rows(reports_path / "dd20_stop_trailing_repair_summary.csv")
        + _read_run_rows(runs_path, parent_run_dir, min_trades)
    )
    for row in rows:
        row["frontier_class"] = classify_row(row, min_trades=min_trades)
        row["constraint_gap_score"] = constraint_gap_score(row, min_trades=min_trades)
        row["config_hash"] = _config_hash_for_strategy(str(row.get("strategy_id") or ""))

    classes = {
        name: [r for r in rows if r["frontier_class"] == name]
        for name in [
            "valid_candidate",
            "near_valid_low_trades",
            "near_valid_bad_years",
            "high_cagr_dd_breach",
            "dd20_low_cagr",
            "rejected",
        ]
    }
    axis_memory = _read_json(Path(state_dir) / "dd20_axis_memory.json", DEFAULT_AXIS_MEMORY)
    best_near = _best_near(rows)
    memory = {
        "rows_scanned": len(rows),
        "class_counts": {k: len(v) for k, v in classes.items()},
        "valid_candidate": _sort_valid(classes["valid_candidate"])[:25],
        "near_valid_low_trades": _sort_near(classes["near_valid_low_trades"])[:25],
        "near_valid_bad_years": _sort_near(classes["near_valid_bad_years"])[:25],
        "high_cagr_dd_breach": _sort_high_cagr(classes["high_cagr_dd_breach"])[:25],
        "dd20_low_cagr": _sort_near(classes["dd20_low_cagr"])[:25],
        "best_valid_by_cagr": _first(_sort_valid(classes["valid_candidate"])),
        "best_valid_by_drawdown": _first(sorted(classes["valid_candidate"], key=lambda r: (-_f(r, "max_drawdown"), -_f(r, "cagr")))),
        "best_valid_by_calmar": _first(sorted(classes["valid_candidate"], key=lambda r: (-_f(r, "calmar"), -_f(r, "cagr")))),
        "best_near_valid": best_near,
        "best_near_valid_low_trades": _first(_sort_near(classes["near_valid_low_trades"])),
        "best_high_cagr_dd_breach": _first(_sort_high_cagr(classes["high_cagr_dd_breach"])),
        "best_trade_count_under_dd20": _first(sorted([r for r in rows if _f(r, "max_drawdown") >= -20], key=lambda r: (-_i(r, "trades"), -_f(r, "cagr")))),
        "best_years_wl_under_dd20": _first(sorted([r for r in rows if _f(r, "max_drawdown") >= -20], key=lambda r: (-(_i(r, "years_beating_spy") - _i(r, "years_losing_to_spy")), -_f(r, "cagr")))),
        "active_axes": axis_memory.get("active_axes", []),
        "cooldown_axes": axis_memory.get("cooldown_axes", []),
        "exhausted_axes": axis_memory.get("exhausted_axes", []),
        "next_axis_recommendation": "",
        "last_generation_reason": "",
        "all_rows": rows,
    }
    axis, reason = choose_next_axis(memory, axis_memory)
    memory["next_axis_recommendation"] = axis
    memory["last_generation_reason"] = reason
    out = Path(state_dir) / "dd20_frontier_memory.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    compact_memory = dict(memory)
    compact_memory.pop("all_rows", None)
    compact_memory["all_rows_count"] = len(rows)
    compact_memory["strategy_ids"] = sorted({str(r.get("strategy_id")) for r in rows if r.get("strategy_id")})
    out.write_text(json.dumps(compact_memory, indent=2, sort_keys=True), encoding="utf-8")
    return memory


def classify_row(row: dict[str, Any], *, min_trades: int = DD20_MIN_TRADES) -> str:
    dd = _f(row, "max_drawdown")
    cagr = _f(row, "cagr")
    spy = _f(row, "spy_cagr")
    trades = _i(row, "trades")
    years_ok = _i(row, "years_beating_spy") >= _i(row, "years_losing_to_spy")
    dd_ok = dd >= -20.0
    cagr_ok = cagr > spy
    trades_ok = trades >= min_trades
    if dd_ok and cagr_ok and trades_ok and years_ok:
        return "valid_candidate"
    if dd_ok and cagr_ok and years_ok and not trades_ok:
        return "near_valid_low_trades"
    if dd_ok and cagr_ok and trades_ok and not years_ok:
        return "near_valid_bad_years"
    if (not dd_ok) and cagr_ok and years_ok:
        return "high_cagr_dd_breach"
    if dd_ok and trades_ok and not cagr_ok:
        return "dd20_low_cagr"
    return "rejected"


def choose_next_axis(frontier_memory: dict[str, Any], axis_memory: dict[str, Any] | None = None) -> tuple[str, str]:
    axis_memory = axis_memory or DEFAULT_AXIS_MEMORY
    cooldown = set(axis_memory.get("cooldown_axes", [])) | set(frontier_memory.get("cooldown_axes", []))
    exhausted = set(axis_memory.get("exhausted_axes", [])) | set(frontier_memory.get("exhausted_axes", []))
    blocked = cooldown | exhausted
    near_low = frontier_memory.get("best_near_valid_low_trades")
    if near_low and _i(near_low, "trades") < DD20_MIN_TRADES and _axis_available("trade_count_repair_around_sl10", blocked):
        return "trade_count_repair_around_sl10", f"Best near-valid `{near_low.get('strategy_id')}` only lacks trades below {DD20_MIN_TRADES}."
    if frontier_memory.get("best_valid_by_cagr") and _axis_available("cagr_repair_under_dd20", blocked):
        return "cagr_repair_under_dd20", "Valid DD20 candidate exists at min_trades=1000; prioritize material CAGR repair under DD20 instead of trade-count repair."
    if frontier_memory.get("best_high_cagr_dd_breach") and _axis_available("dd_rescue_for_high_cagr", blocked):
        return "dd_rescue_for_high_cagr", "High-CAGR variants breach DD20; reduce drawdown without chasing raw CAGR."
    bad_years = frontier_memory.get("near_valid_bad_years")
    if bad_years and _axis_available("annual_consistency_repair", blocked):
        return "annual_consistency_repair", "DD20/CAGR/trades pass but yearly SPY consistency fails."
    low_cagr = frontier_memory.get("dd20_low_cagr")
    if low_cagr and _axis_available("cagr_repair_under_dd20", blocked):
        return "cagr_repair_under_dd20", "Drawdown and trades pass but CAGR fails to beat SPY."
    return "controlled_combo", "No single-axis failure dominates or preferred axis is cooling down."


def generate_next_dd20_strategies(
    frontier_memory: dict[str, Any],
    axis_memory: dict[str, Any] | None = None,
    batch_size: int = 5,
) -> list[dict[str, Any]]:
    axis_memory = axis_memory or DEFAULT_AXIS_MEMORY
    axis, _reason = choose_next_axis(frontier_memory, axis_memory)
    if axis == "trade_count_repair_around_sl10":
        specs = _trade_count_repair_around_sl10_specs() + list(axis_memory.get("expanded_specs", []))
    elif axis == "cagr_repair_under_dd20":
        specs = _cagr_repair_under_dd20_specs() + list(axis_memory.get("expanded_specs", []))
    elif axis == "dd_rescue_for_high_cagr":
        specs = _dd_rescue_for_high_cagr_specs() + list(axis_memory.get("expanded_specs", []))
    else:
        specs = _fallback_controlled_specs(axis)
    existing_ids = {str(r.get("strategy_id")) for r in frontier_memory.get("all_rows", [])}
    existing_hashes = {
        str(r.get("config_hash"))
        for r in frontier_memory.get("all_rows", [])
        if r.get("config_hash")
    }
    out: list[dict[str, Any]] = []
    seen_hashes = set(existing_hashes)
    for spec in specs:
        if spec["strategy_id"] in existing_ids:
            continue
        cfg = render_strategy_config(spec)
        h = config_hash(cfg)
        if h in seen_hashes:
            continue
        spec = dict(spec)
        spec["config_hash"] = h
        out.append(spec)
        seen_hashes.add(h)
        if len(out) >= batch_size:
            break
    return out


def expand_generation_space(frontier_memory: dict[str, Any], axis_memory: dict[str, Any] | None = None) -> dict[str, Any]:
    """Add deterministic causal templates when the current axis runs out.

    Expansion is not random. It keeps the useful SL10 + guard/top-N insight and
    tries small, interpretable changes around the current trade-count frontier.
    """
    axis_memory = deepcopy(axis_memory or DEFAULT_AXIS_MEMORY)
    cooldown = set(axis_memory.get("cooldown_axes", [])) | set(frontier_memory.get("cooldown_axes", []))
    expanded = list(axis_memory.get("expanded_specs", []))
    existing_ids = {s.get("strategy_id") for s in expanded}
    if "trailing" in cooldown:
        expanded = [s for s in expanded if "trailing_stop_pct" not in s.get("risk_management", {})]
        existing_ids = {s.get("strategy_id") for s in expanded}
    axis, _reason = choose_next_axis(frontier_memory, axis_memory)
    candidate_specs = _expanded_trade_count_specs() if axis == "trade_count_repair_around_sl10" else _expanded_cagr_repair_specs()
    for spec in candidate_specs:
        if spec["strategy_id"] in existing_ids:
            continue
        cfg = render_strategy_config(spec)
        spec = dict(spec)
        spec["config_hash"] = config_hash(cfg)
        expanded.append(spec)
        existing_ids.add(spec["strategy_id"])
    axis_memory["expanded_specs"] = expanded
    axis_memory["last_expansion"] = {
        "axis": axis,
        "reason": "Expanded deterministic DD20 templates after duplicate/no-new strategy frontier.",
        "spec_count": len(expanded),
    }
    return axis_memory


def render_strategy_config(spec: dict[str, Any], base_config_path: str | Path = BASE_NEAR_VALID_SL10_CONFIG) -> dict[str, Any]:
    base_path = Path(base_config_path)
    if not base_path.exists():
        base_path = FALLBACK_BASE_CONFIG
    cfg = _read_json(base_path, {})
    risk = deepcopy(cfg.get("risk_management", {}) or {})
    risk.update(deepcopy(spec.get("risk_management", {})))
    cfg.update(
        {
            "strategy_id": spec["strategy_id"],
            "hypothesis_id": spec["strategy_id"],
            "strategy_family": FAMILY,
            "evaluation_mode": "dd20_spy_beater",
            "generation_axis": spec["generation_axis"],
            "parent_strategy_id": spec.get("parent_strategy_id", BASE_DD20_CHAMPION),
            "parent_hypothesis_id": spec.get("parent_hypothesis_id", BASE_DD20_CHAMPION),
            "claim": spec["expected_effect"],
            "causal_mechanism": spec["causal_mechanism"],
            "expected_effect": spec["expected_effect"],
            "falsification_rule": spec["falsification_rule"],
            "changed_parameters": spec["changed_parameters"],
            "empirical_basis": spec["empirical_basis"],
            "why_not_duplicate": spec["why_not_duplicate"],
            "risk_of_overfit": spec["risk_of_overfit"],
            "risk_management": risk,
            "strategy_overrides": {
                "risk_management": risk,
                "market_filter": cfg.get("market_filter", {}),
                "ranking": cfg.get("ranking", {}),
                "risk_filters": cfg.get("risk_filters", {}),
            },
        }
    )
    return cfg


def strategy_registry_entry(spec: dict[str, Any], config_path: str | Path) -> dict[str, Any]:
    return {
        "strategy_id": spec["strategy_id"],
        "strategy_family": FAMILY,
        "status": "candidate",
        "benchmark_ticker": "SPY",
        "config_path": str(config_path).replace("\\", "/"),
        "signal_frequency": "weekly",
        "execution_frequency": "daily",
        "rebalance_frequency": "monthly",
        "parent_strategy_id": spec.get("parent_strategy_id", BASE_DD20_CHAMPION),
        "evaluation_mode": "dd20_spy_beater",
        "generation_axis": spec["generation_axis"],
        "notes": "Adaptive DD20 daemon candidate generated from empirical frontier.",
    }


def hypothesis_entry(spec: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "hypothesis_id": spec["strategy_id"],
        "family": FAMILY,
        "status": "candidate",
        "evaluation_mode": "dd20_spy_beater",
        "generation_axis": spec["generation_axis"],
        "parent_strategy_id": spec.get("parent_strategy_id", BASE_DD20_CHAMPION),
        "parent_hypothesis_id": spec.get("parent_hypothesis_id", BASE_DD20_CHAMPION),
        "causal_mechanism": spec["causal_mechanism"],
        "expected_effect": spec["expected_effect"],
        "falsification_rule": spec["falsification_rule"],
        "changed_parameters": spec["changed_parameters"],
        "empirical_basis": spec["empirical_basis"],
        "why_not_duplicate": spec["why_not_duplicate"],
        "risk_of_overfit": spec["risk_of_overfit"],
        "strategy_overrides": cfg["strategy_overrides"],
    }


def config_hash(cfg: dict[str, Any]) -> str:
    material = {
        "risk_management": cfg.get("risk_management", {}),
        "market_filter": cfg.get("market_filter", {}),
        "ranking": cfg.get("ranking", {}),
        "risk_filters": cfg.get("risk_filters", {}),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def constraint_gap_score(row: dict[str, Any], *, min_trades: int = DD20_MIN_TRADES) -> float:
    return round(
        max(0.0, -20.0 - _f(row, "max_drawdown")) * 10
        + max(0.0, _f(row, "spy_cagr") - _f(row, "cagr")) * 4
        + max(0.0, (min_trades - _i(row, "trades")) / min_trades)
        + max(0, _i(row, "years_losing_to_spy") - _i(row, "years_beating_spy")),
        6,
    )


def _trade_count_repair_around_sl10_specs() -> list[dict[str, Any]]:
    base = {
        "generation_axis": "trade_count_repair_around_sl10",
        "falsification_rule": "Reject if DD < -20, CAGR <= SPY, years W/L turns negative, or trades do not improve toward 1000.",
        "empirical_basis": [
            {
                "strategy_id": BASE_NEAR_VALID_SL10,
                "reason": "Near-valid DD20/SPY strategy with CAGR 9.675868, DD -19.325183, years 17/11, but only 2345 trades.",
            }
        ],
        "risk_of_overfit": "Medium: guard thresholds are coarse and causal; stop at SL8-SL11 range until new evidence exists.",
    }
    return [
        _spec("HYP_DD20_ADAPT_SL10_GUARD18_12_V1", {"equity_drawdown_guard": {"enabled": True, "stop_new_entries_drawdown_pct": -18, "resume_drawdown_pct": -12}, "stop_loss_pct": 10}, "Relax guard resume threshold to reopen entries earlier while SL10 still caps single-position losses.", ["risk_management.equity_drawdown_guard.resume_drawdown_pct"], base),
        _spec("HYP_DD20_ADAPT_SL10_REDUCED_20_V1", {"equity_drawdown_guard": {"enabled": True, "stop_new_entries_drawdown_pct": -18, "resume_drawdown_pct": -10, "reduced_exposure_pct_when_active": 20}, "stop_loss_pct": 10}, "Replace full guard lockout with 20% capped exposure when DD guard is active, recovering trades without removing DD control.", ["risk_management.equity_drawdown_guard.reduced_exposure_pct_when_active"], base),
        _spec("HYP_DD20_ADAPT_SL10_REDUCED_25_V1", {"equity_drawdown_guard": {"enabled": True, "stop_new_entries_drawdown_pct": -18, "resume_drawdown_pct": -10, "reduced_exposure_pct_when_active": 25}, "stop_loss_pct": 10}, "Allow slightly more guard-active exposure than 20% to test whether trade count rises while DD remains under -20.", ["risk_management.equity_drawdown_guard.reduced_exposure_pct_when_active"], base),
        _spec("HYP_DD20_ADAPT_SL10_COOLDOWN_3_V1", {"equity_drawdown_guard": {"enabled": True, "stop_new_entries_drawdown_pct": -18, "resume_drawdown_pct": -10, "cooldown_rebalances": 3, "reduced_exposure_pct_when_active": 20}, "stop_loss_pct": 10}, "Block entries only for three rebalance cycles after guard activation, then resume at reduced exposure unless DD worsens materially.", ["risk_management.equity_drawdown_guard.cooldown_rebalances", "risk_management.equity_drawdown_guard.reduced_exposure_pct_when_active"], base),
        _spec("HYP_DD20_ADAPT_SL10_TOPN5_WHEN_GUARD_V1", {"equity_drawdown_guard": {"enabled": True, "stop_new_entries_drawdown_pct": -18, "resume_drawdown_pct": -10, "allow_entries_when_active_top_n": 5}, "stop_loss_pct": 10}, "Permit only top-5 ranked new entries when the guard is active, preserving strongest momentum participation while filtering weak breadth.", ["risk_management.equity_drawdown_guard.allow_entries_when_active_top_n"], base),
    ]


def _cagr_repair_under_dd20_specs() -> list[dict[str, Any]]:
    base = {
        "generation_axis": "cagr_repair_under_dd20",
        "falsification_rule": "Reject if DD < -20, CAGR <= SPY, trades < 1000, years W/L turns negative, or CAGR/Calmar improvement is only incremental.",
        "empirical_basis": [
            {
                "strategy_id": BASE_DD20_CHAMPION,
                "reason": "Current DD20 champion: CAGR 10.5412, DD -19.6588, trades 2354, years 16/12, Calmar ~0.536.",
            },
            {
                "strategy_id": "HYP_DD20_EXP_SL9_TOPN5_WHEN_GUARD_V1",
                "reason": "Best balance: CAGR 10.1524, DD -18.5957, trades 2385, years 17/11, Calmar ~0.546.",
            },
        ],
        "risk_of_overfit": "Medium-low: only coarse SL/TOPN/guard/dynamic exposure moves; no trailing, profit-lock, rank-deterioration, or 0.1 micro-variants.",
    }
    return [
        _spec("HYP_DD20_CAGR_SL11_TOPN8_GUARD18_10_V1", _risk(top_n=8, stop_loss=11), "Re-run champion geometry as the anchor for duplicate-aware follow-up gating.", ["risk_management.stop_loss_pct", "risk_management.equity_drawdown_guard.allow_entries_when_active_top_n"], base),
        _spec("HYP_DD20_CAGR_SL11_TOPN10_GUARD18_10_V1", _risk(top_n=10, stop_loss=11), "Broaden guard-active participation from top-8 to top-10 while keeping champion SL11 risk control.", ["risk_management.equity_drawdown_guard.allow_entries_when_active_top_n"], base),
        _spec("HYP_DD20_CAGR_SL12_TOPN8_GUARD18_10_V1", _risk(top_n=8, stop_loss=12), "Relax single-position stop from SL11 to SL12 to test whether slightly longer holds improve CAGR without breaking DD20.", ["risk_management.stop_loss_pct"], base),
        _spec("HYP_DD20_CAGR_SL12_TOPN10_GUARD18_10_V1", _risk(top_n=10, stop_loss=12), "Combine SL12 with top-10 guard entries to test a coarse CAGR push under the DD20 guard.", ["risk_management.stop_loss_pct", "risk_management.equity_drawdown_guard.allow_entries_when_active_top_n"], base),
        _spec("HYP_DD20_CAGR_SL10P5_TOPN8_GUARD18_10_V1", _risk(top_n=8, stop_loss=10.5), "Test the only decimal SL midpoint requested by the research plan; reject if the runner does not support decimal stop-loss semantics.", ["risk_management.stop_loss_pct"], base),
        _spec("HYP_DD20_CAGR_SL11_TOPN8_GUARD18_12_V1", _risk(top_n=8, stop_loss=11, resume=-12), "Resume entries earlier at -12 while preserving champion SL11/top-8 structure.", ["risk_management.equity_drawdown_guard.resume_drawdown_pct"], base),
        _spec("HYP_DD20_CAGR_SL11_TOPN8_GUARD18_14_V1", _risk(top_n=8, stop_loss=11, resume=-14), "Resume entries at -14 to balance participation and drawdown recovery without changing stop loss.", ["risk_management.equity_drawdown_guard.resume_drawdown_pct"], base),
        _spec("HYP_DD20_CAGR_SL11_TOPN8_GUARD19_12_V1", _risk(top_n=8, stop_loss=11, stop=-19, resume=-12), "Delay guard activation to -19 and resume at -12 for a coarse CAGR/participation test.", ["risk_management.equity_drawdown_guard.stop_new_entries_drawdown_pct", "risk_management.equity_drawdown_guard.resume_drawdown_pct"], base),
        _spec("HYP_DD20_CAGR_SL11_TOPN8_GUARD18_14_V2", _risk(top_n=8, stop_loss=11, stop=-18, resume=-14), "Keep guard activation at -18 and resume at -14 as the defensive guard/top-N balance candidate.", ["risk_management.equity_drawdown_guard.stop_new_entries_drawdown_pct", "risk_management.equity_drawdown_guard.resume_drawdown_pct"], base),
        _spec("HYP_DD20_CAGR_DYN8055200_SL11_TOPN8_V1", _risk(top_n=8, stop_loss=11, dynamic={"strong": 80, "neutral": 55, "weak": 20, "crisis": 0}), "Controlled dynamic exposure 80/55/20/0 with champion SL11/top-8; crisis remains zero.", ["risk_management.dynamic_regime_exposure_pct"], base),
        _spec("HYP_DD20_CAGR_DYN8550200_SL11_TOPN8_V1", _risk(top_n=8, stop_loss=11, dynamic={"strong": 85, "neutral": 50, "weak": 20, "crisis": 0}), "Controlled dynamic exposure 85/50/20/0 to test strong-regime CAGR while crisis remains zero.", ["risk_management.dynamic_regime_exposure_pct"], base),
        _spec("HYP_DD20_CAGR_DYN8050250_SL11_TOPN8_V1", _risk(top_n=8, stop_loss=11, dynamic={"strong": 80, "neutral": 50, "weak": 25, "crisis": 0}), "Controlled dynamic exposure 80/50/25/0 to test weak-regime participation without crisis exposure.", ["risk_management.dynamic_regime_exposure_pct"], base),
        _spec("HYP_DD20_CAGR_DYN8055250_SL10_TOPN8_V1", _risk(top_n=8, stop_loss=10, dynamic={"strong": 80, "neutral": 55, "weak": 25, "crisis": 0}), "Controlled dynamic exposure 80/55/25/0 with tighter SL10/top-8 for CAGR repair under DD20.", ["risk_management.dynamic_regime_exposure_pct", "risk_management.stop_loss_pct"], base),
    ]


def _dd_rescue_for_high_cagr_specs() -> list[dict[str, Any]]:
    base = {
        "generation_axis": "dd_rescue_for_high_cagr",
        "falsification_rule": "Reject if DD < -20, CAGR <= SPY, trades < 1000, years W/L turns negative, or rescue is only incremental.",
        "empirical_basis": [{"strategy_id": BASE_DD20_CHAMPION, "reason": "Use champion geometry and rescue only DD20 breaches that are close to valid."}],
        "risk_of_overfit": "Medium: rescue templates are coarse exposure reductions; no trailing for now.",
    }
    return [
        _spec("HYP_DD20_RESCUE_DYN8050200_SL11_TOPN8_V1", _risk(top_n=8, stop_loss=11, dynamic={"strong": 80, "neutral": 50, "weak": 20, "crisis": 0}), "Lower weak exposure 25->20 and neutral 55->50 to rescue small DD20 breaches.", ["risk_management.dynamic_regime_exposure_pct"], base),
        _spec("HYP_DD20_RESCUE_DYN8050200_NO_NEW_CRISIS_SL11_TOPN8_V1", _risk(top_n=8, stop_loss=11, dynamic={"strong": 80, "neutral": 50, "weak": 20, "crisis": 0}, no_new_crisis=True), "Add no-new-entries in crisis while keeping crisis exposure at zero.", ["risk_management.dynamic_regime_exposure_pct", "risk_management.no_new_entries_in_crisis"], base),
    ]


def _expanded_cagr_repair_specs() -> list[dict[str, Any]]:
    base_specs = _cagr_repair_under_dd20_specs()
    extras = [
        _spec("HYP_DD20_CAGR_SL12_TOPN12_GUARD18_12_V1", _risk(top_n=12, stop_loss=12, resume=-12), "Coarse expansion: SL12/top-12 with earlier resume, still under DD20 guard.", ["risk_management.stop_loss_pct", "risk_management.equity_drawdown_guard.allow_entries_when_active_top_n", "risk_management.equity_drawdown_guard.resume_drawdown_pct"], base_specs[0]),
        _spec("HYP_DD20_CAGR_DYN8555200_SL11_TOPN10_V1", _risk(top_n=10, stop_loss=11, dynamic={"strong": 85, "neutral": 55, "weak": 20, "crisis": 0}), "Coarse dynamic expansion: 85/55/20/0 with top-10 guard participation.", ["risk_management.dynamic_regime_exposure_pct", "risk_management.equity_drawdown_guard.allow_entries_when_active_top_n"], base_specs[0]),
    ]
    return base_specs + extras


def _expanded_trade_count_specs() -> list[dict[str, Any]]:
    base = {
        "generation_axis": "trade_count_repair_around_sl10",
        "falsification_rule": "Reject if DD < -20, CAGR <= SPY, years W/L turns negative, or trades do not improve toward 1000.",
        "empirical_basis": [
            {
                "strategy_id": "HYP_DD20_ADAPT_SL10_TOPN5_WHEN_GUARD_V1",
                "reason": "Top-N while guard active raised CAGR to 10.240538 with DD -19.325183 and years 17/11, but trades remained 2388.",
            },
            {
                "strategy_id": "HYP_DD20_ADAPT_SL10_REDUCED_25_V1",
                "reason": "Reduced guard exposure reached 2405 trades and kept DD20, but reduced CAGR.",
            },
        ],
        "risk_of_overfit": "Medium: expansions are coarse causal moves around top-N guard participation; no trailing is generated while trailing is cooling down.",
    }
    out: list[dict[str, Any]] = []
    for top_n in [3, 8, 10]:
        out.append(_spec(f"HYP_DD20_EXP_SL10_TOPN{top_n}_WHEN_GUARD_V1", _risk(top_n=top_n), f"Permit only top-{top_n} ranked entries while guard is active to trade only strongest momentum names under drawdown pressure.", ["risk_management.equity_drawdown_guard.allow_entries_when_active_top_n"], base))
    for top_n in [5, 8, 10]:
        out.append(_spec(f"HYP_DD20_EXP_SL10_TOPN{top_n}_GUARD18_12_V1", _risk(top_n=top_n, resume=-12), f"Combine top-{top_n} guard-active entries with earlier resume at -12 to recover trade count without removing SL10.", ["risk_management.equity_drawdown_guard.allow_entries_when_active_top_n", "risk_management.equity_drawdown_guard.resume_drawdown_pct"], base))
    for sl, top_n in [(8, 5), (9, 5), (10, 8), (11, 8)]:
        out.append(_spec(f"HYP_DD20_EXP_SL{sl}_TOPN{top_n}_WHEN_GUARD_V1", _risk(top_n=top_n, stop_loss=sl), f"Test SL{sl} with top-{top_n} guard entries to see whether position-level loss control can free more entries while respecting DD20.", ["risk_management.stop_loss_pct", "risk_management.equity_drawdown_guard.allow_entries_when_active_top_n"], base))
    for label, exposure in [("8055200", {"strong": 80, "neutral": 55, "weak": 20, "crisis": 0}), ("8550200", {"strong": 85, "neutral": 50, "weak": 20, "crisis": 0}), ("8050250", {"strong": 80, "neutral": 50, "weak": 25, "crisis": 0})]:
        out.append(_spec(f"HYP_DD20_EXP_DYN{label}_SL10_TOPN5_V1", _risk(top_n=5, dynamic=exposure), f"Adjust dynamic exposure {exposure} with SL10 and top-5 guard entries to repair trades/CAGR without broad risk-on exposure.", ["risk_management.dynamic_regime_exposure_pct", "risk_management.equity_drawdown_guard.allow_entries_when_active_top_n"], base))
    for label, stop, resume in [("19_12", -19, -12), ("18_14", -18, -14), ("17_10", -17, -10)]:
        out.append(_spec(f"HYP_DD20_EXP_GUARD{label}_SL10_TOPN5_V1", _risk(top_n=5, stop=stop, resume=resume), f"Change guard activation/resume to {stop}/{resume} while keeping SL10 and top-5 guard entries.", ["risk_management.equity_drawdown_guard.stop_new_entries_drawdown_pct", "risk_management.equity_drawdown_guard.resume_drawdown_pct", "risk_management.equity_drawdown_guard.allow_entries_when_active_top_n"], base))
    return out


def _risk(
    *,
    top_n: int,
    stop_loss: int | float = 10,
    stop: int = -18,
    resume: int = -10,
    dynamic: dict[str, int] | None = None,
    no_new_crisis: bool = False,
) -> dict[str, Any]:
    risk = {
        "equity_drawdown_guard": {
            "enabled": True,
            "stop_new_entries_drawdown_pct": stop,
            "resume_drawdown_pct": resume,
            "allow_entries_when_active_top_n": top_n,
        },
        "stop_loss_pct": stop_loss,
    }
    if dynamic is not None:
        risk["dynamic_regime_exposure_pct"] = dynamic
    if no_new_crisis:
        risk["no_new_entries_in_crisis"] = True
    return risk


def _fallback_controlled_specs(axis: str) -> list[dict[str, Any]]:
    spec = _trade_count_repair_around_sl10_specs()[0]
    spec["generation_axis"] = axis
    return [spec]


def _spec(strategy_id: str, risk_management: dict[str, Any], causal: str, changed: list[str], base: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    out.update(
        {
            "strategy_id": strategy_id,
            "risk_management": risk_management,
            "causal_mechanism": causal,
            "expected_effect": "Maintain DD20/CAGR/SPY yearly consistency while repairing the remaining trade-count shortfall.",
            "changed_parameters": changed,
            "why_not_duplicate": f"{strategy_id} changes a distinct equity-guard behavior around the proven SL10 near-valid frontier.",
        }
    )
    return out


def _read_report_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(2048)
        fh.seek(0)
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        for row in csv.DictReader(fh, delimiter=delimiter):
            rows.append(dict(row))
    return rows


def _read_run_rows(runs_path: Path, parent_run_dir: Path | None, min_trades: int) -> list[dict[str, Any]]:
    if not runs_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for run_dir in sorted((p for p in runs_path.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime):
        if not (run_dir / "run_manifest.json").exists():
            continue
        try:
            row = row_from_dd20_audit_or_run(run_dir, parent_run_dir=parent_run_dir, min_trades=min_trades)
            if row.get("strategy_id"):
                rows.append(row)
        except Exception:
            continue
    return rows


def _dedupe_latest_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_strategy: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = str(row.get("strategy_id") or "")
        if sid:
            by_strategy[sid] = row
    return list(by_strategy.values())


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def _config_hash_for_strategy(strategy_id: str) -> str:
    path = ROOT / "configs/generated" / f"{strategy_id}.json"
    if not path.exists():
        return ""
    try:
        return config_hash(_read_json(path, {}))
    except Exception:
        return ""


def _sort_valid(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (-_f(r, "cagr"), -_f(r, "calmar"), -_f(r, "max_drawdown"), -_i(r, "years_beating_spy"), -_i(r, "trades")))


def _sort_near(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (constraint_gap_score(r), -_f(r, "cagr"), -_i(r, "trades")))


def _sort_high_cagr(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (-_f(r, "cagr"), -_i(r, "years_beating_spy"), -_f(r, "max_drawdown")))


def _best_near(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    near = [r for r in rows if classify_row(r) != "valid_candidate"]
    return _first(_sort_near(near))


def _first(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return rows[0] if rows else None


def _axis_available(axis: str, blocked: set[str]) -> bool:
    return axis not in blocked


def _f(row: dict[str, Any], key: str) -> float:
    try:
        return float(str(row.get(key, 0)).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _i(row: dict[str, Any], key: str) -> int:
    try:
        return int(float(str(row.get(key, 0)).replace(",", ".")))
    except (TypeError, ValueError):
        return 0
