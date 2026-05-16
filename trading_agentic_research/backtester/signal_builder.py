"""Signal construction utilities."""

from __future__ import annotations

import warnings

import pandas as pd


def build_momentum_trend_signals(weekly_df, strategy_config) -> pd.DataFrame:
    """Build monthly decision signals from weekly feature-store snapshots.

    The function uses only data available on each signal date.
    """
    if weekly_df is None or len(weekly_df) == 0:
        return pd.DataFrame(
            columns=[
                "signal_date",
                "ticker",
                "rank",
                "ranking_value",
                "selected_top_n",
                "in_exit_universe",
                "market_filter_passed",
                "action_candidate",
            ]
        )

    ranking_column = _get_ranking_column(strategy_config)
    benchmark_ticker = str(strategy_config.get("benchmark_ticker", "SPY"))
    top_n = int(strategy_config.get("entry_rule", {}).get("top_n", 15))
    exit_rank_threshold = int(
        strategy_config.get("exit_rule", {}).get("rank_threshold", 30)
    )

    df = weekly_df.copy()
    if "date" not in df.columns or "ticker" not in df.columns:
        raise ValueError("weekly_df must contain 'date' and 'ticker'")
    if ranking_column not in df.columns:
        raise ValueError(f"weekly_df must contain ranking column: {ranking_column}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values(["date", "ticker"], kind="mergesort")

    # Decision date: last weekly date available each month.
    month_key = df["date"].dt.to_period("M")
    decision_dates = df.groupby(month_key)["date"].max().sort_values().tolist()

    output_frames = []
    for signal_date in decision_dates:
        snapshot = df[df["date"] == signal_date].copy()
        market_filter_passed = _evaluate_market_filter(snapshot, strategy_config, benchmark_ticker)

        operable = snapshot[snapshot["ticker"] != benchmark_ticker].copy()

        # Minimal risk filter: require ranking value for selection and ranking.
        operable = operable.dropna(subset=[ranking_column])

        operable["rank"] = (
            operable[ranking_column].astype(float).rank(method="first", ascending=False).astype(int)
        )
        operable = operable.sort_values("rank", kind="mergesort")

        operable["signal_date"] = signal_date
        operable["ranking_value"] = operable[ranking_column].astype(float)
        operable["selected_top_n"] = operable["rank"] <= top_n
        operable["in_exit_universe"] = operable["rank"] <= exit_rank_threshold
        operable["market_filter_passed"] = bool(market_filter_passed)
        operable["action_candidate"] = operable.apply(_candidate_action, axis=1)

        output_frames.append(
            operable[
                [
                    "signal_date",
                    "ticker",
                    "rank",
                    "ranking_value",
                    "selected_top_n",
                    "in_exit_universe",
                    "market_filter_passed",
                    "action_candidate",
                ]
            ]
        )

    if not output_frames:
        return pd.DataFrame(
            columns=[
                "signal_date",
                "ticker",
                "rank",
                "ranking_value",
                "selected_top_n",
                "in_exit_universe",
                "market_filter_passed",
                "action_candidate",
            ]
        )

    return pd.concat(output_frames, ignore_index=True)


def _get_ranking_column(strategy_config: dict) -> str:
    if "ranking_column" in strategy_config:
        return str(strategy_config["ranking_column"])
    ranking = strategy_config.get("ranking", {})
    return str(ranking.get("field", "ret_52w_pct"))


def _evaluate_market_filter(snapshot: pd.DataFrame, strategy_config: dict, benchmark_ticker: str) -> bool:
    market_filter_cfg = strategy_config.get("market_filter", {})
    require_positive_trend = bool(market_filter_cfg.get("require_positive_trend", True))
    fallback_if_missing = bool(
        market_filter_cfg.get("fallback_allow_if_missing_spy_metric", True)
    )

    if not require_positive_trend:
        return True

    spy_rows = snapshot[snapshot["ticker"] == benchmark_ticker]
    if spy_rows.empty:
        warnings.warn(
            f"Market filter could not find {benchmark_ticker} row on signal date; using fallback.",
            UserWarning,
        )
        return fallback_if_missing

    if "spy_close_vs_sma50_pct" not in spy_rows.columns:
        warnings.warn(
            "Column spy_close_vs_sma50_pct not found; using market filter fallback.",
            UserWarning,
        )
        return fallback_if_missing

    value = pd.to_numeric(spy_rows.iloc[0]["spy_close_vs_sma50_pct"], errors="coerce")
    if pd.isna(value):
        warnings.warn(
            "spy_close_vs_sma50_pct is NaN; using market filter fallback.",
            UserWarning,
        )
        return fallback_if_missing

    return bool(value > 0)


def _candidate_action(row: pd.Series) -> str:
    if not bool(row["market_filter_passed"]):
        return "blocked_by_market_filter"
    if bool(row["selected_top_n"]):
        return "enter_or_hold"
    if bool(row["in_exit_universe"]):
        return "hold_if_already_in_position"
    return "exit_candidate"
