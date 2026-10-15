"""
tests/test_forward_log.py

Hand-checkable tests for research/forward_log.py's summarize() -- the
function that produces the win rate the forward test is judged on.
"""

import pandas as pd
import pytest

from forward_log import summarize, MIN_POSITIONS


def _closed(rets):
    return pd.DataFrame({"ret": rets})


def _open(unreal):
    return pd.DataFrame({"unreal_pct": unreal})


def test_all_in_win_rate_counts_open_positions_and_underwater_ones_as_losses():
    # 8 closed: 7 wins, 1 loss.  Open: 1 up, 1 underwater.
    # all-in = (7 + 1) / (8 + 2) = 80%;  closed-only = 7/8 = 87.5%.
    s = summarize(_closed([2, 2, 2, 2, 2, 2, 2, -12]), _open([1.0, -5.0]))
    assert s["win_rate_closed"] == pytest.approx(87.5)
    assert s["win_rate_all_in"] == pytest.approx(80.0)
    assert s["n_all"] == 10
    assert s["open_underwater"] == 1


def test_a_flat_open_position_is_not_a_win():
    s = summarize(_closed([2.0]), _open([0.0]))
    assert s["win_rate_all_in"] == pytest.approx(50.0)


def test_avg_win_avg_loss_and_expectancy():
    s = summarize(_closed([4, 2, -12]), _open([]))
    assert s["avg_win_pct"] == pytest.approx(3.0)
    assert s["avg_loss_pct"] == pytest.approx(-12.0)
    assert s["expectancy_pct"] == pytest.approx((4 + 2 - 12) / 3)
    assert s["worst_closed_pct"] == pytest.approx(-12.0)


def test_nothing_recorded_yet_does_not_crash_and_is_not_enough_to_conclude():
    s = summarize(_closed([]), _open([]))
    assert s["n_all"] == 0
    assert pd.isna(s["win_rate_all_in"])
    assert s["enough_to_conclude"] is False


def test_the_sample_size_gate():
    just_under = summarize(_closed([2.0] * (MIN_POSITIONS - 1)), _open([]))
    at_gate = summarize(_closed([2.0] * MIN_POSITIONS), _open([]))
    assert just_under["enough_to_conclude"] is False
    assert at_gate["enough_to_conclude"] is True


def test_a_perfect_streak_is_not_significant_against_the_break_even_rate_with_few_trades():
    # 3/3 wins sounds great but is p = 0.791^3 ~ 0.49 against a 79.1% break-even rate.
    s = summarize(_closed([2.0, 2.0, 2.0]), _open([]))
    assert s["p_vs_breakeven"] == pytest.approx(0.791 ** 3, rel=1e-3)
    assert s["p_vs_breakeven"] > 0.05
