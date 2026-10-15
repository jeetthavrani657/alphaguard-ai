"""
tests/test_metrics.py

engine/metrics.py had ZERO ground-truth verification before this file --
every metric had only ever been run against real market data, where
there's no independent correct answer to check against. Every test here
uses a toy dataset small enough to compute the expected value by hand
(shown inline, not just asserted), then checks the code against that
hand calculation -- not the other way around.

All toy cases use risk_free_rate=0.0 so the Sharpe/Sortino arithmetic
reduces to the simplest form (excess_returns == returns exactly),
keeping the by-hand derivation unambiguous.
"""

import numpy as np
import pandas as pd
import pytest

from metrics import compute_metrics

EMPTY_TRADES = pd.DataFrame(columns=[
    "entry_date", "exit_date", "entry_price", "exit_price",
    "quantity", "return_pct", "holding_days", "total_costs",
])


def _flat_position(index):
    """A position series of all-cash (0.0) -- market exposure isn't what these tests check."""
    return pd.Series(0.0, index=index)


def test_cagr_known_growth():
    """
    Equity exactly doubles (100,000 -> 200,000) over 2021-01-01 to
    2022-01-01 -- 365 calendar days (2021 is not a leap year).

    By hand, from the documented formula
        cagr = (final/initial) ** (365.25 / n_days) - 1
    n_days = 365, so:
        cagr = 2 ** (365.25/365) - 1 = 2 ** 1.0006849... - 1
             = 1.0009497... - 1 = 0.0009497... -> 100.09497...% in the
    code's percentage units (total return is 100% flat; CAGR is very
    slightly ABOVE 100% because 365.25/365 is very slightly above 1 --
    the calendar-day convention very slightly over-annualizes a period
    just short of a full 365.25-day year). This is a real, if tiny,
    property of the formula as documented, not an approximation.
    """
    dates = pd.date_range("2021-01-01", "2022-01-01", freq="D")
    equity = pd.Series(100_000.0, index=dates)
    equity.iloc[-1] = 200_000.0

    n_days = (dates[-1] - dates[0]).days
    assert n_days == 365
    expected_cagr_pct = (2.0 ** (365.25 / n_days) - 1) * 100

    m = compute_metrics(equity, EMPTY_TRADES, 100_000.0, _flat_position(dates), risk_free_rate=0.0)

    assert m["total_return_pct"] == pytest.approx(100.0, abs=1e-9)
    assert m["cagr_pct"] == pytest.approx(expected_cagr_pct, abs=1e-9)


def test_max_drawdown_known_depth_and_duration():
    """
    50 daily bars. Peak of 120,000 on day 10, trough of 90,000 on day 15
    (a -25.0% drawdown, exactly: 90000/120000 - 1), staying below the
    peak until a new high of 130,000 on day 40.

    By hand:
        max_drawdown_pct = 90000/120000 - 1 = -0.25 -> -25.0%
        max_drawdown_duration_days = day40 - day10 = 30 (daily freq, so
          calendar days == bar count exactly)
    """
    dates = pd.date_range("2020-01-01", periods=50, freq="D")
    equity = pd.Series(100_000.0, index=dates)
    equity.iloc[10] = 120_000.0
    equity.iloc[15] = 90_000.0
    equity.iloc[16:40] = 95_000.0   # between trough and peak -- never a new high
    equity.iloc[40:] = 130_000.0    # new high, ends the drawdown

    m = compute_metrics(equity, EMPTY_TRADES, 100_000.0, _flat_position(dates), risk_free_rate=0.0)

    assert m["max_drawdown_pct"] == pytest.approx(-25.0, abs=1e-9)
    assert m["max_drawdown_duration_days"] == 30


def test_sharpe_known_mean_and_stdev():
    """
    Four daily returns: 0%, +2%, 0%, +2%.
        mean = 0.01
        sample std (ddof=1, pandas default) = sqrt(((0-.01)^2*2 + (.02-.01)^2*2)/3)
              = sqrt(0.0004/3) = 0.02/sqrt(3) = 0.011547005...
        Sharpe (rf=0) = (mean/std) * sqrt(252)
              = (0.01 / (0.02/sqrt(3))) * sqrt(252)
              = 0.5*sqrt(3) * sqrt(252) = 0.5*sqrt(756) = 13.74772708...
    """
    returns = [0.00, 0.02, 0.00, 0.02]
    dates = pd.date_range("2021-01-01", periods=5, freq="D")
    equity = [100_000.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r))
    equity = pd.Series(equity, index=dates)

    expected_sharpe = 0.5 * np.sqrt(756)

    m = compute_metrics(equity, EMPTY_TRADES, 100_000.0, _flat_position(dates), risk_free_rate=0.0)

    assert m["sharpe_ratio"] == pytest.approx(expected_sharpe, abs=1e-9)


def test_sortino_known_downside_deviation_catches_sign_error():
    """
    Four daily returns: +3%, -1%, +3%, -1% -- deliberately asymmetric
    (unlike the Sharpe case) so a sign error in which side counts as
    "downside" produces a clearly different wrong number, not a
    coincidentally-close one.

        mean = 0.01
        downside squared (only the two -1% days count, positives clip to 0):
              [0, 0.0001, 0, 0.0001], mean over ALL 4 = 0.00005
        downside_deviation = sqrt(0.00005) = 0.01/sqrt(2) = 0.0070710678...
        Sortino (rf=0) = (0.01 / (0.01/sqrt(2))) * sqrt(252)
              = sqrt(2)*sqrt(252) = sqrt(504) = 22.44994432...

    A sign-flipped implementation (treating the two +3% days as
    "downside" instead) would instead give sqrt(2*0.0009/0.0002... ) ->
    a downside_deviation of sqrt(0.00045) and Sortino ~= 7.48 -- a
    clearly different, wrong answer, not a rounding-level difference.
    This is what makes this case actually sensitive to a sign error,
    not just a repeat of the Sharpe case with different numbers.
    """
    returns = [0.03, -0.01, 0.03, -0.01]
    dates = pd.date_range("2021-01-01", periods=5, freq="D")
    equity = [100_000.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r))
    equity = pd.Series(equity, index=dates)

    expected_sortino = np.sqrt(504)

    m = compute_metrics(equity, EMPTY_TRADES, 100_000.0, _flat_position(dates), risk_free_rate=0.0)

    assert m["sortino_ratio"] == pytest.approx(expected_sortino, abs=1e-9)
    # And explicitly confirm it is NOT the sign-flipped value, so this
    # test would fail loudly (not pass by coincidence) if the clip()
    # direction in metrics.py were ever reversed.
    sign_flipped_value = (sum(returns) / 4) / np.sqrt(np.mean([max(r, 0) ** 2 for r in returns])) * np.sqrt(252)
    assert m["sortino_ratio"] != pytest.approx(sign_flipped_value, rel=1e-3)


def test_edge_case_zero_volatility_series():
    """
    A perfectly flat equity curve (no volatility at all). Sharpe and
    Sortino are mathematically undefined (division by zero std) --
    the code must return NaN, not raise, not return inf.
    """
    dates = pd.date_range("2021-01-01", periods=10, freq="D")
    equity = pd.Series(100_000.0, index=dates)

    m = compute_metrics(equity, EMPTY_TRADES, 100_000.0, _flat_position(dates), risk_free_rate=0.0)

    assert m["total_return_pct"] == pytest.approx(0.0, abs=1e-9)
    assert m["cagr_pct"] == pytest.approx(0.0, abs=1e-9)
    assert m["max_drawdown_pct"] == pytest.approx(0.0, abs=1e-9)
    assert np.isnan(m["sharpe_ratio"])
    assert np.isnan(m["sortino_ratio"])


def test_edge_case_all_negative_returns():
    """
    Monotonically declining equity. This is also the case that exercises
    _max_drawdown_duration_days' "still underwater at the end of the
    data" branch: the only peak is day 0, so the drawdown duration must
    be the full span of the series, not zero or undefined.
    """
    dates = pd.date_range("2021-01-01", periods=6, freq="D")
    returns = [-0.01, -0.02, -0.01, -0.02, -0.01]
    equity = [100_000.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r))
    equity = pd.Series(equity, index=dates)

    expected_total_return = equity.iloc[-1] / equity.iloc[0] - 1
    expected_duration = (dates[-1] - dates[0]).days

    m = compute_metrics(equity, EMPTY_TRADES, 100_000.0, _flat_position(dates), risk_free_rate=0.0)

    assert m["total_return_pct"] == pytest.approx(expected_total_return * 100, abs=1e-9)
    assert m["max_drawdown_pct"] == pytest.approx(expected_total_return * 100, abs=1e-9)  # peak is day 0, so DD == total return here
    assert m["max_drawdown_duration_days"] == expected_duration
    assert m["sharpe_ratio"] < 0
    assert m["sortino_ratio"] < 0


def test_edge_case_single_data_point():
    """
    A single-row equity curve. There is no return to compute (pct_change
    of one point is undefined) and no elapsed time -- everything
    dependent on a second data point must come back NaN/0, not raise.
    """
    dates = pd.date_range("2021-01-01", periods=1, freq="D")
    equity = pd.Series([100_000.0], index=dates)

    m = compute_metrics(equity, EMPTY_TRADES, 100_000.0, _flat_position(dates), risk_free_rate=0.0)

    assert m["total_return_pct"] == pytest.approx(0.0, abs=1e-9)
    assert np.isnan(m["cagr_pct"])  # n_days == 0
    assert m["max_drawdown_pct"] == pytest.approx(0.0, abs=1e-9)
    assert m["max_drawdown_duration_days"] == 0
    assert np.isnan(m["sharpe_ratio"])
    assert np.isnan(m["sortino_ratio"])


# --- series for the web app's charts (drawdown, exposure) -------------------------------
# Added with the web app's Stage C. Hand-computed ground truth, like the rest of this file.

import numpy as np  # noqa: E402  (local to this block; the file's own imports are above)
import pandas as pd  # noqa: E402
from metrics import drawdown_series_pct, exposure_series_pct, non_cash_exposure_series_pct  # noqa: E402


def test_drawdown_series_hand_computed():
    # peak 100 -> 120 (new peak) -> 90 (-25% from 120) -> 130 (new peak) -> 65 (-50% from 130)
    eq = pd.Series([100.0, 120.0, 90.0, 130.0, 65.0], index=pd.bdate_range("2024-01-01", periods=5))
    dd = drawdown_series_pct(eq)
    assert dd.tolist() == [0.0, 0.0, -25.0, 0.0, -50.0]


def test_max_drawdown_headline_is_the_minimum_of_the_series():
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2020-01-01", periods=400)
    eq = pd.Series(100_000 * np.exp(np.cumsum(rng.normal(0.0002, 0.012, 400))), index=idx)
    empty = pd.DataFrame(columns=["entry_date", "exit_date", "entry_price", "exit_price",
                                  "quantity", "return_pct", "holding_days", "total_costs"])
    m = compute_metrics(eq, empty, 100_000.0, pd.Series(1.0, index=idx))
    assert m["max_drawdown_pct"] == drawdown_series_pct(eq).min()
    assert (drawdown_series_pct(eq) <= 0).all()


def test_exposure_series_counts_long_books_among_those_present():
    d = pd.bdate_range("2024-01-01", periods=4)
    positions = {
        "A": pd.Series([1.0, 1.0, 0.0, 0.0], index=d),
        "B": pd.Series([0.0, 1.0, 1.0, 0.0], index=d),
        "LATE": pd.Series([1.0, 0.0], index=d[2:]),     # lists on day 3: absent (not "cash") before that
    }
    ex = exposure_series_pct(positions)
    # day1: A long, B cash            -> 1/2 = 50
    # day2: A long, B long            -> 2/2 = 100
    # day3: A cash, B long, LATE long -> 2/3
    # day4: A cash, B cash, LATE cash -> 0
    assert ex.round(6).tolist() == [50.0, 100.0, round(200 / 3, 6), 0.0]


def test_exposure_series_matches_headline_when_every_symbol_covers_the_same_dates():
    d = pd.bdate_range("2024-01-01", periods=6)
    pa = pd.Series([1.0, 1.0, 0.0, 0.0, 1.0, 0.0], index=d)
    pb = pd.Series([0.0, 0.0, 0.0, 1.0, 1.0, 1.0], index=d)
    headline = (pd.concat([pa, pb], ignore_index=True) == 1.0).sum() / 12 * 100
    assert exposure_series_pct({"A": pa, "B": pb}).mean() == pytest.approx(headline)


def test_non_cash_exposure_is_zero_before_the_first_rebalance_and_full_after():
    d = pd.bdate_range("2024-01-01", periods=5)
    s = non_cash_exposure_series_pct(d, d[2])
    assert s.tolist() == [0.0, 0.0, 100.0, 100.0, 100.0]
    assert non_cash_exposure_series_pct(d, None).tolist() == [100.0] * 5   # mirrors the headline's edge case


def test_growth_of_100_ends_at_100_plus_total_return_and_equalises_book_counts():
    from metrics import growth_of_100
    d = pd.bdate_range("2024-01-01", periods=3)
    one_book = pd.Series([1_000_000.0, 1_100_000.0, 990_000.0], index=d)
    fifty_books = one_book * 50                      # same performance, 50 separate books summed
    empty = pd.DataFrame(columns=["entry_date", "exit_date", "entry_price", "exit_price",
                                  "quantity", "return_pct", "holding_days", "total_costs"])
    g1 = growth_of_100(one_book, 1_000_000.0)
    g50 = growth_of_100(fifty_books, 50_000_000.0)
    assert g1.tolist() == pytest.approx([100.0, 110.0, 99.0])
    assert g50.tolist() == pytest.approx(g1.tolist())   # the rupee curves differ 50x; the growth curves do not
    m = compute_metrics(one_book, empty, 1_000_000.0, pd.Series(1.0, index=d))
    assert g1.iloc[-1] - 100 == pytest.approx(m["total_return_pct"])
