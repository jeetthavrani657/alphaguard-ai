"""
tests/test_cross_sectional_momentum.py

Ground-truth tests for strategies/cross_sectional_momentum.py -- a
brand-new module (MOMENTUM_METHODOLOGY.md), held to the same bar this
project's OWN documented coverage gaps (README.md's Technical Debt: MA
crossover and RSI reversion have never had a hand-computed ground-truth
test of their own ranking/signal logic) say new strategy code should
not repeat.
"""

import pandas as pd
import pytest

from cross_sectional_momentum import generate_target_weights, _momentum_score, LOOKBACK_DAYS, SKIP_DAYS


def _toy_df(prices: list, start_date: str = "2020-01-01") -> pd.DataFrame:
    dates = pd.date_range(start_date, periods=len(prices), freq="D")
    return pd.DataFrame({
        "open": prices, "high": prices, "low": prices, "close": prices,
        "volume": [1_000_000] * len(prices),
    }, index=dates)


def _price_path(n_rows: int, price_at_lookback: float, price_at_skip: float, price_at_end: float) -> list:
    """
    A price series `n_rows` long where index [-1 - LOOKBACK_DAYS] equals
    price_at_lookback, index [-1 - SKIP_DAYS] equals price_at_skip, and
    the final row equals price_at_end -- everything else is a flat
    filler at price_at_lookback, since only these three points matter
    for _momentum_score's formula.
    """
    prices = [price_at_lookback] * n_rows
    prices[-1 - SKIP_DAYS] = price_at_skip
    prices[-1] = price_at_end
    return prices


def test_momentum_score_matches_hand_calculation():
    """
    252 trading days ago: 100. 21 trading days ago: 150. Score should be
    exactly 150/100 - 1 = 0.50, regardless of what happened in between
    or in the most recent 21 days (skipped).
    """
    n_rows = LOOKBACK_DAYS + SKIP_DAYS + 50
    prices = _price_path(n_rows, price_at_lookback=100.0, price_at_skip=150.0, price_at_end=9999.0)
    df = _toy_df(prices)
    formation_date = df.index[-1]

    score = _momentum_score(df["close"], formation_date)
    assert score == pytest.approx(0.50, abs=1e-9)


def test_a_huge_move_inside_the_skipped_month_does_not_affect_the_score():
    """
    THE regression this file exists to lock in: the skip-month
    convention (MOMENTUM_METHODOLOGY.md Section 1) means the most recent
    21 trading days must have ZERO effect on the score, no matter how
    dramatic. Two series identical everywhere except the final 21 days
    (one flat, one a 10x rally) must produce the IDENTICAL score.
    """
    n_rows = LOOKBACK_DAYS + SKIP_DAYS + 50
    flat_tail = _price_path(n_rows, price_at_lookback=100.0, price_at_skip=150.0, price_at_end=150.0)
    wild_tail = _price_path(n_rows, price_at_lookback=100.0, price_at_skip=150.0, price_at_end=1500.0)

    df_flat = _toy_df(flat_tail)
    df_wild = _toy_df(wild_tail)
    formation_date = df_flat.index[-1]

    assert _momentum_score(df_flat["close"], formation_date) == pytest.approx(
        _momentum_score(df_wild["close"], formation_date), abs=1e-9
    )


def test_insufficient_history_returns_nan_not_a_fabricated_score():
    prices = [100.0] * (LOOKBACK_DAYS - 10)  # deliberately short of LOOKBACK_DAYS
    df = _toy_df(prices)
    score = _momentum_score(df["close"], df.index[-1])
    assert pd.isna(score)


def test_generate_target_weights_selects_the_correct_top_n_by_rank():
    """
    Three symbols with known, hand-computed 12-1 returns: A=+50%,
    B=+10%, C=-10%. With top_n=2, A and B must each get weight 0.5;
    C must get weight 0.0. A wrong comparison direction (ranking
    ascending instead of descending) would instead pick B and C --
    this test fails loudly, not by coincidence, if that's ever broken.
    """
    n_rows = LOOKBACK_DAYS + SKIP_DAYS + 50
    universe = {
        "A": {"df": _toy_df(_price_path(n_rows, 100.0, 150.0, 150.0))},
        "B": {"df": _toy_df(_price_path(n_rows, 100.0, 110.0, 110.0))},
        "C": {"df": _toy_df(_price_path(n_rows, 100.0, 90.0, 90.0))},
    }

    weights = generate_target_weights(universe, top_n=2)
    formation_date = universe["A"]["df"].index[-1]
    # The month-end grouping snaps to the last trading day OF the final
    # month present -- with a plain daily index that's simply the final
    # row itself, since generation runs one formation date per month
    # and this series covers less than two full calendar months of
    # "final" data after the lookback window resolves. Use .iloc[-1] to
    # avoid hard-coding an exact date the freq="D" calendar happens to land on.
    last_row = weights.iloc[-1]

    assert last_row["A"] == pytest.approx(0.5)
    assert last_row["B"] == pytest.approx(0.5)
    assert last_row["C"] == pytest.approx(0.0)


def test_a_symbol_with_too_little_history_is_never_selected():
    n_rows = LOOKBACK_DAYS + SKIP_DAYS + 50
    universe = {
        "A": {"df": _toy_df(_price_path(n_rows, 100.0, 150.0, 150.0))},
        "B": {"df": _toy_df(_price_path(n_rows, 100.0, 110.0, 110.0))},
        # D has a great trailing return on paper, but not enough rows to compute it.
        "D": {"df": _toy_df([100.0] * (LOOKBACK_DAYS - 10))},
    }

    weights = generate_target_weights(universe, top_n=2)
    assert (weights["D"] == 0.0).all()
