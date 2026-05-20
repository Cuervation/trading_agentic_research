"""Generated candidate feature engineering script. Writes a new output CSV."""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd


def read_feature_csv(path: str) -> pd.DataFrame:
    # Auto-detect delimiter so both comma and semicolon exports work.
    return pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")


def add_supported_features(df: pd.DataFrame) -> pd.DataFrame:
    date_col = "date" if "date" in df.columns else "signal_date" if "signal_date" in df.columns else None
    missing = {"ticker", "close"}.difference(df.columns)
    if date_col is None:
        missing.add("date or signal_date")
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    out = df.copy()
    out["_feature_sort_date"] = pd.to_datetime(out[date_col])
    out = out.sort_values(["ticker", "_feature_sort_date"])
    g = out.groupby("ticker", group_keys=False)
    if "ret_13w_pct" not in out.columns:
        out["ret_13w_pct"] = g["close"].pct_change(13) * 100
    if "ret_26w_pct" not in out.columns:
        out["ret_26w_pct"] = g["close"].pct_change(26) * 100
    if "ret_52w_pct" not in out.columns:
        out["ret_52w_pct"] = g["close"].pct_change(52) * 100
    if "close_vs_sma20w_pct" not in out.columns:
        sma20 = g["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
        out["close_vs_sma20w_pct"] = (out["close"] / sma20 - 1) * 100
    if "close_vs_sma52w_pct" not in out.columns:
        sma52 = g["close"].transform(lambda s: s.rolling(52, min_periods=52).mean())
        out["close_vs_sma52w_pct"] = (out["close"] / sma52 - 1) * 100
    if "channel_r2" not in out.columns:
        def rolling_r2(close: pd.Series, window: int = 52) -> pd.Series:
            y = np.log(close.astype(float).replace(0, np.nan))
            x = np.arange(window, dtype=float)
            def calc(arr):
                if np.isnan(arr).any():
                    return np.nan
                corr = np.corrcoef(x, arr)[0, 1]
                return float(corr*corr) if np.isfinite(corr) else np.nan
            return y.rolling(window, min_periods=window).apply(calc, raw=True)
        out["channel_r2"] = g["close"].transform(rolling_r2)
    if "atr_14w_pct" not in out.columns and {"high", "low", "close"}.issubset(out.columns):
        prev_close = g["close"].shift(1)
        tr = pd.concat([
            (out["high"]-out["low"]).abs(),
            (out["high"]-prev_close).abs(),
            (out["low"]-prev_close).abs(),
        ], axis=1).max(axis=1)
        out["atr_14w_pct"] = tr.groupby(out["ticker"]).transform(lambda s: s.rolling(14, min_periods=14).mean()) / out["close"] * 100
    if "downside_vol_13w_pct" not in out.columns:
        weekly_ret = g["close"].pct_change() * 100
        downside_squared = weekly_ret.where(weekly_ret < 0, 0.0).pow(2)
        out["downside_vol_13w_pct"] = downside_squared.groupby(out["ticker"]).transform(
            lambda s: np.sqrt(s.rolling(13, min_periods=8).mean())
        )
    if "realized_vol_13w_pct" not in out.columns:
        weekly_ret = g["close"].pct_change() * 100
        out["realized_vol_13w_pct"] = weekly_ret.groupby(out["ticker"]).transform(
            lambda s: s.rolling(13, min_periods=8).std()
        )
    if "residual_ret_26w_pct" not in out.columns and "ret_26w_pct" in out.columns:
        spy_ret = out[out["ticker"].astype(str).str.upper()=="SPY"][["_feature_sort_date", "ret_26w_pct"]].rename(
            columns={"ret_26w_pct": "_spy_ret_26w_pct"}
        )
        if not spy_ret.empty:
            out = out.merge(spy_ret, on="_feature_sort_date", how="left")
            out["residual_ret_26w_pct"] = out["ret_26w_pct"] - out["_spy_ret_26w_pct"]
            out = out.drop(columns=["_spy_ret_26w_pct"])
    if "market_breadth_above_sma50_pct" not in out.columns:
        if "close_vs_sma50_pct" in out.columns:
            breadth = out.assign(_above_sma50=out["close_vs_sma50_pct"] > 0).groupby("_feature_sort_date")["_above_sma50"].mean() * 100
            out["market_breadth_above_sma50_pct"] = out["_feature_sort_date"].map(breadth)
        elif "close_above_sma50" in out.columns:
            breadth = out.groupby("_feature_sort_date")["close_above_sma50"].mean() * 100
            out["market_breadth_above_sma50_pct"] = out["_feature_sort_date"].map(breadth)
    if "max_drawdown_26w_pct" not in out.columns:
        def rolling_max_drawdown(close: pd.Series, window: int = 26) -> pd.Series:
            def calc(arr):
                arr = np.asarray(arr, dtype=float)
                if np.isnan(arr).any():
                    return np.nan
                peak = np.maximum.accumulate(arr)
                drawdowns = arr / peak - 1.0
                return float(drawdowns.min() * 100)
            return close.astype(float).rolling(window, min_periods=window).apply(calc, raw=True)
        out["max_drawdown_26w_pct"] = g["close"].transform(rolling_max_drawdown)
    if "spy_close_vs_sma50_pct" not in out.columns:
        spy = out[out["ticker"].astype(str).str.upper()=="SPY"][["_feature_sort_date", "close"]].copy()
        if not spy.empty:
            spy = spy.sort_values("_feature_sort_date")
            spy["spy_close_vs_sma50_pct"] = (spy["close"] / spy["close"].rolling(50, min_periods=50).mean() - 1) * 100
            out = out.merge(spy[["_feature_sort_date", "spy_close_vs_sma50_pct"]], on="_feature_sort_date", how="left")
    out = out.drop(columns=["_feature_sort_date"])
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    out = add_supported_features(read_feature_csv(args.input))
    out.to_csv(args.output, index=False)
    print({"input": args.input, "output": args.output, "rows": len(out), "columns": list(out.columns)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
