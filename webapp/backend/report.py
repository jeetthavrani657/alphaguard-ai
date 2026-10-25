"""
webapp/backend/report.py

The pieces of a strategy's report that are a different view of numbers the snapshot already holds: the return of each calendar month, the spread of the trades' returns,
the worst stretches below the previous peak, and how much evidence there is. Pure functions, a stored series in and a list out; nothing here runs a strategy, reads a file or
computes a Sharpe ratio of a strategy. (The "luck bar" below is a property of how many ideas were tried and how many days were seen, not of any strategy.)

Standard library only: the API never imports pandas, numpy or scipy (a test guards that). The evidence formulas are therefore written out here, and
tests/test_webapp_report.py pins them to research/overfit_checks.py, the project's own version, over a grid of inputs so the two cannot drift apart.
"""

import math
from bisect import bisect_right
from datetime import date
from functools import lru_cache
from statistics import NormalDist

HISTOGRAM_EDGES = [-20.0, -15.0, -10.0, -7.5, -5.0, -2.5, 0.0, 2.5, 5.0, 7.5, 10.0, 15.0, 20.0]      # percent; one bin below the first and one above the last catch the tails
TRADING_DAYS = 252
EULER_GAMMA = 0.5772156649015329
_NORMAL = NormalDist()                                         # the standard normal: .cdf and .inv_cdf


def monthly_returns(dates: list, values: list, base: float | None = None) -> list:
    """
    [{"year", "month", "return_pct"}] oldest first, from a growth series. A month's return is its last value over the previous month's last value; the first month is measured
    from `base` (the level the series started at, e.g. 100 for "growth of 100"), or from the series' first value if no base is given, so a window that begins mid-month still
    reports that part-month.
    """
    if len(values) < 2:
        return []
    last_in_month = {}                                          # (year, month) -> the last value that month; ISO dates sort the same as calendar dates
    for d, v in sorted(zip(dates, values)):
        last_in_month[(int(d[:4]), int(d[5:7]))] = v
    previous = sorted(zip(dates, values))[0][1] if base is None else base
    out = []
    for (year, month), value in sorted(last_in_month.items()):
        out.append({"year": year, "month": month, "return_pct": (value / previous - 1.0) * 100.0})
        previous = value
    return out


def trade_histogram(returns_pct: list) -> list:
    """
    The trades' net returns counted into fixed bins [{"low_pct", "high_pct", "count"}]: one open-ended bin below the lowest edge (low_pct None), the ordinary ones, and one open-ended
    bin above the highest (high_pct None). A return exactly on an edge belongs to the bin that starts there.
    """
    edges = HISTOGRAM_EDGES
    counts = [0] * (len(edges) + 1)
    for r in returns_pct:
        counts[bisect_right(edges, r)] += 1
    lows = [None] + edges
    highs = edges + [None]
    return [{"low_pct": lo, "high_pct": hi, "count": c} for lo, hi, c in zip(lows, highs, counts)]


def drawdown_periods(dates: list, drawdown_pct: list, top: int = 5) -> list:
    """
    The `top` deepest stretches below a previous peak, from a series of percent-below-the-running-peak (0 at a peak, negative below). Each is
    {"peak_date", "trough_date", "recovered_date" (None if it had not recovered by the last day), "depth_pct", "days_peak_to_trough", "days_underwater"}, deepest first.
    """
    day = lambda k: date.fromisoformat(dates[k][:10])
    out, i, n = [], 0, len(drawdown_pct)
    while i < n:
        if drawdown_pct[i] < 0:
            start = i - 1 if i > 0 else 0                                      # the last day at the peak before the fall
            j = i
            while j < n and drawdown_pct[j] < 0:
                j += 1
            trough = min(range(i, j), key=lambda k: drawdown_pct[k])          # the deepest day of this fall
            recovered = j if j < n else None
            end = recovered if recovered is not None else n - 1
            out.append({"peak_date": dates[start], "trough_date": dates[trough], "recovered_date": None if recovered is None else dates[recovered],
                        "depth_pct": float(drawdown_pct[trough]), "days_peak_to_trough": (day(trough) - day(start)).days, "days_underwater": (day(end) - day(start)).days})
            i = j
        else:
            i += 1
    return sorted(out, key=lambda p: p["depth_pct"])[:top]


# --- how much evidence there is (the same formulas as research/overfit_checks.py; see the note at the top) --------------------------------

def _expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """The per-day Sharpe the best of n_trials no-skill strategies would be expected to show (Bailey and Lopez de Prado 2014, eq. 5). One trial expects nothing."""
    if n_trials <= 1:
        return 0.0
    return math.sqrt(var_sr) * ((1.0 - EULER_GAMMA) * _NORMAL.inv_cdf(1.0 - 1.0 / n_trials) + EULER_GAMMA * _NORMAL.inv_cdf(1.0 - 1.0 / (n_trials * math.e)))


def _years_needed(sr_annual: float, n_trials: int, target: float = 0.95) -> float | None:
    """The fewest years of daily data at which a TRUE annual edge of `sr_annual` (normal returns, sample equal to the truth) reaches `target` probability of beating the luck bar; None if over 300 years."""
    sr = sr_annual / math.sqrt(TRADING_DAYS)
    for tenths in range(2, 3000):
        years = tenths / 10.0
        days = int(years * TRADING_DAYS)
        bar = _expected_max_sharpe(n_trials, 1.0 / (days - 1.0))
        if _NORMAL.cdf((sr - bar) * math.sqrt(days - 1.0) / math.sqrt(1.0 + 0.5 * sr ** 2)) >= target:      # skew 0, kurtosis 3
            return years
    return None


@lru_cache(maxsize=256)
def evidence(n_days: int, n_trials: int) -> dict:
    """
    How much a result can tell apart from luck. `luck_bar_annual` is the annual Sharpe that the best of `n_trials` strategies with NO skill would be expected to show over `n_days` days
    (the project's deflated-Sharpe bar); `years_needed_*` is how long a true edge of 1.0 takes to show against that many tries, and against a single try.
    """
    days = max(int(n_days), 3)
    tries = max(int(n_trials), 1)
    bar = _expected_max_sharpe(tries, 1.0 / (days - 1.0)) * math.sqrt(TRADING_DAYS)
    return {"ideas_tried": int(n_trials), "window_days": int(n_days), "window_years": round(n_days / TRADING_DAYS, 2), "luck_bar_annual": round(bar, 3),
            "years_needed_for_edge_of_1": _years_needed(1.0, tries), "years_needed_for_edge_of_1_single_try": _years_needed(1.0, 1)}
