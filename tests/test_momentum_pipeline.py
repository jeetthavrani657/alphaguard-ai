"""
tests/test_momentum_pipeline.py

Regression test for a bug found while adding momentum to the web app.

Momentum ranked ALL 50 symbols, then engine/portfolio_backtest.py dropped
any symbol the discontinuity gate blocks for the window. If a blocked
symbol ranked in the top 10 (ADANIENT did on 28 of 54 in-sample
rebalances), its 10% slot silently became CASH instead of passing to the
next-ranked name -- the portfolio was quietly under-invested and exposure
was over-reported. build_window_inputs() now filters by the gate FIRST,
so a blocked symbol can never be selected.
"""

import pandas as pd
import pytest

from cross_sectional_momentum import LOOKBACK_DAYS, SKIP_DAYS
from run_momentum_strategy import build_window_inputs

N_ROWS = LOOKBACK_DAYS + SKIP_DAYS + 60
START, END = "2020-01-01", "2021-12-31"


def _entry(price_at_lookback, price_at_skip, blocked=False):
    prices = [price_at_lookback] * N_ROWS
    prices[-1 - SKIP_DAYS] = price_at_skip
    prices[-1] = price_at_skip
    df = pd.DataFrame(
        {"open": prices, "high": prices, "low": prices, "close": prices, "volume": [1_000_000] * N_ROWS},
        index=pd.date_range("2020-01-01", periods=N_ROWS, freq="D"),
    )
    discontinuities = []
    if blocked:
        discontinuities = [{"date": pd.Timestamp("2020-06-01"), "magnitude": -0.4,
                            "status": "UNREVIEWED", "reason": "test"}]
    return {"df": df, "report": {"symbol": "X", "discontinuities": discontinuities}}


def test_a_blocked_top_ranked_symbol_is_never_selected_and_its_slot_passes_on():
    universe = {
        "STAR": _entry(100.0, 300.0, blocked=True),   # best momentum by far, but gate-blocked
        "B": _entry(100.0, 150.0),
        "C": _entry(100.0, 120.0),
        "D": _entry(100.0, 90.0),
    }
    eligible, weights, blocked = build_window_inputs(universe, START, END, top_n=2)

    assert [t for t, _ in blocked] == ["STAR"]
    assert "STAR" not in weights.columns
    last = weights.iloc[-1]
    # top_n=2 must be filled by the two best ELIGIBLE names -- B and C --
    # with the full 100% invested, not 50% invested and 50% cash.
    assert last["B"] == pytest.approx(0.5)
    assert last["C"] == pytest.approx(0.5)
    assert last.sum() == pytest.approx(1.0)


def test_with_nothing_blocked_the_ranking_is_unchanged():
    universe = {
        "A": _entry(100.0, 300.0),
        "B": _entry(100.0, 150.0),
        "C": _entry(100.0, 90.0),
    }
    _, weights, blocked = build_window_inputs(universe, START, END, top_n=2)
    assert blocked == []
    assert weights.iloc[-1]["A"] == pytest.approx(0.5)
    assert weights.iloc[-1]["B"] == pytest.approx(0.5)
    assert weights.iloc[-1]["C"] == pytest.approx(0.0)
