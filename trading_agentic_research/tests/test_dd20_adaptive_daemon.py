from pathlib import Path

from scripts.run_dd20_adaptive_research_daemon import is_real_run, next_run_id


def test_real_run_requires_full_dd20_artifacts(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    for name in [
        "equity_curve.csv",
        "trades.csv",
        "metrics.json",
        "spy_comparison_daily.csv",
        "spy_comparison_monthly.csv",
        "spy_comparison_yearly.csv",
        "spy_comparison_summary.json",
        "run_manifest.json",
    ]:
        (run / name).write_text("x", encoding="utf-8")

    assert is_real_run(run)

    (run / "trades.csv").unlink()
    assert not is_real_run(run)


def test_adaptive_run_id_does_not_move_parent_or_baseline(tmp_path):
    run_id = next_run_id(str(tmp_path), 1, "HYP_DD20_ADAPT_TEST")

    assert run_id.startswith("DD20ADAPT_001_")
    assert not (Path(tmp_path) / "current_parent.json").exists()
    assert not (Path(tmp_path) / "current_baseline.json").exists()
