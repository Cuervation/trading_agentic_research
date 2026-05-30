"""Audit the current DD20 champion candidates without changing trading logic.

The script is intentionally read-only for runs/configs/state. It only writes a
timestamped analysis package under reports/dd20_champion_audit/.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN_IDS = [
    "DD20ADAPT_105_HYP_DD20_CAGR_SL12_TOPN8_GUARD18_10_V1",
    "DD20ADAPT_107_HYP_DD20_CAGR_DYN8055250_SL10_TOPN8_V1",
    "DD20ADAPT_105_HYP_DD20_CAGR_SL10P5_TOPN8_GUARD18_10_V1",
]
YEARLY_TIE_THRESHOLD_PCT = 1.0
MONTHLY_TIE_THRESHOLD_PCT = 1.0
REGIME_COLUMNS = [
    "spy_close_vs_sma50_pct",
    "spy_close_sma_50_slope_5d_pct",
    "spy_channel_r2",
    "spy_channel_slope_pct",
]
SPY_COLUMN_ALIASES = {
    "spy_close_vs_sma50_pct": "close_vs_sma50_pct",
    "spy_close_sma_50_slope_5d_pct": "close_sma_50_slope_5d_pct",
    "spy_channel_r2": "channel_r2",
    "spy_channel_slope_pct": "channel_slope_pct",
}


@dataclass
class RunAudit:
    run_id: str
    run_dir: Path
    strategy_id: str = ""
    warnings: list[str] = field(default_factory=list)


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # keep audit moving
        return {"_read_error": str(exc)}


def detect_csv(path: Path) -> tuple[str, str]:
    with path.open("r", encoding="utf-8-sig") as f:
        first = ""
        for line in f:
            if line.strip():
                first = line
                break
    if ";" in first:
        return ";", ","
    return ",", "."


def read_csv(path: Path, *, required: bool = False, **kwargs) -> pd.DataFrame:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Missing file: {path}")
        return pd.DataFrame()
    sep, decimal = detect_csv(path)
    return pd.read_csv(path, sep=sep, decimal=decimal, encoding="utf-8-sig", **kwargs)


def write_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False)


def safe_float(value, default: float = math.nan) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def classify_diff(diff_pct: float, threshold_pct: float) -> str:
    if pd.isna(diff_pct):
        return "unknown"
    if diff_pct > threshold_pct:
        return "win"
    if diff_pct < -threshold_pct:
        return "loss"
    return "tie"


def cumulative_return_pct(returns_pct: pd.Series) -> float:
    r = pd.to_numeric(returns_pct, errors="coerce").dropna() / 100.0
    if r.empty:
        return math.nan
    return float(((1.0 + r).prod() - 1.0) * 100.0)


def find_run(runs_dir: Path, run_id: str) -> RunAudit:
    exact = runs_dir / run_id
    audit = RunAudit(run_id=run_id, run_dir=exact)
    if exact.exists():
        return audit
    matches = [p for p in runs_dir.glob(f"*{run_id}*") if p.is_dir()]
    if matches:
        audit.run_dir = matches[0]
        audit.warnings.append(f"Exact run folder missing; used partial match: {matches[0]}")
        return audit
    audit.warnings.append(f"Run folder not found under {runs_dir}")
    return audit


def get_strategy_id(run_dir: Path, metrics: dict, audit_json: dict) -> str:
    manifest = read_json(run_dir / "run_manifest.json")
    for source in (
        manifest,
        audit_json.get("dd20_spy_beater", {}) if isinstance(audit_json, dict) else {},
        metrics.get("strategy", {}) if isinstance(metrics, dict) else {},
    ):
        value = source.get("strategy_id") if isinstance(source, dict) else None
        if value:
            return str(value)
    return run_dir.name


def build_yearly(run: RunAudit) -> pd.DataFrame:
    yearly = read_csv(run.run_dir / "spy_comparison_yearly.csv")
    if yearly.empty:
        yearly = read_csv(run.run_dir / "yearly_strategy_stats.csv")
    if yearly.empty:
        run.warnings.append("Missing yearly SPY comparison CSV")
        return pd.DataFrame()
    required = {"year", "strategy_return_pct", "spy_return_pct"}
    missing = required - set(yearly.columns)
    if missing:
        run.warnings.append(f"Yearly CSV missing columns: {sorted(missing)}")
        return pd.DataFrame()
    out = yearly.copy()
    out["run_id"] = run.run_id
    out["strategy_id"] = run.strategy_id
    out["diff_pct"] = pd.to_numeric(out["strategy_return_pct"], errors="coerce") - pd.to_numeric(
        out["spy_return_pct"], errors="coerce"
    )
    out["mark"] = out["diff_pct"].apply(lambda x: classify_diff(x, YEARLY_TIE_THRESHOLD_PCT))
    return out[["run_id", "strategy_id", "year", "strategy_return_pct", "spy_return_pct", "diff_pct", "mark"]]


def build_monthly(run: RunAudit) -> pd.DataFrame:
    monthly = read_csv(run.run_dir / "spy_comparison_monthly.csv")
    if monthly.empty:
        run.warnings.append("Missing monthly SPY comparison CSV")
        return pd.DataFrame()
    required = {"year", "month", "strategy_return_pct", "spy_return_pct"}
    missing = required - set(monthly.columns)
    if missing:
        run.warnings.append(f"Monthly CSV missing columns: {sorted(missing)}")
        return pd.DataFrame()
    out = monthly.copy()
    out["run_id"] = run.run_id
    out["strategy_id"] = run.strategy_id
    out["period"] = pd.to_datetime(
        out["year"].astype(str) + "-" + out["month"].astype(str).str.zfill(2) + "-01",
        errors="coerce",
    ).dt.strftime("%Y-%m")
    out["diff_pct"] = pd.to_numeric(out["strategy_return_pct"], errors="coerce") - pd.to_numeric(
        out["spy_return_pct"], errors="coerce"
    )
    out["mark"] = out["diff_pct"].apply(lambda x: classify_diff(x, MONTHLY_TIE_THRESHOLD_PCT))
    return out[
        ["run_id", "strategy_id", "year", "month", "period", "strategy_return_pct", "spy_return_pct", "diff_pct", "mark"]
    ]


def build_summary(run: RunAudit, yearly: pd.DataFrame, monthly: pd.DataFrame) -> dict:
    metrics = read_json(run.run_dir / "metrics.json")
    audit_json = read_json(run.run_dir / "audit.json")
    spy_summary = read_json(run.run_dir / "spy_comparison_summary.json")
    dd20 = audit_json.get("dd20_spy_beater", {}) if isinstance(audit_json, dict) else {}
    strategy = metrics.get("strategy", {}) if isinstance(metrics, dict) else {}
    spy = metrics.get("spy", {}) if isinstance(metrics, dict) else {}
    diagnostics = metrics.get("diagnostics", {}) if isinstance(metrics, dict) else {}
    cagr = safe_float(strategy.get("cagr_pct", dd20.get("cagr")))
    spy_cagr = safe_float(spy.get("cagr_pct", dd20.get("spy_cagr")))
    max_dd = safe_float(strategy.get("max_drawdown_pct", dd20.get("max_drawdown")))
    calmar = cagr / abs(max_dd) if max_dd and not pd.isna(max_dd) else math.nan
    row = {
        "run_id": run.run_id,
        "strategy_id": run.strategy_id,
        "CAGR": cagr,
        "total_return_pct": safe_float(strategy.get("total_return_pct")),
        "max_drawdown_pct": max_dd,
        "SPY_CAGR": spy_cagr,
        "SPY_total_return_pct": safe_float(spy.get("total_return_pct")),
        "excess_CAGR": cagr - spy_cagr if not pd.isna(cagr) and not pd.isna(spy_cagr) else math.nan,
        "years_won_vs_spy": int((yearly["mark"] == "win").sum()) if not yearly.empty else int(dd20.get("years_beating_spy", 0) or 0),
        "years_lost_vs_spy": int((yearly["mark"] == "loss").sum()) if not yearly.empty else int(dd20.get("years_losing_to_spy", 0) or 0),
        "months_won_vs_spy": int((monthly["mark"] == "win").sum())
        if not monthly.empty
        else int(spy_summary.get("months_beating_spy", dd20.get("months_beating_spy", 0)) or 0),
        "months_lost_vs_spy": int((monthly["mark"] == "loss").sum())
        if not monthly.empty
        else int(spy_summary.get("months_losing_to_spy", dd20.get("months_losing_to_spy", 0)) or 0),
        "trades": int(diagnostics.get("number_of_trades", dd20.get("trades", 0)) or 0),
        "calmar_ratio": calmar,
    }
    return row


def build_drawdown_episodes(run: RunAudit) -> pd.DataFrame:
    equity = read_csv(run.run_dir / "equity_curve.csv")
    if equity.empty:
        run.warnings.append("Missing equity_curve.csv; cannot compute drawdown episodes")
        return pd.DataFrame()
    required = {"date", "equity"}
    missing = required - set(equity.columns)
    if missing:
        run.warnings.append(f"equity_curve.csv missing columns: {sorted(missing)}")
        return pd.DataFrame()
    df = equity[["date", "equity"]].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["equity"] = pd.to_numeric(df["equity"], errors="coerce")
    df = df.dropna(subset=["date", "equity"]).sort_values("date")
    if df.empty:
        run.warnings.append("equity_curve.csv has no valid date/equity rows")
        return pd.DataFrame()

    episodes: list[dict] = []
    peak_date = df.iloc[0]["date"]
    peak_equity = float(df.iloc[0]["equity"])
    in_dd = False
    valley_date = None
    valley_dd = 0.0

    for _, row in df.iterrows():
        date = row["date"]
        eq = float(row["equity"])
        if eq >= peak_equity:
            if in_dd:
                episodes.append(
                    {
                        "run_id": run.run_id,
                        "strategy_id": run.strategy_id,
                        "peak_date": peak_date.date().isoformat(),
                        "valley_date": valley_date.date().isoformat() if valley_date is not None else "",
                        "recovery_date": date.date().isoformat(),
                        "drawdown_pct": valley_dd,
                        "days_to_valley": int((valley_date - peak_date).days) if valley_date is not None else 0,
                        "days_to_recover": int((date - peak_date).days),
                        "recovered": True,
                    }
                )
            peak_equity = eq
            peak_date = date
            in_dd = False
            valley_date = None
            valley_dd = 0.0
            continue
        dd = (eq / peak_equity - 1.0) * 100.0 if peak_equity else 0.0
        if not in_dd:
            in_dd = True
            valley_date = date
            valley_dd = dd
        elif dd < valley_dd:
            valley_date = date
            valley_dd = dd

    if in_dd:
        episodes.append(
            {
                "run_id": run.run_id,
                "strategy_id": run.strategy_id,
                "peak_date": peak_date.date().isoformat(),
                "valley_date": valley_date.date().isoformat() if valley_date is not None else "",
                "recovery_date": "",
                "drawdown_pct": valley_dd,
                "days_to_valley": int((valley_date - peak_date).days) if valley_date is not None else 0,
                "days_to_recover": "",
                "recovered": False,
            }
        )
    return pd.DataFrame(episodes).sort_values(["run_id", "drawdown_pct"])


def load_sector_map(data_dir: Path) -> pd.DataFrame:
    sectors = read_csv(data_dir / "sp500_sector_metadata.csv")
    if sectors.empty or "ticker" not in sectors.columns:
        return pd.DataFrame(columns=["ticker", "sector", "industry"])
    keep = [c for c in ["ticker", "sector", "industry"] if c in sectors.columns]
    return sectors[keep].drop_duplicates("ticker")


def build_trade_quality(run: RunAudit, sectors: pd.DataFrame) -> pd.DataFrame:
    trades = read_csv(run.run_dir / "trades.csv")
    if trades.empty:
        run.warnings.append("Missing trades.csv; cannot compute trade quality")
        return pd.DataFrame()
    if "net_return_pct" not in trades.columns:
        run.warnings.append("trades.csv missing net_return_pct; trade quality limited")
        return pd.DataFrame()
    df = trades.copy()
    df["net_return_pct"] = pd.to_numeric(df["net_return_pct"], errors="coerce")
    if "holding_days" not in df.columns and {"entry_date", "exit_date"}.issubset(df.columns):
        df["holding_days"] = (pd.to_datetime(df["exit_date"], errors="coerce") - pd.to_datetime(df["entry_date"], errors="coerce")).dt.days
    if not sectors.empty and "ticker" in df.columns:
        df = df.merge(sectors, on="ticker", how="left")
    else:
        df["sector"] = pd.NA
    df["bucket"] = df["net_return_pct"].apply(lambda x: "winner" if x > 0 else ("loser" if x < 0 else "tie"))
    rows = []
    grouped = {name: group for name, group in df.groupby("bucket", dropna=False)}
    for bucket in ["all", "winner", "loser", "tie"]:
        group = df if bucket == "all" else grouped.get(bucket, pd.DataFrame(columns=df.columns))
        if group.empty:
            rows.append(
                {
                    "run_id": run.run_id,
                    "strategy_id": run.strategy_id,
                    "trade_bucket": bucket,
                    "trades": 0,
                    "avg_return_pct": math.nan,
                    "median_return_pct": math.nan,
                    "worst_trade_pct": math.nan,
                    "best_trade_pct": math.nan,
                    "avg_duration_days": math.nan,
                    "best_trade_ticker": "",
                    "best_trade_sector": "",
                    "worst_trade_ticker": "",
                    "worst_trade_sector": "",
                    "top_sector_by_trade_count": "",
                }
            )
            continue
        best = group.loc[group["net_return_pct"].idxmax()] if group["net_return_pct"].notna().any() else {}
        worst = group.loc[group["net_return_pct"].idxmin()] if group["net_return_pct"].notna().any() else {}
        rows.append(
            {
                "run_id": run.run_id,
                "strategy_id": run.strategy_id,
                "trade_bucket": bucket,
                "trades": int(len(group)),
                "avg_return_pct": float(group["net_return_pct"].mean()),
                "median_return_pct": float(group["net_return_pct"].median()),
                "worst_trade_pct": float(group["net_return_pct"].min()),
                "best_trade_pct": float(group["net_return_pct"].max()),
                "avg_duration_days": float(pd.to_numeric(group.get("holding_days"), errors="coerce").mean())
                if "holding_days" in group
                else math.nan,
                "best_trade_ticker": best.get("ticker", "") if hasattr(best, "get") else "",
                "best_trade_sector": best.get("sector", "") if hasattr(best, "get") else "",
                "worst_trade_ticker": worst.get("ticker", "") if hasattr(worst, "get") else "",
                "worst_trade_sector": worst.get("sector", "") if hasattr(worst, "get") else "",
                "top_sector_by_trade_count": str(group["sector"].mode().iloc[0]) if "sector" in group and not group["sector"].mode().empty else "",
            }
        )
    return pd.DataFrame(rows)


def load_spy_regime_data(data_dir: Path) -> tuple[pd.DataFrame, list[str]]:
    needed_aliases = ["date", *[SPY_COLUMN_ALIASES[c] for c in REGIME_COLUMNS]]
    frames = []
    missing: set[str] = set()
    for path in sorted(data_dir.glob("sp500_feature_store_spy_daily_master_*_*.csv")):
        columns = read_csv(path, nrows=0).columns.tolist()
        usecols = [c for c in needed_aliases if c in columns]
        missing.update(c for c in needed_aliases if c not in columns and c != "date")
        if "date" not in usecols:
            continue
        frames.append(read_csv(path, usecols=usecols))
    if not frames:
        return pd.DataFrame(), [f"No SPY daily master files with regime columns found in {data_dir}"]
    df = pd.concat(frames, ignore_index=True).drop_duplicates("date")
    rename = {alias: prefixed for prefixed, alias in SPY_COLUMN_ALIASES.items() if alias in df.columns}
    df = df.rename(columns=rename)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    missing_prefixed = [c for c in REGIME_COLUMNS if c not in df.columns]
    warnings = [f"Missing SPY regime columns: {missing_prefixed}"] if missing_prefixed else []
    return df, warnings


def regime_bucket(row: pd.Series) -> str:
    pos = row.get("spy_close_vs_sma50_pct")
    slope = row.get("spy_close_sma_50_slope_5d_pct")
    if pd.isna(pos):
        pos_bucket = "sma50_unknown"
    elif pos > 1.0:
        pos_bucket = "above_sma50"
    elif pos < -1.0:
        pos_bucket = "below_sma50"
    else:
        pos_bucket = "near_sma50"
    if pd.isna(slope):
        slope_bucket = "slope_unknown"
    elif slope > 0.05:
        slope_bucket = "slope_rising"
    elif slope < -0.05:
        slope_bucket = "slope_falling"
    else:
        slope_bucket = "slope_flat"
    return f"{pos_bucket}|{slope_bucket}"


def build_regime_breakdown(run: RunAudit, spy_regime: pd.DataFrame) -> pd.DataFrame:
    daily = read_csv(run.run_dir / "spy_comparison_daily.csv")
    equity = read_csv(run.run_dir / "equity_curve.csv")
    if daily.empty:
        run.warnings.append("Missing spy_comparison_daily.csv; cannot compute regime breakdown")
        return pd.DataFrame()
    required = {"date", "strategy_daily_return_pct", "spy_daily_return_pct"}
    missing = required - set(daily.columns)
    if missing:
        run.warnings.append(f"spy_comparison_daily.csv missing columns: {sorted(missing)}")
        return pd.DataFrame()
    if spy_regime.empty:
        run.warnings.append("SPY regime data unavailable; regime_breakdown will be empty")
        return pd.DataFrame()
    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if not equity.empty and {"date", "gross_exposure", "cash", "equity"}.issubset(equity.columns):
        e = equity[["date", "gross_exposure", "cash", "equity", "positions_count"]].copy()
        e["date"] = pd.to_datetime(e["date"], errors="coerce")
        e["cash_pct"] = pd.to_numeric(e["cash"], errors="coerce") / pd.to_numeric(e["equity"], errors="coerce") * 100.0
        e["gross_exposure_pct"] = (
            pd.to_numeric(e["gross_exposure"], errors="coerce") / pd.to_numeric(e["equity"], errors="coerce") * 100.0
        )
        df = df.merge(e[["date", "gross_exposure", "gross_exposure_pct", "cash_pct", "positions_count"]], on="date", how="left")
    merged = df.merge(spy_regime, on="date", how="left")
    merged["regime"] = merged.apply(regime_bucket, axis=1)
    rows = []
    for regime, group in merged.groupby("regime", dropna=False):
        rows.append(
            {
                "run_id": run.run_id,
                "strategy_id": run.strategy_id,
                "regime": regime,
                "days": int(len(group)),
                "strategy_return_pct": cumulative_return_pct(group["strategy_daily_return_pct"]),
                "spy_return_pct": cumulative_return_pct(group["spy_daily_return_pct"]),
                "diff_pct": cumulative_return_pct(group["strategy_daily_return_pct"])
                - cumulative_return_pct(group["spy_daily_return_pct"]),
                "avg_spy_close_vs_sma50_pct": float(pd.to_numeric(group.get("spy_close_vs_sma50_pct"), errors="coerce").mean()),
                "avg_spy_close_sma_50_slope_5d_pct": float(
                    pd.to_numeric(group.get("spy_close_sma_50_slope_5d_pct"), errors="coerce").mean()
                ),
                "avg_spy_channel_r2": float(pd.to_numeric(group.get("spy_channel_r2"), errors="coerce").mean())
                if "spy_channel_r2" in group
                else math.nan,
                "avg_spy_channel_slope_pct": float(pd.to_numeric(group.get("spy_channel_slope_pct"), errors="coerce").mean())
                if "spy_channel_slope_pct" in group
                else math.nan,
                "avg_gross_exposure_value": float(pd.to_numeric(group.get("gross_exposure"), errors="coerce").mean())
                if "gross_exposure" in group
                else math.nan,
                "avg_gross_exposure_pct": float(pd.to_numeric(group.get("gross_exposure_pct"), errors="coerce").mean())
                if "gross_exposure_pct" in group
                else math.nan,
                "avg_cash_pct": float(pd.to_numeric(group.get("cash_pct"), errors="coerce").mean()) if "cash_pct" in group else math.nan,
                "avg_positions_count": float(pd.to_numeric(group.get("positions_count"), errors="coerce").mean())
                if "positions_count" in group
                else math.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(["run_id", "regime"])


def period_daily_stats(run: RunAudit, periods: Iterable[tuple[str, pd.Timestamp, pd.Timestamp]]) -> pd.DataFrame:
    daily = read_csv(run.run_dir / "spy_comparison_daily.csv")
    equity = read_csv(run.run_dir / "equity_curve.csv")
    trades = read_csv(run.run_dir / "trades.csv")
    if daily.empty:
        return pd.DataFrame()
    daily["date"] = pd.to_datetime(daily["date"], errors="coerce")
    if not equity.empty and {"date", "gross_exposure", "cash", "equity", "positions_count"}.issubset(equity.columns):
        equity = equity.copy()
        equity["date"] = pd.to_datetime(equity["date"], errors="coerce")
        equity["cash_pct"] = pd.to_numeric(equity["cash"], errors="coerce") / pd.to_numeric(equity["equity"], errors="coerce") * 100.0
        equity["gross_exposure_pct"] = (
            pd.to_numeric(equity["gross_exposure"], errors="coerce")
            / pd.to_numeric(equity["equity"], errors="coerce")
            * 100.0
        )
        daily = daily.merge(equity[["date", "gross_exposure", "gross_exposure_pct", "cash_pct", "positions_count"]], on="date", how="left")
    if not trades.empty:
        trades = trades.copy()
        date_col = "exit_date" if "exit_date" in trades.columns else "entry_date"
        trades["_period_date"] = pd.to_datetime(trades[date_col], errors="coerce")
        trades["net_return_pct"] = pd.to_numeric(trades.get("net_return_pct"), errors="coerce")

    rows = []
    for label, start, end in periods:
        pdaily = daily[(daily["date"] >= start) & (daily["date"] <= end)]
        ptrades = trades[(trades["_period_date"] >= start) & (trades["_period_date"] <= end)] if not trades.empty else pd.DataFrame()
        stop_count = int(ptrades["exit_reason"].astype(str).str.contains("stop", case=False, na=False).sum()) if "exit_reason" in ptrades else 0
        rows.append(
            {
                "run_id": run.run_id,
                "strategy_id": run.strategy_id,
                "period": label,
                "strategy_return_pct": cumulative_return_pct(pdaily.get("strategy_daily_return_pct", pd.Series(dtype=float))),
                "spy_return_pct": cumulative_return_pct(pdaily.get("spy_daily_return_pct", pd.Series(dtype=float))),
                "diff_pct": cumulative_return_pct(pdaily.get("strategy_daily_return_pct", pd.Series(dtype=float)))
                - cumulative_return_pct(pdaily.get("spy_daily_return_pct", pd.Series(dtype=float))),
                "avg_gross_exposure_value": float(pd.to_numeric(pdaily.get("gross_exposure"), errors="coerce").mean())
                if "gross_exposure" in pdaily
                else math.nan,
                "avg_gross_exposure_pct": float(pd.to_numeric(pdaily.get("gross_exposure_pct"), errors="coerce").mean())
                if "gross_exposure_pct" in pdaily
                else math.nan,
                "avg_cash_pct": float(pd.to_numeric(pdaily.get("cash_pct"), errors="coerce").mean()) if "cash_pct" in pdaily else math.nan,
                "avg_positions_count": float(pd.to_numeric(pdaily.get("positions_count"), errors="coerce").mean())
                if "positions_count" in pdaily
                else math.nan,
                "trades": int(len(ptrades)),
                "trade_avg_return_pct": float(ptrades["net_return_pct"].mean()) if "net_return_pct" in ptrades and not ptrades.empty else math.nan,
                "trade_loss_rate_pct": float((ptrades["net_return_pct"] < 0).mean() * 100.0)
                if "net_return_pct" in ptrades and not ptrades.empty
                else math.nan,
                "stop_loss_trades": stop_count,
                "stop_loss_rate_pct": float(stop_count / len(ptrades) * 100.0) if len(ptrades) else math.nan,
            }
        )
    return pd.DataFrame(rows)


def infer_bad_period_reasons(row: pd.Series) -> list[str]:
    reasons: list[str] = []
    spy_return = row.get("spy_return_pct", math.nan)
    diff = row.get("diff_pct", math.nan)
    exposure = row.get("avg_gross_exposure_pct", row.get("avg_gross_exposure", math.nan))
    cash = row.get("avg_cash_pct", math.nan)
    trade_avg = row.get("trade_avg_return_pct", math.nan)
    loss_rate = row.get("trade_loss_rate_pct", math.nan)
    stop_rate = row.get("stop_loss_rate_pct", math.nan)

    if not pd.isna(trade_avg) and trade_avg < 0 and not pd.isna(loss_rate) and loss_rate > 50:
        reasons.append("mala selección de activos: retorno medio por trade negativo y mayoría de trades perdedores")
    if not pd.isna(exposure) and exposure < 50:
        reasons.append("poca exposición: exposición bruta promedio baja")
    if not pd.isna(cash) and cash > 50:
        reasons.append("exceso de cash: cash promedio alto")
    if not pd.isna(stop_rate) and stop_rate > 25:
        reasons.append("stops frecuentes: alta proporción de salidas por stop")
    if not pd.isna(spy_return) and spy_return > 10 and not pd.isna(diff) and diff < -5 and not pd.isna(exposure) and exposure < 80:
        reasons.append("régimen SPY alcista donde la estrategia quedó defensiva")
    if not reasons and not pd.isna(diff) and diff < 0:
        reasons.append("underperformance vs SPY sin causa concluyente en columnas disponibles")
    if not reasons:
        reasons.append("sin deterioro claro contra SPY en la evidencia disponible")
    return reasons


def render_bad_periods_report(runs: list[RunAudit], yearly_all: pd.DataFrame, monthly_all: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    lines = [
        "# Bad periods report - DD20 champions",
        "",
        "Auditoría drawdown-first: preservar DD < 20% primero, mejorar CAGR segundo, y recién después años ganados vs SPY.",
        "",
        "## Criterios",
        f"- Empate anual/mensual: diferencia contra SPY entre -{YEARLY_TIE_THRESHOLD_PCT:.0f}% y +{YEARLY_TIE_THRESHOLD_PCT:.0f}%.",
        "- Las causas son inferencias desde exposición, cash, trades, stops y retorno relativo; si falta una columna, se reporta como limitación.",
        "",
    ]
    period_rows = []
    for run in runs:
        if yearly_all.empty and monthly_all.empty:
            continue
        y = yearly_all[yearly_all["run_id"] == run.run_id].copy()
        m = monthly_all[monthly_all["run_id"] == run.run_id].copy()
        worst_years = y.sort_values("diff_pct").head(5) if not y.empty else pd.DataFrame()
        focus_years = y[y["year"].isin([2023, 2024, 2025])] if not y.empty else pd.DataFrame()
        worst_months = m.sort_values("diff_pct").head(8) if not m.empty else pd.DataFrame()
        periods = []
        for _, row in pd.concat([worst_years, focus_years]).drop_duplicates(["run_id", "year"]).iterrows():
            year = int(row["year"])
            periods.append((str(year), pd.Timestamp(year=year, month=1, day=1), pd.Timestamp(year=year, month=12, day=31)))
        for _, row in worst_months.iterrows():
            start = pd.Timestamp(year=int(row["year"]), month=int(row["month"]), day=1)
            end = start + pd.offsets.MonthEnd(0)
            periods.append((str(row["period"]), start, end))
        stats = period_daily_stats(run, periods)
        if not stats.empty:
            period_rows.append(stats)

    period_stats = pd.concat(period_rows, ignore_index=True) if period_rows else pd.DataFrame()
    for run in runs:
        lines.extend([f"## {run.run_id}", "", f"Strategy: `{run.strategy_id}`", ""])
        y = yearly_all[yearly_all["run_id"] == run.run_id].copy() if not yearly_all.empty else pd.DataFrame()
        m = monthly_all[monthly_all["run_id"] == run.run_id].copy() if not monthly_all.empty else pd.DataFrame()
        if y.empty:
            lines.append("- Sin comparación anual disponible.")
        else:
            lines.extend(["### Peores años vs SPY", "", "| año | estrategia | SPY | diff | marca | inferencia |", "|---:|---:|---:|---:|:---|:---|"])
            for _, row in y.sort_values("diff_pct").head(5).iterrows():
                ps = period_stats[(period_stats["run_id"] == run.run_id) & (period_stats["period"] == str(int(row["year"])))]
                reasons = infer_bad_period_reasons(ps.iloc[0]) if not ps.empty else ["sin métricas diarias/trades suficientes"]
                lines.append(
                    f"| {int(row['year'])} | {row['strategy_return_pct']:.2f}% | {row['spy_return_pct']:.2f}% | {row['diff_pct']:.2f}% | {row['mark']} | {'; '.join(reasons)} |"
                )
        if not y.empty:
            lines.extend(["", "### Foco 2023-2025", "", "| año | estrategia | SPY | diff | lectura |", "|---:|---:|---:|---:|:---|"])
            for year in [2023, 2024, 2025]:
                row = y[y["year"] == year]
                if row.empty:
                    lines.append(f"| {year} | n/a | n/a | n/a | sin datos |")
                    continue
                row = row.iloc[0]
                ps = period_stats[(period_stats["run_id"] == run.run_id) & (period_stats["period"] == str(year))]
                reasons = infer_bad_period_reasons(ps.iloc[0]) if not ps.empty else ["sin métricas diarias/trades suficientes"]
                lines.append(
                    f"| {year} | {row['strategy_return_pct']:.2f}% | {row['spy_return_pct']:.2f}% | {row['diff_pct']:.2f}% | {'; '.join(reasons)} |"
                )
        if not m.empty:
            lines.extend(["", "### Peores meses vs SPY", "", "| mes | estrategia | SPY | diff | marca |", "|:---|---:|---:|---:|:---|"])
            for _, row in m.sort_values("diff_pct").head(8).iterrows():
                lines.append(
                    f"| {row['period']} | {row['strategy_return_pct']:.2f}% | {row['spy_return_pct']:.2f}% | {row['diff_pct']:.2f}% | {row['mark']} |"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n", period_stats


def render_readme(
    summary: pd.DataFrame,
    yearly: pd.DataFrame,
    drawdowns: pd.DataFrame,
    trade_quality: pd.DataFrame,
    warnings: list[str],
) -> str:
    lines = [
        "# DD20 Champion Audit",
        "",
        "Auditoría comparativa de las tres mejores candidatas DD20 detectadas esta semana. No se modificó lógica de trading, configs, baseline ni parent.",
        "",
        "## Conclusión rápida",
    ]
    if summary.empty:
        lines.append("- No hubo datos suficientes para elegir candidata.")
    else:
        s = summary.copy()
        s["dd_ok"] = s["max_drawdown_pct"] >= -20.0
        s["score"] = (
            s["dd_ok"].astype(int) * 1_000_000
            + s["CAGR"].fillna(-999) * 1_000
            + (s["years_won_vs_spy"] - s["years_lost_vs_spy"]).fillna(0) * 10
            + s["calmar_ratio"].fillna(0)
        )
        best = s.sort_values(["dd_ok", "CAGR", "calmar_ratio"], ascending=[False, False, False]).iloc[0]
        conservative = s.sort_values(["max_drawdown_pct", "calmar_ratio"], ascending=[False, False]).iloc[0]
        consistent = s.assign(year_net=s["years_won_vs_spy"] - s["years_lost_vs_spy"]).sort_values(
            ["year_net", "months_won_vs_spy", "CAGR"], ascending=[False, False, False]
        ).iloc[0]
        lines.extend(
            [
                f"- Mejor candidata drawdown-first: `{best['run_id']}` ({best['CAGR']:.2f}% CAGR, DD {best['max_drawdown_pct']:.2f}%).",
                f"- Más conservadora: `{conservative['run_id']}` (DD {conservative['max_drawdown_pct']:.2f}%).",
                f"- Mejor consistencia vs SPY: `{consistent['run_id']}` ({int(consistent['years_won_vs_spy'])}/{int(consistent['years_lost_vs_spy'])} años win/loss).",
            ]
        )
    lines.extend(
        [
            "",
            "## Tabla ejecutiva",
            "",
            "| run_id | CAGR | DD | SPY CAGR | excess CAGR | años W/L | meses W/L | trades | calmar |",
            "|:---|---:|---:|---:|---:|:---:|:---:|---:|---:|",
        ]
    )
    for _, row in summary.iterrows():
        lines.append(
            f"| `{row['run_id']}` | {row['CAGR']:.2f}% | {row['max_drawdown_pct']:.2f}% | {row['SPY_CAGR']:.2f}% | {row['excess_CAGR']:.2f}% | {int(row['years_won_vs_spy'])}/{int(row['years_lost_vs_spy'])} | {int(row['months_won_vs_spy'])}/{int(row['months_lost_vs_spy'])} | {int(row['trades'])} | {row['calmar_ratio']:.3f} |"
        )
    lines.extend(["", "## Principales debilidades"])
    if not yearly.empty:
        weak = yearly.sort_values("diff_pct").head(6)
        for _, row in weak.iterrows():
            lines.append(f"- `{row['run_id']}` tuvo debilidad fuerte en {int(row['year'])}: {row['diff_pct']:.2f}% vs SPY.")
    if not drawdowns.empty:
        dd = drawdowns.sort_values("drawdown_pct").groupby("run_id").head(1)
        for _, row in dd.iterrows():
            lines.append(
                f"- `{row['run_id']}` peor episodio DD: {row['drawdown_pct']:.2f}% entre {row['peak_date']} y {row['valley_date']}."
            )
    if not trade_quality.empty:
        losers = trade_quality[trade_quality["trade_bucket"] == "loser"]
        for _, row in losers.iterrows():
            lines.append(f"- `{row['run_id']}` perdedores: {int(row['trades'])} trades, mediana {row['median_return_pct']:.2f}%.")
    lines.extend(
        [
            "",
            "## Próximos experimentos recomendados",
            "- No promover baseline todavía: primero revisar los años/meses malos y la causa de defensividad vs SPY.",
            "- Separar experimento de asset-selection vs risk-management: si un año pierde por selección, tocar stop/guardrail no ataca la raíz.",
            "- Revisar exposición/cash en 2023-2025 antes de relajar guardrails. Si SPY subió fuerte y el sistema quedó en cash, el problema es oportunidad perdida, no solo DD.",
            "- Mantener el orden drawdown-first: DD < 20%, después CAGR, después años ganados vs SPY.",
            "",
            "## Archivos generados",
            "- `champion_summary.csv`",
            "- `yearly_vs_spy.csv`",
            "- `monthly_vs_spy.csv`",
            "- `drawdown_episodes.csv`",
            "- `trade_quality.csv`",
            "- `regime_breakdown.csv`",
            "- `bad_periods_report.md`",
            "- `README_AUDIT_DD20_CHAMPIONS.md`",
        ]
    )
    if warnings:
        lines.extend(["", "## Limitaciones de datos"])
        for warning in warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit DD20 champion runs against SPY.")
    parser.add_argument("--runs-dir", default=str(ROOT / "runs"))
    parser.add_argument("--reports-dir", default=str(ROOT / "reports"))
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--run-id", action="append", dest="run_ids", help="Run id to audit. Repeatable.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runs_dir = Path(args.runs_dir)
    reports_dir = Path(args.reports_dir)
    data_dir = Path(args.data_dir)
    run_ids = args.run_ids or DEFAULT_RUN_IDS
    output_dir = reports_dir / "dd20_champion_audit" / datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=False)

    runs = [find_run(runs_dir, run_id) for run_id in run_ids]
    sectors = load_sector_map(data_dir)
    spy_regime, regime_warnings = load_spy_regime_data(data_dir)

    summary_rows = []
    yearly_frames = []
    monthly_frames = []
    drawdown_frames = []
    trade_frames = []
    regime_frames = []
    warnings = [*regime_warnings]

    for run in runs:
        if not run.run_dir.exists():
            warnings.extend([f"{run.run_id}: {w}" for w in run.warnings])
            continue
        metrics = read_json(run.run_dir / "metrics.json")
        audit_json = read_json(run.run_dir / "audit.json")
        run.strategy_id = get_strategy_id(run.run_dir, metrics, audit_json)
        yearly = build_yearly(run)
        monthly = build_monthly(run)
        yearly_frames.append(yearly)
        monthly_frames.append(monthly)
        summary_rows.append(build_summary(run, yearly, monthly))
        drawdown_frames.append(build_drawdown_episodes(run))
        trade_frames.append(build_trade_quality(run, sectors))
        regime_frames.append(build_regime_breakdown(run, spy_regime))
        warnings.extend([f"{run.run_id}: {w}" for w in run.warnings])

    summary = pd.DataFrame(summary_rows)
    yearly_all = pd.concat([df for df in yearly_frames if not df.empty], ignore_index=True) if any(not df.empty for df in yearly_frames) else pd.DataFrame()
    monthly_all = pd.concat([df for df in monthly_frames if not df.empty], ignore_index=True) if any(not df.empty for df in monthly_frames) else pd.DataFrame()
    drawdowns = pd.concat([df for df in drawdown_frames if not df.empty], ignore_index=True) if any(not df.empty for df in drawdown_frames) else pd.DataFrame()
    trade_quality = pd.concat([df for df in trade_frames if not df.empty], ignore_index=True) if any(not df.empty for df in trade_frames) else pd.DataFrame()
    regime = pd.concat([df for df in regime_frames if not df.empty], ignore_index=True) if any(not df.empty for df in regime_frames) else pd.DataFrame()

    write_csv(summary, output_dir / "champion_summary.csv")
    write_csv(yearly_all, output_dir / "yearly_vs_spy.csv")
    write_csv(monthly_all, output_dir / "monthly_vs_spy.csv")
    write_csv(drawdowns, output_dir / "drawdown_episodes.csv")
    write_csv(trade_quality, output_dir / "trade_quality.csv")
    write_csv(regime, output_dir / "regime_breakdown.csv")

    bad_report, bad_stats = render_bad_periods_report(runs, yearly_all, monthly_all)
    (output_dir / "bad_periods_report.md").write_text(bad_report, encoding="utf-8")
    if not bad_stats.empty:
        write_csv(bad_stats, output_dir / "bad_period_metrics.csv")
    (output_dir / "README_AUDIT_DD20_CHAMPIONS.md").write_text(
        render_readme(summary, yearly_all, drawdowns, trade_quality, warnings),
        encoding="utf-8",
    )
    if warnings:
        (output_dir / "data_availability_warnings.md").write_text(
            "# Data availability warnings\n\n" + "\n".join(f"- {w}" for w in warnings) + "\n",
            encoding="utf-8",
        )

    print(f"DD20 champion audit written to: {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
