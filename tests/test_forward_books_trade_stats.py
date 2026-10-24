"""
tests/test_forward_books_trade_stats.py

The daily paper-book run now adds trade statistics to each book's summary (win rate, profit factor, worst loss: research/trade_stats.py), for the go-live gates. What must hold
here: both kinds of book (per-stock and one-account) produce them from their own logs with costs from the engine's cost model; open positions are marked at the last close; and if
anything is inconsistent the statistics are None and the run carries on, because a daily run must never fail on a diagnostic and wrong numbers would be worse than none.
"""

import pandas as pd
import pytest

import forward_books as fb


def universe(**last_closes):
    return {sym: {"df": pd.DataFrame({"close": [last]}, index=pd.DatetimeIndex(["2026-10-23"]))} for sym, last in last_closes.items()}


def test_a_one_account_book_gets_closed_and_open_trades_from_its_rebalance_fills():
    log = pd.DataFrame([
        {"date": pd.Timestamp("2026-10-19"), "symbol": "A.NS", "side": "buy", "shares": 10, "price": 100.0, "costs": 5.0},
        {"date": pd.Timestamp("2026-10-19"), "symbol": "B.NS", "side": "buy", "shares": 10, "price": 50.0, "costs": 5.0},
        {"date": pd.Timestamp("2026-11-02"), "symbol": "A.NS", "side": "sell", "shares": 10, "price": 120.0, "costs": 5.0}])
    s = fb._trade_stats_portfolio(log, universe(**{"A.NS": 120.0, "B.NS": 45.0}), 1_000_000.0)
    assert s["closed"]["n_trades"] == 1 and s["closed"]["n_winning"] == 1 and s["n_open"] == 1 and s["all_in"]["n_trades"] == 2
    assert s["closed"]["win_rate_pct"] == 100.0 and s["all_in"]["win_rate_pct"] == 50.0               # B, still open and under water, is in the honest figure
    assert s["account_inr"] == 1_000_000.0 and s["all_in"]["worst_loss_inr"] < 0


def test_inconsistent_fills_give_none_and_do_not_raise():
    sold_too_much = pd.DataFrame([{"date": pd.Timestamp("2026-10-19"), "symbol": "A.NS", "side": "buy", "shares": 10, "price": 100.0, "costs": 0.0},
                                  {"date": pd.Timestamp("2026-11-02"), "symbol": "A.NS", "side": "sell", "shares": 11, "price": 100.0, "costs": 0.0}])
    assert fb._trade_stats_portfolio(sold_too_much, universe(**{"A.NS": 100.0}), 1_000_000.0) is None
    held_without_a_price = pd.DataFrame([{"date": pd.Timestamp("2026-10-19"), "symbol": "ZZ.NS", "side": "buy", "shares": 10, "price": 100.0, "costs": 0.0}])
    assert fb._trade_stats_portfolio(held_without_a_price, universe(**{"A.NS": 100.0}), 1_000_000.0) is None


def test_a_book_with_no_fills_yet_has_zero_trades_not_none():
    s = fb._trade_stats_portfolio(pd.DataFrame(), universe(**{"A.NS": 100.0}), 1_000_000.0)
    assert s["all_in"]["n_trades"] == 0 and s["all_in"]["win_rate_pct"] is None and s["n_open"] == 0


def test_a_per_stock_book_counts_its_closed_trades_and_marks_its_open_position():
    log = pd.DataFrame([{"quantity": 10, "entry_price": 100.0, "exit_price": 110.0, "total_costs": 5.0, "return_pct": 9.4, "symbol": "A.NS"}])
    run = {"pooled_trade_log": log, "per_symbol": {"A.NS": {"open_position_at_end": None},
                                                    "B.NS": {"open_position_at_end": {"quantity": 10, "entry_price": 100.0, "buy_costs_total": 5.0}}}}
    s = fb._trade_stats_per_symbol(run, universe(**{"A.NS": 110.0, "B.NS": 90.0}), 1_000_000.0)
    assert s["closed"]["n_trades"] == 1 and s["closed"]["n_winning"] == 1 and s["n_open"] == 1
    assert s["all_in"]["n_trades"] == 2 and s["all_in"]["n_winning"] == 1 and s["all_in"]["worst_loss_pct_of_account"] < 0
    assert fb._trade_stats_per_symbol({"pooled_trade_log": log, "per_symbol": {"Q.NS": {"open_position_at_end": {"quantity": 1, "entry_price": 1.0, "buy_costs_total": 0.0}}}},
                                      universe(**{"A.NS": 1.0}), 1_000_000.0) is None                  # an open position with no price in the universe: nothing rather than wrong


def test_the_open_position_pays_the_engines_selling_cost_in_its_mark():
    run = {"pooled_trade_log": pd.DataFrame(), "per_symbol": {"B.NS": {"open_position_at_end": {"quantity": 100, "entry_price": 100.0, "buy_costs_total": 0.0}}}}
    s = fb._trade_stats_per_symbol(run, universe(**{"B.NS": 100.0}), 1_000_000.0)
    assert s["all_in"]["worst_loss_inr"] == pytest.approx(-fb._sell_cost(10_000.0))                     # flat price: the only loss is the cost of getting out
    assert fb._sell_cost(10_000.0) > 0


def test_the_summary_carries_the_statistics_and_the_old_fields_are_unchanged():
    m = {"total_return_pct": 1.0, "max_drawdown_pct": -2.0, "market_exposure_pct": 100.0}
    s = fb._summary(m, {"total_return_pct": 0.5, "max_drawdown_pct": -1.0}, 4, 10, None, {"all_in": {"n_trades": 3}})
    assert s["trade_stats"] == {"all_in": {"n_trades": 3}} and s["n_closed_trades"] is None and s["return_pct"] == 1.0
    assert fb._summary(m, {}, 4, 10, 5)["trade_stats"] is None
