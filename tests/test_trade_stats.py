"""
tests/test_trade_stats.py

research/trade_stats.py produces the numbers the go-live gates read. Each figure is checked against a hand calculation: win rate, average win and loss, profit factor,
the average trade, the worst loss as a share of the account, a position's whole life as one trade (adds and trims inside it), open positions marked with their sale costs,
and the property that matters most: a rule that keeps its losers open looks perfect on closed trades and is caught by the all-in version.
"""

import pandas as pd
import pytest

import trade_stats as ts


def trade(pnl, ret):
    return {"pnl": pnl, "ret_pct": ret}


# --- summarize --------------------------------------------------------------------------------------------------------------------

def test_the_summary_matches_a_hand_calculation():
    s = ts.summarize([trade(100, 1.0), trade(200, 2.0), trade(-50, -0.5), trade(-150, -1.5)], account=10_000.0)
    assert s["n_trades"] == 4 and s["n_winning"] == 2 and s["win_rate_pct"] == 50.0
    assert s["avg_win_pct"] == pytest.approx(1.5) and s["avg_loss_pct"] == pytest.approx(-1.0)
    assert s["profit_factor"] == pytest.approx(300 / 200) and s["expectancy_pct"] == pytest.approx(0.25)
    assert s["worst_loss_inr"] == -150 and s["worst_loss_pct_of_account"] == pytest.approx(-1.5)


def test_no_losing_trade_has_no_profit_factor_and_no_worst_loss_and_no_trade_has_no_averages():
    s = ts.summarize([trade(10, 0.1), trade(30, 0.3)], account=1000.0)
    assert s["profit_factor"] is None and s["avg_loss_pct"] is None            # no ratio and no average loss when nothing lost
    assert s["worst_loss_inr"] == 0.0 and s["worst_loss_pct_of_account"] == 0.0 # the worst loss is zero, which is not the same as "no data"
    assert s["win_rate_pct"] == 100.0
    e = ts.summarize([], account=1000.0)
    assert e["n_trades"] == 0 and e["win_rate_pct"] is None and e["expectancy_pct"] is None and e["profit_factor"] is None
    assert e["worst_loss_inr"] is None and e["worst_loss_pct_of_account"] is None


def test_a_trade_that_made_nothing_is_neither_a_win_nor_a_loss():
    s = ts.summarize([trade(0.0, 0.0), trade(10, 1.0)], account=1000.0)
    assert s["n_trades"] == 2 and s["n_winning"] == 1 and s["win_rate_pct"] == 50.0 and s["worst_loss_inr"] == 0.0


# --- per-stock books --------------------------------------------------------------------------------------------------------------

def test_a_closed_trade_of_a_per_stock_book_is_its_gain_after_both_sides_costs():
    log = pd.DataFrame([{"quantity": 10, "entry_price": 100.0, "exit_price": 110.0, "total_costs": 5.0, "return_pct": 9.4}])
    t = ts.closed_from_log(log)
    assert t == [{"pnl": pytest.approx(95.0), "ret_pct": 9.4}]                                  # 10 x (110 - 100) - 5


def test_an_open_position_is_marked_at_the_last_close_with_the_cost_of_selling_it():
    out = ts.open_marked([{"quantity": 10, "entry_price": 100.0, "buy_costs_total": 5.0, "last_close": 90.0}], sell_cost=lambda v: 0.001 * v)
    assert out[0]["pnl"] == pytest.approx(900 - 0.9 - 1005)                                     # value 900, sale costs 0.9, paid 1005
    assert out[0]["ret_pct"] == pytest.approx(100 * (900 - 0.9 - 1005) / 1005)


# --- one-account books: a position's whole life is one trade ----------------------------------------------------------------------

def fill(date, symbol, side, shares, price, costs=None):
    return {"date": date, "symbol": symbol, "side": side, "shares": shares, "price": price, "costs": costs}


NO_COST = lambda v: 0.0


def test_buys_and_a_final_sell_of_one_position_are_a_single_closed_trade():
    fills = [fill("2026-10-19", "A", "buy", 10, 100.0, 5.0), fill("2026-11-02", "A", "buy", 5, 110.0, 3.0), fill("2026-12-01", "A", "sell", 15, 120.0, 10.0)]
    closed, still_open = ts.round_trips(fills, {}, NO_COST)
    assert still_open == [] and len(closed) == 1
    assert closed[0]["pnl"] == pytest.approx((1800 - 10) - (1000 + 5 + 550 + 3))                # proceeds 1790, cost 1558: 232
    assert closed[0]["ret_pct"] == pytest.approx(100 * 232 / 1558)


def test_a_trim_is_not_a_closed_trade_the_rest_is_an_open_one_marked_with_what_was_already_taken_out():
    fills = [fill("2026-10-19", "A", "buy", 10, 100.0), fill("2026-11-02", "A", "sell", 4, 110.0)]
    closed, still_open = ts.round_trips(fills, {"A": 105.0}, NO_COST)
    assert closed == [] and len(still_open) == 1
    assert still_open[0]["pnl"] == pytest.approx(440 + 6 * 105 - 1000)                          # 70: the 4 sold at 110 and the 6 held at 105, against 1000 paid


def test_an_open_position_of_a_one_account_book_pays_the_cost_of_selling_it_in_its_mark():
    closed, still_open = ts.round_trips([fill("d1", "A", "buy", 10, 100.0)], {"A": 105.0}, sell_cost=lambda v: 0.01 * v)
    assert closed == [] and still_open[0]["pnl"] == pytest.approx(1050 - 10.5 - 1000)           # value 1050, selling costs 10.5, paid 1000: 39.5
    assert still_open[0]["ret_pct"] == pytest.approx(100 * 39.5 / 1000)


def test_a_position_closed_and_opened_again_is_two_separate_trades_and_symbols_are_independent():
    fills = [fill("d1", "A", "buy", 10, 100.0), fill("d1", "B", "buy", 10, 50.0), fill("d2", "A", "sell", 10, 110.0),
             fill("d3", "A", "buy", 10, 120.0), fill("d4", "A", "sell", 10, 100.0), fill("d5", "B", "sell", 10, 40.0)]
    closed, still_open = ts.round_trips(fills, {}, NO_COST)
    assert still_open == [] and [round(c["pnl"]) for c in closed] == [100, -200, -100]          # A: +100, A again: -200, B: -100


def test_selling_more_than_held_or_holding_a_symbol_with_no_last_price_raises_instead_of_giving_wrong_numbers():
    with pytest.raises(ValueError, match="sold 11"):
        ts.round_trips([fill("d1", "A", "buy", 10, 100.0), fill("d2", "A", "sell", 11, 100.0)], {}, NO_COST)
    with pytest.raises(ValueError, match="no last price"):
        ts.round_trips([fill("d1", "A", "buy", 10, 100.0)], {}, NO_COST)


def test_fills_are_processed_oldest_first_whatever_order_they_arrive_in():
    fills = [fill("2026-12-01", "A", "sell", 10, 120.0), fill("2026-10-19", "A", "buy", 10, 100.0)]
    closed, _ = ts.round_trips(fills, {}, NO_COST)
    assert len(closed) == 1 and closed[0]["pnl"] == pytest.approx(200)


# --- closed against all-in --------------------------------------------------------------------------------------------------------

def test_a_rule_that_keeps_its_losers_open_looks_perfect_when_closed_and_is_caught_all_in():
    closed = [trade(100, 1.0)] * 10                                                              # ten winners were sold
    still_open = [trade(-400, -4.0)] * 10                                                        # ten losers were never sold
    b = ts.book_stats(closed, still_open, account=100_000.0)
    assert b["closed"]["win_rate_pct"] == 100.0 and b["all_in"]["win_rate_pct"] == 50.0
    assert b["n_open"] == 10 and b["all_in"]["n_trades"] == 20 and b["all_in"]["profit_factor"] == pytest.approx(1000 / 4000)
    assert b["all_in"]["worst_loss_pct_of_account"] == pytest.approx(-0.4) and b["account_inr"] == 100_000.0
