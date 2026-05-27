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
BASE_NEAR_VALID_SL10_CONFIG = ROOT / "configs/generated/HYP_DD20_STOP_DYN8050200_GUARD1810_SL10_V1.json"
FAMILY = "dd20_adaptive_research"
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
    if near_low and _axis_available("trade_count_repair_around_sl10", blocked):
        return "trade_count_repair_around_sl10", f"Best near-valid `{near_low.get('strategy_id')}` already passes DD20/CAGR/years and only lacks trades."
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
        specs = _trade_count_repair_around_sl10_specs()
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


def render_strategy_config(spec: dict[str, Any], base_config_path: str | Path = BASE_NEAR_VALID_SL10_CONFIG) -> dict[str, Any]:
    cfg = _read_json(Path(base_config_path), {})
    risk = deepcopy(cfg.get("risk_management", {}) or {})
    risk.update(deepcopy(spec.get("risk_management", {})))
    cfg.update(
        {
            "strategy_id": spec["strategy_id"],
            "hypothesis_id": spec["strategy_id"],
            "strategy_family": FAMILY,
            "evaluation_mode": "dd20_spy_beater",
            "generation_axis": spec["generation_axis"],
            "parent_strategy_id": BASE_NEAR_VALID_SL10,
            "parent_hypothesis_id": BASE_NEAR_VALID_SL10,
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
        "parent_strategy_id": BASE_NEAR_VALID_SL10,
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
        "parent_strategy_id": BASE_NEAR_VALID_SL10,
        "parent_hypothesis_id": BASE_NEAR_VALID_SL10,
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
        "falsification_rule": "Reject if DD < -20, CAGR <= SPY, years W/L turns negative, or trades do not improve toward 3000.",
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
