"""
tests/test_overfit_checks.py

research/overfit_checks.py computes the Deflated Sharpe Ratio and the Probability of Backtest Overfitting. A wrong formula here would
quietly bless or condemn a strategy, so each piece is checked against a value worked out by hand or a behaviour it must have.
"""

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

import overfit_checks as oc


def test_one_trial_expects_no_lucky_sharpe_and_more_trials_expect_more():
    assert oc.expected_max_sharpe(1, 1.0) == 0.0
    bars = [oc.expected_max_sharpe(n, 1.0) for n in (2, 10, 50, 215, 1000)]
    assert all(a < b for a, b in zip(bars, bars[1:]))


def test_the_expected_best_of_215_noise_tries_matches_the_formula_worked_by_hand():
    g = oc.EULER_GAMMA
    by_hand = (1 - g) * norm.ppf(1 - 1 / 215) + g * norm.ppf(1 - 1 / (215 * np.e))          # about 2.79 standard deviations
    assert oc.expected_max_sharpe(215, 1.0) == pytest.approx(by_hand) and 2.7 < by_hand < 2.9
    assert oc.expected_max_sharpe(215, 4.0) == pytest.approx(2 * by_hand)                      # scales with the spread of Sharpe estimates


def test_probabilistic_sharpe_is_half_at_the_benchmark_and_follows_the_normal_case_formula():
    assert oc.probabilistic_sharpe(0.05, 0.05, 500, 0.0, 3.0) == pytest.approx(0.5)
    sr, t = 0.08, 600
    normal_case = norm.cdf(sr * np.sqrt(t - 1) / np.sqrt(1 + sr ** 2 / 2))                    # skew 0 and kurtosis 3 reduce the formula to this
    assert oc.probabilistic_sharpe(sr, 0.0, t, 0.0, 3.0) == pytest.approx(normal_case)


def test_negative_skew_and_fat_tails_lower_the_probability_that_a_positive_sharpe_is_real():
    base = oc.probabilistic_sharpe(0.1, 0.0, 500, 0.0, 3.0)
    assert oc.probabilistic_sharpe(0.1, 0.0, 500, -1.0, 3.0) < base                            # crash-prone returns
    assert oc.probabilistic_sharpe(0.1, 0.0, 500, 0.0, 9.0) < base                             # fat tails
    assert oc.probabilistic_sharpe(0.1, 0.0, 2000, 0.0, 3.0) > base                            # more days, more confidence


def _excess(mean, sd, n=1300, seed=1):
    return pd.Series(np.random.default_rng(seed).normal(mean, sd, n), index=pd.bdate_range("2020-01-01", periods=n))


def test_the_deflated_sharpe_is_never_above_the_plain_probability_and_equals_it_for_one_trial():
    x = _excess(0.0006, 0.01)
    one, many = oc.deflated_sharpe(x, 1), oc.deflated_sharpe(x, 215)
    assert one["dsr"] == pytest.approx(one["psr_vs_zero"])
    assert many["dsr"] < many["psr_vs_zero"] and many["benchmark_sr_annual"] > 0


def test_a_strong_strategy_usually_survives_215_tries_and_a_mediocre_one_does_not():
    """One random draw can be unlucky, so this looks at the average over many draws of the same two true strategies."""
    strong = [oc.deflated_sharpe(_excess(0.0015, 0.01, seed=s), 215)["dsr"] for s in range(40)]      # true Sharpe about 2.4 a year
    weak = [oc.deflated_sharpe(_excess(0.0003, 0.01, seed=s), 215)["dsr"] for s in range(40)]        # true Sharpe about 0.5 a year
    assert np.mean(strong) > 0.9 and np.mean(weak) < 0.3 and np.mean(strong) > np.mean(weak) + 0.5


def test_the_annualised_sharpe_agrees_with_the_projects_own_sharpe_on_the_same_curve():
    import advisory as adv
    import config
    rng = np.random.default_rng(5)
    equity = pd.Series(100.0 * np.cumprod(1 + rng.normal(0.0006, 0.009, 900)), index=pd.bdate_range("2021-01-01", periods=900))
    mine = oc.sharpe_stats(oc.daily_excess(equity, config.RISK_FREE_RATE))["sr_annual"]
    assert mine == pytest.approx(adv.window_metrics(equity)["sharpe"], rel=0.01)


def _noise(m=12, t=1600, seed=4):
    return pd.DataFrame(np.random.default_rng(seed).normal(0.0, 0.01, (t, m)))


def test_with_pure_noise_picking_the_in_sample_winner_is_a_coin_toss_on_average():
    """A single dataset can land anywhere (the 70 splits share the same days); across many datasets the PBO centres on 50%."""
    results = [oc.pbo_cscv(_noise(seed=sd)) for sd in range(30)]
    assert 0.38 <= float(np.mean([r["pbo"] for r in results])) <= 0.62
    assert results[0]["n_splits_used"] == 70 and results[0]["n_candidates"] == 12


def test_a_candidate_with_a_real_edge_keeps_winning_out_of_sample():
    data = _noise()
    data[0] += 0.003                                                                           # one candidate truly better than the rest
    r = oc.pbo_cscv(data)
    assert r["pbo"] < 0.05 and r["share_of_splits_where_the_winner_lost_money"] == 0.0 and r["mean_logit"] > 0


def test_pbo_refuses_unusable_settings_and_is_repeatable():
    with pytest.raises(ValueError):
        oc.pbo_cscv(_noise(), n_splits=7)
    with pytest.raises(ValueError):
        oc.pbo_cscv(_noise(m=2))
    assert oc.pbo_cscv(_noise()) == oc.pbo_cscv(_noise())
