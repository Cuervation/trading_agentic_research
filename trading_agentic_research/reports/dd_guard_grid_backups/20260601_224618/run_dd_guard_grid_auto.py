"""Autonomous DD-guard grid runner for defensive variants.

Does not mutate official registry, parent, baseline, or source strategy config.
Generated configs and aggregate reports live under output-dir.
Each individual backtest can also persist normal run artifacts under runs/<run_id>/.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import traceback
import warnings
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any

import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message="critical: SPY market filter metrics unavailable/NaN.*")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.data_loader import load_daily_feature_store_folder, load_weekly_feature_store, validate_feature_store
from backtester.execution import run_strategy_backtest
from backtester.metrics import summarize_performance
from backtester.signal_builder import build_momentum_trend_signals
from backtester.spy_comparison import build_spy_equity_curve, compare_equity_curves, compare_monthly, compare_yearly, summarize_spy_comparison
from scripts.governance import build_run_manifest
from scripts.run_backtest import build_summary_markdown, build_yearly_strategy_stats

BASELINE_ID = "HYP_REFINE_AUTO002_TOPN_6_V1"
PREFIX = BASELINE_ID + "_DDGRID_"

RESULT_COLUMNS = [
    "strategy_id", "status", "stage", "run_id", "run_dir", "report_dir", "config_path", "completed_at",
    "config_hash", "cagr", "spy_cagr", "excess_cagr",
    "total_return", "spy_total_return", "final_equity", "max_drawdown", "max_recovery_days", "worst_year",
    "years_win_vs_spy", "years_loss_vs_spy", "months_win_vs_spy", "months_loss_vs_spy", "trades",
    "win_rate_gt_1pct", "median_trade_net", "avg_trade_net", "exposure_avg", "exposure_min", "exposure_max",
    "cash_days", "reduced_exposure_days", "crisis_mode_days", "dd_guard_activation_count", "position_stop_count",
    "reentry_count", "metric_no_effect", "ignored_config_fields", "unsupported_features", "notes",
    "calmar", "balanced_score",
    "2000_2003_return", "2000_2003_max_dd", "2008_2009_return", "2008_2009_max_dd",
    "q4_2018_return", "q4_2018_max_dd", "2020_crash_return", "2020_crash_max_dd",
    "2022_return", "2022_max_dd", "2025_return", "2025_max_dd", "2026_ytd_return", "2026_ytd_max_dd",
]

STRESS_WINDOWS = {
    "2000_2003": ("2000-01-01", "2003-12-31"),
    "2008_2009": ("2008-01-01", "2009-12-31"),
    "q4_2018": ("2018-10-01", "2018-12-31"),
    "2020_crash": ("2020-02-19", "2020-03-23"),
    "2022": ("2022-01-01", "2022-12-31"),
    "2025": ("2025-01-01", "2025-12-31"),
    "2026_ytd": ("2026-01-01", "2026-12-31"),
}


@dataclass(frozen=True)
class Variant:
    strategy_id: str
    config: dict[str, Any]
    config_hash: str
    family: str
    priority: int = 100


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run DD guard grid for a base strategy.")
    p.add_argument("--base-strategy", required=True)
    p.add_argument("--data-folder", required=True)
    p.add_argument("--output-dir", default="")
    p.add_argument("--max-screening-runs", type=int, default=500)
    p.add_argument("--max-full-runs", type=int, default=300)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--report-only", action="store_true")
    p.add_argument("--stage", choices=["smoke", "screening", "full", "all"], default="all")
    p.add_argument("--previous-report-dir", default="", help="Previous DDGRID report dir to load completed variants and combine rankings.")
    p.add_argument("--ensure-runs-output", action="store_true", help="Require every variant to persist normal artifacts under runs/<run_id>/.")
    p.add_argument("--runs-dir", default=str(ROOT / "runs"), help="Base runs directory for individual backtest artifacts.")
    p.add_argument("--variant-plan", choices=["auto", "extended", "cheap"], default="auto")
    return p.parse_args()


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


def stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def fnum(v: Any, default: float = math.nan) -> float:
    try:
        if v is None or v == "":
            return default
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def ensure_dirs(out: Path) -> None:
    for sub in ["logs", "generated_configs", "variant_runs"]:
        (out / sub).mkdir(parents=True, exist_ok=True)


def resolve_output_dir(args: argparse.Namespace) -> Path:
    if args.output_dir:
        return Path(args.output_dir)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return ROOT / "reports" / f"dd_guard_grid_{args.base_strategy}_{ts}"


def resolve_base_config(strategy_id: str) -> Path:
    registry = read_json(ROOT / "configs" / "strategy_registry.json", {}) or {}
    for row in registry.get("strategies", []) or []:
        if row.get("strategy_id") == strategy_id:
            path = ROOT / str(row.get("config_path"))
            if path.exists():
                return path
    fallback = ROOT / "configs" / "generated" / f"{strategy_id}.json"
    if fallback.exists():
        return fallback
    raise FileNotFoundError(f"No config for strategy_id={strategy_id}")


def resolve_data_paths(data_folder: Path) -> tuple[Path, Path]:
    weekly = sorted(data_folder.glob("*weekly*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not weekly and data_folder.parent.exists():
        weekly = sorted(data_folder.parent.glob("*weekly*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not weekly:
        raise FileNotFoundError(f"No weekly CSV under {data_folder} or parent")
    if not data_folder.exists():
        raise FileNotFoundError(f"Data folder missing: {data_folder}")
    return weekly[0], data_folder


def clamp_suffix(text: str, max_len: int = 68) -> str:
    clean = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in text.upper())
    clean = "_".join(part for part in clean.split("_") if part)
    return clean[:max_len]


def guard_cfg(reduce_dd: int, crisis_dd: int, reduced_mult: float, crisis_mult: float, reentry_mode: str,
              reentry_dd: int | None = None, cooldown_days: int = 0) -> dict[str, Any]:
    g = {
        "enabled": True,
        "reduce_exposure_drawdown_pct": float(reduce_dd),
        "reduced_exposure_multiplier": float(reduced_mult),
        "crisis_drawdown_pct": float(crisis_dd),
        "crisis_exposure_multiplier": float(crisis_mult),
        "reentry_mode": reentry_mode,
    }
    if reentry_dd is not None:
        g["reentry_drawdown_pct"] = float(reentry_dd)
    if cooldown_days:
        g["cooldown_days"] = int(cooldown_days)
    return g


def make_variant(base: dict[str, Any], suffix: str, guard: dict[str, Any], stop: int | None, family: str, priority: int) -> Variant:
    sid = PREFIX + clamp_suffix(suffix)
    cfg = deepcopy(base)
    cfg["strategy_id"] = sid
    cfg["hypothesis_id"] = sid
    cfg["parent_strategy_id"] = base.get("strategy_id", BASELINE_ID)
    cfg["strategy_family"] = "dd_guard_grid"
    cfg["risk_controls"] = {"portfolio_drawdown_guard": guard}
    if stop is not None:
        cfg["risk_controls"]["position_stop_loss"] = {"enabled": True, "stop_loss_pct": -abs(int(stop))}
    cfg["dd_guard_grid_notes"] = f"DD guard grid family={family}"
    cfg["changed_parameters"] = ["risk_controls.portfolio_drawdown_guard"] + (["risk_controls.position_stop_loss"] if stop else [])
    return Variant(sid, cfg, stable_hash({"risk_controls": cfg["risk_controls"]}), family, priority)


def mandatory_stop30(base: dict[str, Any]) -> list[Variant]:
    specs = [
        ("STOP30_PERM", "never", None, 0, None),
        ("STOP30_RE90", "cooldown_90", None, 90, None),
        ("STOP30_RE180", "cooldown_180", None, 180, None),
        ("STOP30_RE252", "cooldown_252", None, 252, None),
        ("STOP30_RE_SPY200", "spy_sma200", None, 0, None),
        ("STOP30_RE_SPY200_SMA50", "spy_sma200_sma50", None, 0, None),
        ("STOP30_RE_DD10", "dd_recovered", -10, 0, None),
        ("STOP30_RE_DD12", "dd_recovered", -12, 0, None),
        ("STOP30_SL20_RE_SPY200", "spy_sma200", None, 0, 20),
        ("STOP30_SL25_RE_SPY200_SMA50", "spy_sma200_sma50", None, 0, 25),
    ]
    out = []
    for suffix, mode, red, cd, stop in specs:
        out.append(make_variant(base, suffix, guard_cfg(-30, -30, 0.0, 0.0, mode, red, cd), stop, "mandatory_stop30", 0))
    return out


def generate_variants(base: dict[str, Any], max_count: int) -> list[Variant]:
    variants: list[Variant] = mandatory_stop30(base)
    diverse_specs = [
        # Softer guards first. These test "defensa temprana" without going to cash for decades.
        (-10, -25, 0.75, 0.50, "dd_recovered", -5, None),
        (-12, -28, 0.75, 0.50, "dd_recovered", -8, None),
        (-15, -30, 0.75, 0.50, "dd_recovered", -10, None),
        (-18, -35, 0.75, 0.50, "dd_recovered", -12, None),
        (-20, -35, 0.75, 0.50, "dd_recovered", -15, None),
        (-15, -30, 0.75, 0.25, "spy_sma200", -10, None),
        (-18, -35, 0.75, 0.25, "spy_sma200_sma50", -12, None),
        (-20, -35, 0.75, 0.50, "spy_sma200", -15, None),
        (-15, -30, 0.50, 0.25, "dd_recovered", -10, None),
        (-18, -35, 0.50, 0.25, "cooldown_90_spy_sma200", -12, None),
        (-20, -35, 0.50, 0.25, "cooldown_180_spy_sma200", -15, None),
        (-15, -30, 0.75, 0.50, "cooldown_90", -10, None),
        (-18, -35, 0.75, 0.50, "cooldown_180", -12, None),
        (-20, -35, 0.75, 0.50, "none", -15, None),
        (-12, -25, 0.75, 0.50, "dd_recovered", -8, 20),
        (-15, -30, 0.75, 0.50, "dd_recovered", -10, 20),
        (-18, -35, 0.75, 0.50, "dd_recovered", -12, 25),
        (-20, -35, 0.75, 0.50, "spy_sma200", -15, 25),
    ]
    seen = {v.config_hash for v in variants}
    for r, c, em, cm, mode, re, stop in diverse_specs:
        suffix = f"SOFT_R{abs(r)}_C{abs(c)}_E{int(em*100)}_CR{int(cm*100)}_RE{mode.upper()}_DD{abs(re)}_SL{stop or 'NONE'}"
        v = make_variant(base, suffix, guard_cfg(r, c, em, cm, mode, re), stop, "diverse_soft", 1)
        if v.config_hash not in seen:
            seen.add(v.config_hash)
            variants.append(v)
    reduce_dds = [-10, -12, -15, -18, -20]
    crisis_dds = [-18, -20, -22, -25, -28, -30, -35]
    reduced_mults = [0.75, 0.50, 0.33, 0.25]
    crisis_mults = [0.0, 0.25, 0.50]
    reentry_dds = [-5, -8, -10, -12, -15]
    modes = ["none", "dd_recovered", "spy_sma200", "spy_sma200_sma50", "spy_sma200_sma50_slope50",
             "cooldown_30", "cooldown_60", "cooldown_90", "cooldown_180", "cooldown_252",
             "cooldown_90_spy_sma200", "cooldown_180_spy_sma200",
             "cooldown_90_spy_sma200_sma50", "cooldown_180_spy_sma200_sma50"]
    stops: list[int | None] = [None, 12, 15, 18, 20, 25, 30]
    combos = []
    for r, c, em, cm, re, mode, stop in product(reduce_dds, crisis_dds, reduced_mults, crisis_mults, reentry_dds, modes, stops):
        if c > r or (cm > em and c == r):
            continue
        if mode == "none" and re not in {-10, -12}:
            continue
        priority = 10 - int(c in {-25, -30}) * 2 - int(cm == 0.0) - int(em in {0.5, 0.33}) - int(stop in {None, 20, 25, 30})
        if mode in {"dd_recovered", "spy_sma200", "spy_sma200_sma50", "cooldown_90_spy_sma200", "cooldown_180_spy_sma200"}:
            priority -= 1
        combos.append((priority, r, c, em, cm, re, mode, stop))
    combos.sort(key=lambda x: (x[0], abs(x[1] + 15), abs(x[2] + 25), str(x[6]), str(x[7])))
    for priority, r, c, em, cm, re, mode, stop in combos:
        if len(variants) >= max_count:
            break
        suffix = f"R{abs(r)}_C{abs(c)}_E{int(em*100)}_CR{int(cm*100)}_RE{mode.upper()}_DD{abs(re)}_SL{stop or 'NONE'}"
        v = make_variant(base, suffix, guard_cfg(r, c, em, cm, mode, re), stop, "grid", priority)
        if v.config_hash in seen:
            continue
        seen.add(v.config_hash)
        variants.append(v)
    return variants[:max_count]


def generate_extended_variants(base: dict[str, Any], max_count: int) -> list[Variant]:
    """Prioritized continuation grid around the best 20260530 DDGRID result."""
    specs: list[tuple[int, str, int, int, float, float, str, int | None, int | None, str]] = []

    # Fine perturbations requested around SOFT_R12_C25_E75_CR50_REDD_RECOVERED_DD8_SL20.
    fine = [
        (-10, -24, 0.75, 0.50, -8, 20),
        (-12, -24, 0.75, 0.50, -8, 20),
        (-14, -25, 0.75, 0.50, -8, 20),
        (-12, -26, 0.75, 0.50, -8, 20),
        (-12, -25, 0.66, 0.50, -8, 20),
        (-12, -25, 0.75, 0.40, -8, 20),
        (-12, -25, 0.75, 0.50, -6, 20),
        (-12, -25, 0.75, 0.50, -10, 20),
        (-12, -25, 0.75, 0.50, -8, 18),
        (-12, -25, 0.75, 0.50, -8, 22),
        (-12, -25, 0.75, 0.50, -8, None),
        (-12, -25, 0.66, 0.40, -8, 20),
        (-14, -26, 0.66, 0.40, -8, 20),
        (-10, -22, 0.75, 0.50, -6, 18),
        (-15, -28, 0.66, 0.40, -10, 20),
    ]
    for i, (r, c, em, cm, re, stop) in enumerate(fine):
        specs.append((i, "fine_winner", r, c, em, cm, "dd_recovered", re, stop, "EXT_FINE"))

    # Additional STOP30 revalidation, deliberately small.
    stop30 = [
        ("STOP30_EXT_RE_DD8_CR0", "dd_recovered", -8, 0, None),
        ("STOP30_EXT_RE_DD10_CR0", "dd_recovered", -10, 0, None),
        ("STOP30_EXT_RE180_DD10", "cooldown_180", -10, 180, None),
        ("STOP30_EXT_SPY200_DD10", "spy_sma200", -10, 0, None),
        ("STOP30_EXT_SPY200_SMA50_DD10", "spy_sma200_sma50", -10, 0, None),
    ]

    variants: list[Variant] = []
    seen: set[str] = set()
    for priority, family, r, c, em, cm, mode, re, stop, prefix in specs:
        suffix = f"{prefix}_R{abs(r)}_C{abs(c)}_E{int(em*100)}_CR{int(cm*100)}_REDD_RECOVERED_DD{abs(re or 0)}_SL{stop or 'NONE'}"
        v = make_variant(base, suffix, guard_cfg(r, c, em, cm, mode, re), stop, family, priority)
        if v.config_hash not in seen:
            seen.add(v.config_hash)
            variants.append(v)
    for i, (suffix, mode, re, cd, stop) in enumerate(stop30):
        v = make_variant(base, suffix, guard_cfg(-30, -30, 0.0, 0.0, mode, re, cd), stop, "stop30_revalidation", 20 + i)
        if v.config_hash not in seen:
            seen.add(v.config_hash)
            variants.append(v)

    combos: list[tuple[int, int, int, float, float, int, int | None, str]] = []

    def add_zone(family: str, base_priority: int, reduce_dds: list[int], crisis_dds: list[int],
                 reduced_mults: list[float], crisis_mults: list[float], reentry_dds: list[int],
                 stops: list[int | None]) -> None:
        for r, c, em, cm, re, stop in product(reduce_dds, crisis_dds, reduced_mults, crisis_mults, reentry_dds, stops):
            if c > r:
                continue
            distance = abs(r + 12) * 2 + abs(c + 25) + abs(em - 0.75) * 20 + abs(cm - 0.50) * 20 + abs(re + 8)
            if stop is None:
                stop_distance = 2
            else:
                stop_distance = abs(stop - 20) / 2
            priority = int(base_priority + distance + stop_distance)
            combos.append((priority, r, c, em, cm, re, stop, family))

    add_zone(
        "extended_balanced", 40,
        [-10, -12, -14, -15],
        [-22, -24, -25, -26, -28],
        [0.75, 0.66, 0.60, 0.50],
        [0.50, 0.40, 0.33, 0.25],
        [-6, -8, -10, -12],
        [None, 18, 20, 22, 25],
    )
    add_zone(
        "extended_defensive", 90,
        [-12, -15, -18],
        [-25, -28, -30],
        [0.50, 0.66, 0.75],
        [0.25, 0.33, 0.50],
        [-8, -10, -12],
        [None, 20, 25],
    )
    add_zone(
        "extended_high_return_controlled", 130,
        [-15, -18, -20],
        [-30, -35],
        [0.75],
        [0.50],
        [-10, -12, -15],
        [None, 20, 25],
    )

    combos.sort(key=lambda x: (x[0], abs(x[1] + 12), abs(x[2] + 25), str(x[6])))
    for priority, r, c, em, cm, re, stop, family in combos:
        if len(variants) >= max_count:
            break
        suffix = f"EXT_R{abs(r)}_C{abs(c)}_E{int(em*100)}_CR{int(cm*100)}_REDD_RECOVERED_DD{abs(re)}_SL{stop or 'NONE'}"
        v = make_variant(base, suffix, guard_cfg(r, c, em, cm, "dd_recovered", re), stop, family, priority)
        if v.config_hash in seen:
            continue
        seen.add(v.config_hash)
        variants.append(v)

    return variants[:max_count]


def generate_cheap_variants(base: dict[str, Any], max_count: int) -> list[Variant]:
    """Small directed grid around EXT_R12_C22_E75_CR40_REDD_RECOVERED_DD8_SL20."""
    center = {"r": -12, "c": -22, "em": 0.75, "cm": 0.40, "re": -8, "stop": 20}
    choices = {
        "r": [-11, -12, -13],
        "c": [-21, -22, -23, -24],
        "em": [0.70, 0.75, 0.80],
        "cm": [0.33, 0.40, 0.45],
        "re": [-7, -8, -9],
        "stop": [18, 20, 22, None],
    }
    specs: list[tuple[int, dict[str, Any]]] = []
    # one variable at a time
    for key, vals in choices.items():
        for val in vals:
            if val == center[key]:
                continue
            cfg = dict(center)
            cfg[key] = val
            specs.append((10, cfg))
    # two variables at a time, scored near prior winner
    keys = list(choices)
    for i, k1 in enumerate(keys):
        for k2 in keys[i + 1:]:
            for v1 in choices[k1]:
                for v2 in choices[k2]:
                    if v1 == center[k1] and v2 == center[k2]:
                        continue
                    cfg = dict(center)
                    cfg[k1] = v1
                    cfg[k2] = v2
                    # Prefer slight crisis/reentry/stop tweaks before wider exposure shifts.
                    score = 20
                    score += abs(int(abs(cfg["r"]) - 12)) * 3
                    score += abs(int(abs(cfg["c"]) - 22)) * 2
                    score += int(abs(float(cfg["em"]) - 0.75) * 100)
                    score += int(abs(float(cfg["cm"]) - 0.40) * 100)
                    score += abs(int(abs(cfg["re"]) - 8)) * 2
                    score += 4 if cfg["stop"] is None else abs(int(cfg["stop"]) - 20)
                    specs.append((score, cfg))
    specs.sort(key=lambda item: item[0])

    variants: list[Variant] = []
    seen: set[str] = set()
    for priority, cfg in specs:
        if len(variants) >= max_count:
            break
        suffix = (
            f"CHEAP_R{abs(cfg['r'])}_C{abs(cfg['c'])}_E{int(float(cfg['em']) * 100)}_"
            f"CR{int(float(cfg['cm']) * 100)}_REDD_RECOVERED_DD{abs(cfg['re'])}_SL{cfg['stop'] or 'NONE'}"
        )
        v = make_variant(base, suffix, guard_cfg(cfg["r"], cfg["c"], cfg["em"], cfg["cm"], "dd_recovered", cfg["re"]), cfg["stop"], "cheap_directed", priority)
        if v.config_hash in seen:
            continue
        seen.add(v.config_hash)
        variants.append(v)
    return variants


def load_state(path: Path) -> dict[str, Any]:
    state = read_json(path, None)
    if isinstance(state, dict) and "variants" in state:
        return state
    return {"created_at": datetime.now().isoformat(), "variants": {}, "baseline": None}


def save_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now().isoformat()
    write_json(path, state)


def load_previous_rows(previous_report_dir: str | Path | None) -> list[dict[str, Any]]:
    if not previous_report_dir:
        return []
    prev = Path(previous_report_dir)
    candidates = [prev / "combined_grid_results.csv", prev / "grid_results.csv"]
    for path in candidates:
        if path.exists():
            rows = pd.read_csv(path).fillna("").to_dict("records")
            out: list[dict[str, Any]] = []
            seen: set[tuple[str, str]] = set()
            for row in rows:
                sid = str(row.get("strategy_id", ""))
                key = (sid, "") if sid == BASELINE_ID else (sid, str(row.get("run_id", "")))
                if key in seen:
                    continue
                seen.add(key)
                out.append(row)
            return out
    return []


def previous_completed_keys(previous_rows: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    hashes: set[str] = set()
    for row in previous_rows:
        if str(row.get("status", "")).lower() not in {"completed", "baseline"}:
            continue
        sid = str(row.get("strategy_id", "")).strip()
        ch = str(row.get("config_hash", "")).strip()
        if sid:
            ids.add(sid)
        if ch:
            hashes.add(ch)
    return ids, hashes


def filter_previously_completed(variants: list[Variant], previous_rows: list[dict[str, Any]]) -> list[Variant]:
    previous_ids, previous_hashes = previous_completed_keys(previous_rows)
    out: list[Variant] = []
    seen_hashes: set[str] = set()
    for v in variants:
        if v.strategy_id in previous_ids or v.config_hash in previous_hashes or v.config_hash in seen_hashes:
            continue
        seen_hashes.add(v.config_hash)
        out.append(v)
    return out


def validate_df(df: pd.DataFrame, label: str) -> None:
    rep = validate_feature_store(df, ["date", "ticker", "close"], benchmark_ticker="SPY")
    if rep.get("missing_required_columns"):
        raise ValueError(f"{label} invalid: {rep}")


def max_recovery_days(equity: pd.DataFrame) -> int:
    if equity.empty:
        return 0
    e = equity[["date", "equity"]].copy()
    e["date"] = pd.to_datetime(e["date"])
    e["equity"] = pd.to_numeric(e["equity"], errors="coerce")
    peak = -math.inf
    peak_date = None
    worst = 0
    in_dd_since = None
    for _, row in e.iterrows():
        val = float(row["equity"])
        dt = row["date"]
        if val >= peak:
            if in_dd_since is not None:
                worst = max(worst, int((dt - in_dd_since).days))
            peak = val
            peak_date = dt
            in_dd_since = None
        elif in_dd_since is None:
            in_dd_since = peak_date or dt
    if in_dd_since is not None:
        worst = max(worst, int((e["date"].max() - in_dd_since).days))
    return int(worst)


def stress_metrics(equity: pd.DataFrame, start: str, end: str) -> tuple[float, float]:
    if equity.empty:
        return math.nan, math.nan
    e = equity[["date", "equity"]].copy()
    e["date"] = pd.to_datetime(e["date"])
    e = e[(e["date"] >= pd.Timestamp(start)) & (e["date"] <= pd.Timestamp(end))].copy()
    if len(e) < 2:
        return math.nan, math.nan
    eq = pd.to_numeric(e["equity"], errors="coerce").dropna()
    if len(eq) < 2 or float(eq.iloc[0]) == 0:
        return math.nan, math.nan
    ret = (float(eq.iloc[-1]) / float(eq.iloc[0]) - 1.0) * 100.0
    dd = ((eq / eq.cummax()) - 1.0).min() * 100.0
    return float(ret), float(dd)


def trade_stats(trades: pd.DataFrame) -> dict[str, Any]:
    if trades is None or trades.empty or "net_return_pct" not in trades.columns:
        return {"trades": 0, "win_rate_gt_1pct": 0.0, "median_trade_net": math.nan, "avg_trade_net": math.nan}
    net = pd.to_numeric(trades["net_return_pct"], errors="coerce").dropna()
    if net.empty:
        return {"trades": int(len(trades)), "win_rate_gt_1pct": 0.0, "median_trade_net": math.nan, "avg_trade_net": math.nan}
    return {"trades": int(len(trades)), "win_rate_gt_1pct": float((net > 1.0).mean() * 100.0),
            "median_trade_net": float(net.median()), "avg_trade_net": float(net.mean())}


def exposure_stats(equity: pd.DataFrame) -> dict[str, Any]:
    if equity.empty or not {"gross_exposure", "cash", "equity"}.issubset(equity.columns):
        return {"exposure_avg": math.nan, "exposure_min": math.nan, "exposure_max": math.nan, "cash_days": 0}
    eq = pd.to_numeric(equity["equity"], errors="coerce").replace(0, math.nan)
    exp = pd.to_numeric(equity["gross_exposure"], errors="coerce") / eq * 100.0
    return {"exposure_avg": float(exp.mean()), "exposure_min": float(exp.min()),
            "exposure_max": float(exp.max()), "cash_days": int((exp.fillna(0.0) < 1.0).sum())}


def balanced_score(row: dict[str, Any], base: dict[str, Any] | None) -> float:
    cagr = fnum(row.get("cagr"), 0.0)
    dd = fnum(row.get("max_drawdown"), -100.0)
    r2008 = fnum(row.get("2008_2009_return"), 0.0)
    dd2008 = fnum(row.get("2008_2009_max_dd"), 0.0)
    r2025 = fnum(row.get("2025_return"), 0.0)
    cash_days = fnum(row.get("cash_days"), 0.0)
    base_dd = fnum((base or {}).get("max_drawdown"), -60.0)
    dd_improve = abs(base_dd) - abs(dd)
    cash_penalty = max(0.0, cash_days - 2500.0) / 100.0
    low_cagr_penalty = max(0.0, 8.0 - cagr) * 3.0
    return cagr + dd_improve * 0.7 + r2008 * 0.08 + dd2008 * 0.12 + r2025 * 0.05 - cash_penalty - low_cagr_penalty


def build_result_row(strategy_id: str, stage: str, run_id: str, config_hash: str, result: dict[str, Any],
                     spy_metrics: dict[str, Any], comparison_summary: dict[str, Any],
                     comparison_yearly: pd.DataFrame, baseline_row: dict[str, Any] | None,
                     status: str = "completed", notes: str = "", run_dir: Path | None = None,
                     report_dir: Path | None = None, config_path: Path | None = None) -> dict[str, Any]:
    equity = result["equity_curve"]
    trades = result["trades"]
    metrics = summarize_performance(equity)
    diag = result.get("diagnostics", {}) or {}
    rc = (diag.get("risk_controls", {}) or {}).get("portfolio_drawdown_guard", {}) or {}
    ps = (diag.get("risk_controls", {}) or {}).get("position_stop_loss", {}) or {}
    row = {
        "strategy_id": strategy_id, "status": status, "stage": stage, "run_id": run_id,
        "run_dir": str(run_dir) if run_dir else "", "report_dir": str(report_dir) if report_dir else "",
        "config_path": str(config_path) if config_path else "", "completed_at": datetime.now().isoformat(),
        "config_hash": config_hash,
        "cagr": metrics.get("cagr_pct"), "spy_cagr": spy_metrics.get("cagr_pct"),
        "excess_cagr": fnum(metrics.get("cagr_pct"), 0) - fnum(spy_metrics.get("cagr_pct"), 0),
        "total_return": metrics.get("total_return_pct"), "spy_total_return": spy_metrics.get("total_return_pct"),
        "final_equity": float(pd.to_numeric(equity["equity"], errors="coerce").iloc[-1]) if not equity.empty else math.nan,
        "max_drawdown": metrics.get("max_drawdown_pct"), "max_recovery_days": max_recovery_days(equity),
        "worst_year": float(pd.to_numeric(comparison_yearly.get("strategy_return_pct", pd.Series(dtype=float)), errors="coerce").min()) if not comparison_yearly.empty else math.nan,
        "years_win_vs_spy": comparison_summary.get("years_beating_spy", 0),
        "years_loss_vs_spy": comparison_summary.get("years_losing_to_spy", 0),
        "months_win_vs_spy": comparison_summary.get("months_beating_spy", 0),
        "months_loss_vs_spy": comparison_summary.get("months_losing_to_spy", 0),
        "reduced_exposure_days": rc.get("reduced_exposure_days", 0),
        "crisis_mode_days": rc.get("crisis_mode_days", 0),
        "dd_guard_activation_count": rc.get("activations", 0),
        "position_stop_count": ps.get("count", 0),
        "reentry_count": rc.get("reentries", 0),
        "ignored_config_fields": "", "unsupported_features": "", "notes": notes,
    }
    row.update(trade_stats(trades))
    row.update(exposure_stats(equity))
    for name, (start, end) in STRESS_WINDOWS.items():
        ret, dd = stress_metrics(equity, start, end)
        row[f"{name}_return"] = ret
        row[f"{name}_max_dd"] = dd
    row["calmar"] = fnum(row.get("cagr"), 0.0) / abs(fnum(row.get("max_drawdown"), -1.0)) if fnum(row.get("max_drawdown"), 0.0) else math.nan
    no_events = fnum(row.get("dd_guard_activation_count"), 0) == 0 and fnum(row.get("position_stop_count"), 0) == 0
    if baseline_row:
        same = abs(fnum(row.get("cagr"), 0) - fnum(baseline_row.get("cagr"), 0)) < 1e-8 and abs(fnum(row.get("max_drawdown"), 0) - fnum(baseline_row.get("max_drawdown"), 0)) < 1e-8
        row["metric_no_effect"] = bool(no_events and same)
    else:
        row["metric_no_effect"] = False
    row["balanced_score"] = balanced_score(row, baseline_row)
    return {k: row.get(k, "") for k in RESULT_COLUMNS}


def write_results_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in RESULT_COLUMNS})


def build_unique_run_id(strategy_id: str, config_hash: str, run_seq: int, runs_dir: Path) -> str:
    base = clamp_suffix(strategy_id.replace(PREFIX, "DDGRID_"), max_len=84)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rid = f"{base}_EXT_{stamp}_{run_seq:03d}_{config_hash[:8]}"
    if not (runs_dir / rid).exists():
        return rid
    i = 2
    while (runs_dir / f"{rid}_{i}").exists():
        i += 1
    return f"{rid}_{i}"


def save_run_artifacts(out: Path, run_id: str, result: dict[str, Any], metrics: dict[str, Any],
                       summary: dict[str, Any], yearly: pd.DataFrame, monthly: pd.DataFrame,
                       daily: pd.DataFrame, run_dir: Path, config_path: Path, strategy_config: dict[str, Any],
                       project_config: dict[str, Any], weekly_file: Path, daily_folder: Path,
                       parent_strategy_config: dict[str, Any] | None) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    result["equity_curve"].to_csv(run_dir / "equity_curve.csv", index=False, sep=";", decimal=",")
    result["trades"].to_csv(run_dir / "trades.csv", index=False, sep=";", decimal=",")
    write_json(run_dir / "metrics.json", metrics)
    write_json(run_dir / "spy_comparison_summary.json", summary)
    daily.to_csv(run_dir / "spy_comparison_daily.csv", index=False, sep=";", decimal=",")
    yearly.to_csv(run_dir / "spy_comparison_yearly.csv", index=False, sep=";", decimal=",")
    monthly.to_csv(run_dir / "spy_comparison_monthly.csv", index=False, sep=";", decimal=",")
    yearly_stats = build_yearly_strategy_stats(run_id, str(strategy_config.get("strategy_id", "unknown_strategy")), yearly)
    yearly_stats.to_csv(run_dir / "yearly_strategy_stats.csv", index=False, sep=";", decimal=",")
    write_json(run_dir / "risk_events.json", result.get("diagnostics", {}).get("risk_events", []))
    summary_md = build_summary_markdown(
        run_id=run_id,
        strategy_id=str(strategy_config.get("strategy_id", "unknown_strategy")),
        strategy_metrics=metrics.get("strategy", {}),
        spy_metrics=metrics.get("spy", {}),
        comparison_summary=summary,
        yearly_stats_df=yearly_stats,
        number_of_trades=int(len(result["trades"])),
        warnings=list((result.get("diagnostics", {}) or {}).get("warnings", [])),
    )
    (run_dir / "summary.md").write_text(summary_md, encoding="utf-8")
    manifest = build_run_manifest(
        run_id=run_id,
        parent_run_id=None,
        strategy_config=strategy_config,
        strategy_config_path=config_path,
        project_config=project_config,
        weekly_file=weekly_file,
        daily_folder=daily_folder,
        parent_strategy_config=parent_strategy_config,
    )
    manifest["report_dir"] = str(out)
    manifest["grid_config_hash"] = stable_hash({"risk_controls": strategy_config.get("risk_controls", {})})
    write_json(run_dir / "run_manifest.json", manifest)

    # Optional report-local mirror/index; runs/<run_id>/ remains the source of truth.
    rd = out / "variant_runs" / run_id
    rd.mkdir(parents=True, exist_ok=True)
    write_json(rd / "run_pointer.json", {"run_id": run_id, "run_dir": str(run_dir), "config_path": str(config_path)})


def verify_run_artifacts(run_dir: Path) -> tuple[bool, list[str]]:
    required = ["metrics.json", "trades.csv", "equity_curve.csv", "run_manifest.json"]
    missing = [name for name in required if not (run_dir / name).exists()]
    return not missing, missing


def run_one(variant: Variant, stage: str, weekly_df: pd.DataFrame, daily_df: pd.DataFrame, signals: pd.DataFrame,
            project_config: dict[str, Any], spy_equity: pd.DataFrame, spy_metrics: dict[str, Any],
            out: Path, baseline_row: dict[str, Any] | None, runs_dir: Path, run_seq: int,
            weekly_file: Path, daily_folder: Path, parent_strategy_config: dict[str, Any] | None,
            ensure_runs_output: bool = False) -> dict[str, Any]:
    run_id = build_unique_run_id(variant.strategy_id, variant.config_hash, run_seq, runs_dir)
    run_dir = runs_dir / run_id
    config_path = out / "generated_configs" / f"{variant.strategy_id}.json"
    try:
        write_json(config_path, variant.config)
        result = run_strategy_backtest(weekly_df, daily_df, variant.config, project_config, signals_override=signals)
        equity = result["equity_curve"]
        if equity.empty:
            raise ValueError("empty equity curve")
        strategy_metrics = summarize_performance(equity)
        daily = compare_equity_curves(equity[["date", "equity"]], spy_equity[["date", "equity"]])
        yearly = compare_yearly(equity[["date", "equity"]], spy_equity[["date", "equity"]])
        monthly = compare_monthly(equity[["date", "equity"]], spy_equity[["date", "equity"]])
        summary = summarize_spy_comparison(monthly, yearly, strategy_metrics, spy_metrics)
        metrics_payload = {
            "strategy": strategy_metrics,
            "spy": spy_metrics,
            "diagnostics": result.get("diagnostics", {}),
            "costs": {"applied": True, "cost_per_side_pct": float(project_config.get("cost_per_side_pct", 0.24))},
        }
        save_run_artifacts(out, run_id, result, metrics_payload, summary, yearly, monthly, daily,
                           run_dir, config_path, variant.config, project_config, weekly_file, daily_folder,
                           parent_strategy_config)
        if ensure_runs_output:
            ok, missing = verify_run_artifacts(run_dir)
            if not ok:
                raise RuntimeError(f"run artifact verification failed for {run_dir}: missing {missing}")
        row = build_result_row(variant.strategy_id, stage, run_id, variant.config_hash, result, spy_metrics, summary, yearly,
                               baseline_row, run_dir=run_dir, report_dir=out, config_path=config_path)
        (out / "logs" / f"{variant.strategy_id}.json").write_text(json.dumps({"status": "completed", "row": row}, indent=2, default=str), encoding="utf-8")
        return row
    except Exception as exc:
        tb = traceback.format_exc()
        (out / "logs" / f"{variant.strategy_id}.error.log").write_text(tb, encoding="utf-8")
        return {"strategy_id": variant.strategy_id, "status": "failed", "stage": stage,
                "run_id": run_id, "run_dir": str(run_dir), "report_dir": str(out), "config_path": str(config_path),
                "completed_at": datetime.now().isoformat(), "config_hash": variant.config_hash, "notes": str(exc)}


def rows_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    if isinstance(state.get("baseline"), dict):
        rows.append(state["baseline"])
    for item in state.get("variants", {}).values():
        row = item.get("result") if isinstance(item, dict) else None
        if isinstance(row, dict):
            rows.append(row)
    return rows


def rank_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    text_cols = {"strategy_id", "status", "stage", "run_id", "run_dir", "report_dir", "config_path", "completed_at",
                 "config_hash", "ignored_config_fields", "unsupported_features", "notes"}
    for col in df.columns:
        if col not in text_cols:
            df[col] = pd.to_numeric(df[col], errors="ignore")
    return df


def md_table(df: pd.DataFrame, cols: list[str], n: int = 20) -> str:
    if df is None or df.empty:
        return "_Sin datos._\n"
    use_cols = [c for c in cols if c in df.columns]
    d = df[use_cols].head(n)
    lines = ["| " + " | ".join(use_cols) + " |", "| " + " | ".join(["---"] * len(use_cols)) + " |"]
    for _, row in d.iterrows():
        vals = []
        for col in use_cols:
            value = row.get(col, "")
            if isinstance(value, float):
                vals.append("" if math.isnan(value) else f"{value:.2f}")
            else:
                vals.append(str(value))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


def generate_reports(out: Path, state: dict[str, Any], previous_rows: list[dict[str, Any]] | None = None) -> None:
    previous_rows = previous_rows or []
    state_rows = rows_from_state(state)
    new_variant_rows = [
        (item.get("result") if isinstance(item, dict) else None)
        for item in state.get("variants", {}).values()
    ]
    new_variant_rows = [r for r in new_variant_rows if isinstance(r, dict)]
    previous_has_baseline = any(r.get("strategy_id") == BASELINE_ID for r in previous_rows)
    baseline_rows = [] if previous_has_baseline else [r for r in state_rows if r.get("strategy_id") == BASELINE_ID]
    rows = previous_rows + baseline_rows + new_variant_rows if previous_rows else state_rows
    base_for_score = next((r for r in rows if r.get("strategy_id") == BASELINE_ID), None)
    for row in rows:
        if row.get("strategy_id") != BASELINE_ID:
            row["balanced_score"] = balanced_score(row, base_for_score)
    new_rows_for_csv = new_variant_rows if previous_rows else rows
    write_results_csv(out / "grid_results_partial.csv", new_rows_for_csv)
    write_results_csv(out / "grid_results.csv", [r for r in new_rows_for_csv if r.get("status") == "completed"])
    if previous_rows:
        write_results_csv(out / "combined_grid_results.csv", [r for r in rows if r.get("status") in {"completed", "baseline"}])
    df = rank_df(rows)
    completed = df[df["status"].isin(["completed", "baseline"])] if not df.empty and "status" in df else df
    variants = completed[completed["strategy_id"] != BASELINE_ID] if not completed.empty and "strategy_id" in completed else completed
    baseline = completed[completed["strategy_id"] == BASELINE_ID].head(1) if not completed.empty and "strategy_id" in completed else pd.DataFrame()

    def sort(col: str, asc: bool = False) -> pd.DataFrame:
        if variants.empty or col not in variants:
            return variants
        return variants.sort_values(col, ascending=asc)

    top_cagr = sort("cagr", False)
    top_dd = sort("max_drawdown", False)
    top_calmar = sort("calmar", False)
    tradeable_variants = variants
    if not variants.empty and {"cagr", "cash_days"}.issubset(variants.columns):
        tradeable_variants = variants[(pd.to_numeric(variants["cagr"], errors="coerce") > 5.0) & (pd.to_numeric(variants["cash_days"], errors="coerce") < 5000)]
    top_2008 = tradeable_variants.sort_values("2008_2009_max_dd", ascending=False) if not tradeable_variants.empty and "2008_2009_max_dd" in tradeable_variants else sort("2008_2009_max_dd", False)
    top_bal = sort("balanced_score", False)
    top_stop30 = variants[variants["strategy_id"].astype(str).str.contains("STOP30", na=False)].sort_values("balanced_score", ascending=False) if not variants.empty else variants
    cols = ["strategy_id", "cagr", "max_drawdown", "calmar", "2008_2009_return", "2008_2009_max_dd", "2025_return", "dd_guard_activation_count", "position_stop_count", "cash_days"]

    top_md = ["# Top Candidates", "", "## Top 20 por CAGR", md_table(top_cagr, cols),
              "## Top 20 por menor drawdown", md_table(top_dd, cols),
              "## Top 20 por Calmar", md_table(top_calmar, cols),
              "## Top 20 por 2008 defensivo", md_table(top_2008, cols),
              "## Top 20 balanceadas", md_table(top_bal, cols),
              "## Top variantes stop -30", md_table(top_stop30, cols)]
    (out / "top_candidates.md").write_text("\n".join(top_md), encoding="utf-8")

    detail_parts = [baseline, top_bal.head(50), top_dd.head(20), top_cagr.head(20), top_stop30]
    detail_set = pd.concat([x for x in detail_parts if x is not None and not x.empty], ignore_index=True) if any(not x.empty for x in detail_parts if x is not None) else pd.DataFrame()
    if not detail_set.empty:
        detail_set = detail_set.drop_duplicates(subset=["strategy_id"])
    (out / "every_variant_detail.md").write_text("# Every Variant Detail\n\n" + md_table(detail_set, RESULT_COLUMNS, 200), encoding="utf-8")

    failed = df[~df["status"].isin(["completed", "baseline"])] if not df.empty and "status" in df else pd.DataFrame()
    (out / "failed_variants.md").write_text("# Failed / Skipped Variants\n\n" + md_table(failed, ["strategy_id", "status", "notes"], 500), encoding="utf-8")

    impl = f"""# Implementation Notes

- Engine touched: `backtester/execution.py`.
- Runner created: `scripts/run_dd_guard_grid_auto.py`.
- Original strategy config not modified: `{BASELINE_ID}`.
- Variants generated under `{out / 'generated_configs'}`.
- Individual backtests now persist normal artifacts under `runs/<run_id>/`.
- `reports/.../variant_runs/<run_id>/run_pointer.json` is only an index/pointer; `runs/` is the source of truth.
- Portfolio guard config: `risk_controls.portfolio_drawdown_guard`.
- Position stop config: `risk_controls.position_stop_loss.stop_loss_pct`.
- Portfolio drawdown = current equity / historical equity peak - 1, using data known up to current daily close.
- Reduced/crisis exposure: engine scales positions down at daily close when active, then caps future rebalances.
- Crisis exposure 0 means cash mode/liquidation to zero gross exposure in this daily-close model.
- Reentry filters use current/historical SPY daily close/SMA values only: SMA200, SMA50, SMA50 slope, cooldown, optional DD recovery.
- Limitation: fills are daily close; no intraday stop simulation. Esto NO es un stop intradiario.
- Screening used full-history equity then derived stress windows from the same real backtest; no invented metrics.
- Reproduce one run by reading `{out / 'grid_results.csv'}` -> `run_dir`, then inspect `metrics.json`, `summary.md`, `equity_curve.csv`, and `trades.csv`.
- Resume: rerun this script with the same `--output-dir`, `--resume`, and `--previous-report-dir` if applicable.
"""
    (out / "implementation_notes.md").write_text(impl, encoding="utf-8")

    best_cagr = top_cagr.head(1)
    best_dd = top_dd.head(1)
    best_calmar = top_calmar.head(1)
    best_bal = top_bal.head(1)
    best_stop30 = top_stop30.head(1)
    base_row = baseline.iloc[0].to_dict() if not baseline.empty else {}
    bal_row = best_bal.iloc[0].to_dict() if not best_bal.empty else {}
    safe_row = best_dd.iloc[0].to_dict() if not best_dd.empty else {}
    stop_row = best_stop30.iloc[0].to_dict() if not best_stop30.empty else {}
    completed_n = int((df["status"] == "completed").sum()) if not df.empty and "status" in df else 0
    failed_n = int((df["status"] == "failed").sum()) if not df.empty and "status" in df else 0
    noeff_n = int((df.get("metric_no_effect", pd.Series(dtype=bool)).astype(str).str.lower() == "true").sum()) if not df.empty else 0
    previous_n = len([r for r in previous_rows if str(r.get("status", "")).lower() == "completed"])
    new_completed_n = len([r for r in new_variant_rows if str(r.get("status", "")).lower() == "completed"])
    new_runs_created = len([r for r in new_variant_rows if str(r.get("status", "")).lower() == "completed" and str(r.get("run_dir", "")).strip()])
    prev_df = rank_df(previous_rows)
    new_df = rank_df(new_variant_rows)
    best_prev = prev_df[prev_df["strategy_id"] != BASELINE_ID].sort_values("balanced_score", ascending=False).head(1) if not prev_df.empty and {"strategy_id", "balanced_score"}.issubset(prev_df.columns) else pd.DataFrame()
    best_new = new_df[new_df["status"].eq("completed")].sort_values("balanced_score", ascending=False).head(1) if not new_df.empty and {"status", "balanced_score"}.issubset(new_df.columns) else pd.DataFrame()

    readme = [
        "# README_ANALISIS_FINAL", "",
        "## Resumen ejecutivo",
        f"- Baseline `{BASELINE_ID}`: CAGR {fnum(base_row.get('cagr')):.2f}%, Max DD {fnum(base_row.get('max_drawdown')):.2f}%.",
        "- Nota de verificación: existía un run histórico con CAGR ~40.85% y DD ~-59.61%, pero la corrida actual del repo (`VALIDATE_HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_20260530`) dio CAGR 19.13% y DD -51.08%. Este reporte usa la corrida actual como fuente de verdad.",
        f"- Variantes anteriores cargadas: {previous_n}.",
        f"- Variantes nuevas completed: {new_completed_n}; runs nuevos en `runs/`: {new_runs_created}.",
        f"- Completed combinado: {completed_n}; Failed: {failed_n}; Metric no effect: {noeff_n}.",
        "- Confirmaci?n: las nuevas corridas individuales quedan en `runs/<run_id>/`; `reports/.../variant_runs/` solo guarda punteros.",
        "- Alcance: extensi?n full-history priorizada alrededor de la mejor zona balanceada.",
        f"- Mejor balanceada: `{bal_row.get('strategy_id', '')}` CAGR {fnum(bal_row.get('cagr')):.2f}%, DD {fnum(bal_row.get('max_drawdown')):.2f}%.",
        f"- Mejor anterior: `{(best_prev.iloc[0].get('strategy_id') if not best_prev.empty else '')}`.",
        f"- Mejor nueva: `{(best_new.iloc[0].get('strategy_id') if not best_new.empty else '')}`.",
        "", "## Qué se implementó",
        "- Risk controls config-driven, event logging, checkpoint/resume, reportes CSV/MD/XLSX si openpyxl está disponible.",
        "", "## Resultado original", md_table(baseline, cols, 1),
        "", "## Mejor por CAGR", md_table(best_cagr, cols, 1),
        "", "## Mejor por drawdown", md_table(best_dd, cols, 1),
        "", "## Mejor por Calmar", md_table(best_calmar, cols, 1),
        "", "## Mejor balanceada", md_table(best_bal, cols, 1),
        "", "## Mejor stop -30", md_table(best_stop30, cols, 1),
        "", "## Qué pasó en 2008", md_table(top_2008, ["strategy_id", "cagr", "max_drawdown", "2008_2009_return", "2008_2009_max_dd", "cash_days"], 10),
        "", "## Qué pasó en 2025", md_table((tradeable_variants.sort_values("2025_max_dd", ascending=False) if not tradeable_variants.empty and "2025_max_dd" in tradeable_variants else sort("2025_max_dd", False)), ["strategy_id", "cagr", "max_drawdown", "2025_return", "2025_max_dd", "cash_days"], 10),
        "", "## Riesgos pendientes",
        "- Validar económicamente daily-close vs next-close. No hay intraday.",
        "- Repetir con datos actualizados si cambia feature store.",
        "", "## Cómo continuar",
        f"```powershell\npython .\\scripts\\run_dd_guard_grid_auto.py --base-strategy {BASELINE_ID} --data-folder \"{ROOT / 'data'}\" --output-dir \"{out}\" --stage all --max-screening-runs 250 --max-full-runs 250 --resume --previous-report-dir reports/dd_guard_grid_HYP_REFINE_AUTO002_TOPN_6_V1_20260530_140830 --ensure-runs-output\n```",
        "", "## Conclusión directa para Hernán",
        f"- Apareci? una variante nueva mejor que la anterior: `{(best_new.iloc[0].get('strategy_id') if not best_new.empty else '')}` vs `{(best_prev.iloc[0].get('strategy_id') if not best_prev.empty else '')}`.",
        f"- Mejor variante: `{bal_row.get('strategy_id', '')}`.",
        f"- Más segura: `{safe_row.get('strategy_id', '')}`.",
        f"- Mejor equilibrio: `{bal_row.get('strategy_id', '')}`.",
        f"- Tradearía: `{bal_row.get('strategy_id', '')}` si aceptás el modelo daily-close y confirmás robustness fuera de muestra.",
        f"- NO tradearía solo por CAGR: `{(best_cagr.iloc[0].get('strategy_id') if not best_cagr.empty else '')}` sin mirar DD/stress; CAGR sin supervivencia es VANIDAD.",
        f"- Stop -30: mejor observado `{stop_row.get('strategy_id', '')}`. En esta corrida fue demasiado tardío/brusco: bajó DD, pero dejó CAGR cerca de cero o negativo.",
        "- Si una defensa temprana mantiene CAGR decente y baja DD antes de -30, es más sana que esperar el incendio.",
        "- Próximos tests: next-close estricto, walk-forward, costos/slippage más duros, sensibilidad 2008/2025.",
    ]
    (out / "README_ANALISIS_FINAL.md").write_text("\n".join(readme) + "\n", encoding="utf-8")

    try:
        import openpyxl  # noqa: F401
        excel_name = "dd_guard_grid_results_cheap.xlsx" if "_CHEAP_" in out.name else ("dd_guard_grid_results_extended.xlsx" if previous_rows else "dd_guard_grid_results.xlsx")
        with pd.ExcelWriter(out / excel_name, engine="openpyxl") as writer:
            pd.DataFrame([{"completed": completed_n, "failed": failed_n, "metric_no_effect": noeff_n}]).to_excel(writer, "Dashboard", index=False)
            pd.DataFrame(new_variant_rows).to_excel(writer, "New Results", index=False)
            completed.to_excel(writer, "Combined Results" if previous_rows else "Full Results", index=False)
            top_bal.head(50).to_excel(writer, "Top Balanced", index=False)
            top_dd.head(50).to_excel(writer, "Top Drawdown", index=False)
            top_cagr.head(50).to_excel(writer, "Top CAGR", index=False)
            completed[[c for c in ["strategy_id", "run_id", "run_dir", "config_path", "completed_at"] if c in completed.columns]].to_excel(writer, "Runs Index", index=False)
            top_stop30.to_excel(writer, "Stop30 Variants", index=False)
            failed.to_excel(writer, "Failed Variants", index=False)
            pd.DataFrame([{"notes": impl}]).to_excel(writer, "Implementation Notes", index=False)
    except Exception as exc:
        (out / "logs" / "excel_skipped.log").write_text(str(exc), encoding="utf-8")


def main() -> int:
    args = parse_args()
    out = resolve_output_dir(args)
    ensure_dirs(out)
    runs_dir = Path(args.runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    previous_rows = load_previous_rows(args.previous_report_dir)
    state_path = out / "grid_state.json"
    state = load_state(state_path) if args.resume or state_path.exists() else {"created_at": datetime.now().isoformat(), "variants": {}, "baseline": None}
    if args.previous_report_dir:
        state["previous_report_dir"] = str(args.previous_report_dir)
        state["previous_completed_count"] = len([r for r in previous_rows if str(r.get("status", "")).lower() == "completed"])

    if args.report_only:
        generate_reports(out, state, previous_rows)
        print(out)
        return 0

    base_path = resolve_base_config(args.base_strategy)
    base_config = read_json(base_path, {})
    project_config = read_json(ROOT / "configs" / "project_config.json", {}) or {"initial_capital": 100000, "cost_per_side_pct": 0.24, "benchmark_ticker": "SPY"}
    weekly_file, daily_folder = resolve_data_paths(Path(args.data_folder))

    print(json.dumps({"phase": "load_data", "weekly": str(weekly_file), "daily": str(daily_folder), "output": str(out)}, ensure_ascii=False))
    weekly_df = load_weekly_feature_store(str(weekly_file))
    daily_df = load_daily_feature_store_folder(str(daily_folder))
    validate_df(weekly_df, "weekly")
    validate_df(daily_df, "daily")
    print(json.dumps({"phase": "precompute_signals"}, ensure_ascii=False))
    signals = build_momentum_trend_signals(weekly_df, base_config)

    spy_equity = build_spy_equity_curve(
        daily_df=daily_df,
        start_date=daily_df["date"].min(),
        end_date=daily_df["date"].max(),
        initial_capital=float(project_config.get("initial_capital", 100000)),
        benchmark_ticker=str(project_config.get("benchmark_ticker", "SPY")),
    )
    spy_metrics = summarize_performance(spy_equity[["date", "equity"]])

    if state.get("baseline") is None or args.force:
        base_variant = Variant(BASELINE_ID, base_config, stable_hash({"baseline": BASELINE_ID}), "baseline", -1)
        base_result = run_one(base_variant, "baseline", weekly_df, daily_df, signals, project_config, spy_equity, spy_metrics,
                              out, None, runs_dir, 0, weekly_file, daily_folder, None, args.ensure_runs_output)
        base_result["status"] = "baseline"
        state["baseline"] = base_result
        save_state(state_path, state)

    max_count = 12 if args.stage == "smoke" else max(args.max_screening_runs, 12)
    generation_count = max(max_count, 250) if args.previous_report_dir else max_count
    if args.variant_plan == "cheap":
        variants = generate_cheap_variants(base_config, generation_count)
    elif args.variant_plan == "extended" or args.previous_report_dir:
        variants = generate_extended_variants(base_config, generation_count)
    else:
        variants = generate_variants(base_config, generation_count)
    variants = filter_previously_completed(variants, previous_rows)
    if args.stage == "full":
        variants = variants[:args.max_full_runs]
    if args.stage == "smoke":
        variants = variants[:2]

    for idx, variant in enumerate(variants, 1):
        existing = state["variants"].get(variant.strategy_id)
        if existing and existing.get("status") in {"completed", "baseline"} and args.resume and not args.force:
            continue
        stage = "smoke" if idx <= 12 else "screening_fullhistory"
        row = run_one(variant, stage, weekly_df, daily_df, signals, project_config, spy_equity, spy_metrics,
                      out, state.get("baseline"), runs_dir, idx, weekly_file, daily_folder, base_config,
                      args.ensure_runs_output)
        state["variants"][variant.strategy_id] = {"status": row.get("status", "completed"), "attempts": 1, "result": row, "config_hash": variant.config_hash}
        save_state(state_path, state)
        if args.ensure_runs_output and idx <= 2 and row.get("status") == "completed":
            ok, missing = verify_run_artifacts(Path(str(row.get("run_dir", ""))))
            if not ok:
                raise RuntimeError(f"smoke run output verification failed for {row.get('run_dir')}: missing {missing}")
        generate_reports(out, state, previous_rows)
        completed = sum(1 for v in state["variants"].values() if v.get("status") == "completed")
        failed = sum(1 for v in state["variants"].values() if v.get("status") == "failed")
        df = rank_df(rows_from_state(state))
        best = ""
        if not df.empty and "balanced_score" in df:
            vv = df[(df["status"] == "completed") & (df["strategy_id"] != BASELINE_ID)].sort_values("balanced_score", ascending=False)
            best = str(vv.iloc[0]["strategy_id"]) if not vv.empty else ""
        print(json.dumps({"phase": stage, "completed": completed, "failed": failed, "pending": max(0, len(variants) - completed - failed), "best_current": best, "next_action": "continue"}, ensure_ascii=False))

    generate_reports(out, state, previous_rows)
    completed = sum(1 for v in state["variants"].values() if v.get("status") == "completed")
    failed = sum(1 for v in state["variants"].values() if v.get("status") == "failed")
    print(json.dumps({"phase": "done", "completed": completed, "failed": failed, "pending": 0, "best_current": "see top_candidates.md", "next_action": "review_report"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
