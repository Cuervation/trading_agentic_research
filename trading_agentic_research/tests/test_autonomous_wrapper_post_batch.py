from scripts.research.research_policy import DEFAULT_POLICY, validate_post_batch, validate_autonomous_launch


def test_post_batch_blocks_zero_iterations():
    result = validate_post_batch(
        policy=DEFAULT_POLICY,
        batch_state={"completed": 0, "status": "stopped", "stop_reason": "no_eligible"},
        allow_zero_iterations=False,
        requested_max_runs=5,
    )
    assert result["ok"] is False
    assert result["reason"] == "batch_completed_zero_iterations"


def test_post_batch_allows_completed_iterations():
    result = validate_post_batch(
        policy=DEFAULT_POLICY,
        batch_state={"completed": 3, "status": "stopped", "stop_reason": "consecutive_rejections:2"},
        requested_max_runs=5,
    )
    assert result["ok"] is True
    assert result["completed"] == 3
    assert result["warnings"]


def test_launch_policy_blocks_too_many_runs():
    result = validate_autonomous_launch(policy=DEFAULT_POLICY, allow_parent_update=False, max_runs=999)
    assert result["ok"] is False
