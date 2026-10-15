"""
tests/test_backtest_date_window.py

Regression test for a real, previously-undetected bug: run_backtest()'s
`start`/`end` parameters were used ONLY by the discontinuity gate check
-- the actual trading loop ran over df's ENTIRE history regardless of
what range was requested. Confirmed by hand-tracing HAVELLS.NS: an
"in-sample" (2015 to 2020-06-30) and "out-of-sample" (2020-07-01 to
2025-12-31) call on the same symbol/signal produced byte-identical
equity curves. This meant every in-sample/out-of-sample comparison in
this project (run_validation.py, the harness demo scripts, the
Midcap/Smallcap control comparison) was running the same full-history
backtest twice, not two genuinely different windows -- the harness's
entire "confirmed on out-of-sample data" validation criterion was
checking nothing. See MIDCAP_SMALLCAP_FINDINGS.md's amendment section.

Fixed in engine/backtest.py: position/signal are still derived from the
FULL history (correct MA warm-up, and a trend already established
going into `start` is respected rather than artificially forgotten),
but the trading loop, equity curve, and trade log are now sliced to
[start, end], and every call starts flat with fresh capital.
"""

import pandas as pd
import pytest

from backtest import run_backtest


def _trend_df():
    """
    20 days. Prices rise steadily throughout -- the exact price path
    doesn't matter here, only that entry/exit costs are computable and
    the signal transitions are known ahead of time.
    """
    dates = pd.date_range("2021-01-01", periods=20, freq="D")
    prices = [100.0 + i for i in range(20)]
    return pd.DataFrame({
        "open": prices, "high": [p + 5 for p in prices], "low": [p - 5 for p in prices],
        "close": prices, "volume": [1_000_000] * 20,
    }, index=dates)


def _passing_report():
    return {"symbol": "TEST.NS", "discontinuities": [], "usable": True, "checks": []}


def _signal_up_from_day5(index):
    """Flat (0) for the first 5 days, then long (1) for the rest -- one clean transition on day index 5."""
    return pd.Series([0.0] * 5 + [1.0] * 15, index=index, name="signal")


def test_equity_curve_is_restricted_to_the_requested_window():
    df = _trend_df()
    signal = _signal_up_from_day5(df.index)
    report = _passing_report()

    start, end = "2021-01-10", "2021-01-15"  # entirely inside the trend-up region
    result = run_backtest(df, signal, report, start, end, initial_capital=100_000.0)

    assert result["equity_curve"].index.min() == pd.Timestamp(start)
    assert result["equity_curve"].index.max() == pd.Timestamp(end)
    assert len(result["equity_curve"]) == 6  # 2021-01-10 .. 2021-01-15 inclusive


def test_a_trend_already_established_before_start_is_respected_on_day_one():
    """
    The signal went long on day index 5 (2021-01-06); the lagged
    POSITION -- what run_backtest actually acts on -- reflects that
    starting the next bar, 2021-01-07, well before this window starts
    on 2021-01-10. The window must open ALREADY IN A TRADE (entered on
    its very first bar), not wait to "discover" a trend it should
    already know about from real prior history.
    """
    df = _trend_df()
    signal = _signal_up_from_day5(df.index)
    report = _passing_report()

    result = run_backtest(df, signal, report, "2021-01-10", "2021-01-15", initial_capital=100_000.0)

    assert result["open_position_at_end"] is not None
    assert result["open_position_at_end"]["entry_date"] == pd.Timestamp("2021-01-10")


def test_each_window_starts_flat_with_fresh_capital_not_a_continuation():
    """
    Running the SAME uptrend in two back-to-back windows must each
    independently start flat and re-enter on their own first bar --
    neither window inherits the other's cash/shares state.
    """
    df = _trend_df()
    signal = _signal_up_from_day5(df.index)
    report = _passing_report()

    # Both windows fall entirely after the signal's one transition
    # (position goes to 1 starting 2021-01-07, i.e. signal.shift(1) of
    # the day-index-5 flip) -- position is already 1 on both windows'
    # first bar, so each must independently enter on ITS OWN day one.
    window_a = run_backtest(df, signal, report, "2021-01-08", "2021-01-12", initial_capital=100_000.0)
    window_b = run_backtest(df, signal, report, "2021-01-13", "2021-01-20", initial_capital=100_000.0)

    assert window_a["open_position_at_end"]["entry_date"] == pd.Timestamp("2021-01-08")
    assert window_b["open_position_at_end"]["entry_date"] == pd.Timestamp("2021-01-13")
    # Window B's first-bar equity must reflect ITS OWN fresh capital, not
    # window A's ending equity -- i.e. it bought using ~100,000, not
    # window A's (different) final cash+shares figure.
    assert window_b["equity_curve"].iloc[0] == pytest.approx(100_000.0, rel=0.01)


def test_two_disjoint_windows_on_the_same_signal_now_produce_different_results():
    """
    THE regression this file exists to lock in: before the fix, this
    would have returned IDENTICAL equity curves for both windows
    (both silently ran over the full 20-day df). They must now differ,
    since each window covers different, non-overlapping calendar days.
    """
    df = _trend_df()
    signal = _signal_up_from_day5(df.index)
    report = _passing_report()

    in_sample = run_backtest(df, signal, report, "2021-01-01", "2021-01-10", initial_capital=100_000.0)
    out_of_sample = run_backtest(df, signal, report, "2021-01-11", "2021-01-20", initial_capital=100_000.0)

    assert not in_sample["equity_curve"].equals(out_of_sample["equity_curve"])
    assert list(in_sample["equity_curve"].index) != list(out_of_sample["equity_curve"].index)


def test_a_window_entirely_outside_the_data_raises_instead_of_silently_using_everything():
    df = _trend_df()
    signal = _signal_up_from_day5(df.index)
    report = _passing_report()

    with pytest.raises(ValueError, match="No rows in df"):
        run_backtest(df, signal, report, "2022-01-01", "2022-12-31", initial_capital=100_000.0)
