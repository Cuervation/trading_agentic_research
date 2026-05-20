import pandas as pd
from scripts.generated.feature_engineering_candidate import add_supported_features, read_feature_csv


def test_add_supported_features_basic():
    rows = []
    dates = pd.date_range("2020-01-03", periods=60, freq="W-FRI")
    for ticker in ["SPY", "AAA"]:
        for i, date in enumerate(dates):
            rows.append({"ticker": ticker, "date": str(date.date()), "close": 100+i, "high": 101+i, "low": 99+i})
    out = add_supported_features(pd.DataFrame(rows))
    for col in ["ret_13w_pct", "ret_26w_pct", "ret_52w_pct", "close_vs_sma20w_pct", "close_vs_sma52w_pct", "channel_r2", "downside_vol_13w_pct", "max_drawdown_26w_pct", "realized_vol_13w_pct", "residual_ret_26w_pct"]:
        assert col in out.columns


def test_add_supported_cross_sectional_features():
    rows = []
    dates = pd.date_range("2020-01-03", periods=60, freq="W-FRI")
    for ticker in ["SPY", "AAA", "BBB"]:
        for i, date in enumerate(dates):
            close = 100 + i if ticker != "BBB" else 150 - i * 0.2
            rows.append({"ticker": ticker, "date": str(date.date()), "close": close, "close_vs_sma50_pct": i - 30})
    out = add_supported_features(pd.DataFrame(rows))
    assert "market_breadth_above_sma50_pct" in out.columns
    assert "residual_ret_26w_pct" in out.columns
    assert "realized_vol_13w_pct" in out.columns


def test_add_supported_features_signal_date_alias():
    rows = []
    dates = pd.date_range("2020-01-03", periods=60, freq="W-FRI")
    for i, date in enumerate(dates):
        rows.append({"ticker": "AAA", "signal_date": str(date.date()), "close": 100+i})
    out = add_supported_features(pd.DataFrame(rows))
    assert "ret_13w_pct" in out.columns
    assert "signal_date" in out.columns


def test_read_feature_csv_semicolon(tmp_path):
    csv_path = tmp_path / "weekly.csv"
    csv_path.write_text("date;ticker;close\n2020-01-03;SPY;100\n", encoding="utf-8")
    df = read_feature_csv(str(csv_path))
    assert set(["date", "ticker", "close"]).issubset(df.columns)
