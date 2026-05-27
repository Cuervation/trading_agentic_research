from scripts.run_dd20_continuous_supervisor import manual_stop_requested


def test_supervisor_stop_file_is_detected(tmp_path):
    assert not manual_stop_requested(tmp_path)

    (tmp_path / "stop_dd20_supervisor.txt").write_text("stop", encoding="utf-8")

    assert manual_stop_requested(tmp_path)
