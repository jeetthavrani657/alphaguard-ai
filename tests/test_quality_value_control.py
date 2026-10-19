"""
tests/test_quality_value_control.py

research/quality_value_control.py is the zero-skill control for the quality + value forward book.
These tests use toy prices and a toy archive (no network) and check what makes the control fair and
safe: it draws from the same pool the book could have chosen from, it is reproducible, it refuses to
give a verdict before the pre-registered age gate, and a rehearsal never produces a verdict.
"""

import numpy as np
import pandas as pd
import pytest

import forward_books
import quality_value
import quality_value_control as qvc

END = pd.Timestamp("2026-10-20")
REPORT = {"usable": True, "checks": [], "discontinuities": []}


def _universe(n=25, n_days=700, seed=5):
    idx = pd.bdate_range(end=END, periods=n_days)
    rng = np.random.default_rng(seed)
    data = {}
    for k in range(n):
        close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.014, n_days)))
        df = pd.DataFrame({"open": close * 0.999, "high": close * 1.01, "low": close * 0.99, "close": close,
                           "volume": 1_000_000.0}, index=idx)
        data[f"S{k:02d}.NS"] = {"df": df, "report": REPORT, "symbol": f"S{k:02d}"}
    return data


def _archive(n=25):
    rows = []
    for k in range(n):
        ni, shares = 100.0 + 10 * k, 10.0
        for item, v in (("Net Income Common Stockholders", ni), ("Stockholders Equity", 500.0),
                        ("Ordinary Shares Number", shares), ("Basic EPS", ni / shares)):
            rows.append({"symbol": f"S{k:02d}", "freq": "annual", "period_end": pd.Timestamp("2026-03-31"), "item": item,
                         "value": v, "assumed_available_from": pd.Timestamp("2026-06-29"),
                         "first_seen_date": pd.Timestamp("2026-08-01")})
    return pd.DataFrame(rows), {f"S{k:02d}": "INR" for k in range(n)}


@pytest.fixture
def window(monkeypatch):
    monkeypatch.setattr(forward_books, "FORWARD_START", "2026-09-01")
    monkeypatch.setattr(forward_books, "FIRST_COUNTED_DAY", "2026-09-02")


# --- the pool: the same stocks the book could have chosen from -----------------------------------------------

def test_the_pool_is_exactly_the_stocks_the_book_could_score_and_empty_when_it_would_hold_cash():
    uni, (facts, ccy) = _universe(), _archive()
    d = pd.Timestamp("2026-09-01")
    pool = qvc.pool_by_date(uni, facts, ccy, [d])
    assert sorted(pool[d]) == sorted(quality_value.score_universe(uni, facts, ccy, d, strict=True)["ticker"])
    assert len(pool[d]) == 25
    few = qvc.pool_by_date(uni, facts, {f"S{k:02d}": ("INR" if k < 19 else "USD") for k in range(25)}, [d])
    assert few[d] == []                                                    # 19 < MIN_ELIGIBLE: the book would hold cash


def test_the_pool_respects_strict_point_in_time():
    uni, (facts, ccy) = _universe(), _archive()
    facts["first_seen_date"] = pd.Timestamp("2026-09-15")                  # the archive saw the figures after the date
    assert qvc.pool_by_date(uni, facts, ccy, [pd.Timestamp("2026-09-01")])[pd.Timestamp("2026-09-01")] == []


# --- the random arm -------------------------------------------------------------------------------------------------

def test_random_portfolios_are_reproducible_and_depend_on_the_seed(window):
    uni = _universe()
    pool = {pd.Timestamp("2026-09-01"): list(uni)}
    a = qvc.random_sharpes(uni, pool, "2026-09-01", "2026-10-20", n_sims=6, seed=1)
    b = qvc.random_sharpes(uni, pool, "2026-09-01", "2026-10-20", n_sims=6, seed=1)
    c = qvc.random_sharpes(uni, pool, "2026-09-01", "2026-10-20", n_sims=6, seed=2)
    assert np.array_equal(a, b) and not np.array_equal(a, c)
    assert len(a) == 6 and not np.isnan(a).any()


def test_random_portfolios_draw_only_from_the_pool(window):
    """If the pool is exactly ten stocks, every random portfolio IS those ten, so every Sharpe is identical."""
    uni = _universe()
    ten = list(uni)[:10]
    sims = qvc.random_sharpes(uni, {pd.Timestamp("2026-09-01"): ten}, "2026-09-01", "2026-10-20", n_sims=5)
    assert np.ptp(sims) < 1e-12


def test_percentile_counts_only_portfolios_strictly_below_the_book():
    sims = np.array([0.1, 0.2, 0.3, 0.4])
    assert qvc.percentile_of(0.35, sims) == 75.0
    assert qvc.percentile_of(0.3, sims) == 50.0                            # a tie is not a win
    assert qvc.percentile_of(9.0, sims) == 100.0 and qvc.percentile_of(-9.0, sims) == 0.0


# --- the pre-registered age gate -------------------------------------------------------------------------------------

def test_the_frozen_constants_have_not_been_edited():
    assert (qvc.N_SIMS, qvc.SEED, qvc.PASS_PERCENTILE) == (500, 20261016, 90.0)
    assert (qvc.MIN_TRADING_DAYS, qvc.MIN_JUNE_REBALANCES) == (504, 2)


def test_a_verdict_needs_both_enough_days_and_two_completed_june_rebalances():
    f = [pd.Timestamp("2026-10-16"), pd.Timestamp("2027-06-30"), pd.Timestamp("2028-06-30")]
    last = pd.Timestamp("2028-10-20")
    assert qvc.verdict_allowed(520, f, last)[0] is True
    ok, why = qvc.verdict_allowed(503, f, last)
    assert ok is False and "503 of 504" in why
    ok, why = qvc.verdict_allowed(600, f[:2], last)                        # only the 2027 rebalance exists
    assert ok is False and "1 of 2 June rebalances" in why
    assert qvc.june_rebalances_done(f, pd.Timestamp("2028-06-30")) == 1    # the 2028 trade has not executed yet on its own date


# --- the whole control -----------------------------------------------------------------------------------------------

def test_before_the_book_is_old_enough_nothing_is_simulated_and_there_is_no_verdict(window, monkeypatch):
    monkeypatch.setattr(qvc, "random_sharpes", lambda *a, **k: pytest.fail("simulations must not run before the age gate"))
    r = qvc.run_control(_universe(), *_archive())
    assert r["allowed"] is False and r["verdict"] is None and r["random_sharpes"] is None and r["percentile"] is None
    assert "forward trading days" in r["reason"]


def test_the_controls_day_count_matches_the_books_and_excludes_the_freeze_day(window):
    uni = _universe()
    r = qvc.run_control(uni, *_archive(), rehearse=True, n_sims=3)
    expected = sum(1 for d in uni["S00.NS"]["df"].index if d >= pd.Timestamp("2026-09-02"))
    assert r["n_trading_days"] == expected                      # sessions from the first counted day, not the freeze day


def test_a_rehearsal_runs_the_machinery_but_never_gives_a_verdict(window):
    r = qvc.run_control(_universe(), *_archive(), rehearse=True, n_sims=5)
    assert r["allowed"] is False and r["verdict"] is None
    assert r["percentile"] is not None and 0 <= r["percentile"] <= 100 and len(r["random_sharpes"]) == 5


def test_once_old_enough_the_verdict_follows_the_percentile_bar(window, monkeypatch):
    monkeypatch.setattr(qvc, "MIN_TRADING_DAYS", 5)
    monkeypatch.setattr(qvc, "MIN_JUNE_REBALANCES", 0)                     # the gate lowered for this test only
    r = qvc.run_control(_universe(), *_archive(), n_sims=8)
    assert r["allowed"] is True and r["verdict"] in ("PASS", "FAIL")
    assert (r["verdict"] == "PASS") == (r["percentile"] >= qvc.PASS_PERCENTILE)
