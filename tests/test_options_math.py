"""
tests/test_options_math.py

research/options_math.py turns option prices into implied volatilities. A wrong formula here would put a wrong number under every options result, so each piece
is checked against a value worked out independently (a textbook value, put-call parity, round trips) and against the edge cases that must give NaN.
"""

import math
from datetime import date

import numpy as np
import pytest

import options_math as om


def test_an_at_the_money_call_matches_the_textbook_value():
    # F = K = 100, T = 1, sigma = 20%, no discounting: 100 * (2 N(0.1) - 1) = 7.9656
    assert om.price(100, 100, 1.0, 0.20, 0.0, True) == pytest.approx(7.9656, abs=1e-4)
    assert om.price(100, 100, 1.0, 0.20, 0.05, True) == pytest.approx(7.9656 * math.exp(-0.05), abs=1e-4)     # discounting scales the price


@pytest.mark.parametrize("f,k,t,s,r", [(100, 100, 1.0, 0.2, 0.0), (22800, 23000, 0.08, 0.14, 0.065), (22800, 21000, 0.25, 0.30, 0.06), (100, 150, 0.5, 0.4, 0.05)])
def test_put_call_parity_holds_for_the_model_prices(f, k, t, s, r):
    c, p = om.price(f, k, t, s, r, True), om.price(f, k, t, s, r, False)
    assert c - p == pytest.approx(math.exp(-r * t) * (f - k), rel=1e-9, abs=1e-9)


def test_prices_never_go_below_intrinsic_and_never_above_the_ceiling():
    for k in (80, 100, 120):
        for s in (0.05, 0.2, 1.0):
            c, p = om.price(100, k, 0.5, s, 0.05, True), om.price(100, k, 0.5, s, 0.05, False)
            assert c >= math.exp(-0.025) * max(100 - k, 0) - 1e-12 and c <= math.exp(-0.025) * 100
            assert p >= math.exp(-0.025) * max(k - 100, 0) - 1e-12 and p <= math.exp(-0.025) * k


@pytest.mark.parametrize("is_call", [True, False])
@pytest.mark.parametrize("f,k,t,s", [(100, 100, 1.0, 0.2), (22800, 22800, 0.02, 0.12), (22800, 24000, 0.08, 0.25), (22800, 20000, 0.5, 0.18), (100, 90, 0.1, 0.9)])
def test_implied_vol_recovers_the_volatility_that_made_the_price(f, k, t, s, is_call):
    px = om.price(f, k, t, s, 0.065, is_call)
    got = om.implied_vol(px, f, k, t, 0.065, is_call)
    if px < 1e-8:
        assert math.isnan(got) or got == pytest.approx(s, rel=1e-3)                 # a price that has rounded to nothing has no information
    else:
        assert got == pytest.approx(s, abs=1e-6)


def test_implied_vol_is_nan_when_no_volatility_can_explain_the_price():
    f, k, t, r = 100, 100, 0.5, 0.05
    intrinsic = om.price(f, 90, t, 0.0, r, True)
    for bad in (intrinsic, intrinsic - 0.5, 0.0, -1.0, math.exp(-r * t) * f + 1.0, float("nan")):     # at or below intrinsic, zero, negative, above the ceiling, not a number
        assert math.isnan(om.implied_vol(bad, f, 90, t, r, True))
    assert math.isnan(om.implied_vol(5.0, f, k, 0.0, r, True)) and math.isnan(om.implied_vol(5.0, f, k, -0.1, r, True))      # no time left
    assert math.isnan(om.implied_vol(5.0, 0.0, k, t, r, True)) and math.isnan(om.implied_vol(5.0, f, 0.0, t, r, True))


def test_delta_vega_and_the_limits_of_a_dying_option():
    f, k, t, s, r = 100, 105, 0.25, 0.25, 0.05
    dc, dp = om.delta(f, k, t, s, r, True), om.delta(f, k, t, s, r, False)
    assert 0 < dc < 1 and -1 < dp < 0 and dc - dp == pytest.approx(math.exp(-r * t))                  # call delta minus put delta is the discount factor
    assert om.vega(f, k, t, s, r) > 0
    bump = 1e-5                                                                                          # delta is the slope of price in the forward
    slope = (om.price(f + bump, k, t, s, r, True) - om.price(f - bump, k, t, s, r, True)) / (2 * bump)
    assert dc == pytest.approx(slope, rel=1e-5)
    vol_slope = (om.price(f, k, t, s + bump, r, True) - om.price(f, k, t, s - bump, r, True)) / (2 * bump)
    assert om.vega(f, k, t, s, r) == pytest.approx(vol_slope, rel=1e-5)
    assert om.delta(120, 100, 0.0, 0.2, r, True) == 1.0 and om.delta(80, 100, 0.0, 0.2, r, True) == 0.0 and om.vega(100, 100, 0.0, 0.2, r) == 0.0


def test_the_implied_forward_recovers_the_forward_the_prices_were_made_from():
    f, t, s, r = 22810.0, 0.07, 0.15, 0.065
    strikes = np.arange(21500, 24200, 100.0)
    calls = [om.price(f, k, t, s, r, True) for k in strikes]
    puts = [om.price(f, k, t, s, r, False) for k in strikes]
    assert om.implied_forward(strikes, calls, puts, t, r) == pytest.approx(f, abs=1e-6)             # exact, because the prices are model prices
    assert math.isnan(om.implied_forward([], [], [], t, r)) and math.isnan(om.implied_forward(strikes, calls, puts, 0.0, r))
    assert math.isnan(om.implied_forward([100.0], [0.0], [5.0], t, r))                                # a strike with a zero price is not used


def test_the_implied_forward_uses_the_money_strike_where_real_prices_are_clean_not_a_noisy_far_strike():
    """Real prices of far strikes carry spread and rounding error; the strike where call and put are closest is the liquid one."""
    f, t, s, r = 22810.0, 0.07, 0.15, 0.065
    strikes = np.arange(21500, 24200, 100.0)
    far = lambda k: abs(k - f) > 400
    calls = [om.price(f, k, t, s, r, True) + (3.0 if far(k) else 0.0) for k in strikes]       # far strikes: the call is quoted 3 rupees too high
    puts = [om.price(f, k, t, s, r, False) for k in strikes]
    assert om.implied_forward(strikes, calls, puts, t, r) == pytest.approx(f, abs=0.2)


def test_years_between_counts_calendar_days_over_365():
    assert om.years_between(date(2026, 10, 21), date(2026, 10, 27)) == pytest.approx(6 / 365)
    assert om.years_between(date(2026, 10, 27), date(2026, 10, 27)) == 0.0
