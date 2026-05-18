from scripts.research.data_quality_diagnostics import diagnose_data_quality


def test_data_quality_diagnostics_reports_spy_nan(tmp_path):
    weekly = tmp_path / "weekly.csv"
    weekly.write_text("signal_date,ticker,close,spy_close_vs_sma50_pct\n2020-01-03,SPY,100,\n2020-01-10,AAA,10,1.2\n", encoding="utf-8")
    reports = tmp_path / "reports"
    payload = diagnose_data_quality(weekly_file=weekly, reports_dir=reports, max_warn_nan_pct=10)
    assert payload["status"] == "warning"
    assert any("spy_close_vs_sma50_pct" in w for w in payload["warnings"])
    assert (reports / "data_quality_diagnostics.md").exists()
