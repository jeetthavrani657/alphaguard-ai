"""
tests/test_options_vol.py

research/options_vol.py compares implied with following realised volatility. On a synthetic option market with a KNOWN flat volatility the implied number must come back
exactly, the realised number must match a hand calculation, and the interpolation between expiries must follow total variance.
"""

import math

import numpy as np
import pandas as pd
import pytest

import options_backtest as ob
import options_math as om
import options_vol as ov

RATE = 0.06
DAYS = list(pd.bdate_range("2026-01-05", "2026-04-30"))


def table_for(sigma_by_expiry, spot=22000.0):
    rows = []
    for d in DAYS:
        for e, sigma in sigma_by_expiry.items():
            if d > e or (e - d).days > 70:
                continue
            t = (e - d).days / 365.0
            fwd = spot * math.exp(RATE * t)
            for k in np.arange(spot - 2500, spot + 2500, 100.0):
                for kind in ("CE", "PE"):
                    px = om.price(fwd, k, t, sigma, RATE, kind == "CE") if t > 0 else (max(spot - k, 0) if kind == "CE" else max(k - spot, 0))
                    rows.append({"date": d, "instrument": "OPTIDX", "symbol": "NIFTY", "expiry": e, "strike": float(k), "option_type": kind, "settle": px, "volume": 1})
    return pd.DataFrame(rows)


EXP = {pd.Timestamp("2026-02-26"): 0.20, pd.Timestamp("2026-03-26"): 0.20, pd.Timestamp("2026-04-30"): 0.20}


@pytest.fixture(scope="module")
def book():
    return ob.index_table(table_for(EXP))


def exps_by_day(book):
    out = {}
    for d, e in book:
        out.setdefault(d, []).append(e)
    return out


def test_the_at_the_money_implied_volatility_comes_back_exactly_from_flat_prices(book):
    day = pd.Timestamp("2026-02-02")
    iv, t = ov.atm_iv(book, day, pd.Timestamp("2026-02-26"), RATE)
    assert iv == pytest.approx(0.20, abs=1e-6) and t == pytest.approx(24 / 365)
    assert math.isnan(ov.atm_iv(book, day, pd.Timestamp("2026-09-24"), RATE)[0])                           # an expiry with no chain


def test_with_a_flat_surface_the_thirty_day_figure_is_that_volatility(book):
    day = pd.Timestamp("2026-02-02")                                                                        # expiries at 24 and 52 days: one each side of 30
    assert ov.implied_30d(book, day, RATE, exps_by_day(book)) == pytest.approx(0.20, abs=1e-6)


def test_the_interpolation_is_linear_in_total_variance_not_in_volatility():
    table = table_for({pd.Timestamp("2026-02-26"): 0.10, pd.Timestamp("2026-03-26"): 0.30})
    b = ob.index_table(table)
    day = pd.Timestamp("2026-02-02")
    t1, t2, tgt = 24 / 365, 52 / 365, 30 / 365
    w = 0.10 ** 2 * t1 + (0.30 ** 2 * t2 - 0.10 ** 2 * t1) * (tgt - t1) / (t2 - t1)
    assert ov.implied_30d(b, day, RATE, exps_by_day(b)) == pytest.approx(math.sqrt(w / tgt), abs=1e-6)
    naive = 0.10 + (0.30 - 0.10) * (tgt - t1) / (t2 - t1)
    assert abs(ov.implied_30d(b, day, RATE, exps_by_day(b)) - naive) > 0.001                                 # the two methods really differ


def test_a_day_needs_an_expiry_on_each_side_of_thirty_days_to_have_a_figure(book):
    assert math.isfinite(ov.implied_30d(book, pd.Timestamp("2026-03-20"), RATE, exps_by_day(book)))        # 6 and 41 days: one each side of 30, so this one HAS a figure
    late = pd.Timestamp("2026-04-20")                                                                       # only the 10-day expiry is left: nothing above 30
    assert math.isnan(ov.implied_30d(book, late, RATE, exps_by_day(book)))


def test_realised_volatility_is_the_annualised_standard_deviation_of_the_next_thirty_days_returns():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2026-01-01", "2026-04-30")
    spot = pd.Series(22000 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))), index=idx)
    day = pd.Timestamp("2026-02-02")
    window = spot.loc[(spot.index > day) & (spot.index <= day + pd.Timedelta(days=30))]
    path = pd.concat([spot.loc[:day].iloc[[-1]], window])
    expected = np.log(path).diff().dropna().std(ddof=1) * math.sqrt(252)
    assert ov.realised_30d(spot, day) == pytest.approx(expected)
    assert math.isnan(ov.realised_30d(spot, pd.Timestamp("2026-04-25")))                                    # too few days left to measure


def test_realised_volatility_looks_only_forward_never_at_the_days_before(book):
    idx = pd.bdate_range("2026-01-01", "2026-04-30")
    calm = pd.Series(22000.0, index=idx)
    calm.loc[calm.index < "2026-02-02"] = 22000 * np.exp(np.cumsum(np.random.default_rng(2).normal(0, 0.05, (calm.index < "2026-02-02").sum())))  # a wild past
    assert ov.realised_30d(calm, pd.Timestamp("2026-02-02")) == pytest.approx(0.0, abs=1e-12) or ov.realised_30d(calm, pd.Timestamp("2026-02-02")) < 0.5


def test_the_premium_table_and_the_yearly_summary_give_implied_minus_realised(book):
    idx = pd.bdate_range("2025-12-01", "2026-04-30")
    spot = pd.Series(22000 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.008, len(idx)))), index=idx)
    prem = ov.premium_table(book, spot)
    ok = prem.dropna()
    assert len(ok) > 5 and np.allclose(ok["premium"], ok["implied_30d"] - ok["realised_30d"])
    summary = ov.by_year(prem)
    assert list(summary.index) == [2026] and summary.loc[2026, "implied"] == pytest.approx(20.0, abs=0.01) and 0 <= summary.loc[2026, "share_implied_above"] <= 1


def test_the_spot_series_uses_the_cache_and_then_the_recorded_underlying(tmp_path):
    cache = tmp_path / "nsei.csv"
    pd.DataFrame({"close": [100.0, 101.0]}, index=pd.DatetimeIndex(["2025-12-29", "2025-12-30"], name="date")).to_csv(cache)
    bt = pd.DataFrame({"date": pd.to_datetime(["2025-12-30", "2026-01-02", "2026-01-02", "2026-01-05"]), "symbol": "NIFTY",
                       "underlying": [999.0, 102.0, 104.0, 103.0]})
    s = ov.spot_series(bt, str(cache))
    assert list(s.index.strftime("%Y-%m-%d")) == ["2025-12-29", "2025-12-30", "2026-01-02", "2026-01-05"]
    assert s.loc["2025-12-30"] == 101.0 and s.loc["2026-01-02"] == 103.0 and s.loc["2026-01-05"] == 103.0       # the cache wins where it exists; later, the median recorded level


def test_the_expiry_day_itself_has_no_chain_figure_and_does_not_crash(book):
    """On the expiry day there is no time left: there is no forward or volatility to find. This used to raise KeyError('iv')."""
    day = pd.Timestamp("2026-02-26")
    iv, t = ov.atm_iv(book, day, pd.Timestamp("2026-02-26"), RATE)
    assert math.isnan(iv) and t == 0.0
