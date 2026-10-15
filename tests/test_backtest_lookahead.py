"""
tests/test_backtest_lookahead.py

The look-ahead guard in engine/backtest.py was verified by REASONING,
never by actually breaking the lag and watching the assertion fire. An
assertion that has never been observed to fire is not known to work --
this file breaks it, on purpose, two different ways, and confirms it
actually raises. It also confirms the normal, correctly-lagged case does
NOT raise (a guard that always fires is as useless as one that never does).
"""

import pandas as pd
import pytest

import backtest
from backtest import _apply_look_ahead_lag, _assert_no_look_ahead, run_backtest


def _tiny_df():
    dates = pd.date_range("2021-01-01", periods=10, freq="D")
    return pd.DataFrame({
        "open": [100.0, 101, 102, 103, 104, 105, 106, 107, 108, 109],
        "high": [110.0] * 10,
        "low": [90.0] * 10,
        "close": [100.0, 101, 102, 103, 104, 105, 106, 107, 108, 109],
        "volume": [1_000_000] * 10,
    }, index=dates)


def _passing_report():
    """A report with no discontinuities -- the gate should never block this."""
    return {"symbol": "TEST.NS", "discontinuities": [], "usable": True, "checks": []}


def _signal_with_transitions(index):
    # A signal with more than one transition, so a broken lag has
    # multiple opportunities to be caught, not just one lucky boundary.
    return pd.Series([0.0, 0, 0, 1, 1, 1, 0, 0, 1, 1], index=index, name="signal")


# --- 1. Direct unit tests of the guard itself ---

def test_correctly_lagged_position_does_not_raise():
    df = _tiny_df()
    signal = _signal_with_transitions(df.index)
    position = _apply_look_ahead_lag(signal)
    _assert_no_look_ahead(signal, position)  # must not raise


def test_guard_fires_when_position_equals_signal_unlagged():
    """The most direct possible violation: position == signal, no lag at all."""
    df = _tiny_df()
    signal = _signal_with_transitions(df.index)
    broken_position = signal.copy()  # the bug: forgot to shift

    with pytest.raises(AssertionError, match="LOOK-AHEAD VIOLATION"):
        _assert_no_look_ahead(signal, broken_position)


def test_guard_fires_when_first_bar_is_nonzero():
    """A position that starts long on bar 0, with no prior signal to justify it."""
    df = _tiny_df()
    signal = _signal_with_transitions(df.index)
    correctly_lagged = _apply_look_ahead_lag(signal)
    tampered = correctly_lagged.copy()
    tampered.iloc[0] = 1.0  # bug: claims a position before any signal existed

    with pytest.raises(AssertionError, match="first bar's position must be 0"):
        _assert_no_look_ahead(signal, tampered)


def test_guard_fires_on_a_single_shifted_bar():
    """A lag that's correct everywhere except one bar -- the guard must still catch it."""
    df = _tiny_df()
    signal = _signal_with_transitions(df.index)
    correctly_lagged = _apply_look_ahead_lag(signal)
    tampered = correctly_lagged.copy()
    # Bar 3 is a real transition point (signal flips 0->1 between index 2
    # and 3), so overwriting position[3] with signal[3] instead of the
    # correct signal[2] actually changes its value -- not a no-op tamper.
    assert signal.iloc[2] != signal.iloc[3]
    tampered.iloc[3] = signal.iloc[3]  # bug: this one bar peeked at same-day signal

    with pytest.raises(AssertionError, match="LOOK-AHEAD VIOLATION"):
        _assert_no_look_ahead(signal, tampered)


# --- 2. Integration test: the guard fires from inside run_backtest() itself,
#        not just when called directly ---

def test_run_backtest_raises_if_the_lag_is_disabled(monkeypatch):
    """
    Monkeypatches _apply_look_ahead_lag itself (as it's actually called
    from inside run_backtest) to simulate someone weakening it in the
    real code path -- e.g. "fixing" it to return the signal unchanged.
    run_backtest must fail loudly, not produce a plausible-looking result.
    """
    df = _tiny_df()
    signal = _signal_with_transitions(df.index)
    report = _passing_report()

    monkeypatch.setattr(backtest, "_apply_look_ahead_lag", lambda s: s)

    with pytest.raises(AssertionError, match="LOOK-AHEAD VIOLATION"):
        run_backtest(df, signal, report, "2021-01-01", "2021-01-10", initial_capital=100_000.0)


def test_run_backtest_does_not_raise_with_the_real_lag_intact():
    """Sanity check: the same setup, WITHOUT tampering, must run cleanly -- proves the test above is testing the tampering, not something else broken in the fixtures."""
    df = _tiny_df()
    signal = _signal_with_transitions(df.index)
    report = _passing_report()

    result = run_backtest(df, signal, report, "2021-01-01", "2021-01-10", initial_capital=100_000.0)
    assert "equity_curve" in result
