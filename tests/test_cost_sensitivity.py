"""
tests/test_cost_sensitivity.py

research/cost_sensitivity.py reruns registered rules at worse slippage. Whatever it reports, worse slippage must never IMPROVE a rule, the
costs it reports must rise with it, and the numbers at the engine's own assumption must be the engine's own. A small synthetic market, no network.
"""

import numpy as np
import pandas as pd
import pytest

import cost_sensitivity as cs
import factor_ideas as fi

DAYS = pd.bdate_range("2019-01-01", "2020-12-31")


def _market():
    """Eight stocks with real day-to-day noise, so a one-month reversal rule trades a lot."""
    universe = {}
    for i in range(8):
        rng = np.random.default_rng(100 + i)
        close = pd.Series(100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, len(DAYS)))), index=DAYS)
        df = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1e6})
        universe[f"S{i}"] = {"df": df, "report": {"symbol": f"S{i}", "discontinuities": [], "usable": True, "checks": []}}
    return universe


START, END = "2020-01-02", "2020-12-31"


def test_worse_slippage_never_improves_a_busy_rule_and_raises_the_costs_paid():
    universe = _market()
    weights = fi.target_weights(universe, fi.score_reversal, top_n=3)
    runs = [cs.run_at(universe, weights, START, END, s) for s in cs.SLIPPAGES]
    cagr = [r["cagr_pct"] for r in runs]
    paid = [r["cost_paid_pct_of_start_per_year"] for r in runs]
    assert all(a >= b for a, b in zip(cagr, cagr[1:])) and cagr[0] > cagr[-1]            # return falls as slippage rises
    assert all(a <= b for a, b in zip(paid, paid[1:])) and paid[-1] > paid[0] > 0          # and the costs paid rise


def test_a_rule_that_never_trades_pays_nothing_at_any_slippage():
    universe = _market()
    idle = pd.DataFrame(0.0, index=fi.formation_dates(universe), columns=list(universe))   # always cash
    for s in cs.SLIPPAGES:
        assert cs.run_at(universe, idle, START, END, s)["cost_paid_pct_of_start_per_year"] == 0.0


def test_the_first_level_is_the_engines_own_assumption_and_the_run_is_repeatable():
    import config
    assert cs.SLIPPAGES[0] == config.COSTS["slippage_pct"] and cs.SLIPPAGES == sorted(cs.SLIPPAGES)
    universe = _market()
    weights = fi.target_weights(universe, fi.score_lowvol, top_n=3)
    a = cs.run_at(universe, weights, START, END, cs.SLIPPAGES[0])
    b = cs.run_at(universe, weights, START, END, cs.SLIPPAGES[0])
    assert a == b


def test_the_rule_list_matches_the_registered_settings():
    by_id = {r["id"]: r for r in cs.RULES}
    assert [by_id[i]["top_n"] for i in ("momentum_nifty50", "lowvol_nifty50", "reversal1m_nifty50", "momentum_midcap150")] == [10, 10, 10, 30]
