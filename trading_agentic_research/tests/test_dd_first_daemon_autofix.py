from scripts.run_dd_first_autonomous_daemon import classify_daemon_error


def test_daemon_classifies_column_errors_for_autofix():
    assert classify_daemon_error("weekly_df must contain ranking column: nope") == "data_or_column_error"
    assert classify_daemon_error("Traceback TypeError boom") == "code_error"
