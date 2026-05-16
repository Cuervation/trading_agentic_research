from backtester.costs import apply_transaction_cost, calculate_trade_net_return


def test_apply_transaction_cost_two_sides():
    net = apply_transaction_cost(return_pct=5.0, cost_per_side_pct=0.24, sides=2)
    assert net == 4.52


def test_apply_transaction_cost_one_side():
    net = apply_transaction_cost(return_pct=1.0, cost_per_side_pct=0.24, sides=1)
    assert net == 0.76


def test_calculate_trade_net_return():
    # Gross = 10%, Net = 10 - 0.48 = 9.52
    net = calculate_trade_net_return(entry_price=100.0, exit_price=110.0, cost_per_side_pct=0.24)
    assert round(net, 6) == 9.52
