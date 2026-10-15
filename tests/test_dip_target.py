"""
tests/test_dip_target.py

Ground-truth tests for strategies/dip_target.py's stateful entry/exit
logic, using hand-built close and RSI series (the RSI itself is
rsi_reversion's, already hand-verified there).
"""

import numpy as np
import pandas as pd
import pytest

from dip_target import _stateful_signal


def _series(values):
    return pd.Series(values, index=pd.date_range("2021-01-01", periods=len(values), freq="D"), dtype=float)


def test_enters_on_oversold_and_exits_at_take_profit():
    close = _series([100, 100, 100, 101, 103.5, 103, 99])
    rsi = _series([np.nan, 50, 25, 40, 40, 40, 40])
    sig = _stateful_signal(close, rsi, oversold=30, take_profit=0.03, stop_loss=None)
    # idx0 NaN; idx1 flat; idx2 RSI 25 < 30 -> long (entry reference close 100);
    # idx3 101 < 103 -> hold; idx4 103.5 >= 103 -> exit; idx5/6 RSI 40 -> stays flat.
    assert pd.isna(sig.iloc[0])
    assert sig.iloc[1:].tolist() == [0.0, 1.0, 1.0, 0.0, 0.0, 0.0]


def test_without_a_stop_a_crashing_position_is_held_forever():
    """THE property that manufactures a high win rate: a loser is never closed."""
    close = _series([100, 100, 100, 90, 70, 50, 30])
    rsi = _series([np.nan, 50, 25, 20, 15, 10, 5])
    sig = _stateful_signal(close, rsi, oversold=30, take_profit=0.03, stop_loss=None)
    assert sig.iloc[2:].tolist() == [1.0, 1.0, 1.0, 1.0, 1.0]  # still long at -70%


def test_a_stop_loss_closes_the_loser():
    close = _series([100, 100, 100, 96, 94, 94, 94])
    rsi = _series([np.nan, 50, 25, 20, 15, 40, 40])
    sig = _stateful_signal(close, rsi, oversold=30, take_profit=0.03, stop_loss=0.05)
    # idx3 close 96 > 95 -> hold; idx4 close 94 <= 95 -> stopped out; stays flat after.
    assert sig.iloc[2:].tolist() == [1.0, 1.0, 0.0, 0.0, 0.0]


def test_can_reenter_after_exit():
    close = _series([100, 100, 100, 104, 104, 100, 100, 100])
    rsi = _series([np.nan, 50, 25, 40, 40, 50, 20, 40])
    sig = _stateful_signal(close, rsi, oversold=30, take_profit=0.03, stop_loss=None)
    # enter idx2 (ref 100) -> exit idx3 (104 >= 103) -> flat -> re-enter idx6 (RSI 20, ref 100)
    assert sig.iloc[2:].tolist() == [1.0, 0.0, 0.0, 0.0, 1.0, 1.0]


def test_entry_gate_blocks_an_oversold_signal_outside_the_uptrend():
    close = _series([100, 100, 100, 100, 100])
    rsi = _series([np.nan, 50, 25, 25, 25])
    gate = pd.Series([False, False, False, True, True], index=close.index)
    sig = _stateful_signal(close, rsi, oversold=30, take_profit=0.03, stop_loss=None, entry_ok=gate)
    # RSI is oversold on idx2 but the gate is closed -> no entry; opens at idx3.
    assert sig.iloc[1:].tolist() == [0.0, 0.0, 1.0, 1.0]


def test_max_hold_force_exits_a_position_that_hits_neither_level():
    close = _series([100, 100, 100, 101, 101, 101, 101, 101])
    rsi = _series([np.nan, 50, 25, 40, 40, 40, 40, 40])
    sig = _stateful_signal(close, rsi, oversold=30, take_profit=0.10, stop_loss=0.10, max_hold_days=3)
    # enter idx2; bars_held 1,2,3 on idx3,4,5 -> forced out on idx5; flat after.
    assert sig.iloc[2:].tolist() == [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
