"""
tests/test_universe_prelisting.py

Regression test for a real bug found during Stage 5: engine/universe.py
combined multiple symbols' equity curves by concat + ffill + sum. A
symbol that lists AFTER the backtest start date (e.g. JIOFIN.NS, which
only has data from 2023-08-21 onward) has no rows before its listing --
ffill() leaves those rows NaN, and sum(skipna=True) then silently
treated that symbol's capital as ZERO for years, instead of "idle cash
sitting at its own initial_capital," understating the combined curve.

Fixed by fillna(initial_capital) after the ffill(). This test locks that
fix in: a two-symbol universe where one symbol lists late must show the
combined curve holding at exactly 2x initial_capital before the late
symbol starts, and the correct sum of both real curves after.

Uses the real cached CSVs for RELIANCE.NS (full 2015- history) and
JIOFIN.NS (starts 2023-08-21) -- read directly from data/cache/, NOT
through data.loader.load_price_data(), which would fall back to a
network call on any cache gap. No network access in this test, ever.
"""

import os

import pandas as pd
import pytest

from universe import run_strategy_on_universe
import buy_and_hold

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache")
RELIANCE_TICKER = "RELIANCE.NS"
JIOFIN_TICKER = "JIOFIN.NS"
START = "2015-01-01"
END = "2025-12-31"
INITIAL_CAPITAL = 1_000_000.0


def _read_cached(ticker):
    path = os.path.join(CACHE_DIR, f"{ticker}.csv")
    if not os.path.exists(path):
        pytest.skip(f"{path} not cached -- run the project's earlier stages once to populate data/cache/")
    df = pd.read_csv(path, index_col="date", parse_dates=True)
    return df


def _empty_report(ticker):
    """No discontinuities -- this test is about aggregation math, not the gate (covered in test_gate.py)."""
    return {"symbol": ticker, "discontinuities": [], "usable": True, "checks": []}


@pytest.fixture
def two_symbol_universe():
    reliance_df = _read_cached(RELIANCE_TICKER)
    jiofin_df = _read_cached(JIOFIN_TICKER)

    assert reliance_df.index.min() <= pd.Timestamp("2015-01-05")  # full early history
    assert jiofin_df.index.min() >= pd.Timestamp("2023-08-01")    # confirms this really is a late listing

    return {
        RELIANCE_TICKER: {"df": reliance_df, "report": _empty_report(RELIANCE_TICKER), "symbol": "RELIANCE"},
        JIOFIN_TICKER: {"df": jiofin_df, "report": _empty_report(JIOFIN_TICKER), "symbol": "JIOFIN"},
    }


def test_combined_curve_holds_at_two_x_capital_before_late_listing(two_symbol_universe):
    """
    Before JIOFIN.NS has any data at all, its "book" is 100% idle cash --
    the combined equity curve must equal exactly 2x initial_capital
    (RELIANCE's book, wherever it is, PLUS JIOFIN's book sitting flat at
    initial_capital), not 1x (which is what the bug produced: JIOFIN's
    book silently contributing zero instead of its own idle capital).
    """
    result = run_strategy_on_universe(
        two_symbol_universe, buy_and_hold, {}, START, END,
        initial_capital=INITIAL_CAPITAL,
    )
    combined = result["combined_equity_curve"]

    # buy_and_hold enters on day 2 (the look-ahead lag delays entry by
    # one bar), so RELIANCE's book is still exactly INITIAL_CAPITAL on
    # day 1 too -- the very first day is the cleanest possible check.
    first_day_value = combined.iloc[0]
    assert first_day_value == pytest.approx(2 * INITIAL_CAPITAL, abs=1e-6)

    # And every day up to (not including) JIOFIN's listing date must
    # still equal RELIANCE's own book plus JIOFIN's idle capital.
    reliance_curve = result["per_symbol"][RELIANCE_TICKER]["equity_curve"]
    pre_listing_dates = combined.index[combined.index < pd.Timestamp("2023-08-21")]
    assert len(pre_listing_dates) > 1000  # sanity: this is most of the series, not a one-off edge

    for date in [pre_listing_dates[0], pre_listing_dates[len(pre_listing_dates) // 2], pre_listing_dates[-1]]:
        expected = reliance_curve.loc[date] + INITIAL_CAPITAL
        assert combined.loc[date] == pytest.approx(expected, abs=1e-6), (
            f"On {date.date()} (before JIOFIN listed), combined equity should be "
            f"RELIANCE's book + JIOFIN's idle capital, not RELIANCE's book alone."
        )


def test_symbol_with_zero_rows_in_the_window_is_excluded_not_crashed(two_symbol_universe):
    """
    Regression test for engine/backtest.py's date-window fix: querying a
    window entirely before a symbol's listing date (JIOFIN.NS starts
    2023-08-21) now makes run_backtest() raise ValueError (see
    tests/test_backtest_date_window.py) instead of silently running that
    symbol's full history. run_strategy_on_universe() must catch that
    and exclude the symbol gracefully -- the same way a gate block or a
    warm-up shortfall is already handled -- not crash the whole batch.
    """
    result = run_strategy_on_universe(
        two_symbol_universe, buy_and_hold, {}, "2015-01-01", "2020-06-30",
        initial_capital=INITIAL_CAPITAL,
    )
    assert JIOFIN_TICKER not in result["per_symbol"]
    blocked_tickers = [t for t, _ in result["blocked"]]
    assert JIOFIN_TICKER in blocked_tickers
    reason = dict(result["blocked"])[JIOFIN_TICKER]
    assert "no data in this window" in reason
    # RELIANCE has full history over this window and must still be included.
    assert RELIANCE_TICKER in result["per_symbol"]


def test_combined_curve_after_listing_is_the_true_sum_of_both_books(two_symbol_universe):
    """After JIOFIN lists, the combined curve must be the exact sum of both symbols' real, independently-computed equity curves -- not just 'not NaN'."""
    result = run_strategy_on_universe(
        two_symbol_universe, buy_and_hold, {}, START, END,
        initial_capital=INITIAL_CAPITAL,
    )
    combined = result["combined_equity_curve"]
    reliance_curve = result["per_symbol"][RELIANCE_TICKER]["equity_curve"]
    jiofin_curve = result["per_symbol"][JIOFIN_TICKER]["equity_curve"]

    post_listing_dates = combined.index[combined.index >= pd.Timestamp("2023-08-21")]
    check_date = post_listing_dates[len(post_listing_dates) // 2]  # a date well after listing, both books active

    expected = reliance_curve.loc[check_date] + jiofin_curve.loc[check_date]
    assert combined.loc[check_date] == pytest.approx(expected, abs=1e-6)
