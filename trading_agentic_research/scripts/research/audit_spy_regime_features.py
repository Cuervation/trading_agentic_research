"""Audit SPY regime feature availability and market-filter reliability.

Why this exists:
- signal_builder.py falls back when spy_close_vs_sma50_pct is missing/NaN.
- Paper/regime hypotheses can look like they were tested, but if SPY metrics are
  unavailable on signal dates the backtest may be measuring fallback behavior.
- This script produces a small report that lets the autonomous loop or a human
  decide whether paper_regime_filter should be trusted, cooled down, or fixed by
  regenerating the feature store.

It is read-only: it never mutates parent, strategy registry, hypothesis bank, or
run decisions.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


SPY_COLUMNS = [
    "spy_close_vs_sma50_pct",
    "spy_channel_r2",
    "spy_channel_slope_pct",
    "spy_close_sma_50_slope_5d_pct",
]

REGIME_FAMILY_HINTS = {
    "paper_regime_filter",
    "feature_space_regime",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def read_csv_auto(path: str | Path, nrows: int | None = None) -> pd.DataFrame:
    return pd.read_csv(path, sep=None, engine="python", nrows=nrows)


def _date_column(df: pd.DataFrame) -> str | None:
    for col in ("signal_date", "date", "week", "timestamp"):
        if col in df.columns:
            return col
    return None


def _resolve_weekly_file(state_dir: str | Path, weekly_file: str | Path | None = None) -> str | None:
    if weekly_file:
        return str(weekly_file)
    resolved = read_json(Path(state_dir) / "data_paths_resolved.json", {}) or {}
    return resolved.get("weekly_file")


def _families_from_recent_runs(state_dir: str | Path, max_rows: int = 250) -> dict[str, int]:
    ledger = read_jsonl(Path(state_dir) / "research_ledger.jsonl")
    counts: Counter[str] = Counter()
    for row in ledger[-max_rows:]:
        family = str(row.get("family") or row.get("strategy_family") or "")
        if family:
            counts[family] += 1
    return dict(counts)


def audit_spy_regime_features(
    *,
    weekly_file: str | Path | None = None,
    state_dir: str | Path = "state",
    reports_dir: str | Path = "reports",
    max_warn_nan_pct: float = 5.0,
    max_warn_missing_spy_dates_pct: float = 2.0,
) -> dict[str, Any]:
    weekly = _resolve_weekly_file(state_dir, weekly_file)
    if not weekly or not Path(weekly).exists():
        payload = {
            "status": "blocked",
            "reason": "missing_weekly_file",
            "weekly_file": weekly,
            "generated_at": now_iso(),
        }
        write_json(Path(state_dir) / "spy_regime_feature_audit.json", payload)
        write_json(Path(reports_dir) / "spy_regime_feature_audit.json", payload)
        return payload

    df = read_csv_auto(weekly)
    date_col = _date_column(df)
    ticker_col = "ticker" if "ticker" in df.columns else None
    rows = int(len(df))
    warnings: list[str] = []

    if date_col:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    if ticker_col:
        df[ticker_col] = df[ticker_col].astype(str).str.upper()

    if not date_col:
        warnings.append("missing_date_column")
    if not ticker_col:
        warnings.append("missing_ticker_column")

    unique_dates = int(df[date_col].nunique()) if date_col else 0
    spy_df = df[df[ticker_col] == "SPY"].copy() if ticker_col else pd.DataFrame()
    spy_rows = int(len(spy_df))
    spy_dates = int(spy_df[date_col].nunique()) if date_col and not spy_df.empty else 0
    missing_spy_dates_pct = 0.0
    if unique_dates:
        missing_spy_dates_pct = round((1.0 - (spy_dates / unique_dates)) * 100, 4)
        if missing_spy_dates_pct > max_warn_missing_spy_dates_pct:
            warnings.append(f"high_missing_spy_dates_pct:{missing_spy_dates_pct:.2f}")

    column_reports: list[dict[str, Any]] = []
    for col in SPY_COLUMNS:
        if col not in df.columns:
            column_reports.append({"column": col, "exists": False, "nan_pct_all": None, "nan_pct_spy_rows": None, "non_null_spy_rows": 0})
            warnings.append(f"missing_spy_feature_column:{col}")
            continue

        all_nan_pct = round(float(pd.to_numeric(df[col], errors="coerce").isna().mean() * 100), 4) if rows else 100.0
        if spy_rows:
            spy_values = pd.to_numeric(spy_df[col], errors="coerce")
            spy_nan_pct = round(float(spy_values.isna().mean() * 100), 4)
            non_null_spy = int(spy_values.notna().sum())
        else:
            spy_nan_pct = 100.0
            non_null_spy = 0

        if col == "spy_close_vs_sma50_pct" and spy_nan_pct > max_warn_nan_pct:
            warnings.append(f"high_nan_pct_on_spy_rows:{col}:{spy_nan_pct:.2f}")

        column_reports.append(
            {
                "column": col,
                "exists": True,
                "nan_pct_all": all_nan_pct,
                "nan_pct_spy_rows": spy_nan_pct,
                "non_null_spy_rows": non_null_spy,
            }
        )

    first_bad_dates: list[str] = []
    if date_col and not spy_df.empty and "spy_close_vs_sma50_pct" in spy_df.columns:
        bad = spy_df[pd.to_numeric(spy_df["spy_close_vs_sma50_pct"], errors="coerce").isna()]
        first_bad_dates = [str(x.date() if hasattr(x, "date") else x) for x in bad[date_col].dropna().head(20).tolist()]

    family_counts = _families_from_recent_runs(state_dir)
    recent_regime_family_count = sum(count for family, count in family_counts.items() if family in REGIME_FAMILY_HINTS or "regime" in family)

    recommendation = "ok"
    if any(w.startswith("high_nan_pct_on_spy_rows:spy_close_vs_sma50_pct") for w in warnings):
        recommendation = "fix_or_regenerate_spy_regime_features_before_trusting_regime_hypotheses"
    elif any(w.startswith("missing_spy_feature_column:spy_close_vs_sma50_pct") for w in warnings):
        recommendation = "add_spy_close_vs_sma50_pct_to_feature_store_before_regime_tests"
    elif recent_regime_family_count >= 3 and warnings:
        recommendation = "avoid_more_regime_hypotheses_until_spy_audit_is_clean"

    status = "warning" if warnings else "ok"
    payload = {
        "status": status,
        "generated_at": now_iso(),
        "weekly_file": str(weekly),
        "rows": rows,
        "date_column": date_col,
        "ticker_column": ticker_col,
        "unique_dates": unique_dates,
        "spy_rows": spy_rows,
        "spy_dates": spy_dates,
        "missing_spy_dates_pct": missing_spy_dates_pct,
        "spy_feature_columns": column_reports,
        "first_bad_spy_close_vs_sma50_dates": first_bad_dates,
        "recent_regime_family_count": recent_regime_family_count,
        "recent_family_counts": family_counts,
        "warnings": warnings,
        "recommendation": recommendation,
    }

    write_json(Path(state_dir) / "spy_regime_feature_audit.json", payload)
    reports = Path(reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    write_json(reports / "spy_regime_feature_audit.json", payload)

    md = [
        "# SPY Regime Feature Audit",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Status: **{payload['status']}**",
        f"- Recommendation: `{payload['recommendation']}`",
        f"- Weekly file: `{payload['weekly_file']}`",
        f"- Rows: **{rows}**",
        f"- Unique dates: **{unique_dates}**",
        f"- SPY rows: **{spy_rows}**",
        f"- SPY dates: **{spy_dates}**",
        f"- Missing SPY dates %: **{missing_spy_dates_pct}**",
        "",
        "## SPY feature columns",
        "",
        "| column | exists | NaN % all rows | NaN % SPY rows | non-null SPY rows |",
        "|---|:---:|---:|---:|---:|",
    ]
    for item in column_reports:
        md.append(
            f"| `{item['column']}` | {str(item['exists']).lower()} | {item['nan_pct_all'] if item['nan_pct_all'] is not None else '-'} | {item['nan_pct_spy_rows'] if item['nan_pct_spy_rows'] is not None else '-'} | {item['non_null_spy_rows']} |"
        )
    md.extend(["", "## First bad SPY dates for spy_close_vs_sma50_pct", ""])
    md.extend([f"- {d}" for d in first_bad_dates] if first_bad_dates else ["- none"])
    md.extend(["", "## Warnings", ""])
    md.extend([f"- {w}" for w in warnings] if warnings else ["- none"])
    (reports / "spy_regime_feature_audit.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--weekly-file", default=None)
    p.add_argument("--state-dir", default="state")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--max-warn-nan-pct", type=float, default=5.0)
    p.add_argument("--max-warn-missing-spy-dates-pct", type=float, default=2.0)
    args = p.parse_args()
    print(
        json.dumps(
            audit_spy_regime_features(
                weekly_file=args.weekly_file,
                state_dir=args.state_dir,
                reports_dir=args.reports_dir,
                max_warn_nan_pct=args.max_warn_nan_pct,
                max_warn_missing_spy_dates_pct=args.max_warn_missing_spy_dates_pct,
            ),
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
