from backtester.dd_first import DD_FIRST_COLUMNS, write_dd_first_summary


def test_dd_first_summary_columns(tmp_path):
    out = tmp_path / "dd_first_summary.csv"
    write_dd_first_summary(out, [])

    header = out.read_text(encoding="utf-8-sig").splitlines()[0].split(";")

    assert header == DD_FIRST_COLUMNS
    assert "hypothesis_id" in header
    assert "value_delivered" in header
    assert "next_action" in header
