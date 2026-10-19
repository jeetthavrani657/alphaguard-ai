"""
tests/test_compare_upstox_yfinance.py

The comparison must catch the failure that matters: one source adjusting a split and the other not.
Toy price series only, no network.
"""

import numpy as np
import pandas as pd

import compare_upstox_yfinance as cmp


def _prices(n=300, seed=1):
    idx = pd.bdate_range("2024-01-01", periods=n)
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"close": 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n)))}, index=idx)


def test_two_sources_that_differ_only_by_a_constant_factor_agree():
    """Different dividend adjustment = a constant price ratio, which must NOT be flagged."""
    yf = _prices()
    r = cmp.compare_one(yf * 1.07, yf)
    assert r["days_diff_over_big"] == 0 and r["days_diff_over_small"] == 0
    assert abs(r["return_corr"] - 1) < 1e-9 and abs(r["ratio_last"] - 1.07) < 1e-9
    assert cmp.verdict_line(r).startswith("AGREES")


def test_an_unadjusted_split_in_one_source_is_flagged_on_the_right_day():
    yf = _prices()
    split_day = yf.index[150]
    up = yf.copy()
    up.loc[up.index >= split_day, "close"] *= 0.5            # a 2-for-1 split that Upstox shows but yfinance has adjusted away
    r = cmp.compare_one(up, yf)
    assert r["days_diff_over_big"] == 1 and r["worst"][0][0] == split_day.date()
    assert abs(r["worst"][0][1] - (-0.5)) < 0.1              # Upstox shows roughly a -50% day
    assert cmp.verdict_line(r).startswith("DIFFERS")


def test_missing_days_on_either_side_are_counted():
    yf = _prices()
    up = yf.drop(yf.index[[10, 11, 12]])
    r = cmp.compare_one(up, yf)
    assert r["days_only_in_yfinance"] == 3 and r["days_only_in_upstox"] == 0


def test_days_outside_the_span_upstox_was_asked_for_are_not_counted_as_missing():
    """Regression: the yfinance cache runs to today, so 2026 days were reported as 'only in yfinance'."""
    yf = _prices()
    up = yf.iloc[:200]                                          # Upstox was only asked for the first 200 days
    r = cmp.compare_one(up, yf)
    assert r["days_only_in_yfinance"] == 0 and r["overlap_days"] == 200


def test_too_little_overlap_is_reported_not_compared():
    a = _prices(20)
    r = cmp.compare_one(a, a)
    assert "error" in r and cmp.verdict_line(r) == r["error"]
