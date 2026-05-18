import pandas as pd
from scripts.generated.feature_engineering_candidate import add_supported_features, read_feature_csv


def test_add_supported_features_basic():
    rows = []
    dates = pd.date_range("2020-01-03", periods=60, freq="W-FRI")
    for ticker in ["SPY", "AAA"]:
        for i, date in enumerate(dates):
            rows.append({"ticker": ticker, "date": str(date.date()), "close": 100+i, "high": 101+i, "low": 99+i})
    out = add_supported_features(pd.DataFrame(rows))
    for col in ["ret_26w_pct", "ret_52w_pct", "close_vs_sma20w_pct", "close_vs_sma52w_pct", "channel_r2"]:
        assert col in out.columns


def test_read_feature_csv_semicolon(tmp_path):
    csv_path = tmp_path / "weekly.csv"
    csv_path.write_text("date;ticker;close\n2020-01-03;SPY;100\n", encoding="utf-8")
    df = read_feature_csv(str(csv_path))
    assert set(["date", "ticker", "close"]).issubset(df.columns)
