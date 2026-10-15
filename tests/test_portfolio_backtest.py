"""
tests/test_portfolio_backtest.py

Regression tests for engine/portfolio_backtest.py -- the new,
weight-target backtest engine built for cross-sectional momentum
(MOMENTUM_METHODOLOGY.md). Structural correctness (rebalance timing,
sizing, turnover, look-ahead safety, gate exclusion) is verified by
hand on a small, fully hand-traceable toy universe; exact cost amounts
reuse engine/costs.py directly (already ground-truth tested in
test_costs.py) rather than re-deriving the cost formula here.
"""

import pandas as pd
import pytest

import costs
from portfolio_backtest import run_portfolio_backtest, _map_formations_to_execution_dates

INITIAL_CAPITAL = 100_000.0


def _toy_df(prices: list, start_date: str) -> pd.DataFrame:
    dates = pd.date_range(start_date, periods=len(prices), freq="D")
    return pd.DataFrame({
        "open": prices, "high": [p * 1.01 for p in prices], "low": [p * 0.99 for p in prices],
        "close": prices, "volume": [1_000_000] * len(prices),
    }, index=dates)


def _clean_report(ticker):
    return {"symbol": ticker, "discontinuities": [], "usable": True, "checks": []}


def _blocked_report(ticker, date):
    return {
        "symbol": ticker,
        "discontinuities": [{"date": pd.Timestamp(date), "magnitude": -0.5, "status": "UNREVIEWED", "reason": "test"}],
    }


# --- 1. Formation-to-execution-date mapping (the look-ahead boundary) ---

def test_formation_maps_to_first_later_window_date_not_same_day():
    window_dates = list(pd.date_range("2021-01-02", "2021-01-10", freq="D"))
    formations = pd.DatetimeIndex(["2021-01-05"])  # inside the window
    mapping = _map_formations_to_execution_dates(formations, window_dates)
    assert mapping[pd.Timestamp("2021-01-06")] == pd.Timestamp("2021-01-05")
    assert pd.Timestamp("2021-01-05") not in mapping  # never executes same-day


def test_formation_equal_to_window_start_executes_the_day_after_not_on_start():
    """
    The edge case that made an earlier version of this engine unsafe: a
    formation date exactly equal to the window's first trading day must
    NOT execute on that same day (that would be trading on information
    dated the same day as the trade, i.e. look-ahead) -- it must wait
    for the next one.
    """
    window_dates = list(pd.date_range("2021-01-02", "2021-01-10", freq="D"))
    formations = pd.DatetimeIndex(["2021-01-02"])  # == window_dates[0]
    mapping = _map_formations_to_execution_dates(formations, window_dates)
    assert mapping[pd.Timestamp("2021-01-03")] == pd.Timestamp("2021-01-02")
    assert pd.Timestamp("2021-01-02") not in mapping


def test_a_pre_window_formation_is_picked_up_on_the_windows_first_day():
    """A formation date from before the window still governs what the
    portfolio holds walking into day 1 -- real, already-public info."""
    window_dates = list(pd.date_range("2021-02-01", "2021-02-05", freq="D"))
    formations = pd.DatetimeIndex(["2021-01-15"])  # well before the window
    mapping = _map_formations_to_execution_dates(formations, window_dates)
    assert mapping[pd.Timestamp("2021-02-01")] == pd.Timestamp("2021-01-15")


def test_the_most_recent_of_several_stale_formations_wins():
    """Two formations both before the window map to the SAME first
    window date -- the more recent one must be what's actually used."""
    window_dates = list(pd.date_range("2021-03-01", "2021-03-05", freq="D"))
    formations = pd.DatetimeIndex(["2021-01-01", "2021-02-01"])  # ascending, both pre-window
    mapping = _map_formations_to_execution_dates(formations, window_dates)
    assert mapping[pd.Timestamp("2021-03-01")] == pd.Timestamp("2021-02-01")  # not 2021-01-01


# --- 2. Full backtest: rebalance sizing, turnover, and gate exclusion ---

@pytest.fixture
def two_symbol_universe():
    # Flat prices (open == close, no drift) so every rupee amount is
    # hand-computable without predicting a price path.
    a_df = _toy_df([100.0] * 20, "2021-01-01")
    b_df = _toy_df([200.0] * 20, "2021-01-01")
    return {
        "A": {"df": a_df, "report": _clean_report("A")},
        "B": {"df": b_df, "report": _clean_report("B")},
    }


def test_equal_weight_rebalance_sizing_is_correct(two_symbol_universe):
    """
    One formation date (day 5, 2021-01-06) sets A=0.5/B=0.5, executing
    on day 6 (2021-01-07) at that day's open. With flat prices and no
    prior holdings, expected shares are floor(50,000/100)=500 for A and
    floor(50,000/200)=250 for B, MINUS whatever buy costs
    engine/costs.py actually charges (computed here via the real
    function, not re-derived by hand -- see test_costs.py for that).
    """
    target_weights = pd.DataFrame(
        {"A": [0.5], "B": [0.5]}, index=pd.DatetimeIndex(["2021-01-06"]),
    )
    result = run_portfolio_backtest(
        two_symbol_universe, target_weights, "2021-01-01", "2021-01-20",
        initial_capital=INITIAL_CAPITAL,
    )

    exec_date = pd.Timestamp("2021-01-07")
    buys = result["trade_log"][(result["trade_log"]["date"] == exec_date) & (result["trade_log"]["side"] == "buy")]
    assert set(buys["symbol"]) == {"A", "B"}

    a_shares = int(buys.loc[buys["symbol"] == "A", "shares"].iloc[0])
    b_shares = int(buys.loc[buys["symbol"] == "B", "shares"].iloc[0])
    assert a_shares == int((INITIAL_CAPITAL * 0.5) // 100.0)
    # B is bought SECOND (alphabetical loop order), after A's purchase
    # has already spent real cash on transaction costs -- B's naive
    # floor(50,000/200)=250 shares can legitimately cost a few rupees
    # more than what's left, correctly buying one share fewer (249) in
    # that case rather than overspending. Both values are acceptable;
    # anything else would mean the cash-affordability check is broken.
    naive_b_shares = int((INITIAL_CAPITAL * 0.5) // 200.0)
    assert b_shares in (naive_b_shares, naive_b_shares - 1)

    # Post-rebalance equity must equal cash left + both positions' value,
    # i.e. initial capital minus exactly the costs actually charged.
    total_buy_costs = buys["costs"].sum()
    post_equity = result["equity_curve"].loc[exec_date]
    assert post_equity == pytest.approx(INITIAL_CAPITAL - total_buy_costs, abs=1e-6)


def test_full_rebalance_exits_a_dropped_name_and_concentrates_the_rest(two_symbol_universe):
    """Two formation dates: first holds A+B equally, second drops B
    entirely and goes all-in on A -- confirms a full (not incremental)
    rebalance actually sells out of a no-longer-selected name."""
    target_weights = pd.DataFrame(
        {"A": [0.5, 1.0], "B": [0.5, 0.0]},
        index=pd.DatetimeIndex(["2021-01-06", "2021-01-12"]),
    )
    result = run_portfolio_backtest(
        two_symbol_universe, target_weights, "2021-01-01", "2021-01-20",
        initial_capital=INITIAL_CAPITAL,
    )

    second_exec = pd.Timestamp("2021-01-13")
    sells = result["trade_log"][(result["trade_log"]["date"] == second_exec) & (result["trade_log"]["side"] == "sell")]
    assert "B" in set(sells["symbol"])
    assert result["final_shares"]["B"] == 0
    assert result["final_shares"]["A"] > 0


def test_turnover_is_reported_and_roughly_matches_traded_value(two_symbol_universe):
    target_weights = pd.DataFrame(
        {"A": [0.5], "B": [0.5]}, index=pd.DatetimeIndex(["2021-01-06"]),
    )
    result = run_portfolio_backtest(
        two_symbol_universe, target_weights, "2021-01-01", "2021-01-20",
        initial_capital=INITIAL_CAPITAL,
    )
    rebalance = result["rebalance_log"].iloc[0]
    # First-ever rebalance from all-cash: turnover should be close to
    # the full portfolio value (everything traded from scratch).
    assert rebalance["turnover_pct"] == pytest.approx(100.0, abs=1.0)


def test_a_gate_blocked_symbol_is_excluded_from_eligibility_entirely(two_symbol_universe):
    two_symbol_universe["B"]["report"] = _blocked_report("B", "2021-01-10")
    target_weights = pd.DataFrame(
        {"A": [0.5], "B": [0.5]}, index=pd.DatetimeIndex(["2021-01-06"]),
    )
    result = run_portfolio_backtest(
        two_symbol_universe, target_weights, "2021-01-01", "2021-01-20",
        initial_capital=INITIAL_CAPITAL,
    )
    assert "B" not in result["eligible_symbols"]
    assert any(t == "B" for t, _ in result["blocked"])
    assert (result["trade_log"]["symbol"] == "B").sum() == 0


def test_an_unlisted_never_held_symbol_does_not_poison_equity_with_nan():
    """
    Regression test for a second real bug found immediately after fixing
    the one above: forward-fill cannot fill dates BEFORE a symbol's own
    first real row (e.g. a late listing) -- those stay genuine NaN.
    `shares[t] * NaN` is NaN in Python/pandas even when shares[t] == 0,
    which poisoned the ENTIRE portfolio's summed equity for every day of
    an early window until the late-listed symbol actually started
    trading (first observed on Nifty 50's real 2015-2020 in-sample
    window, where several universe members list well after 2015 --
    Sharpe/CAGR came back NaN for the whole window). D here lists 5 days
    into the window and is never selected (weight always 0) -- equity on
    days before D lists must be a real, finite number, not NaN.
    """
    d_dates = pd.date_range("2021-01-06", periods=5, freq="D")  # D starts 5 days into the window
    d_df = pd.DataFrame({
        "open": [30.0] * 5, "high": [31.0] * 5, "low": [29.0] * 5, "close": [30.0] * 5, "volume": [1_000_000] * 5,
    }, index=d_dates)
    a_df = _toy_df([100.0] * 10, "2021-01-01")

    universe = {
        "A": {"df": a_df, "report": _clean_report("A")},
        "D": {"df": d_df, "report": _clean_report("D")},
    }
    # D is never selected -- weight 0 for the one and only formation date.
    target_weights = pd.DataFrame({"A": [1.0], "D": [0.0]}, index=pd.DatetimeIndex(["2021-01-01"]))

    result = run_portfolio_backtest(universe, target_weights, "2021-01-01", "2021-01-10", initial_capital=INITIAL_CAPITAL)

    assert not result["equity_curve"].isna().any(), (
        f"Equity curve contains NaN before D's listing date:\n{result['equity_curve']}"
    )
    assert result["final_shares"]["D"] == 0


def test_a_held_symbol_missing_a_row_on_some_date_is_forward_filled_not_zeroed():
    """
    Regression test for a real bug found while running this engine for
    the first time on real Nifty 50 data: 2025-03-18 is a known
    market-wide data artifact (data/known_issues.md) that
    data/loader.py correctly strips from every symbol's OWN frame -- but
    the window's UNION trading calendar still included that date because
    a DIFFERENT (non-held) symbol still had a row for it. Every held
    symbol missing that date got marked to a price of 0.0 via a plain
    `.get(date, 0.0)`, producing a fabricated ~99.8% one-day "crash"
    that reverted the very next day. Reproduced directly here: symbol A
    (held) is missing a row on day 3; symbol C (never held, just present
    in the universe) has a row on day 3, so day 3 IS in the window's
    trading calendar. Equity on day 3 must equal A's LAST REAL price
    (forward-filled), not zero.
    """
    dates_with_gap = pd.date_range("2021-01-01", periods=10, freq="D").delete(2)  # A is missing day index 2
    a_df = pd.DataFrame({
        "open": [100.0] * len(dates_with_gap), "high": [101.0] * len(dates_with_gap),
        "low": [99.0] * len(dates_with_gap), "close": [100.0] * len(dates_with_gap),
        "volume": [1_000_000] * len(dates_with_gap),
    }, index=dates_with_gap)
    c_df = _toy_df([50.0] * 10, "2021-01-01")  # has every day, including the one A is missing; never selected

    universe = {
        "A": {"df": a_df, "report": _clean_report("A")},
        "C": {"df": c_df, "report": _clean_report("C")},
    }
    target_weights = pd.DataFrame({"A": [1.0], "C": [0.0]}, index=pd.DatetimeIndex(["2021-01-01"]))

    result = run_portfolio_backtest(universe, target_weights, "2021-01-01", "2021-01-10", initial_capital=INITIAL_CAPITAL)

    gap_date = pd.Timestamp("2021-01-03")  # the date A is missing but C has
    assert gap_date in result["equity_curve"].index
    day_before = result["equity_curve"].loc[pd.Timestamp("2021-01-02")]
    day_of_gap = result["equity_curve"].loc[gap_date]
    day_after = result["equity_curve"].loc[pd.Timestamp("2021-01-04")]

    # A's price didn't move (flat 100 throughout its own real rows), so
    # equity on the gap day must equal the surrounding days almost
    # exactly -- NOT collapse toward zero and then jump back.
    assert day_of_gap == pytest.approx(day_before, rel=1e-6)
    assert day_of_gap == pytest.approx(day_after, rel=1e-6)


def test_a_price_change_after_the_execution_date_cannot_affect_an_already_executed_trade(two_symbol_universe):
    """
    Direct look-ahead check: re-run with symbol A's price changed ONLY
    on and after 2021-01-15 (well after the 2021-01-07 execution date)
    and confirm the executed trade on 2021-01-07 is byte-identical.
    """
    target_weights = pd.DataFrame(
        {"A": [0.5], "B": [0.5]}, index=pd.DatetimeIndex(["2021-01-06"]),
    )
    baseline = run_portfolio_backtest(
        two_symbol_universe, target_weights, "2021-01-01", "2021-01-20",
        initial_capital=INITIAL_CAPITAL,
    )

    altered_universe = {
        "A": {"df": two_symbol_universe["A"]["df"].copy(), "report": _clean_report("A")},
        "B": {"df": two_symbol_universe["B"]["df"].copy(), "report": _clean_report("B")},
    }
    altered_universe["A"]["df"].loc["2021-01-15":, ["open", "close"]] = 9999.0
    altered = run_portfolio_backtest(
        altered_universe, target_weights, "2021-01-01", "2021-01-20",
        initial_capital=INITIAL_CAPITAL,
    )

    exec_date = pd.Timestamp("2021-01-07")
    baseline_trades = baseline["trade_log"][baseline["trade_log"]["date"] == exec_date].reset_index(drop=True)
    altered_trades = altered["trade_log"][altered["trade_log"]["date"] == exec_date].reset_index(drop=True)
    pd.testing.assert_frame_equal(baseline_trades, altered_trades)
