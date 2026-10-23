"""
tests/test_factor_ideas.py

research/factor_ideas.py ranks stocks three new ways. Whatever the results turn out to be, they must come from rankings that
(a) pick the stocks the idea says they pick, (b) never use a price from after the formation date, and (c) give the zero-skill
random arm the same dates, sizes and eligible pool as the real selection. Small synthetic markets, no network.
"""

import random

import numpy as np
import pandas as pd
import pytest

import factor_ideas as fi

DAYS = pd.bdate_range("2019-01-01", "2020-12-31")            # about 520 sessions: enough for the 252-day windows


def _stock(daily_vol, drift=0.0, seed=0, start=None):
    rng = np.random.default_rng(seed)
    days = DAYS if start is None else DAYS[DAYS >= start]
    close = pd.Series(100.0 * np.exp(np.cumsum(rng.normal(drift, daily_vol, len(days)))), index=days)
    return {"df": pd.DataFrame({"close": close})}


def _market():
    return {"CALM": _stock(0.004, seed=1), "MID": _stock(0.012, seed=2), "WILD": _stock(0.03, seed=3),
            "LATE": _stock(0.01, seed=4, start=pd.Timestamp("2020-09-01"))}      # listed too recently to rank until later


LAST = DAYS[-1]


def test_low_volatility_scores_the_calm_stock_highest_and_needs_a_full_year():
    m = _market()
    scores = {t: fi.score_lowvol(e["df"]["close"], LAST) for t, e in m.items()}
    assert scores["CALM"] > scores["MID"] > scores["WILD"]
    assert np.isnan(scores["LATE"])                                       # under 253 prices: not rankable
    assert np.isnan(fi.score_lowvol(m["CALM"]["df"]["close"], DAYS[100]))


def test_reversal_scores_last_months_loser_highest():
    up = pd.Series(np.linspace(100, 120, 60), index=DAYS[:60])
    down = pd.Series(np.linspace(100, 80, 60), index=DAYS[:60])
    d = DAYS[59]
    assert fi.score_reversal(down, d) > fi.score_reversal(up, d)
    assert fi.score_reversal(down, d) == pytest.approx(-(80 / down.iloc[-22] - 1))     # minus the 21-day return exactly
    assert np.isnan(fi.score_reversal(up, DAYS[10]))                       # fewer than 22 prices


def test_each_formation_date_holds_the_top_n_equal_weighted_and_the_rest_zero():
    w = fi.target_weights(_market(), fi.score_lowvol, top_n=2)
    last = w.iloc[-1]
    assert set(last[last > 0].index) == {"CALM", "MID"} and last[last > 0].tolist() == [0.5, 0.5]
    assert last["WILD"] == 0.0
    assert (w.sum(axis=1).round(9).isin([0.0, 1.0])).all()                 # fully invested, or all cash while nothing is rankable
    assert w.index.equals(pd.DatetimeIndex(sorted(set(DAYS.to_series().groupby(DAYS.to_period("M")).max()))))   # month-ends only


def test_it_is_all_cash_until_some_stock_can_be_ranked():
    w = fi.target_weights(_market(), fi.score_lowvol, top_n=2)
    early = w.loc[w.index < DAYS[252]]                                     # fewer than 253 prices so far
    assert (early.sum(axis=1) == 0).all()


def test_a_ranking_never_uses_prices_after_the_formation_date():
    m = _market()
    before = fi.target_weights(m, fi.score_reversal, top_n=2)
    cut = pd.Timestamp("2020-06-30")
    changed = {t: {"df": e["df"].copy()} for t, e in m.items()}
    for e in changed.values():
        e["df"].loc[e["df"].index > cut, "close"] *= np.random.default_rng(9).uniform(0.5, 2.0, (e["df"].index > cut).sum())
    after = fi.target_weights(changed, fi.score_reversal, top_n=2)
    early = before.index[before.index <= cut]
    pd.testing.assert_frame_equal(before.loc[early], after.loc[early])       # the past decisions did not move


def test_the_random_arm_has_the_same_dates_sizes_and_pool_as_the_real_selection():
    m = _market()
    real = fi.target_weights(m, fi.score_lowvol, top_n=2)
    rand = fi.random_weights(m, fi.score_lowvol, 2, random.Random(1))
    assert rand.index.equals(real.index)
    assert ((rand > 0).sum(axis=1) == (real > 0).sum(axis=1)).all()          # same number of names on every date
    unrankable = [(date, t) for date in rand.index for t in rand.columns
                  if rand.loc[date, t] > 0 and np.isnan(fi.score_lowvol(m[t]["df"]["close"], pd.Timestamp(date)))]
    assert unrankable == []                                                  # never draws a stock the real rule could not rank


def test_the_random_arm_is_reproducible_from_its_seed_and_differs_across_seeds():
    m = _market()
    a = fi.random_weights(m, fi.score_lowvol, 1, random.Random(5))
    b = fi.random_weights(m, fi.score_lowvol, 1, random.Random(5))
    c = fi.random_weights(m, fi.score_lowvol, 1, random.Random(6))
    pd.testing.assert_frame_equal(a, b)
    assert not a.equals(c)


def test_the_universe_benchmark_holds_every_rankable_stock_equally():
    w = fi.equal_weight_all(_market(), fi.score_lowvol)
    last = w.iloc[-1]
    assert last["LATE"] == 0.0                                                          # listed 2020-09: under a year of prices, unrankable
    assert np.allclose(last[["CALM", "MID", "WILD"]].to_numpy(), 1 / 3)                 # the three rankable stocks share equally
    short = fi.equal_weight_all(_market(), fi.score_reversal).iloc[-1]                  # one month of prices is enough for reversal
    assert np.allclose(short.to_numpy(), 1 / 4)                                         # so all four are held there


def test_the_frozen_settings_are_the_ones_written_in_the_design_note():
    by_id = {i["id"]: i for i in fi.IDEAS}
    assert (by_id["lowvol_nifty50"]["top_n"], by_id["reversal1m_nifty50"]["top_n"], by_id["momentum_midcap150"]["top_n"]) == (10, 10, 30)
    assert fi.VOL_DAYS == 252 and fi.REVERSAL_DAYS == 21 and fi.RANDOM_SEED == 20261022 and len(fi.IDEAS) == 3


# --- the survivorship diagnostic (research/midcap_survivorship_check.py) ----------------------------------------------

def test_a_stock_that_stopped_trading_can_no_longer_be_ranked_by_momentum():
    import midcap_survivorship_check as sv
    from cross_sectional_momentum import _momentum_score
    close = _stock(0.01, seed=7)["df"]["close"]
    dead = close.loc[:"2019-12-31"]                                        # delisted at the end of 2019
    live_day = pd.Timestamp("2019-12-31")
    assert sv.live_momentum_score(dead, live_day) == pytest.approx(_momentum_score(dead, live_day))   # same as the registered score
    assert np.isnan(sv.live_momentum_score(dead, pd.Timestamp("2020-06-30")))                          # six months on: not rankable
    assert not np.isnan(_momentum_score(dead, pd.Timestamp("2020-06-30")))                             # the registered one would be frozen, not NaN


# --- re-judging the stored results at a later ledger count ----------------------------------------------------------------------------

def test_rejudging_changes_only_the_status_and_the_bar_and_runs_nothing(tmp_path, monkeypatch):
    import json
    import harness
    window = lambda sh: {"sharpe": sh, "n_obs": 1400, "start": "a", "end": "b"}
    data = {"ledger_total": 215, "ideas": {i["id"]: {"in_sample": window(0.5), "out_of_sample": window(1.2), "name": i["name"], "harness_status": "OLD", "p_in_sample": 1,
                                                       "p_out_of_sample": 1, "bonferroni_bar": 1} for i in fi.IDEAS}}
    path = tmp_path / "factor.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(harness, "cumulative_hypotheses", lambda: 1000)
    out = fi.rejudge(str(path))
    assert out["ledger_total"] == 1000 and json.loads(path.read_text())["ledger_total"] == 1000
    for idea in out["ideas"].values():
        assert idea["harness_status"] != "OLD" and idea["bonferroni_bar"] == pytest.approx(0.05 / 1000)
        assert idea["in_sample"] == window(0.5) and idea["out_of_sample"] == window(1.2)                       # the stored numbers are untouched
