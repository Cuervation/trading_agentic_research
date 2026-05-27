from backtester.execution import _equity_guard_rebalance_policy


def test_cooldown_rebalances_blocks_then_releases_to_partial_guard():
    guard = {
        "stop_new_entries_drawdown_pct": -18,
        "resume_drawdown_pct": -10,
        "cooldown_rebalances": 3,
        "reduced_exposure_pct_when_active": 20,
    }

    blocked = _equity_guard_rebalance_policy(
        equity_guard_active=True,
        current_equity_dd_pct=-18.5,
        equity_drawdown_guard=guard,
        cooldown_remaining=3,
    )
    released = _equity_guard_rebalance_policy(
        equity_guard_active=True,
        current_equity_dd_pct=-18.5,
        equity_drawdown_guard=guard,
        cooldown_remaining=0,
    )

    assert blocked["block_new_entries"] is True
    assert released["block_new_entries"] is False
    assert released["reduced_exposure_pct_when_active"] == 20


def test_cooldown_keeps_full_block_on_hard_breach():
    guard = {
        "stop_new_entries_drawdown_pct": -18,
        "resume_drawdown_pct": -10,
        "cooldown_rebalances": 3,
        "reduced_exposure_pct_when_active": 20,
    }

    policy = _equity_guard_rebalance_policy(
        equity_guard_active=True,
        current_equity_dd_pct=-21.1,
        equity_drawdown_guard=guard,
        cooldown_remaining=0,
    )

    assert policy["block_new_entries"] is True
