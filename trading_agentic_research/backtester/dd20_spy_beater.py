"""DD20 + SPY-beater constrained scoring and reporting helpers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.governance import artifact_hashes, artifacts_are_duplicate

DD20_LIMIT_PCT = -20.0
DD20_MIN_TRADES = 1000
DD20_COLUMNS = [
    "run_id",
    "strategy_id",
    "cagr",
    "spy_cagr",
    "excess_cagr",
    "max_drawdown",
    "dd_limit",
    "passes_dd20",
    "beats_spy_cagr",
    "years_beating_spy",
    "years_losing_to_spy",
    "months_beating_spy",
    "months_losing_to_spy",
    "calmar",
    "trades",
    "decision",
    "rejection_reason",
    "rank_under_constraint",
]

REQUIRED_RUN_FILES = [
    "equity_curve.csv",
    "trades.csv",
    "metrics.json",
    "spy_comparison_daily.csv",
    "spy_comparison_monthly.csv",
    "spy_comparison_yearly.csv",
    "spy_comparison_summary.json",
    "run_manifest.json",
]

REFERENCE_STRATEGY_IDS = [
    "SPY",
    "HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_65_55_45_25_V1",
    "HYP_DD_FIRST_AUTO002_EXPOSURE_50_V1",
    "HYP_DD_FIRST_AUTO002_EXPOSURE_60_V1",
    "HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_65_55_45_25_V1",
]


def evaluate_dd20_spy_beater_run(
    run_dir: str | Path,
    *,
    parent_run_dir: str | Path | None = None,
    min_trades: int = DD20_MIN_TRADES,
    dd_limit: float = DD20_LIMIT_PCT,
) -> dict[str, Any]:
    """Evaluate one run under hard DD20 + SPY constraints.

    This mode is deliberately stricter than DD_FIRST: any candidate with max DD
    below -20% is rejected even if CAGR is high.
    """
    path = Path(run_dir)
    parent_path = Path(parent_run_dir) if parent_run_dir is not None else None
    manifest = _read_json(path / "run_manifest.json") if (path / "run_manifest.json").exists() else {}
    metrics = _read_json(path / "metrics.json") if (path / "metrics.json").exists() else {}
    summary = _read_json(path / "spy_comparison_summary.json") if (path / "spy_comparison_summary.json").exists() else {}
    trades_df = _read_csv(path / "trades.csv")

    strategy_metrics = metrics.get("strategy", {}) if isinstance(metrics, dict) else {}
    spy_metrics = metrics.get("spy", {}) if isinstance(metrics, dict) else {}

    cagr = _first_float(summary.get("strategy_cagr_pct"), strategy_metrics.get("cagr_pct"))
    spy_cagr = _first_float(summary.get("spy_cagr_pct"), spy_metrics.get("cagr_pct"))
    excess_cagr = _first_float(summary.get("excess_cagr_pct"))
    if excess_cagr is None and cagr is not None and spy_cagr is not None:
        excess_cagr = cagr - spy_cagr
    max_dd = _first_float(strategy_metrics.get("max_drawdown_pct"))
    years_beating = _as_int(summary.get("years_beating_spy"), 0)
    years_losing = _as_int(summary.get("years_losing_to_spy"), 0)
    months_beating = _as_int(summary.get("months_beating_spy"), 0)
    months_losing = _as_int(summary.get("months_losing_to_spy"), 0)
    trades = int(len(trades_df)) if trades_df is not None else 0
    calmar = _calmar(cagr, max_dd)

    missing_files = [name for name in REQUIRED_RUN_FILES if not (path / name).exists()]
    missing_spy_fields = [
        field
        for field in [
            "strategy_cagr_pct",
            "spy_cagr_pct",
            "months_beating_spy",
            "months_losing_to_spy",
            "years_beating_spy",
            "years_losing_to_spy",
        ]
        if field not in summary
    ]
    costs_present = _costs_are_present(metrics, trades_df)
    duplicate_or_noop = _duplicate_or_noop(path, parent_path, cagr, spy_cagr, max_dd, trades_df)

    passes_dd20 = max_dd is not None and max_dd >= dd_limit
    beats_spy = cagr is not None and spy_cagr is not None and cagr > spy_cagr

    rejection_reasons: list[str] = []
    if missing_files:
        rejection_reasons.append(f"missing_required_artifacts:{','.join(missing_files)}")
    if missing_spy_fields:
        rejection_reasons.append(f"missing_spy_comparison:{','.join(missing_spy_fields)}")
    if not costs_present:
        rejection_reasons.append("missing_costs")
    if duplicate_or_noop:
        rejection_reasons.append("duplicate_or_noop")
    if trades == 0:
        rejection_reasons.append("zero_trades")
    if trades < min_trades:
        rejection_reasons.append(f"insufficient_trades:{trades}<{min_trades}")
    if max_dd is None or cagr is None or spy_cagr is None:
        rejection_reasons.append("missing_core_metrics")
    elif not passes_dd20:
        rejection_reasons.append(f"max_drawdown_breaches_dd20:{max_dd:.6f}<{dd_limit:.6f}")
    if cagr is not None and spy_cagr is not None and not beats_spy:
        rejection_reasons.append(f"does_not_beat_spy_cagr:{cagr:.6f}<={spy_cagr:.6f}")
    if years_beating < years_losing:
        rejection_reasons.append(f"loses_more_years_than_beats:{years_beating}<{years_losing}")

    if not rejection_reasons:
        if cagr is not None and cagr >= 10 and years_beating > years_losing and calmar >= 0.50:
            decision = "excellent_candidate"
        elif cagr is not None and spy_cagr is not None and cagr >= spy_cagr + 2 and years_beating > years_losing:
            decision = "strong_candidate"
        else:
            decision = "valid_candidate"
    else:
        decision = "rejected"

    row = {
        "run_id": path.name,
        "strategy_id": str(manifest.get("strategy_id") or ""),
        "cagr": _round_or_blank(cagr),
        "spy_cagr": _round_or_blank(spy_cagr),
        "excess_cagr": _round_or_blank(excess_cagr),
        "max_drawdown": _round_or_blank(max_dd),
        "dd_limit": dd_limit,
        "passes_dd20": bool(passes_dd20),
        "beats_spy_cagr": bool(beats_spy),
        "years_beating_spy": years_beating,
        "years_losing_to_spy": years_losing,
        "months_beating_spy": months_beating,
        "months_losing_to_spy": months_losing,
        "calmar": round(calmar, 6),
        "trades": trades,
        "decision": decision,
        "rejection_reason": "; ".join(dict.fromkeys(rejection_reasons)),
        "rank_under_constraint": "",
    }

    return {
        "audit_status": "completed" if not missing_files else "completed_with_missing_files",
        "evaluation_mode": "dd20_spy_beater",
        "decision": decision,
        "reasons": rejection_reasons,
        "blocking_issues": rejection_reasons,
        "can_move_parent": False,
        "can_promote_baseline": False,
        "dd20_spy_beater": row,
    }


def row_from_dd20_audit_or_run(run_dir: str | Path, parent_run_dir: str | Path | None = None, min_trades: int = DD20_MIN_TRADES) -> dict[str, Any]:
    path = Path(run_dir)
    audit_path = path / "audit.json"
    if audit_path.exists():
        audit = _read_json(audit_path)
        if isinstance(audit.get("dd20_spy_beater"), dict):
            return audit["dd20_spy_beater"]
    return evaluate_dd20_spy_beater_run(path, parent_run_dir=parent_run_dir, min_trades=min_trades)["dd20_spy_beater"]


def valid_dd20_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [r for r in rows if str(r.get("decision")) in {"valid_candidate", "strong_candidate", "excellent_candidate"}],
        key=lambda r: (-_f(r, "cagr"), -_f(r, "calmar"), -_f(r, "max_drawdown"), -_i(r, "years_beating_spy"), -_i(r, "trades")),
    )


def ranked_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = [dict(r) for r in rows]
    rank_by_run = {r.get("run_id"): i for i, r in enumerate(valid_dd20_rows(out), start=1)}
    for row in out:
        row["rank_under_constraint"] = rank_by_run.get(row.get("run_id"), "")
    return sorted(out, key=lambda r: (_rank_sort_key(r), str(r.get("strategy_id") or "")))


def write_dd20_summary_csv(report_path: str | Path, rows: list[dict[str, Any]]) -> None:
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DD20_COLUMNS, extrasaction="ignore", delimiter=";")
        writer.writeheader()
        for row in ranked_rows(rows):
            writer.writerow({key: _csv_value(row.get(key, "")) for key in DD20_COLUMNS})


def build_dd20_summary_markdown(rows: list[dict[str, Any]]) -> str:
    rows = ranked_rows(rows)
    valid = valid_dd20_rows(rows)
    lines = [
        "# DD20 SPY Beater Summary",
        "",
        "Constraint: `max_drawdown >= -20`, `CAGR > SPY CAGR`, `trades >= 1000`, `years_beating_spy >= years_losing_to_spy`.",
        "",
    ]
    if valid:
        lines += ["## Ranking valid candidates", "", "| rank | strategy_id | CAGR | SPY CAGR | excess | DD | Calmar | trades | years W/L |", "|---:|:---|---:|---:|---:|---:|---:|---:|:---|"]
        for row in valid:
            lines.append(
                f"| {row.get('rank_under_constraint', '')} | `{row.get('strategy_id')}` | {_f(row,'cagr'):.4f}% | {_f(row,'spy_cagr'):.4f}% | {_f(row,'excess_cagr'):.4f}% | {_f(row,'max_drawdown'):.4f}% | {_f(row,'calmar'):.4f} | {_i(row,'trades')} | {_i(row,'years_beating_spy')}/{_i(row,'years_losing_to_spy')} |"
            )
    else:
        lines += ["## No valid candidates yet", ""]
        nearest = nearest_candidates(rows)
        if nearest.get("by_drawdown"):
            row = nearest["by_drawdown"]
            dd_gap = max(0.0, DD20_LIMIT_PCT - _f(row, "max_drawdown"))
            if dd_gap == 0:
                lines.append(f"- Closest by DD: `{row.get('strategy_id')}` already passes DD20 at DD {_f(row,'max_drawdown'):.4f}%; missing: {missing_to_pass(row)}.")
            else:
                lines.append(f"- Closest by DD: `{row.get('strategy_id')}` at DD {_f(row,'max_drawdown'):.4f}% needs {dd_gap:.4f} pct less drawdown.")
        if nearest.get("by_cagr"):
            row = nearest["by_cagr"]
            lines.append(f"- Closest by CAGR: `{row.get('strategy_id')}` at CAGR {_f(row,'cagr'):.4f}% vs SPY {_f(row,'spy_cagr'):.4f}%.")
        if nearest.get("overall"):
            lines.append(f"- Missing to pass: {missing_to_pass(nearest['overall'])}")
        lines += [
            "- Parameter adjustment indicated: lower weak/crisis exposure first; if DD passes but yearly SPY balance fails, keep crisis at 0 and restore selective strong-regime exposure or use a softer equity guard.",
        ]

    lines += ["", "## Reference comparison", "", "| strategy_id | CAGR | SPY CAGR | DD | Calmar | trades | decision |", "|:---|---:|---:|---:|---:|---:|:---|"]
    for row in reference_rows(rows):
        lines.append(f"| `{row.get('strategy_id')}` | {_f(row,'cagr'):.4f}% | {_f(row,'spy_cagr'):.4f}% | {_f(row,'max_drawdown'):.4f}% | {_f(row,'calmar'):.4f} | {_i(row,'trades')} | {row.get('decision')} |")
    if not reference_rows(rows):
        lines.append("| _No reference rows available in scanned runs._ |  |  |  |  |  |  |")
    return "\n".join(lines) + "\n"


def write_dd20_summary_markdown(report_path: str | Path, rows: list[dict[str, Any]]) -> None:
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_dd20_summary_markdown(rows), encoding="utf-8")


def nearest_candidates(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    if not rows:
        return {"by_drawdown": None, "by_cagr": None, "overall": None}
    by_drawdown = min(rows, key=lambda r: (abs(min(_f(r, "max_drawdown"), DD20_LIMIT_PCT) - DD20_LIMIT_PCT), -_f(r, "cagr")))
    by_cagr = max(rows, key=lambda r: (_f(r, "cagr"), _f(r, "max_drawdown")))
    overall = min(rows, key=_constraint_gap_score)
    return {"by_drawdown": by_drawdown, "by_cagr": by_cagr, "overall": overall}


def missing_to_pass(row: dict[str, Any]) -> str:
    parts: list[str] = []
    dd = _f(row, "max_drawdown")
    cagr = _f(row, "cagr")
    spy = _f(row, "spy_cagr")
    trades = _i(row, "trades")
    if dd < DD20_LIMIT_PCT:
        parts.append(f"reduce drawdown by {DD20_LIMIT_PCT - dd:.4f} pct")
    if cagr <= spy:
        parts.append(f"increase CAGR by {spy - cagr + 0.000001:.4f} pct")
    if trades < DD20_MIN_TRADES:
        parts.append(f"add {DD20_MIN_TRADES - trades} trades")
    if _i(row, "years_beating_spy") < _i(row, "years_losing_to_spy"):
        parts.append("improve yearly SPY win/loss balance")
    return "; ".join(parts) if parts else "nothing"


def reference_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_strategy: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = str(row.get("strategy_id") or "")
        if sid and (sid not in by_strategy or _f(row, "cagr") > _f(by_strategy[sid], "cagr")):
            by_strategy[sid] = row
    out = []
    for sid in REFERENCE_STRATEGY_IDS:
        if sid in by_strategy and by_strategy[sid] not in out:
            out.append(by_strategy[sid])
    return out


def _rank_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    rank = row.get("rank_under_constraint")
    return (0, int(rank)) if str(rank).isdigit() else (1, -_f(row, "cagr"))


def _constraint_gap_score(row: dict[str, Any]) -> tuple[float, float]:
    dd_gap = max(0.0, DD20_LIMIT_PCT - _f(row, "max_drawdown"))
    cagr_gap = max(0.0, _f(row, "spy_cagr") - _f(row, "cagr"))
    trade_gap = max(0.0, float(DD20_MIN_TRADES - _i(row, "trades"))) / DD20_MIN_TRADES
    year_gap = max(0.0, float(_i(row, "years_losing_to_spy") - _i(row, "years_beating_spy")))
    return (dd_gap * 10.0 + cagr_gap * 4.0 + trade_gap + year_gap, -_f(row, "cagr"))


def _duplicate_or_noop(path: Path, parent_path: Path | None, cagr: float | None, spy_cagr: float | None, max_dd: float | None, trades_df: pd.DataFrame | None) -> bool:
    if parent_path is None or not parent_path.exists():
        return False
    try:
        if artifacts_are_duplicate(artifact_hashes(path), artifact_hashes(parent_path)):
            return True
    except Exception:
        pass
    if cagr is None or spy_cagr is None or max_dd is None or trades_df is None:
        return False
    return False


def _costs_are_present(metrics: dict, trades_df: pd.DataFrame | None) -> bool:
    costs = metrics.get("costs", {}) if isinstance(metrics, dict) else {}
    if costs.get("applied") is True and _as_float(costs.get("cost_per_side_pct"), 0.0) > 0:
        return True
    if trades_df is None or trades_df.empty:
        return False
    if {"gross_return_pct", "net_return_pct"}.issubset(trades_df.columns):
        return bool((trades_df["gross_return_pct"] != trades_df["net_return_pct"]).any())
    return False


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as f:
        first = next((line for line in f if line.strip()), "")
    if ";" in first:
        return pd.read_csv(path, sep=";", decimal=",")
    return pd.read_csv(path)


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _as_float(value, None)
        if parsed is not None:
            return parsed
    return None


def _as_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _calmar(cagr: float | None, max_drawdown: float | None) -> float:
    if cagr is None or max_drawdown is None or max_drawdown == 0:
        return 0.0
    return cagr / abs(max_drawdown)


def _round_or_blank(value: float | None) -> float | str:
    return "" if value is None else round(float(value), 6)


def _csv_value(value: Any) -> Any:
    if isinstance(value, float):
        return str(value).replace(".", ",")
    return value


def _f(row: dict[str, Any], key: str) -> float:
    return _as_float(row.get(key), 0.0) or 0.0


def _i(row: dict[str, Any], key: str) -> int:
    return _as_int(row.get(key), 0)
