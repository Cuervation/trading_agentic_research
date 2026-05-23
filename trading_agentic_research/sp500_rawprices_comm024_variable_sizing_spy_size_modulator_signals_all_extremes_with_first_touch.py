
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import warnings
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

warnings.filterwarnings("ignore", category=FutureWarning)

# =============================================================================
# CONFIG
# =============================================================================

START_DAILY = "2000-01-01"
END_DAILY = "2026-05-23"
SIGNAL_START = "2000-01-01"
SIGNAL_END = "2026-05-23"

USE_ADJ_CLOSE = False

MAX_HOLD_WEEKS = 52
MIN_AVG_DOLLAR_VOL = 20_000_000
MIN_HISTORY_WEEKS = 210

# Canal alcista explícito
CHANNEL_WINDOW_WEEKS = 52
CHANNEL_WIDTH_SIGMA = 1.5
LOWER_TOUCH_TOL_PCT = 0.02
MAX_DISTANCE_TO_CHANNEL_LOWER_PCT = 0.8
MIN_CHANNEL_SLOPE_PCT_52W = 0.0
MIN_CHANNEL_R2 = 0.60
UPSIDE_TARGET_LOOKBACK_WEEKS = 20

# Filtro SPY semanal
USE_SPY_WEEKLY_FILTER = False
SPY_TICKER = "SPY"
SPY_REGIME_EMA_WEEKS = 20
SPY_REGIME_REQUIRE_PRICE_ABOVE_EMA = True
SPY_REGIME_REQUIRE_EMA_UP = True

# Confirmación diaria del sistema original
USE_DAILY_CONFIRMATION = True
CONFIRM_CLOSE_ABOVE_SIGNAL_CLOSE = True
CONFIRM_LOW_HOLDS_SIGNAL_LOW = True

# Gestión sistema original
INITIAL_STOP_LOSS_PCT = 0.05
FIRST_TARGET_PCT = 0.10
TARGET_STEP_PCT = 0.05
STOP_LOCK_STEP_PCT = 0.05
COMMISSION_PCT_PER_SIDE = 0.0024

ONE_POSITION_PER_TICKER = True
MAX_TRADES_PER_WEEK = 10
MAX_OPEN_POSITIONS = 20

# Setup V1 exacto con first-touch
SETUP_V1_ENABLED = True
SETUP_V1_REQUIRE_TREND_OK = True
SETUP_V1_REQUIRE_CLOSE_ENOUGH_TO_LOWER = True
SETUP_V1_MIN_CHANNEL_R2 = 0.8602
SETUP_V1_REQUIRE_MIN_LIQUIDITY = True
SETUP_V1_TOP_N_PER_WEEK = 5
SETUP_V1_ONE_POSITION_PER_TICKER = True
SETUP_V1_MAX_OPEN_POSITIONS = 20
SETUP_V1_USE_CONFIRMATION_FOR_ENTRY = False
SETUP_V1_TARGET_PCT = 0.15
SETUP_V1_STOP_PCT = 0.07
SETUP_V1_MAX_HOLD_WEEKS = 52
SETUP_V1_INTRADAY_PRIORITY = "stop"  # "stop" o "target"
SETUP_V1_CAPITAL_PER_TRADE = 500.0

OUTPUT_PREFIX = "sp500_channel_pullback_signals_all_with_first_touch"
LOCAL_SP500_CSV = None  # ej: r"C:\Pythons\ML-Trading\sp500_tickers.csv"

EXCEL_NUM_FMT_4 = '#,##0.0000'


# =============================================================================
# HELPERS
# =============================================================================

def clean_float(x) -> float:
    try:
        if pd.isna(x):
            return np.nan
        return float(x)
    except Exception:
        return np.nan


def rr(entry: float, stop: float, target: float) -> float:
    risk = entry - stop
    if risk <= 0:
        return np.nan
    return (target - entry) / risk


def find_next_daily_bar(df_daily: pd.DataFrame, after_date: pd.Timestamp) -> Optional[pd.Timestamp]:
    idx = df_daily.index[df_daily.index > after_date]
    if len(idx) == 0:
        return None
    return idx[0]


def get_weekly_row_for_date(weekly: pd.DataFrame, date: pd.Timestamp) -> Optional[pd.Timestamp]:
    eligible = weekly.index[weekly.index <= date]
    if len(eligible) == 0:
        return None
    return eligible[-1]


def auto_fit_worksheet(ws) -> None:
    for col_cells in ws.columns:
        max_len = 0
        col_idx = col_cells[0].column
        col_letter = get_column_letter(col_idx)

        for cell in col_cells:
            value = "" if cell.value is None else str(cell.value)
            if len(value) > max_len:
                max_len = len(value)

        adjusted_width = min(max(max_len + 2, 10), 80)
        ws.column_dimensions[col_letter].width = adjusted_width


def format_excel_file(path: str, df: pd.DataFrame) -> None:
    wb = load_workbook(path)
    ws = wb.active

    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    numeric_cols = []
    for idx, col_name in enumerate(df.columns, start=1):
        if pd.api.types.is_numeric_dtype(df[col_name]):
            numeric_cols.append((idx, col_name))

    for col_idx, col_name in numeric_cols:
        col_letter = get_column_letter(col_idx)
        lower = str(col_name).lower()

        if any(k in lower for k in ["volume", "winners", "losers", "bars", "signals", "trades", "hits", "slots", "positions", "rank"]):
            num_fmt = '#,##0'
        else:
            num_fmt = EXCEL_NUM_FMT_4

        for row in range(2, ws.max_row + 1):
            ws[f"{col_letter}{row}"].number_format = num_fmt

    auto_fit_worksheet(ws)
    wb.save(path)


def export_to_excel(df: pd.DataFrame, path: str, sheet_name: str = "data") -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    format_excel_file(path, df)


# =============================================================================
# DATA
# =============================================================================

def get_sp500_tickers_current(local_csv_path: Optional[str] = None) -> List[str]:
    if local_csv_path:
        local_path = Path(local_csv_path)
        if not local_path.exists():
            raise FileNotFoundError(f"No existe el CSV local: {local_csv_path}")

        df_local = pd.read_csv(local_path)
        possible_cols = [c for c in df_local.columns if str(c).strip().lower() in {"symbol", "ticker", "tickers"}]

        if possible_cols:
            s = df_local[possible_cols[0]]
        elif df_local.shape[1] == 1:
            s = df_local.iloc[:, 0]
        else:
            raise ValueError(
                "El CSV local no tiene una columna reconocible. "
                "Usá una columna llamada Symbol, symbol, ticker o un CSV de una sola columna."
            )

        tickers = (
            s.astype(str)
            .str.strip()
            .str.replace(".", "-", regex=False)
            .tolist()
        )
        tickers = [t for t in tickers if t and t.lower() != "nan"]
        return sorted(set(tickers))

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

    try:
        import requests
        from io import StringIO

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        }

        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()

        tables = pd.read_html(StringIO(resp.text))
        if not tables:
            raise RuntimeError("No se encontraron tablas HTML en Wikipedia.")

        df = tables[0]
        if "Symbol" not in df.columns:
            raise RuntimeError("La tabla de Wikipedia no tiene la columna 'Symbol'.")

        tickers = (
            df["Symbol"]
            .astype(str)
            .str.strip()
            .str.replace(".", "-", regex=False)
            .tolist()
        )
        tickers = [t for t in tickers if t and t.lower() != "nan"]
        return sorted(set(tickers))

    except Exception as e:
        raise RuntimeError(
            "No pude obtener la lista actual del S&P 500 desde Wikipedia. "
            "Probablemente el sitio devolvió 403 o la red bloqueó el acceso.\n"
            "Solución rápida: exportá un CSV local con una columna 'Symbol' y pasalo a "
            "get_sp500_tickers_current(local_csv_path='sp500_tickers.csv').\n"
            f"Detalle original: {e}"
        )


def download_daily_ohlcv(ticker: str, start: str, end: str) -> pd.DataFrame:
    df = yf.download(
        ticker,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=USE_ADJ_CLOSE,
        progress=False,
        threads=False,
    )

    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    keep_cols = [c for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in df.columns]
    df = df[keep_cols].copy()
    df = df.dropna(subset=[c for c in ["Open", "High", "Low", "Close"] if c in df.columns])

    if "Adj Close" not in df.columns:
        df["Adj Close"] = df["Close"]

    df.index = pd.to_datetime(df.index)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def daily_to_weekly(df_daily: pd.DataFrame) -> pd.DataFrame:
    if df_daily.empty:
        return pd.DataFrame()

    weekly = pd.DataFrame(index=pd.date_range(df_daily.index.min(), df_daily.index.max(), freq="W-FRI"))
    weekly["Open"] = df_daily["Open"].resample("W-FRI").first()
    weekly["High"] = df_daily["High"].resample("W-FRI").max()
    weekly["Low"] = df_daily["Low"].resample("W-FRI").min()
    weekly["Close"] = df_daily["Close"].resample("W-FRI").last()
    weekly["Adj Close"] = df_daily["Adj Close"].resample("W-FRI").last()
    weekly["Volume"] = df_daily["Volume"].resample("W-FRI").sum()
    weekly = weekly.dropna(subset=["Open", "High", "Low", "Close"])
    return weekly


def fit_regression_channel_last(close: pd.Series, window: int, width_sigma: float) -> Tuple[float, float, float, float, float]:
    y = close.tail(window).astype(float).values
    x = np.arange(len(y), dtype=float)

    m, b = np.polyfit(x, y, 1)
    y_hat = m * x + b
    residuals = y - y_hat

    ss_res = np.sum((y - y_hat) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    sigma = np.std(residuals, ddof=1) if len(residuals) > 1 else 0.0
    last_mid = m * x[-1] + b
    last_lower = last_mid - width_sigma * sigma
    last_upper = last_mid + width_sigma * sigma

    slope_pct = ((m * 52.0) / last_mid) * 100.0 if last_mid != 0 else np.nan
    return last_mid, last_lower, last_upper, slope_pct, r2


def compute_weekly_indicators(w: pd.DataFrame) -> pd.DataFrame:
    w = w.copy()
    w["sma200w"] = w["Close"].rolling(200).mean()
    w["ema200w"] = w["Close"].ewm(span=200, adjust=False).mean()

    w["sma200w_up"] = w["sma200w"] > w["sma200w"].shift(4)
    w["ema200w_up"] = w["ema200w"] > w["ema200w"].shift(4)

    w["high_20w_prev"] = w["High"].shift(1).rolling(UPSIDE_TARGET_LOOKBACK_WEEKS).max()

    mids = []
    lowers = []
    uppers = []
    slopes = []
    r2s = []

    closes = w["Close"]
    for i in range(len(w)):
        if i + 1 < CHANNEL_WINDOW_WEEKS:
            mids.append(np.nan)
            lowers.append(np.nan)
            uppers.append(np.nan)
            slopes.append(np.nan)
            r2s.append(np.nan)
            continue

        sub = closes.iloc[: i + 1]
        mid, lower, upper, slope_pct, r2 = fit_regression_channel_last(
            sub, CHANNEL_WINDOW_WEEKS, CHANNEL_WIDTH_SIGMA
        )
        mids.append(mid)
        lowers.append(lower)
        uppers.append(upper)
        slopes.append(slope_pct)
        r2s.append(r2)

    w["channel_mid"] = mids
    w["channel_lower"] = lowers
    w["channel_upper"] = uppers
    w["channel_slope_pct"] = slopes
    w["channel_r2"] = r2s
    w["ema_regime_w"] = w["Close"].ewm(span=SPY_REGIME_EMA_WEEKS, adjust=False).mean()
    w["ema_regime_up"] = w["ema_regime_w"] > w["ema_regime_w"].shift(1)
    return w


def spy_regime_is_ok(spy_weekly: pd.DataFrame, signal_date: pd.Timestamp) -> Tuple[bool, float, float]:
    if spy_weekly is None or spy_weekly.empty or signal_date not in spy_weekly.index:
        return False, np.nan, np.nan

    row = spy_weekly.loc[signal_date]
    spy_close = clean_float(row.get("Close", np.nan))
    spy_ema = clean_float(row.get("ema_regime_w", np.nan))
    if not np.isfinite(spy_close) or not np.isfinite(spy_ema):
        return False, spy_close, spy_ema

    conds = []
    if SPY_REGIME_REQUIRE_PRICE_ABOVE_EMA:
        conds.append(spy_close > spy_ema)
    if SPY_REGIME_REQUIRE_EMA_UP:
        conds.append(bool(row.get("ema_regime_up", False)))

    regime_ok = all(conds) if conds else True
    return regime_ok, spy_close, spy_ema


def build_quality_score(
    close: float,
    channel_lower: float,
    channel_upper: float,
    channel_slope_pct: float,
    channel_r2: float,
    adv20: float,
) -> float:
    if not np.isfinite(close) or not np.isfinite(channel_lower) or not np.isfinite(channel_upper):
        return np.nan

    dist_to_lower_pct = abs((close / channel_lower - 1.0) * 100.0)
    upside_to_upper_pct = max((channel_upper / close - 1.0) * 100.0, 0.0)

    closeness_score = max(0.0, 30.0 - dist_to_lower_pct * 6.0)
    upside_score = min(upside_to_upper_pct, 20.0) * 1.8
    slope_score = min(max(channel_slope_pct, 0.0), 25.0) * 1.2
    r2_score = min(max(channel_r2, 0.0), 1.0) * 20.0
    adv_m = adv20 / 1_000_000.0
    adv_score = min(max(adv_m, 0.0), 50.0) * 0.4

    return closeness_score + upside_score + slope_score + r2_score + adv_score


def compute_post_signal_extremes(
    daily: pd.DataFrame,
    signal_date: pd.Timestamp,
    reference_price: float,
) -> Dict[str, object]:
    result = {
        "max_price_after_signal": np.nan,
        "max_price_after_signal_pct": np.nan,
        "max_price_after_signal_date": None,
        "min_price_after_signal": np.nan,
        "min_price_after_signal_pct": np.nan,
        "min_price_after_signal_date": None,
    }

    if daily is None or daily.empty:
        return result
    if not np.isfinite(reference_price) or reference_price <= 0:
        return result

    future = daily.loc[daily.index > signal_date].copy()
    if future.empty:
        return result

    high_series = pd.to_numeric(future["High"], errors="coerce").dropna()
    low_series = pd.to_numeric(future["Low"], errors="coerce").dropna()

    if not high_series.empty:
        max_dt = high_series.idxmax()
        max_px = clean_float(high_series.loc[max_dt])
        result["max_price_after_signal"] = round(max_px, 4)
        result["max_price_after_signal_pct"] = round((max_px / reference_price - 1.0) * 100.0, 4)
        result["max_price_after_signal_date"] = pd.Timestamp(max_dt).date().isoformat()

    if not low_series.empty:
        min_dt = low_series.idxmin()
        min_px = clean_float(low_series.loc[min_dt])
        result["min_price_after_signal"] = round(min_px, 4)
        result["min_price_after_signal_pct"] = round((min_px / reference_price - 1.0) * 100.0, 4)
        result["min_price_after_signal_date"] = pd.Timestamp(min_dt).date().isoformat()

    return result


# =============================================================================
# FIRST TOUCH
# =============================================================================

def compute_first_touch_from_entry(
    daily: pd.DataFrame,
    entry_date: pd.Timestamp,
    entry_price: float,
    target_pct: float,
    stop_pct: float,
    max_hold_weeks: int,
    intraday_priority: str = "stop",
) -> Dict[str, object]:
    result = {
        "entry_date": None,
        "entry_price": np.nan,
        "target_pct": target_pct * 100.0,
        "stop_pct": stop_pct * 100.0,
        "target_price": np.nan,
        "stop_price": np.nan,
        "first_target_date": None,
        "first_stop_date": None,
        "first_touch_result": None,
        "exit_date": None,
        "exit_price": np.nan,
        "exit_reason": None,
        "bars_held": np.nan,
        "days_held": np.nan,
        "gross_return_pct": np.nan,
        "net_return_pct": np.nan,
    }

    if daily is None or daily.empty:
        return result
    if pd.isna(entry_date) or entry_date not in daily.index:
        return result
    if not np.isfinite(entry_price) or entry_price <= 0:
        return result

    target_price = entry_price * (1.0 + target_pct)
    stop_price = entry_price * (1.0 - stop_pct)

    result["entry_date"] = pd.Timestamp(entry_date).date().isoformat()
    result["entry_price"] = round(entry_price, 4)
    result["target_price"] = round(target_price, 4)
    result["stop_price"] = round(stop_price, 4)

    future = daily.loc[daily.index >= entry_date].copy()
    if future.empty:
        return result

    max_bars = max_hold_weeks * 5
    bar_count = 0

    first_target_date = None
    first_stop_date = None
    exit_date = None
    exit_price = np.nan
    exit_reason = None
    first_touch_result = None

    for dt, row in future.iterrows():
        day_high = clean_float(row["High"])
        day_low = clean_float(row["Low"])
        day_close = clean_float(row["Close"])

        hit_target = np.isfinite(day_high) and day_high >= target_price
        hit_stop = np.isfinite(day_low) and day_low <= stop_price

        if first_target_date is None and hit_target:
            first_target_date = dt
        if first_stop_date is None and hit_stop:
            first_stop_date = dt

        if hit_target and hit_stop:
            if intraday_priority == "target":
                first_touch_result = "target"
                exit_reason = "target"
                exit_price = target_price
            else:
                first_touch_result = "stop"
                exit_reason = "stop"
                exit_price = stop_price
            exit_date = dt
            break
        elif hit_target:
            first_touch_result = "target"
            exit_reason = "target"
            exit_date = dt
            exit_price = target_price
            break
        elif hit_stop:
            first_touch_result = "stop"
            exit_reason = "stop"
            exit_date = dt
            exit_price = stop_price
            break

        bar_count += 1
        if bar_count >= max_bars:
            first_touch_result = "none"
            exit_reason = "time_exit"
            exit_date = dt
            exit_price = day_close
            break

    if exit_date is None:
        last_dt = future.index[-1]
        last_close = clean_float(future.iloc[-1]["Close"])
        first_touch_result = "none"
        exit_reason = "end_of_data"
        exit_date = last_dt
        exit_price = last_close

    result["first_target_date"] = None if first_target_date is None else pd.Timestamp(first_target_date).date().isoformat()
    result["first_stop_date"] = None if first_stop_date is None else pd.Timestamp(first_stop_date).date().isoformat()
    result["first_touch_result"] = first_touch_result
    result["exit_date"] = pd.Timestamp(exit_date).date().isoformat()
    result["exit_price"] = round(exit_price, 4)
    result["exit_reason"] = exit_reason
    result["bars_held"] = int((future.index <= exit_date).sum())
    result["days_held"] = int((pd.Timestamp(exit_date) - pd.Timestamp(entry_date)).days)

    gross_ret = (exit_price / entry_price - 1.0) * 100.0
    net_entry_price = entry_price * (1.0 + COMMISSION_PCT_PER_SIDE)
    net_exit_price = exit_price * (1.0 - COMMISSION_PCT_PER_SIDE)
    net_ret = (net_exit_price / net_entry_price - 1.0) * 100.0
    result["gross_return_pct"] = round(gross_ret, 4)
    result["net_return_pct"] = round(net_ret, 4)
    return result


def compute_setup_v1_fields(
    row_data: dict,
    daily: pd.DataFrame,
    signal_date: pd.Timestamp,
) -> Dict[str, object]:
    result = {
        "setup_v1_filter_pass": 0,
        "setup_v1_adv20_rank": np.nan,
        "setup_v1_top_n_flag": 0,
        "setup_v1_selected_for_trade": 0,
        "setup_v1_selection_reason": "",
        "setup_v1_confirmation_date": None,
        "setup_v1_entry_date": None,
        "setup_v1_entry_price": np.nan,
        "setup_v1_target_pct": round(SETUP_V1_TARGET_PCT * 100.0, 4),
        "setup_v1_stop_pct": round(SETUP_V1_STOP_PCT * 100.0, 4),
        "setup_v1_target_price": np.nan,
        "setup_v1_stop_price": np.nan,
        "setup_v1_first_target_date": None,
        "setup_v1_first_stop_date": None,
        "setup_v1_first_touch_result": None,
        "setup_v1_exit_date": None,
        "setup_v1_exit_price": np.nan,
        "setup_v1_exit_reason": None,
        "setup_v1_bars_held": np.nan,
        "setup_v1_days_held": np.nan,
        "setup_v1_gross_return_pct": np.nan,
        "setup_v1_net_return_pct": np.nan,
    }

    trend_ok = bool(row_data.get("trend_ok", 0))
    close_enough_to_lower = bool(row_data.get("close_enough_to_lower", 0))
    channel_r2 = clean_float(row_data.get("channel_r2", np.nan))
    adv20 = clean_float(row_data.get("adv20", np.nan))

    passes = True
    if SETUP_V1_REQUIRE_TREND_OK:
        passes &= trend_ok
    if SETUP_V1_REQUIRE_CLOSE_ENOUGH_TO_LOWER:
        passes &= close_enough_to_lower
    passes &= np.isfinite(channel_r2) and channel_r2 >= SETUP_V1_MIN_CHANNEL_R2
    if SETUP_V1_REQUIRE_MIN_LIQUIDITY:
        passes &= np.isfinite(adv20) and adv20 >= MIN_AVG_DOLLAR_VOL

    result["setup_v1_filter_pass"] = int(bool(passes))
    if not passes:
        result["setup_v1_selection_reason"] = "setup_filter_failed"
        return result

    confirmation_date = None
    if SETUP_V1_USE_CONFIRMATION_FOR_ENTRY:
        confirmation_date = find_next_daily_bar(daily, signal_date)
        if confirmation_date is None or confirmation_date not in daily.index:
            result["setup_v1_selection_reason"] = "missing_confirmation_bar"
            return result

    if SETUP_V1_USE_CONFIRMATION_FOR_ENTRY:
        entry_date = find_next_daily_bar(daily, confirmation_date)
    else:
        entry_date = find_next_daily_bar(daily, signal_date)

    if entry_date is None or entry_date not in daily.index:
        result["setup_v1_selection_reason"] = "missing_entry_bar"
        return result

    entry_price = clean_float(daily.loc[entry_date, "Open"])
    if not np.isfinite(entry_price) or entry_price <= 0:
        result["setup_v1_selection_reason"] = "invalid_entry_price"
        return result

    ft = compute_first_touch_from_entry(
        daily=daily,
        entry_date=entry_date,
        entry_price=entry_price,
        target_pct=SETUP_V1_TARGET_PCT,
        stop_pct=SETUP_V1_STOP_PCT,
        max_hold_weeks=SETUP_V1_MAX_HOLD_WEEKS,
        intraday_priority=SETUP_V1_INTRADAY_PRIORITY,
    )

    result.update({
        "setup_v1_confirmation_date": None if confirmation_date is None else pd.Timestamp(confirmation_date).date().isoformat(),
        "setup_v1_entry_date": ft["entry_date"],
        "setup_v1_entry_price": ft["entry_price"],
        "setup_v1_target_price": ft["target_price"],
        "setup_v1_stop_price": ft["stop_price"],
        "setup_v1_first_target_date": ft["first_target_date"],
        "setup_v1_first_stop_date": ft["first_stop_date"],
        "setup_v1_first_touch_result": ft["first_touch_result"],
        "setup_v1_exit_date": ft["exit_date"],
        "setup_v1_exit_price": ft["exit_price"],
        "setup_v1_exit_reason": ft["exit_reason"],
        "setup_v1_bars_held": ft["bars_held"],
        "setup_v1_days_held": ft["days_held"],
        "setup_v1_gross_return_pct": ft["gross_return_pct"],
        "setup_v1_net_return_pct": ft["net_return_pct"],
        "setup_v1_selection_reason": "setup_filter_passed",
    })
    return result


# =============================================================================
# AUDIT ROW
# =============================================================================

def build_audit_row(
    ticker: str,
    weekly: pd.DataFrame,
    daily: pd.DataFrame,
    signal_date: pd.Timestamp,
    spy_weekly: Optional[pd.DataFrame] = None,
) -> dict:
    review_date = signal_date + pd.Timedelta(days=2)
    audit = {
        "signal_date": signal_date.date().isoformat(),
        "review_date": review_date.date().isoformat(),
        "ticker": ticker,
        "is_candidate_signal": 0,
        "selected_for_trade": 0,
        "selection_reason": "not_signal",
        "reject_stage": "",
        "reject_reason": "",
        "weekly_rank": np.nan,
        "confirmation_date": None,
        "planned_entry_date": None,
        "strategy": "channel_pullback",
        "regime": "bullish",
        "setup_status": "",
        "entry_type": None,
        "entry_price": np.nan,
        "stop_price": np.nan,
        "target_1": np.nan,
        "target_2": np.nan,
        "risk_pct": np.nan,
        "rr_t1": np.nan,
        "rr_t2": np.nan,
        "close": np.nan,
        "low": np.nan,
        "prev_close": np.nan,
        "sma200w": np.nan,
        "ema200w": np.nan,
        "support_level": np.nan,
        "resistance_level": np.nan,
        "channel_mid": np.nan,
        "channel_lower": np.nan,
        "channel_upper": np.nan,
        "channel_slope_pct": np.nan,
        "channel_r2": np.nan,
        "distance_to_channel_lower_pct": np.nan,
        "upside_to_upper_pct": np.nan,
        "adv20": np.nan,
        "quality_score": np.nan,
        "spy_close": np.nan,
        "spy_ema_regime": np.nan,
        "spy_regime_ok": np.nan,
        "trend_ok": 0,
        "channel_ok": 0,
        "touched_lower": 0,
        "reclaimed": 0,
        "reaction": 0,
        "close_enough_to_lower": 0,
        "confirm_close_ok": np.nan,
        "confirm_low_ok": np.nan,
        "max_price_after_signal": np.nan,
        "max_price_after_signal_pct": np.nan,
        "max_price_after_signal_date": None,
        "min_price_after_signal": np.nan,
        "min_price_after_signal_pct": np.nan,
        "min_price_after_signal_date": None,
        "notes": "",
    }

    if signal_date not in weekly.index:
        audit["reject_stage"] = "missing_week"
        audit["reject_reason"] = "signal_date_not_in_weekly_index"
        audit.update(compute_setup_v1_fields(audit, daily, signal_date))
        return audit

    row = weekly.loc[signal_date]
    prev_close = clean_float(weekly["Close"].shift(1).loc[signal_date]) if signal_date in weekly.index else np.nan
    audit["prev_close"] = round(prev_close, 4) if pd.notna(prev_close) else np.nan

    required_cols = [
        "sma200w", "ema200w", "high_20w_prev",
        "channel_mid", "channel_lower", "channel_upper",
        "channel_slope_pct", "channel_r2"
    ]

    close = clean_float(row.get("Close", np.nan))
    low = clean_float(row.get("Low", np.nan))
    audit["close"] = round(close, 4) if pd.notna(close) else np.nan
    audit["low"] = round(low, 4) if pd.notna(low) else np.nan
    audit.update(compute_post_signal_extremes(daily, signal_date, close))

    if any(pd.isna(row[c]) for c in required_cols):
        audit["reject_stage"] = "missing_indicators"
        audit["reject_reason"] = "required_weekly_indicators_nan"
        audit.update(compute_setup_v1_fields(audit, daily, signal_date))
        return audit

    sma200w = clean_float(row["sma200w"])
    ema200w = clean_float(row["ema200w"])
    prev_high = clean_float(row["high_20w_prev"])
    channel_mid = clean_float(row["channel_mid"])
    channel_lower = clean_float(row["channel_lower"])
    channel_upper = clean_float(row["channel_upper"])
    channel_slope_pct = clean_float(row["channel_slope_pct"])
    channel_r2 = clean_float(row["channel_r2"])

    audit.update({
        "sma200w": round(sma200w, 4),
        "ema200w": round(ema200w, 4),
        "support_level": round(channel_lower, 4),
        "resistance_level": round(prev_high, 4),
        "channel_mid": round(channel_mid, 4),
        "channel_lower": round(channel_lower, 4),
        "channel_upper": round(channel_upper, 4),
        "channel_slope_pct": round(channel_slope_pct, 4),
        "channel_r2": round(channel_r2, 4),
    })

    daily_hist = daily.loc[:signal_date]
    if len(daily_hist) >= 20:
        adv20 = ((daily_hist["Close"] * daily_hist["Volume"]).tail(20)).mean()
        audit["adv20"] = round(adv20, 4)
    else:
        adv20 = np.nan

    spy_close = np.nan
    spy_ema_regime = np.nan
    spy_regime_ok = True
    if spy_weekly is not None and not spy_weekly.empty:
        spy_regime_ok, spy_close, spy_ema_regime = spy_regime_is_ok(spy_weekly, signal_date)
    audit["spy_close"] = round(spy_close, 4) if pd.notna(spy_close) else np.nan
    audit["spy_ema_regime"] = round(spy_ema_regime, 4) if pd.notna(spy_ema_regime) else np.nan
    audit["spy_regime_ok"] = int(bool(spy_regime_ok))

    trend_ok = (
        np.isfinite(close) and np.isfinite(sma200w) and np.isfinite(ema200w)
        and close > sma200w
        and close > ema200w
        and bool(row["sma200w_up"])
        and bool(row["ema200w_up"])
    )
    channel_ok = (
        np.isfinite(channel_slope_pct) and np.isfinite(channel_r2)
        and channel_slope_pct > MIN_CHANNEL_SLOPE_PCT_52W
        and channel_r2 >= MIN_CHANNEL_R2
        and channel_upper > channel_lower
    )
    distance_to_channel_lower_pct = (close / channel_lower - 1.0) * 100.0 if np.isfinite(close) and np.isfinite(channel_lower) and channel_lower > 0 else np.nan
    touched_lower = np.isfinite(low) and np.isfinite(channel_lower) and low <= channel_lower * (1.0 + LOWER_TOUCH_TOL_PCT)
    reclaimed = np.isfinite(close) and np.isfinite(channel_lower) and close >= channel_lower
    reaction = close > prev_close if np.isfinite(prev_close) else False
    close_enough_to_lower = np.isfinite(distance_to_channel_lower_pct) and distance_to_channel_lower_pct <= MAX_DISTANCE_TO_CHANNEL_LOWER_PCT
    upside_to_upper_pct = (channel_upper / close - 1.0) * 100.0 if np.isfinite(channel_upper) and np.isfinite(close) and close > 0 else np.nan

    audit.update({
        "distance_to_channel_lower_pct": round(distance_to_channel_lower_pct, 4) if pd.notna(distance_to_channel_lower_pct) else np.nan,
        "upside_to_upper_pct": round(upside_to_upper_pct, 4) if pd.notna(upside_to_upper_pct) else np.nan,
        "trend_ok": int(bool(trend_ok)),
        "channel_ok": int(bool(channel_ok)),
        "touched_lower": int(bool(touched_lower)),
        "reclaimed": int(bool(reclaimed)),
        "reaction": int(bool(reaction)),
        "close_enough_to_lower": int(bool(close_enough_to_lower)),
    })

    if np.isfinite(close) and np.isfinite(channel_lower) and np.isfinite(channel_upper) and np.isfinite(channel_slope_pct) and np.isfinite(channel_r2) and np.isfinite(adv20):
        qscore = build_quality_score(
            close=close,
            channel_lower=channel_lower,
            channel_upper=channel_upper,
            channel_slope_pct=channel_slope_pct,
            channel_r2=channel_r2,
            adv20=adv20,
        )
        audit["quality_score"] = round(qscore, 4)

    confirmation_note = (
        " Confirmación diaria: la primera rueda post-señal cerró arriba del cierre semanal y sostuvo el mínimo semanal."
        if USE_DAILY_CONFIRMATION else ""
    )
    spy_note = ""
    if USE_SPY_WEEKLY_FILTER:
        spy_note = (
            " Filtro SPY semanal activo: SPY debe estar arriba de EMA20w y EMA20w en alza."
            if (SPY_REGIME_REQUIRE_PRICE_ABOVE_EMA and SPY_REGIME_REQUIRE_EMA_UP)
            else " Filtro SPY semanal activo."
        )
    audit["notes"] = (
        "Pullback semanal a banda inferior de canal alcista con filtro SMA/EMA200w."
        + confirmation_note
        + spy_note
    )

    if len(daily_hist) < 20:
        audit["reject_stage"] = "liquidity_history"
        audit["reject_reason"] = "daily_history_lt_20"
    elif adv20 < MIN_AVG_DOLLAR_VOL:
        audit["reject_stage"] = "liquidity_filter"
        audit["reject_reason"] = "adv20_below_min"
    elif USE_SPY_WEEKLY_FILTER and not spy_regime_ok:
        audit["reject_stage"] = "spy_filter"
        audit["reject_reason"] = "spy_regime_not_ok"
    elif not trend_ok:
        audit["reject_stage"] = "trend_filter"
        audit["reject_reason"] = "trend_not_ok"
    elif not channel_ok:
        audit["reject_stage"] = "channel_filter"
        audit["reject_reason"] = "channel_not_ok"
    elif not touched_lower:
        audit["reject_stage"] = "pullback_filter"
        audit["reject_reason"] = "did_not_touch_lower_band"
    elif not reclaimed:
        audit["reject_stage"] = "pullback_filter"
        audit["reject_reason"] = "did_not_reclaim_lower_band"
    elif not reaction:
        audit["reject_stage"] = "reaction_filter"
        audit["reject_reason"] = "weekly_close_not_above_prev_close"
    elif not close_enough_to_lower:
        audit["reject_stage"] = "distance_filter"
        audit["reject_reason"] = "too_far_from_lower_band"
    else:
        confirmation_date = None
        planned_entry_date = None
        entry_type = "next_open"
        confirm_close_ok = True
        confirm_low_ok = True

        if USE_DAILY_CONFIRMATION:
            confirmation_date = find_next_daily_bar(daily, signal_date)
            if confirmation_date is not None and confirmation_date in daily.index:
                confirmation_close = clean_float(daily.loc[confirmation_date, "Close"])
                confirmation_low = clean_float(daily.loc[confirmation_date, "Low"])
                confirm_close_ok = (confirmation_close > close) if CONFIRM_CLOSE_ABOVE_SIGNAL_CLOSE else True
                confirm_low_ok = (confirmation_low >= low) if CONFIRM_LOW_HOLDS_SIGNAL_LOW else True
                audit["confirmation_date"] = confirmation_date.date().isoformat()
                audit["confirm_close_ok"] = int(bool(confirm_close_ok))
                audit["confirm_low_ok"] = int(bool(confirm_low_ok))

                if confirm_close_ok and confirm_low_ok:
                    planned_entry_date = find_next_daily_bar(daily, confirmation_date)
                    entry_type = "confirmed_next_open"
                else:
                    audit["reject_stage"] = "confirmation_filter"
                    audit["reject_reason"] = (
                        "confirmation_close_failed" if not confirm_close_ok else "confirmation_low_failed"
                    )
            else:
                audit["reject_stage"] = "confirmation_filter"
                audit["reject_reason"] = "missing_confirmation_bar"
        else:
            planned_entry_date = find_next_daily_bar(daily, signal_date)

        if audit["reject_reason"] == "" and (planned_entry_date is None or planned_entry_date not in daily.index):
            audit["reject_stage"] = "entry_bar"
            audit["reject_reason"] = "missing_planned_entry_bar"

        if audit["reject_reason"] == "":
            entry_price = clean_float(daily.loc[planned_entry_date, "Open"])
            stop_price = entry_price * (1.0 - INITIAL_STOP_LOSS_PCT)
            target_1 = entry_price * (1.0 + FIRST_TARGET_PCT)
            target_2 = entry_price * (1.0 + FIRST_TARGET_PCT + TARGET_STEP_PCT)

            audit.update({
                "is_candidate_signal": 1,
                "selection_reason": "candidate",
                "reject_stage": "candidate",
                "reject_reason": "passed_all_signal_filters",
                "setup_status": "active",
                "confirmation_date": None if confirmation_date is None else confirmation_date.date().isoformat(),
                "planned_entry_date": planned_entry_date.date().isoformat(),
                "entry_type": entry_type,
                "entry_price": round(entry_price, 4),
                "stop_price": round(stop_price, 4),
                "target_1": round(target_1, 4),
                "target_2": round(target_2, 4),
                "risk_pct": round(INITIAL_STOP_LOSS_PCT * 100.0, 4),
                "rr_t1": round(rr(entry_price, stop_price, target_1), 4),
                "rr_t2": round(rr(entry_price, stop_price, target_2), 4),
            })

    audit.update(compute_setup_v1_fields(audit, daily, signal_date))
    return audit


# =============================================================================
# SETUP V1 PORTFOLIO
# =============================================================================

def count_open_positions(trades: List[dict], as_of_date: pd.Timestamp) -> int:
    count = 0
    as_of_date = pd.Timestamp(as_of_date)
    for tr in trades:
        entry_dt = pd.Timestamp(tr["setup_v1_entry_date"])
        exit_dt = pd.Timestamp(tr["setup_v1_exit_date"])
        if entry_dt <= as_of_date <= exit_dt:
            count += 1
    return count


def ticker_is_open(trades: List[dict], ticker: str, as_of_date: pd.Timestamp) -> bool:
    as_of_date = pd.Timestamp(as_of_date)
    for tr in trades:
        if tr["ticker"] != ticker:
            continue
        entry_dt = pd.Timestamp(tr["setup_v1_entry_date"])
        exit_dt = pd.Timestamp(tr["setup_v1_exit_date"])
        if entry_dt <= as_of_date <= exit_dt:
            return True
    return False


def build_setup_v1_trades(signals_all_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if signals_all_df.empty:
        empty = pd.DataFrame()
        return empty, empty, empty, empty

    df = signals_all_df.copy()
    df["signal_date_ts"] = pd.to_datetime(df["signal_date"])
    df["setup_v1_entry_date_ts"] = pd.to_datetime(df["setup_v1_entry_date"], errors="coerce")
    df["setup_v1_exit_date_ts"] = pd.to_datetime(df["setup_v1_exit_date"], errors="coerce")

    selected_trades: List[dict] = []
    weekly_selection_rows: List[dict] = []

    for signal_date, week_df in df.groupby("signal_date_ts"):
        week_pass = week_df[week_df["setup_v1_top_n_flag"] == 1].copy()
        week_pass = week_pass.sort_values(["setup_v1_adv20_rank", "quality_score", "ticker"], ascending=[True, False, True])

        selected_count = 0
        overlap_count = 0
        full_count = 0
        invalid_count = 0

        for idx, row in week_pass.iterrows():
            entry_dt = row["setup_v1_entry_date_ts"]
            exit_dt = row["setup_v1_exit_date_ts"]
            ticker = row["ticker"]

            if pd.isna(entry_dt) or pd.isna(exit_dt):
                df.at[idx, "setup_v1_selection_reason"] = "missing_exit_or_entry"
                invalid_count += 1
                continue

            if SETUP_V1_ONE_POSITION_PER_TICKER and ticker_is_open(selected_trades, ticker, entry_dt):
                df.at[idx, "setup_v1_selection_reason"] = "ticker_overlap"
                overlap_count += 1
                continue

            currently_open = count_open_positions(selected_trades, entry_dt)
            if currently_open >= SETUP_V1_MAX_OPEN_POSITIONS:
                df.at[idx, "setup_v1_selection_reason"] = "portfolio_full"
                full_count += 1
                continue

            gross_pct = clean_float(row.get("setup_v1_gross_return_pct", np.nan))
            net_pct = clean_float(row.get("setup_v1_net_return_pct", np.nan))
            pnl_dollars = SETUP_V1_CAPITAL_PER_TRADE * (net_pct / 100.0) if np.isfinite(net_pct) else np.nan

            trade_row = row.to_dict()
            trade_row["setup_v1_selected_for_trade"] = 1
            trade_row["setup_v1_selection_reason"] = "selected"
            trade_row["setup_v1_capital_per_trade"] = SETUP_V1_CAPITAL_PER_TRADE
            trade_row["setup_v1_net_pnl_dollars"] = round(pnl_dollars, 4) if pd.notna(pnl_dollars) else np.nan
            selected_trades.append(trade_row)

            df.at[idx, "setup_v1_selected_for_trade"] = 1
            df.at[idx, "setup_v1_selection_reason"] = "selected"
            selected_count += 1

        weekly_selection_rows.append({
            "signal_date": pd.Timestamp(signal_date).date().isoformat(),
            "review_date": (pd.Timestamp(signal_date) + pd.Timedelta(days=2)).date().isoformat(),
            "setup_v1_filter_pass_count": int((week_df["setup_v1_filter_pass"] == 1).sum()),
            "setup_v1_top_n_count": int((week_df["setup_v1_top_n_flag"] == 1).sum()),
            "setup_v1_selected_count": int(selected_count),
            "discarded_ticker_overlap": int(overlap_count),
            "discarded_portfolio_full": int(full_count),
            "discarded_invalid_entry_exit": int(invalid_count),
            "max_open_positions": int(SETUP_V1_MAX_OPEN_POSITIONS),
        })

    trades_df = pd.DataFrame(selected_trades)
    weekly_selection_df = pd.DataFrame(weekly_selection_rows)

    if trades_df.empty:
        summary_df = pd.DataFrame([{
            "capital_per_trade": SETUP_V1_CAPITAL_PER_TRADE,
            "max_open_positions": SETUP_V1_MAX_OPEN_POSITIONS,
            "top_n_per_week": SETUP_V1_TOP_N_PER_WEEK,
            "target_pct": round(SETUP_V1_TARGET_PCT * 100.0, 4),
            "stop_pct": round(SETUP_V1_STOP_PCT * 100.0, 4),
            "selected_trades": 0,
            "winners": 0,
            "losers": 0,
            "win_rate_pct": np.nan,
            "avg_net_return_pct": np.nan,
            "avg_net_pnl_dollars": np.nan,
            "total_net_pnl_dollars": 0.0,
        }])
        return df.drop(columns=["signal_date_ts", "setup_v1_entry_date_ts", "setup_v1_exit_date_ts"]), trades_df, summary_df

    trades_df = trades_df.sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    winners = int((trades_df["setup_v1_net_return_pct"] > 0).sum())
    losers = int((trades_df["setup_v1_net_return_pct"] <= 0).sum())
    avg_net_return = trades_df["setup_v1_net_return_pct"].mean()
    avg_net_pnl = trades_df["setup_v1_net_pnl_dollars"].mean()
    total_net_pnl = trades_df["setup_v1_net_pnl_dollars"].sum()

    summary_df = pd.DataFrame([{
        "capital_per_trade": SETUP_V1_CAPITAL_PER_TRADE,
        "max_open_positions": SETUP_V1_MAX_OPEN_POSITIONS,
        "top_n_per_week": SETUP_V1_TOP_N_PER_WEEK,
        "target_pct": round(SETUP_V1_TARGET_PCT * 100.0, 4),
        "stop_pct": round(SETUP_V1_STOP_PCT * 100.0, 4),
        "selected_trades": int(len(trades_df)),
        "winners": winners,
        "losers": losers,
        "win_rate_pct": round((winners / len(trades_df)) * 100.0, 4),
        "avg_net_return_pct": round(avg_net_return, 4),
        "avg_net_pnl_dollars": round(avg_net_pnl, 4),
        "total_net_pnl_dollars": round(total_net_pnl, 4),
    }])

    df = df.drop(columns=["signal_date_ts", "setup_v1_entry_date_ts", "setup_v1_exit_date_ts"])
    return df, trades_df, summary_df, weekly_selection_df


# =============================================================================
# MAIN
# =============================================================================

def main():
    tickers = get_sp500_tickers_current(local_csv_path=LOCAL_SP500_CSV)
    print(f"Tickers S&P 500 actuales encontrados: {len(tickers)}")

    signal_weeks = pd.date_range(SIGNAL_START, SIGNAL_END, freq="W-FRI")
    print("Semanas a evaluar (cierres de viernes):", [d.date().isoformat() for d in signal_weeks])
    print(
        f"Setup V1 => target={SETUP_V1_TARGET_PCT * 100:.2f}% | stop={SETUP_V1_STOP_PCT * 100:.2f}% | "
        f"top_n={SETUP_V1_TOP_N_PER_WEEK} | max_open={SETUP_V1_MAX_OPEN_POSITIONS} | "
        f"entry={'confirmed_next_open' if SETUP_V1_USE_CONFIRMATION_FOR_ENTRY else 'next_open'} | "
        f"intraday_priority={SETUP_V1_INTRADAY_PRIORITY}"
    )

    data_by_ticker: Dict[str, Dict[str, pd.DataFrame]] = {}
    errors: List[Tuple[str, str]] = []

    spy_weekly = None
    if USE_SPY_WEEKLY_FILTER:
        try:
            print(f"[SPY] Descargando {SPY_TICKER} para filtro de régimen...")
            spy_daily = download_daily_ohlcv(SPY_TICKER, START_DAILY, END_DAILY)
            if spy_daily.empty:
                raise RuntimeError(f"No pude descargar {SPY_TICKER}.")
            spy_weekly = compute_weekly_indicators(daily_to_weekly(spy_daily))
        except Exception as e:
            raise RuntimeError(f"Falló la descarga/cálculo de {SPY_TICKER} para filtro de régimen: {e}")

    for i, ticker in enumerate(tickers, 1):
        try:
            print(f"[{i}/{len(tickers)}] {ticker}")
            daily = download_daily_ohlcv(ticker, START_DAILY, END_DAILY)
            if daily.empty or len(daily) < 300:
                continue

            weekly = daily_to_weekly(daily)
            if weekly.empty or len(weekly) < MIN_HISTORY_WEEKS:
                continue

            weekly = compute_weekly_indicators(weekly)
            data_by_ticker[ticker] = {"daily": daily, "weekly": weekly}
        except Exception as e:
            errors.append((ticker, str(e)))

    all_evaluated_signals: List[dict] = []
    all_candidate_signals: List[dict] = []

    for signal_date in signal_weeks:
        weekly_candidates: List[dict] = []

        for ticker, data in data_by_ticker.items():
            audit_row = build_audit_row(ticker, data["weekly"], data["daily"], signal_date, spy_weekly=spy_weekly)
            all_evaluated_signals.append(audit_row)
            if int(audit_row.get("is_candidate_signal", 0)) == 1:
                weekly_candidates.append(audit_row)

        weekly_candidates = sorted(
            weekly_candidates,
            key=lambda r: (-np.nan_to_num(clean_float(r.get("quality_score", np.nan)), nan=-1e9), r["ticker"])
        )

        for rank, row in enumerate(weekly_candidates, start=1):
            row_copy = dict(row)
            row_copy["weekly_rank"] = rank
            all_candidate_signals.append(row_copy)

    signals_all_df = pd.DataFrame(all_evaluated_signals)
    signals_df = pd.DataFrame(all_candidate_signals)

    if not signals_df.empty:
        signals_df = signals_df.sort_values(["signal_date", "weekly_rank", "ticker"]).reset_index(drop=True)

    if not signals_all_df.empty:
        signals_all_df = signals_all_df.sort_values(["signal_date", "ticker"]).reset_index(drop=True)

    # Copiamos weekly_rank y datos completos de candidate a signals_all
    if not signals_df.empty and not signals_all_df.empty:
        for _, srow in signals_df.iterrows():
            mask = (signals_all_df["signal_date"] == srow["signal_date"]) & (signals_all_df["ticker"] == srow["ticker"])
            signals_all_df.loc[mask, "weekly_rank"] = srow["weekly_rank"]

    # Setup V1 ranking por fecha
    if not signals_all_df.empty:
        signals_all_df["setup_v1_adv20_rank"] = np.nan
        signals_all_df["setup_v1_top_n_flag"] = 0
        for signal_date, grp in signals_all_df.groupby("signal_date"):
            elig = grp[(grp["setup_v1_filter_pass"] == 1)].copy()
            if elig.empty:
                continue
            elig = elig.sort_values(["adv20", "quality_score", "ticker"], ascending=[True, False, True])
            for rank, (idx, row) in enumerate(elig.iterrows(), start=1):
                signals_all_df.at[idx, "setup_v1_adv20_rank"] = rank
                signals_all_df.at[idx, "setup_v1_top_n_flag"] = 1 if rank <= SETUP_V1_TOP_N_PER_WEEK else 0

        signals_all_df["setup_v1_top_n_flag"] = signals_all_df["setup_v1_top_n_flag"].fillna(0).astype(int)
        signals_all_df["setup_v1_selected_for_trade"] = signals_all_df["setup_v1_selected_for_trade"].fillna(0).astype(int)

    if signals_all_df.empty:
        updated_signals_all_df = signals_all_df.copy()
        setup_v1_trades_df = pd.DataFrame()
        setup_v1_summary_df = pd.DataFrame()
        setup_v1_weekly_selection_df = pd.DataFrame()
    else:
        updated_signals_all_df, setup_v1_trades_df, setup_v1_summary_df, setup_v1_weekly_selection_df = build_setup_v1_trades(signals_all_df)

    errors_df = pd.DataFrame(errors, columns=["ticker", "error"]) if errors else pd.DataFrame(columns=["ticker", "error"])

    ts = datetime.now().strftime("%y%m%d%H%M%S")
    signals_all_path = f"{OUTPUT_PREFIX}_signals_all_{ts}.xlsx"
    signals_path = f"{OUTPUT_PREFIX}_signals_{ts}.xlsx"
    setup_v1_trades_path = f"{OUTPUT_PREFIX}_setup_v1_trades_{ts}.xlsx"
    setup_v1_summary_path = f"{OUTPUT_PREFIX}_setup_v1_summary_{ts}.xlsx"
    setup_v1_weekly_selection_path = f"{OUTPUT_PREFIX}_setup_v1_weekly_selection_{ts}.xlsx"
    errors_path = f"{OUTPUT_PREFIX}_errors_{ts}.xlsx"

    export_to_excel(updated_signals_all_df, signals_all_path, sheet_name="signals_all")
    export_to_excel(signals_df, signals_path, sheet_name="signals")
    export_to_excel(setup_v1_trades_df, setup_v1_trades_path, sheet_name="setup_v1_trades")
    export_to_excel(setup_v1_summary_df, setup_v1_summary_path, sheet_name="setup_v1_summary")
    export_to_excel(setup_v1_weekly_selection_df, setup_v1_weekly_selection_path, sheet_name="setup_v1_weekly_selection")
    export_to_excel(errors_df, errors_path, sheet_name="errors")

    print("=" * 90)
    print("Listo.")
    print(f"Signals All enriquecido: {signals_all_path} ({len(updated_signals_all_df)} filas)")
    print(f"Signals candidatos:      {signals_path} ({len(signals_df)} filas)")
    print(f"Setup V1 Trades:         {setup_v1_trades_path} ({len(setup_v1_trades_df)} filas)")
    print(f"Setup V1 Summary:        {setup_v1_summary_path}")
    print(f"Setup V1 Weekly Sel:     {setup_v1_weekly_selection_path}")
    print(f"Errores:                 {errors_path} ({len(errors_df)} filas)")
    print("=" * 90)

    if not setup_v1_summary_df.empty:
        print(setup_v1_summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
