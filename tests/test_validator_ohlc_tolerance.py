"""
tests/test_validator_ohlc_tolerance.py

Regression test for a real bug found running the validator on the
Midcap150/Smallcap250 universes: yfinance's split/dividend adjustment
arithmetic leaves floating-point rounding noise (~1e-14 to 1e-15) that
a strict `<`/`>` OHLC comparison flags as a "violation" even though the
two prices are economically identical. 8 real symbols (NHPC, FSL,
GRAPHITE, HEG, TRIDENT, CHENNPETRO, and two others) were wrongly failing
hard validation for this reason alone. Fixed with a small absolute
tolerance; this locks the fix in and confirms a GENUINE violation still
gets caught.
"""

import pandas as pd

from validator import _check_ohlc_logic


def _base_df(n=5):
    dates = pd.date_range("2021-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open": [100.0] * n, "high": [105.0] * n, "low": [95.0] * n,
        "close": [100.0] * n, "volume": [1_000_000] * n,
    }, index=dates)


def test_floating_point_noise_does_not_fail_the_check():
    """close is 1.8e-15 below low -- economically identical, must pass."""
    df = _base_df()
    df.loc[df.index[2], "low"] = 100.00000000000002
    df.loc[df.index[2], "close"] = 100.00000000000000  # 1.8e-15 below "low" in float64 terms
    result = _check_ohlc_logic(df)
    assert result["passed"], "floating-point noise on the order of 1e-15 must not fail OHLC validation"


def test_genuine_violation_still_caught():
    """close meaningfully (Rs 5) above high -- a real violation, must still fail."""
    df = _base_df()
    df.loc[df.index[2], "close"] = 110.0  # high is 105.0 -- a real, large violation
    result = _check_ohlc_logic(df)
    assert not result["passed"]
    assert result["count"] == 1


def test_genuine_high_below_low_still_caught():
    df = _base_df()
    df.loc[df.index[1], "high"] = 90.0  # low is 95.0 -- high < low by Rs 5, real violation
    result = _check_ohlc_logic(df)
    assert not result["passed"]
    assert result["count"] == 1
