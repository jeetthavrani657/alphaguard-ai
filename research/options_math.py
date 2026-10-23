"""
research/options_math.py

Pricing arithmetic for European options on a forward (index options on the NSE are European and cash-settled), used to turn the
end-of-day option prices in data/fo_bhavcopy.py into implied volatilities and Greeks. Plain functions, no state, no data access.

Black-76: with forward F, strike K, time to expiry T in years, volatility sigma and a continuously compounded discount rate r,
    call = exp(-rT) * (F N(d1) - K N(d2)),   put = exp(-rT) * (K N(-d2) - F N(-d1)),
    d1 = (ln(F/K) + sigma^2 T / 2) / (sigma sqrt T),   d2 = d1 - sigma sqrt T.
The forward is taken from the option prices themselves by put-call parity (implied_forward), so it holds for weekly expiries that have no future
and it needs no dividend or interest assumption beyond the discount rate.
"""

import math

import numpy as np
from scipy.optimize import brentq

VOL_LOW, VOL_HIGH = 1e-4, 5.0           # the search range for an implied volatility: 0.01% to 500% a year


_SQRT2 = math.sqrt(2.0)
_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _cdf(x: float) -> float:
    """The standard normal distribution function, from math.erfc (about a hundred times faster than scipy's wrapper, which matters when a chain needs thousands of them)."""
    return 0.5 * math.erfc(-x / _SQRT2)


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _d1_d2(forward: float, strike: float, t: float, sigma: float) -> tuple:
    root_t = math.sqrt(t)
    d1 = (math.log(forward / strike) + 0.5 * sigma * sigma * t) / (sigma * root_t)
    return d1, d1 - sigma * root_t


def price(forward: float, strike: float, t: float, sigma: float, rate: float, is_call: bool) -> float:
    """Black-76 price. At no time left or no volatility it is the discounted intrinsic value."""
    discount = math.exp(-rate * t) if t > 0 else 1.0
    if t <= 0 or sigma <= 0:
        return discount * max(forward - strike, 0.0) if is_call else discount * max(strike - forward, 0.0)
    d1, d2 = _d1_d2(forward, strike, t, sigma)
    if is_call:
        return discount * (forward * _cdf(d1) - strike * _cdf(d2))
    return discount * (strike * _cdf(-d2) - forward * _cdf(-d1))


def delta(forward: float, strike: float, t: float, sigma: float, rate: float, is_call: bool) -> float:
    """Change in the option price for a one-rupee change in the forward."""
    if t <= 0 or sigma <= 0:
        return (1.0 if forward > strike else 0.0) if is_call else (-1.0 if forward < strike else 0.0)
    d1, _ = _d1_d2(forward, strike, t, sigma)
    return math.exp(-rate * t) * (_cdf(d1) if is_call else _cdf(d1) - 1.0)


def vega(forward: float, strike: float, t: float, sigma: float, rate: float) -> float:
    """Change in the price for a change of 1.00 (100 points) in volatility; divide by 100 for one volatility point."""
    if t <= 0 or sigma <= 0:
        return 0.0
    d1, _ = _d1_d2(forward, strike, t, sigma)
    return math.exp(-rate * t) * forward * _pdf(d1) * math.sqrt(t)


def implied_vol(option_price: float, forward: float, strike: float, t: float, rate: float, is_call: bool) -> float:
    """
    The volatility that gives option_price, or NaN when there is none: no time left, a price at or below the discounted intrinsic value
    (no volatility can explain it), or one above the largest value an option can have. NaN is returned rather than a number that looks plausible.
    """
    if not all(math.isfinite(x) for x in (option_price, forward, strike, t, rate)) or t <= 0 or forward <= 0 or strike <= 0 or option_price <= 0:
        return float("nan")
    intrinsic = price(forward, strike, t, 0.0, rate, is_call)
    ceiling = math.exp(-rate * t) * (forward if is_call else strike)
    if option_price <= intrinsic + 1e-12 or option_price >= ceiling:
        return float("nan")
    f = lambda s: price(forward, strike, t, s, rate, is_call) - option_price
    if f(VOL_LOW) > 0 or f(VOL_HIGH) < 0:
        return float("nan")
    return float(brentq(f, VOL_LOW, VOL_HIGH, xtol=1e-10, maxiter=200))


def implied_forward(strikes, call_prices, put_prices, t: float, rate: float) -> float:
    """
    The forward implied by put-call parity, C - P = exp(-rT) (F - K), taken at the strike where the call and put prices are closest (the money), which
    is where both are liquid. Returns NaN if no strike has both prices.
    """
    k, c, p = (np.asarray(x, dtype=float) for x in (strikes, call_prices, put_prices))
    ok = np.isfinite(k) & np.isfinite(c) & np.isfinite(p) & (c > 0) & (p > 0)
    if not ok.any() or t <= 0:
        return float("nan")
    k, c, p = k[ok], c[ok], p[ok]
    i = int(np.argmin(np.abs(c - p)))
    return float(k[i] + math.exp(rate * t) * (c[i] - p[i]))


def years_between(day, expiry) -> float:
    """Calendar days to expiry over 365: the convention behind exchange-quoted implied volatilities."""
    return (expiry - day).days / 365.0
