#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import importlib.util
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import warnings

import numpy as np
import pandas as pd
from pandas.errors import PerformanceWarning

# Pandas emite muchos PerformanceWarning por inserción incremental de columnas.
# No rompe el cálculo; solo avisa que puede ir más lento.
warnings.simplefilter("ignore", PerformanceWarning)


# =============================================================================
# CONFIG PRINCIPAL
# =============================================================================

# Módulo base del proyecto (descarga universe, OHLCV diario, weekly indicators, SPY ticker, etc.)
BASE_GENERATOR_PY = None
BASE_GENERATOR_GLOB = "sp500_rawprices_comm024_variable_sizing_spy_size_modulator_signals_all_extremes_with_first_touch.py"

OUTPUT_PREFIX = "sp500_feature_store"
OUTPUT_DIR = None  # None => misma carpeta que este script
EXPORT_FORMAT = "csv"  # csv | xlsx
CSV_ENCODING = "utf-8-sig"

# Rango de descarga/historia para poder calcular indicadores con lookback suficiente.
DOWNLOAD_START = "1999-01-01"
DOWNLOAD_END = "2026-12-31"

# Rango efectivo que querés exportar a los archivos maestros.
EXPORT_START = "1999-01-01"
EXPORT_END = "2026-12-31"

# Rango del snapshot semanal alineado a signal_date.
SNAPSHOT_START = EXPORT_START
SNAPSHOT_END = EXPORT_END

# Universo / descarga.
LOCAL_SP500_CSV = None
DOWNLOAD_WORKERS = 4
MIN_DAILY_ROWS = 300
MIN_WEEKLY_ROWS = 52

# Qué archivos generar.
EXPORT_DAILY_MASTER = True
EXPORT_WEEKLY_MASTER = True
EXPORT_SPY_DAILY_MASTER = True
EXPORT_SPY_WEEKLY_MASTER = False
EXPORT_SIGNAL_SNAPSHOT = True
EXPORT_ERRORS = True
EXPORT_DATA_DICTIONARY = True
EXPORT_RUN_CONFIG = True

# Cómo partir los archivos para que no pesen tanto.
SPLIT_DAILY_BY_YEAR = True
SPLIT_WEEKLY_BY_YEAR = False
SPLIT_SPY_DAILY_BY_YEAR = True
SPLIT_SPY_WEEKLY_BY_YEAR = False

# Si querés reducir tamaño, podés apagar tablas auxiliares en research.
INCLUDE_SIGNAL_SNAPSHOT_DAILY_COLUMNS = True


# =============================================================================
# HELPERS GENERALES
# =============================================================================


def ts_now() -> str:
    return datetime.now().strftime("%y%m%d%H%M%S")


TS_RUN = ts_now()


def clean_float(x) -> float:
    try:
        if x is None or (isinstance(x, str) and x.strip() == ""):
            return float("nan")
        return float(x)
    except Exception:
        return float("nan")


def ensure_output_dir() -> Path:
    if OUTPUT_DIR:
        out = Path(OUTPUT_DIR)
    else:
        out = Path(__file__).resolve().parent
    out.mkdir(parents=True, exist_ok=True)
    return out


OUT_DIR = ensure_output_dir()


def make_output_path(stem: str, ext: str) -> str:
    return str((OUT_DIR / f"{stem}.{ext}").resolve())


def parse_date_or_none(value: Optional[str]) -> Optional[pd.Timestamp]:
    if value is None:
        return None
    ts = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(ts) else pd.Timestamp(ts).normalize()


def pct_change_safe(series: pd.Series, periods: int) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    out = (s / s.shift(periods) - 1.0) * 100.0
    return out.replace([np.inf, -np.inf], np.nan)


def slope_pct(series: pd.Series, periods: int) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    out = (s / s.shift(periods) - 1.0) * 100.0
    return out.replace([np.inf, -np.inf], np.nan)


def rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    mu = s.rolling(window, min_periods=window).mean()
    sd = s.rolling(window, min_periods=window).std(ddof=0)
    out = (s - mu) / sd.replace(0, np.nan)
    return out.replace([np.inf, -np.inf], np.nan)


def compute_rsi(series: pd.Series, period: int) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    delta = s.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    roll_up = up.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    roll_down = down.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.replace([np.inf, -np.inf], np.nan)


def compute_true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    h = pd.to_numeric(high, errors="coerce")
    l = pd.to_numeric(low, errors="coerce")
    c = pd.to_numeric(close, errors="coerce")
    prev_close = c.shift(1)
    return pd.concat([
        h - l,
        (h - prev_close).abs(),
        (l - prev_close).abs(),
    ], axis=1).max(axis=1)


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    tr = compute_true_range(high, low, close)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def compute_stochastic(close: pd.Series, high: pd.Series, low: pd.Series, period: int = 14) -> pd.Series:
    c = pd.to_numeric(close, errors="coerce")
    h = pd.to_numeric(high, errors="coerce")
    l = pd.to_numeric(low, errors="coerce")
    hh = h.rolling(period, min_periods=period).max()
    ll = l.rolling(period, min_periods=period).min()
    return (((c - ll) / (hh - ll).replace(0, np.nan)) * 100.0).replace([np.inf, -np.inf], np.nan)


def compute_williams_r(close: pd.Series, high: pd.Series, low: pd.Series, period: int = 14) -> pd.Series:
    c = pd.to_numeric(close, errors="coerce")
    h = pd.to_numeric(high, errors="coerce")
    l = pd.to_numeric(low, errors="coerce")
    hh = h.rolling(period, min_periods=period).max()
    ll = l.rolling(period, min_periods=period).min()
    return (-100.0 * ((hh - c) / (hh - ll).replace(0, np.nan))).replace([np.inf, -np.inf], np.nan)


def compute_cci(close: pd.Series, high: pd.Series, low: pd.Series, period: int = 20) -> pd.Series:
    tp = (pd.to_numeric(high, errors="coerce") + pd.to_numeric(low, errors="coerce") + pd.to_numeric(close, errors="coerce")) / 3.0
    sma = tp.rolling(period, min_periods=period).mean()
    mad = tp.rolling(period, min_periods=period).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    cci = (tp - sma) / (0.015 * mad.replace(0, np.nan))
    return cci.replace([np.inf, -np.inf], np.nan)


def compute_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    c = pd.to_numeric(close, errors="coerce")
    v = pd.to_numeric(volume, errors="coerce").fillna(0.0)
    direction = np.sign(c.diff()).fillna(0.0)
    return (direction * v).cumsum()


def compute_streak(series: pd.Series, positive: bool = True) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").fillna(0.0)
    cond = s > 0 if positive else s < 0
    grp = (cond != cond.shift(1)).cumsum()
    streak = cond.groupby(grp).cumcount() + 1
    return streak.where(cond, 0).astype(float)


def normalize_ohlcv_columns(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    rename_map = {}
    for c in d.columns:
        cl = str(c).strip().lower()
        if cl == "open":
            rename_map[c] = "open"
        elif cl == "high":
            rename_map[c] = "high"
        elif cl == "low":
            rename_map[c] = "low"
        elif cl == "close":
            rename_map[c] = "close"
        elif cl in {"adj close", "adj_close", "adjclose"}:
            rename_map[c] = "adj_close"
        elif cl == "volume":
            rename_map[c] = "volume"
    return d.rename(columns=rename_map)


# =============================================================================
# CARGA DEL GENERADOR BASE
# =============================================================================

_RUNTIME_BASE_MOD = None
_RUNTIME_CONFIG_ATTRS = {
    "START_DAILY",
    "END_DAILY",
    "SIGNAL_START",
    "SIGNAL_END",
    "LOCAL_SP500_CSV",
    "USE_SPY_WEEKLY_FILTER",
    "SPY_TICKER",
    "MIN_HISTORY_WEEKS",
    "COMMISSION_PCT_PER_SIDE",
}


def locate_base_generator() -> Path:
    if BASE_GENERATOR_PY:
        p = Path(BASE_GENERATOR_PY)
        if not p.exists():
            raise FileNotFoundError(f"No encuentro BASE_GENERATOR_PY: {p}")
        return p
    here = Path(__file__).resolve().parent
    candidate = here / BASE_GENERATOR_GLOB
    if candidate.exists():
        return candidate
    matches = sorted(here.glob("sp500_rawprices_comm024_variable_sizing_spy_size_modulator_signals_all_extremes*_with_first_touch.py"))
    if not matches:
        raise FileNotFoundError(f"No encontré el generador base en {here}")
    return matches[0]


def sync_runtime_base_config(mod) -> None:
    # El módulo base necesita estas variables con nombres históricos.
    setattr(mod, "START_DAILY", DOWNLOAD_START)
    setattr(mod, "END_DAILY", DOWNLOAD_END)
    setattr(mod, "SIGNAL_START", SNAPSHOT_START)
    setattr(mod, "SIGNAL_END", SNAPSHOT_END)
    setattr(mod, "LOCAL_SP500_CSV", LOCAL_SP500_CSV)


def load_base_module(force_reload: bool = False):
    global _RUNTIME_BASE_MOD
    if _RUNTIME_BASE_MOD is not None and not force_reload:
        sync_runtime_base_config(_RUNTIME_BASE_MOD)
        return _RUNTIME_BASE_MOD
    path = locate_base_generator()
    spec = importlib.util.spec_from_file_location("base_generator_mod", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No pude cargar el módulo base desde {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sync_runtime_base_config(mod)
    _RUNTIME_BASE_MOD = mod
    return mod


# =============================================================================
# FEATURES DAILY
# =============================================================================


def build_daily_master_one(ticker: str, daily_raw: pd.DataFrame) -> pd.DataFrame:
    d = normalize_ohlcv_columns(daily_raw)
    if not isinstance(d.index, pd.DatetimeIndex):
        raise ValueError(f"{ticker} daily sin DatetimeIndex")

    out = pd.DataFrame(index=pd.to_datetime(d.index, errors="coerce").normalize())
    out["ticker"] = ticker
    out["date"] = out.index
    for col in ["open", "high", "low", "close", "adj_close", "volume"]:
        out[col] = pd.to_numeric(d[col], errors="coerce") if col in d.columns else np.nan
    out = out.sort_values("date").reset_index(drop=True)

    close = pd.to_numeric(out["close"], errors="coerce")
    high = pd.to_numeric(out["high"], errors="coerce")
    low = pd.to_numeric(out["low"], errors="coerce")
    open_ = pd.to_numeric(out["open"], errors="coerce")
    volume = pd.to_numeric(out["volume"], errors="coerce")

    out["year"] = out["date"].dt.year
    out["month"] = out["date"].dt.month
    out["day"] = out["date"].dt.day
    out["weekday"] = out["date"].dt.day_name()
    out["weekday_num"] = out["date"].dt.weekday
    out["weekofyear"] = out["date"].dt.isocalendar().week.astype(int)
    out["quarter"] = out["date"].dt.quarter

    for p in [1, 2, 3, 5, 10, 20, 60, 120]:
        out[f"ret_{p}d_pct"] = pct_change_safe(close, p)

    out["gap_open_pct"] = ((open_ / close.shift(1)) - 1.0).replace([np.inf, -np.inf], np.nan) * 100.0
    out["intraday_body_pct"] = ((close / open_) - 1.0).replace([np.inf, -np.inf], np.nan) * 100.0
    out["daily_range_pct"] = ((high / low) - 1.0).replace([np.inf, -np.inf], np.nan) * 100.0
    out["close_location_value"] = ((close - low) / (high - low).replace(0, np.nan))
    out["upper_wick_pct_of_range"] = ((high - np.maximum(open_, close)) / (high - low).replace(0, np.nan)) * 100.0
    out["lower_wick_pct_of_range"] = ((np.minimum(open_, close) - low) / (high - low).replace(0, np.nan)) * 100.0

    for p in [5, 10, 20, 50, 100, 200]:
        out[f"close_sma_{p}"] = close.rolling(p, min_periods=p).mean()
        out[f"close_vs_sma{p}_pct"] = ((close / out[f"close_sma_{p}"]) - 1.0) * 100.0
    for p in [5, 10, 20, 50]:
        out[f"close_ema_{p}"] = close.ewm(span=p, adjust=False, min_periods=p).mean()
        out[f"close_vs_ema{p}_pct"] = ((close / out[f"close_ema_{p}"]) - 1.0) * 100.0

    for p in [20, 50, 100, 200]:
        col = f"close_sma_{p}"
        for lag in [3, 5, 10, 20]:
            out[f"{col}_slope_{lag}d_pct"] = slope_pct(out[col], lag)
    for p in [20, 50]:
        col = f"close_ema_{p}"
        for lag in [3, 5, 10, 20]:
            out[f"{col}_slope_{lag}d_pct"] = slope_pct(out[col], lag)

    out["sma_5_gt_20"] = (out["close_sma_5"] > out["close_sma_20"]).astype(float)
    out["sma_10_gt_20"] = (out["close_sma_10"] > out["close_sma_20"]).astype(float)
    out["sma_20_gt_50"] = (out["close_sma_20"] > out["close_sma_50"]).astype(float)
    out["sma_50_gt_200"] = (out["close_sma_50"] > out["close_sma_200"]).astype(float)
    out["close_above_sma20"] = (close > out["close_sma_20"]).astype(float)
    out["close_above_sma50"] = (close > out["close_sma_50"]).astype(float)
    out["close_above_sma200"] = (close > out["close_sma_200"]).astype(float)
    out["days_above_sma20_last10"] = out["close_above_sma20"].rolling(10, min_periods=1).sum()
    out["days_above_sma50_last20"] = out["close_above_sma50"].rolling(20, min_periods=1).sum()

    for p in [2, 5, 14]:
        out[f"rsi_{p}"] = compute_rsi(close, p)
    out["stoch_k_14"] = compute_stochastic(close, high, low, 14)
    out["stoch_d_3"] = out["stoch_k_14"].rolling(3, min_periods=3).mean()
    out["williams_r_14"] = compute_williams_r(close, high, low, 14)
    out["cci_20"] = compute_cci(close, high, low, 20)
    for p in [3, 5, 10, 20]:
        out[f"roc_{p}"] = pct_change_safe(close, p)

    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    out["macd_line"] = ema12 - ema26
    out["macd_signal"] = out["macd_line"].ewm(span=9, adjust=False, min_periods=9).mean()
    out["macd_hist"] = out["macd_line"] - out["macd_signal"]

    for p in [5, 14, 20]:
        out[f"atr_{p}"] = compute_atr(high, low, close, p)
        out[f"atr_{p}_pct"] = (out[f"atr_{p}"] / close) * 100.0
    for p in [5, 10, 20, 60]:
        out[f"volatility_{p}d_pct"] = close.pct_change().rolling(p, min_periods=p).std(ddof=0) * np.sqrt(252) * 100.0
    out["range_expansion_vs_20d"] = out["daily_range_pct"] / out["daily_range_pct"].rolling(20, min_periods=20).mean()
    out["atr_5_vs_20"] = out["atr_5_pct"] / out["atr_20_pct"]

    for p in [5, 10, 20, 50]:
        out[f"volume_sma_{p}"] = volume.rolling(p, min_periods=p).mean()
        out[f"volume_ratio_vs_sma{p}"] = volume / out[f"volume_sma_{p}"]
    out["volume_ratio_5_vs_20"] = out["volume_sma_5"] / out["volume_sma_20"]
    out["volume_ratio_10_vs_20"] = out["volume_sma_10"] / out["volume_sma_20"]
    out["volume_climax_20d_flag"] = (out["volume_ratio_vs_sma20"] >= 2.0).astype(float)
    out["volume_dryup_20d_flag"] = (out["volume_ratio_vs_sma20"] <= 0.5).astype(float)
    out["obv"] = compute_obv(close, volume)
    out["obv_slope_5d_pct"] = slope_pct(out["obv"].replace(0, np.nan), 5)
    out["obv_slope_20d_pct"] = slope_pct(out["obv"].replace(0, np.nan), 20)

    for p in [10, 20, 50, 100, 200]:
        out[f"rolling_high_{p}"] = high.rolling(p, min_periods=p).max()
        out[f"rolling_low_{p}"] = low.rolling(p, min_periods=p).min()
        out[f"dist_to_high_{p}_pct"] = ((close / out[f"rolling_high_{p}"]) - 1.0) * 100.0
        out[f"dist_to_low_{p}_pct"] = ((close / out[f"rolling_low_{p}"]) - 1.0) * 100.0
        out[f"drawdown_from_high_{p}_pct"] = ((close / out[f"rolling_high_{p}"]) - 1.0) * 100.0

    out["zscore_close_20"] = rolling_zscore(close, 20)
    out["zscore_close_50"] = rolling_zscore(close, 50)
    out["red_day_flag"] = (close < close.shift(1)).astype(float)
    out["green_day_flag"] = (close > close.shift(1)).astype(float)
    out["red_days_last_5"] = out["red_day_flag"].rolling(5, min_periods=1).sum()
    out["red_days_last_10"] = out["red_day_flag"].rolling(10, min_periods=1).sum()
    out["green_days_last_5"] = out["green_day_flag"].rolling(5, min_periods=1).sum()
    out["up_streak_days"] = compute_streak(close.diff(), positive=True)
    out["down_streak_days"] = compute_streak(close.diff(), positive=False)

    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_open = open_.shift(1)
    prev_close = close.shift(1)
    out["inside_day_flag"] = ((high <= prev_high) & (low >= prev_low)).astype(float)
    out["outside_day_flag"] = ((high >= prev_high) & (low <= prev_low)).astype(float)
    out["higher_high_flag"] = (high > prev_high).astype(float)
    out["lower_low_flag"] = (low < prev_low).astype(float)
    out["bullish_engulfing_flag"] = ((close > open_) & (prev_close < prev_open) & (close >= prev_open) & (open_ <= prev_close)).astype(float)
    out["bearish_engulfing_flag"] = ((close < open_) & (prev_close > prev_open) & (close <= prev_open) & (open_ >= prev_close)).astype(float)
    body = (close - open_).abs()
    range_ = (high - low).replace(0, np.nan)
    out["hammer_flag"] = (((out["lower_wick_pct_of_range"] >= 50.0) & (body / range_ <= 0.35))).astype(float)
    out["shooting_star_flag"] = (((out["upper_wick_pct_of_range"] >= 50.0) & (body / range_ <= 0.35))).astype(float)

    numeric_cols = [c for c in out.columns if c not in {"ticker", "date", "weekday"}]
    for c in numeric_cols:
        if c in {"year", "month", "day", "weekday_num", "weekofyear", "quarter"}:
            continue
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.reset_index(drop=True)


# =============================================================================
# FEATURES WEEKLY
# =============================================================================


def normalize_weekly_frame(ticker: str, weekly_raw: pd.DataFrame) -> pd.DataFrame:
    w = normalize_ohlcv_columns(weekly_raw)
    if not isinstance(w.index, pd.DatetimeIndex):
        raise ValueError(f"{ticker} weekly sin DatetimeIndex")
    out = w.copy()
    out.index = pd.to_datetime(out.index, errors="coerce").normalize()
    out["ticker"] = ticker
    out["signal_date"] = out.index
    out = out.sort_values("signal_date")
    return out.reset_index(drop=True)


def add_weekly_features(weekly_df: pd.DataFrame) -> pd.DataFrame:
    out = weekly_df.copy()
    close = pd.to_numeric(out.get("close"), errors="coerce")
    high = pd.to_numeric(out.get("high"), errors="coerce")
    low = pd.to_numeric(out.get("low"), errors="coerce")
    open_ = pd.to_numeric(out.get("open"), errors="coerce")
    volume = pd.to_numeric(out.get("volume"), errors="coerce")

    out["year"] = pd.to_datetime(out["signal_date"]).dt.year
    out["month"] = pd.to_datetime(out["signal_date"]).dt.month
    out["quarter"] = pd.to_datetime(out["signal_date"]).dt.quarter
    out["weekofyear"] = pd.to_datetime(out["signal_date"]).dt.isocalendar().week.astype(int)

    for p in [1, 2, 4, 8, 12, 26, 52]:
        out[f"ret_{p}w_pct"] = pct_change_safe(close, p)

    out["weekly_range_pct"] = ((high / low) - 1.0).replace([np.inf, -np.inf], np.nan) * 100.0
    out["weekly_body_pct"] = ((close / open_) - 1.0).replace([np.inf, -np.inf], np.nan) * 100.0
    out["weekly_close_location_value"] = ((close - low) / (high - low).replace(0, np.nan))
    out["weekly_upper_wick_pct_of_range"] = ((high - np.maximum(open_, close)) / (high - low).replace(0, np.nan)) * 100.0
    out["weekly_lower_wick_pct_of_range"] = ((np.minimum(open_, close) - low) / (high - low).replace(0, np.nan)) * 100.0

    for p in [4, 8, 13, 20, 26, 40, 52]:
        out[f"close_sma_{p}w"] = close.rolling(p, min_periods=p).mean()
        out[f"close_vs_sma{p}w_pct"] = ((close / out[f"close_sma_{p}w"]) - 1.0) * 100.0
    for p in [4, 8, 13, 20, 26]:
        out[f"close_ema_{p}w"] = close.ewm(span=p, adjust=False, min_periods=p).mean()
        out[f"close_vs_ema{p}w_pct"] = ((close / out[f"close_ema_{p}w"]) - 1.0) * 100.0

    for p in [13, 20, 26, 40, 52]:
        col = f"close_sma_{p}w"
        for lag in [2, 4, 8]:
            out[f"{col}_slope_{lag}w_pct"] = slope_pct(out[col], lag)
    for p in [13, 20, 26]:
        col = f"close_ema_{p}w"
        for lag in [2, 4, 8]:
            out[f"{col}_slope_{lag}w_pct"] = slope_pct(out[col], lag)

    out["close_above_sma13w"] = (close > out["close_sma_13w"]).astype(float)
    out["close_above_sma26w"] = (close > out["close_sma_26w"]).astype(float)
    out["close_above_sma52w"] = (close > out["close_sma_52w"]).astype(float)
    out["sma13_gt_sma26w"] = (out["close_sma_13w"] > out["close_sma_26w"]).astype(float)
    out["sma26_gt_sma52w"] = (out["close_sma_26w"] > out["close_sma_52w"]).astype(float)
    out["weeks_above_sma13_last8"] = out["close_above_sma13w"].rolling(8, min_periods=1).sum()
    out["weeks_above_sma26_last13"] = out["close_above_sma26w"].rolling(13, min_periods=1).sum()

    for p in [2, 5, 14]:
        out[f"rsi_{p}w"] = compute_rsi(close, p)
    out["stoch_k_14w"] = compute_stochastic(close, high, low, 14)
    out["stoch_d_3w"] = out["stoch_k_14w"].rolling(3, min_periods=3).mean()
    out["williams_r_14w"] = compute_williams_r(close, high, low, 14)
    out["cci_20w"] = compute_cci(close, high, low, 20)
    for p in [2, 4, 8, 12, 26]:
        out[f"roc_{p}w"] = pct_change_safe(close, p)

    for p in [4, 8, 14]:
        out[f"atr_{p}w"] = compute_atr(high, low, close, p)
        out[f"atr_{p}w_pct"] = (out[f"atr_{p}w"] / close) * 100.0
    for p in [4, 8, 12, 26]:
        out[f"volatility_{p}w_pct"] = close.pct_change().rolling(p, min_periods=p).std(ddof=0) * np.sqrt(52) * 100.0
    out["weekly_range_expansion_vs_12w"] = out["weekly_range_pct"] / out["weekly_range_pct"].rolling(12, min_periods=12).mean()

    for p in [4, 8, 13, 26]:
        out[f"volume_sma_{p}w"] = volume.rolling(p, min_periods=p).mean()
        out[f"volume_ratio_vs_sma{p}w"] = volume / out[f"volume_sma_{p}w"]
    out["volume_ratio_4_vs_13w"] = out["volume_sma_4w"] / out["volume_sma_13w"]
    out["volume_climax_13w_flag"] = (out["volume_ratio_vs_sma13w"] >= 2.0).astype(float)
    out["volume_dryup_13w_flag"] = (out["volume_ratio_vs_sma13w"] <= 0.5).astype(float)
    out["obv_w"] = compute_obv(close, volume)
    out["obv_w_slope_4w_pct"] = slope_pct(out["obv_w"].replace(0, np.nan), 4)
    out["obv_w_slope_13w_pct"] = slope_pct(out["obv_w"].replace(0, np.nan), 13)

    for p in [13, 26, 52]:
        out[f"rolling_high_{p}w"] = high.rolling(p, min_periods=p).max()
        out[f"rolling_low_{p}w"] = low.rolling(p, min_periods=p).min()
        out[f"dist_to_high_{p}w_pct"] = ((close / out[f"rolling_high_{p}w"]) - 1.0) * 100.0
        out[f"dist_to_low_{p}w_pct"] = ((close / out[f"rolling_low_{p}w"]) - 1.0) * 100.0
        out[f"drawdown_from_high_{p}w_pct"] = ((close / out[f"rolling_high_{p}w"]) - 1.0) * 100.0

    out["zscore_close_13w"] = rolling_zscore(close, 13)
    out["zscore_close_26w"] = rolling_zscore(close, 26)
    out["red_week_flag"] = (close < close.shift(1)).astype(float)
    out["green_week_flag"] = (close > close.shift(1)).astype(float)
    out["red_weeks_last_4"] = out["red_week_flag"].rolling(4, min_periods=1).sum()
    out["red_weeks_last_8"] = out["red_week_flag"].rolling(8, min_periods=1).sum()
    out["red_weeks_last_12"] = out["red_week_flag"].rolling(12, min_periods=1).sum()
    out["up_streak_weeks"] = compute_streak(close.diff(), positive=True)
    out["down_streak_weeks"] = compute_streak(close.diff(), positive=False)

    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_open = open_.shift(1)
    prev_close = close.shift(1)
    out["inside_week_flag"] = ((high <= prev_high) & (low >= prev_low)).astype(float)
    out["outside_week_flag"] = ((high >= prev_high) & (low <= prev_low)).astype(float)
    out["bullish_engulfing_week_flag"] = ((close > open_) & (prev_close < prev_open) & (close >= prev_open) & (open_ <= prev_close)).astype(float)
    out["bearish_engulfing_week_flag"] = ((close < open_) & (prev_close > prev_open) & (close <= prev_open) & (open_ >= prev_close)).astype(float)
    body = (close - open_).abs()
    range_ = (high - low).replace(0, np.nan)
    out["hammer_week_flag"] = (((out["weekly_lower_wick_pct_of_range"] >= 50.0) & (body / range_ <= 0.35))).astype(float)
    out["shooting_star_week_flag"] = (((out["weekly_upper_wick_pct_of_range"] >= 50.0) & (body / range_ <= 0.35))).astype(float)

    for col in out.columns:
        if col not in {"ticker", "signal_date"}:
            try:
                out[col] = pd.to_numeric(out[col], errors="ignore")
            except Exception:
                pass
    return out.reset_index(drop=True)


# =============================================================================
# BUILDERS
# =============================================================================


def load_one_ticker_payload(mod, ticker: str) -> Tuple[str, Optional[Dict[str, pd.DataFrame]], Optional[str]]:
    try:
        daily = mod.download_daily_ohlcv(ticker, DOWNLOAD_START, DOWNLOAD_END)
        if daily is None or daily.empty or len(daily) < MIN_DAILY_ROWS:
            return ticker, None, None
        weekly_raw = mod.daily_to_weekly(daily)
        if weekly_raw is None or weekly_raw.empty or len(weekly_raw) < MIN_WEEKLY_ROWS:
            return ticker, None, None
        weekly_ind = mod.compute_weekly_indicators(weekly_raw.copy())
        return ticker, {"daily": daily, "weekly_ind": weekly_ind}, None
    except Exception as e:
        return ticker, None, str(e)


def build_feature_store(mod):
    tickers = mod.get_sp500_tickers_current(local_csv_path=LOCAL_SP500_CSV)
    data_by_ticker: Dict[str, Dict[str, pd.DataFrame]] = {}
    errors: List[Tuple[str, str]] = []

    if DOWNLOAD_WORKERS <= 1:
        for ticker in tickers:
            t, payload, err = load_one_ticker_payload(mod, ticker)
            if err:
                errors.append((t, err))
            elif payload is not None:
                data_by_ticker[t] = payload
    else:
        futures = {}
        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as ex:
            for ticker in tickers:
                futures[ex.submit(load_one_ticker_payload, mod, ticker)] = ticker
            done = 0
            for fut in as_completed(futures):
                done += 1
                t, payload, err = fut.result()
                print(f"[{done}/{len(tickers)}] {t}")
                if err:
                    errors.append((t, err))
                elif payload is not None:
                    data_by_ticker[t] = payload

    daily_parts: List[pd.DataFrame] = []
    weekly_parts: List[pd.DataFrame] = []

    for ticker, payload in data_by_ticker.items():
        try:
            daily_parts.append(build_daily_master_one(ticker, payload["daily"]))
        except Exception as e:
            errors.append((ticker, f"daily_master: {e}"))
            continue

        try:
            weekly_norm = normalize_weekly_frame(ticker, payload["weekly_ind"])
            weekly_parts.append(add_weekly_features(weekly_norm))
        except Exception as e:
            errors.append((ticker, f"weekly_master: {e}"))
            continue

    daily_master = pd.concat(daily_parts, ignore_index=True) if daily_parts else pd.DataFrame()
    weekly_master = pd.concat(weekly_parts, ignore_index=True) if weekly_parts else pd.DataFrame()
    errors_df = pd.DataFrame(errors, columns=["ticker", "error"]) if errors else pd.DataFrame(columns=["ticker", "error"])
    return daily_master, weekly_master, errors_df


def build_spy_masters(mod) -> Tuple[pd.DataFrame, pd.DataFrame]:
    spy_ticker = getattr(mod, "SPY_TICKER", "SPY")
    spy_daily_raw = mod.download_daily_ohlcv(spy_ticker, DOWNLOAD_START, DOWNLOAD_END)
    if spy_daily_raw is None or spy_daily_raw.empty:
        return pd.DataFrame(), pd.DataFrame()
    spy_daily_master = build_daily_master_one(spy_ticker, spy_daily_raw)
    spy_weekly_ind = mod.compute_weekly_indicators(mod.daily_to_weekly(spy_daily_raw))
    spy_weekly_master = add_weekly_features(normalize_weekly_frame(spy_ticker, spy_weekly_ind))
    return spy_daily_master, spy_weekly_master


def merge_spy_and_relative_daily(daily_master: pd.DataFrame, spy_daily: pd.DataFrame) -> pd.DataFrame:
    if daily_master.empty or spy_daily.empty:
        return daily_master

    out = daily_master.copy()
    spy = spy_daily.copy()
    spy_feature_cols = [c for c in spy.columns if c not in {"ticker", "date", "weekday"}]
    rename = {c: f"spy_{c}" for c in spy_feature_cols if c != "date"}
    spy = spy.rename(columns=rename)
    spy = spy[["date"] + list(rename.values())].copy()
    out = out.merge(spy, on="date", how="left")

    for c in ["ret_1d_pct", "ret_5d_pct", "ret_20d_pct", "close_vs_sma20_pct", "close_vs_sma50_pct", "rsi_14", "daily_range_pct"]:
        spy_c = f"spy_{c}"
        if c in out.columns and spy_c in out.columns:
            out[f"rel_{c}_minus_spy"] = out[c] - out[spy_c]
    if "spy_close" in out.columns:
        out["close_vs_spy_ratio"] = out["close"] / out["spy_close"].replace(0, np.nan)

    out = out.sort_values(["ticker", "date"]).reset_index(drop=True)

    if "spy_ret_1d_pct" in out.columns:
        def add_roll(g: pd.DataFrame) -> pd.DataFrame:
            asset_ret = pd.to_numeric(g["ret_1d_pct"], errors="coerce") / 100.0
            spy_ret = pd.to_numeric(g["spy_ret_1d_pct"], errors="coerce") / 100.0
            for w in [20, 60]:
                cov = asset_ret.rolling(w, min_periods=w).cov(spy_ret)
                var = spy_ret.rolling(w, min_periods=w).var(ddof=0)
                g[f"beta_vs_spy_{w}d"] = cov / var.replace(0, np.nan)
                g[f"corr_vs_spy_{w}d"] = asset_ret.rolling(w, min_periods=w).corr(spy_ret)
            if "ret_20d_pct" in g.columns and "spy_ret_20d_pct" in g.columns:
                g["ret_20d_minus_spy"] = g["ret_20d_pct"] - g["spy_ret_20d_pct"]
            return g
        out = out.groupby("ticker", group_keys=False).apply(add_roll).reset_index(drop=True)

    return out


def merge_spy_and_relative_weekly(weekly_master: pd.DataFrame, spy_weekly: pd.DataFrame) -> pd.DataFrame:
    if weekly_master.empty or spy_weekly.empty:
        return weekly_master

    out = weekly_master.copy()
    spy = spy_weekly.copy()
    spy_feature_cols = [c for c in spy.columns if c not in {"ticker", "signal_date"}]
    rename = {c: f"spy_{c}" for c in spy_feature_cols if c != "signal_date"}
    spy = spy.rename(columns=rename)
    spy = spy[["signal_date"] + list(rename.values())].copy()
    out = out.merge(spy, on="signal_date", how="left")

    for c in ["channel_r2", "channel_slope_pct", "close_vs_sma50_pct", "close_sma_50_slope_5d_pct", "ret_4w_pct", "ret_12w_pct", "rsi_14w", "weekly_range_pct"]:
        spy_c = f"spy_{c}"
        if c in out.columns and spy_c in out.columns:
            out[f"rel_{c}_minus_spy"] = out[c] - out[spy_c]

    out = out.sort_values(["ticker", "signal_date"]).reset_index(drop=True)

    if "spy_ret_1w_pct" in out.columns:
        def add_roll(g: pd.DataFrame) -> pd.DataFrame:
            asset_ret = pd.to_numeric(g["ret_1w_pct"], errors="coerce") / 100.0
            spy_ret = pd.to_numeric(g["spy_ret_1w_pct"], errors="coerce") / 100.0
            for w in [8, 13, 26]:
                cov = asset_ret.rolling(w, min_periods=w).cov(spy_ret)
                var = spy_ret.rolling(w, min_periods=w).var(ddof=0)
                g[f"beta_vs_spy_{w}w"] = cov / var.replace(0, np.nan)
                g[f"corr_vs_spy_{w}w"] = asset_ret.rolling(w, min_periods=w).corr(spy_ret)
            if "ret_12w_pct" in g.columns and "spy_ret_12w_pct" in g.columns:
                g["ret_12w_minus_spy"] = g["ret_12w_pct"] - g["spy_ret_12w_pct"]
            return g
        out = out.groupby("ticker", group_keys=False).apply(add_roll).reset_index(drop=True)

    return out


def build_signal_snapshot(weekly_master: pd.DataFrame, daily_master: pd.DataFrame) -> pd.DataFrame:
    if weekly_master.empty:
        return pd.DataFrame()

    start_ts = parse_date_or_none(SNAPSHOT_START)
    end_ts = parse_date_or_none(SNAPSHOT_END)

    snap = weekly_master.copy()
    snap["signal_date"] = pd.to_datetime(snap["signal_date"], errors="coerce").dt.normalize()
    if start_ts is not None:
        snap = snap[snap["signal_date"] >= start_ts].copy()
    if end_ts is not None:
        snap = snap[snap["signal_date"] <= end_ts].copy()
    if snap.empty or daily_master.empty or not INCLUDE_SIGNAL_SNAPSHOT_DAILY_COLUMNS:
        return snap

    asset_daily_cols = [
        "ticker", "date",
        "ret_1d_pct", "ret_3d_pct", "ret_5d_pct", "ret_10d_pct", "ret_20d_pct",
        "daily_range_pct", "intraday_body_pct", "close_location_value",
        "close_vs_sma20_pct", "close_vs_sma50_pct", "close_vs_sma200_pct",
        "close_sma_50_slope_5d_pct", "rsi_2", "rsi_5", "rsi_14",
        "atr_14_pct", "volume_ratio_vs_sma20", "red_days_last_5", "down_streak_days",
        "inside_day_flag", "outside_day_flag", "bullish_engulfing_flag", "hammer_flag",
        "spy_ret_1d_pct", "spy_ret_5d_pct", "spy_ret_20d_pct",
        "spy_close_vs_sma20_pct", "spy_close_vs_sma50_pct", "spy_rsi_14",
        "beta_vs_spy_20d", "corr_vs_spy_20d",
    ]

    dm = daily_master.copy()
    for c in asset_daily_cols:
        if c not in dm.columns and c not in {"ticker", "date"}:
            dm[c] = np.nan
    daily_sig = dm[asset_daily_cols].copy().rename(columns={"date": "signal_date"})
    rename_map = {c: f"daily_{c}" for c in daily_sig.columns if c not in {"ticker", "signal_date"}}
    daily_sig = daily_sig.rename(columns=rename_map)
    return snap.merge(daily_sig, on=["ticker", "signal_date"], how="left")


# =============================================================================
# FILTROS DE EXPORTACIÓN
# =============================================================================


def filter_daily_export_range(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()
    start_ts = parse_date_or_none(EXPORT_START)
    end_ts = parse_date_or_none(EXPORT_END)
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    if start_ts is not None:
        out = out[out["date"] >= start_ts].copy()
    if end_ts is not None:
        out = out[out["date"] <= end_ts].copy()
    return out.reset_index(drop=True)


def filter_weekly_export_range(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()
    start_ts = parse_date_or_none(EXPORT_START)
    end_ts = parse_date_or_none(EXPORT_END)
    out = df.copy()
    out["signal_date"] = pd.to_datetime(out["signal_date"], errors="coerce").dt.normalize()
    if start_ts is not None:
        out = out[out["signal_date"] >= start_ts].copy()
    if end_ts is not None:
        out = out[out["signal_date"] <= end_ts].copy()
    return out.reset_index(drop=True)


# =============================================================================
# EXPORTS
# =============================================================================


def export_table(df: pd.DataFrame, stem: str, sheet_name: str) -> str:
    if EXPORT_FORMAT == "xlsx":
        path = make_output_path(stem, "xlsx")
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
        return path
    path = make_output_path(stem, "csv")
    df.to_csv(path, index=False, encoding=CSV_ENCODING)
    return path


def export_table_by_year(df: pd.DataFrame, date_col: str, stem_prefix: str, sheet_name_prefix: str) -> List[str]:
    if df is None or df.empty:
        return []
    out = df.copy()
    out[date_col] = pd.to_datetime(out[date_col], errors="coerce")
    out = out.dropna(subset=[date_col]).copy()
    if out.empty:
        return []
    paths: List[str] = []
    for year in sorted(out[date_col].dt.year.dropna().unique()):
        part = out[out[date_col].dt.year == year].copy().reset_index(drop=True)
        if part.empty:
            continue
        stem = f"{stem_prefix}_{int(year)}_{TS_RUN}"
        paths.append(export_table(part, stem, f"{sheet_name_prefix}_{int(year)}"))
    return paths


def build_data_dictionary(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, df in frames.items():
        if df is None or df.empty:
            continue
        for col in df.columns:
            rows.append({
                "dataset": name,
                "column_name": col,
                "dtype": str(df[col].dtype),
            })
    return pd.DataFrame(rows)


def build_run_config() -> pd.DataFrame:
    rows = [
        ("base_generator_py", BASE_GENERATOR_PY),
        ("base_generator_glob", BASE_GENERATOR_GLOB),
        ("output_prefix", OUTPUT_PREFIX),
        ("output_dir", str(OUT_DIR)),
        ("export_format", EXPORT_FORMAT),
        ("download_start", DOWNLOAD_START),
        ("download_end", DOWNLOAD_END),
        ("export_start", EXPORT_START),
        ("export_end", EXPORT_END),
        ("snapshot_start", SNAPSHOT_START),
        ("snapshot_end", SNAPSHOT_END),
        ("local_sp500_csv", LOCAL_SP500_CSV),
        ("download_workers", DOWNLOAD_WORKERS),
        ("min_daily_rows", MIN_DAILY_ROWS),
        ("min_weekly_rows", MIN_WEEKLY_ROWS),
        ("export_daily_master", EXPORT_DAILY_MASTER),
        ("export_weekly_master", EXPORT_WEEKLY_MASTER),
        ("export_spy_daily_master", EXPORT_SPY_DAILY_MASTER),
        ("export_spy_weekly_master", EXPORT_SPY_WEEKLY_MASTER),
        ("export_signal_snapshot", EXPORT_SIGNAL_SNAPSHOT),
        ("split_daily_by_year", SPLIT_DAILY_BY_YEAR),
        ("split_weekly_by_year", SPLIT_WEEKLY_BY_YEAR),
        ("split_spy_daily_by_year", SPLIT_SPY_DAILY_BY_YEAR),
        ("split_spy_weekly_by_year", SPLIT_SPY_WEEKLY_BY_YEAR),
        ("include_signal_snapshot_daily_columns", INCLUDE_SIGNAL_SNAPSHOT_DAILY_COLUMNS),
        ("ts_run", TS_RUN),
    ]
    return pd.DataFrame(rows, columns=["config_key", "config_value"])


# =============================================================================
# MAIN
# =============================================================================


def main() -> None:
    mod = load_base_module()

    print("=" * 110)
    print("GENERADOR LIMPIO DE FEATURE STORE - SIN BACKTEST / SIN EVALUACIÓN")
    print(f"Generador base:        {locate_base_generator()}")
    print(f"Download range:        {DOWNLOAD_START} -> {DOWNLOAD_END}")
    print(f"Effective export:      {EXPORT_START} -> {EXPORT_END}")
    print(f"Effective snapshot:    {SNAPSHOT_START} -> {SNAPSHOT_END}")
    print(f"Formato export:        {EXPORT_FORMAT}")
    print(f"Output dir:            {OUT_DIR}")
    print(f"Download workers:      {DOWNLOAD_WORKERS}")
    print("=" * 110)

    print("Descargando universo y calculando features...")
    daily_master, weekly_master, errors_df = build_feature_store(mod)
    print(f"Daily master bruto:    {len(daily_master):,} filas")
    print(f"Weekly master bruto:   {len(weekly_master):,} filas")

    print("Armando SPY master...")
    spy_daily_master, spy_weekly_master = build_spy_masters(mod)

    print("Mergeando SPY y relaciones relativas...")
    daily_master = merge_spy_and_relative_daily(daily_master, spy_daily_master)
    weekly_master = merge_spy_and_relative_weekly(weekly_master, spy_weekly_master)

    print("Filtrando rango efectivo de exportación...")
    daily_export = filter_daily_export_range(daily_master)
    weekly_export = filter_weekly_export_range(weekly_master)
    spy_daily_export = filter_daily_export_range(spy_daily_master)
    spy_weekly_export = filter_weekly_export_range(spy_weekly_master)

    print(f"Daily master export:   {len(daily_export):,} filas")
    print(f"Weekly master export:  {len(weekly_export):,} filas")
    print(f"SPY daily export:      {len(spy_daily_export):,} filas")
    print(f"SPY weekly export:     {len(spy_weekly_export):,} filas")

    signal_snapshot = pd.DataFrame()
    if EXPORT_SIGNAL_SNAPSHOT:
        print("Armando signal snapshot...")
        signal_snapshot = build_signal_snapshot(weekly_export, daily_export)
        print(f"Signal snapshot:       {len(signal_snapshot):,} filas")

    outputs: List[Tuple[str, str]] = []

    if EXPORT_DAILY_MASTER:
        if SPLIT_DAILY_BY_YEAR:
            for p in export_table_by_year(daily_export, "date", f"{OUTPUT_PREFIX}_daily_master", "daily_master"):
                outputs.append(("Daily Master", p))
        else:
            p = export_table(daily_export, f"{OUTPUT_PREFIX}_daily_master_{TS_RUN}", "daily_master")
            outputs.append(("Daily Master", p))

    if EXPORT_WEEKLY_MASTER:
        if SPLIT_WEEKLY_BY_YEAR:
            for p in export_table_by_year(weekly_export, "signal_date", f"{OUTPUT_PREFIX}_weekly_master", "weekly_master"):
                outputs.append(("Weekly Master", p))
        else:
            p = export_table(weekly_export, f"{OUTPUT_PREFIX}_weekly_master_{TS_RUN}", "weekly_master")
            outputs.append(("Weekly Master", p))

    if EXPORT_SPY_DAILY_MASTER:
        if SPLIT_SPY_DAILY_BY_YEAR:
            for p in export_table_by_year(spy_daily_export, "date", f"{OUTPUT_PREFIX}_spy_daily_master", "spy_daily_master"):
                outputs.append(("SPY Daily Master", p))
        else:
            p = export_table(spy_daily_export, f"{OUTPUT_PREFIX}_spy_daily_master_{TS_RUN}", "spy_daily_master")
            outputs.append(("SPY Daily Master", p))

    if EXPORT_SPY_WEEKLY_MASTER:
        if SPLIT_SPY_WEEKLY_BY_YEAR:
            for p in export_table_by_year(spy_weekly_export, "signal_date", f"{OUTPUT_PREFIX}_spy_weekly_master", "spy_weekly_master"):
                outputs.append(("SPY Weekly Master", p))
        else:
            p = export_table(spy_weekly_export, f"{OUTPUT_PREFIX}_spy_weekly_master_{TS_RUN}", "spy_weekly_master")
            outputs.append(("SPY Weekly Master", p))

    if EXPORT_SIGNAL_SNAPSHOT:
        p = export_table(signal_snapshot, f"{OUTPUT_PREFIX}_signal_snapshot_{TS_RUN}", "signal_snapshot")
        outputs.append(("Signal Snapshot", p))

    if EXPORT_ERRORS:
        p = export_table(errors_df, f"{OUTPUT_PREFIX}_errors_{TS_RUN}", "errors")
        outputs.append(("Errors", p))

    if EXPORT_DATA_DICTIONARY:
        data_dict = build_data_dictionary({
            "daily_master": daily_export,
            "weekly_master": weekly_export,
            "spy_daily_master": spy_daily_export,
            "spy_weekly_master": spy_weekly_export,
            "signal_snapshot": signal_snapshot,
        })
        p = export_table(data_dict, f"{OUTPUT_PREFIX}_data_dictionary_{TS_RUN}", "data_dictionary")
        outputs.append(("Data Dictionary", p))

    if EXPORT_RUN_CONFIG:
        run_config_df = build_run_config()
        p = export_table(run_config_df, f"{OUTPUT_PREFIX}_run_config_{TS_RUN}", "run_config")
        outputs.append(("Run Config", p))

    print("=" * 110)
    print("Listo. Archivos generados:")
    for name, path in outputs:
        print(f"{name:<20}: {path}")
    print("=" * 110)


if __name__ == "__main__":
    main()
