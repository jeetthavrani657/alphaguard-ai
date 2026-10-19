"""
tests/test_advisory_forward.py

research/advisory_forward.py collects out-of-time evidence for the three advisory profiles. These tests use made-up
returns (no network) and check the discipline: the clock starts at the freeze day, the base day is not counted as a
forward day, the numbers are recomputed identically, the history never duplicates, and no Sharpe is produced early.
"""

import numpy as np
import pandas as pd
import pytest

import advisory as adv
import advisory_forward as fwd


def _returns(end="2026-10-23", n=1500, seed=5):
    rng = np.random.default_rng(seed)
    vols = {"equity_large": 0.010, "equity_mid": 0.013, "intl_equity": 0.012, "gold": 0.008, "debt": 0.004, "crypto": 0.035}
    idx = pd.bdate_range(end=end, periods=n)
    r = pd.DataFrame({k: rng.normal(0.0003, v, n) for k, v in vols.items()}, index=idx)
    r["cash"] = (1 + adv.CASH_RATE) ** (1 / adv.TRADING_DAYS) - 1
    return r


def test_the_clock_has_not_started_when_data_ends_before_the_first_counted_day():
    rep = fwd.build_profile("moderate", _returns(end="2026-10-19"))
    assert rep["status"] == "NOT_STARTED" and rep["n_trading_days"] == 0 and rep["summary"] is None


def test_the_freeze_day_is_the_base_of_100_and_is_not_counted_as_a_forward_day():
    r = _returns()                                              # data through Fri 2026-10-23: sessions 20, 21, 22, 23 are forward days
    rep = fwd.build_profile("moderate", r)
    g = rep["growth_strategy"]
    assert g["dates"][0] == "2026-10-19" and g["values"][0] == 100.0
    assert rep["n_trading_days"] == 4 and len(g["dates"]) == 5
    assert rep["growth_benchmark"]["values"][0] == 100.0


def test_the_forward_return_is_the_frozen_rules_own_equity_curve_rebased_at_the_freeze_day():
    r = _returns()
    rep = fwd.build_profile("aggressive", r)
    eq = adv.simulate(r, adv.PROFILES["aggressive"])["equity"]
    expected = (eq.iloc[-1] / eq.loc["2026-10-19"] - 1) * 100
    assert rep["summary"]["return_pct"] == pytest.approx(expected, abs=0.001)
    bench = (1 + r["equity_large"].loc["2026-10-20":]).prod() - 1                 # buy-and-hold from the first counted day
    assert rep["summary"]["benchmark_return_pct"] == pytest.approx(bench * 100, abs=0.001)


def test_running_it_twice_on_the_same_data_gives_the_same_answer_and_one_history_row_per_profile_and_date(tmp_path):
    r = _returns()
    a, b = fwd.build_profile("conservative", r), fwd.build_profile("conservative", r)
    assert a == b
    path = tmp_path / "hist.csv"
    fwd.append_history(a, str(path))
    fwd.append_history(b, str(path))
    fwd.append_history(fwd.build_profile("moderate", r), str(path))
    rows = pd.read_csv(path)
    assert len(rows) == 2 and set(rows["profile_id"]) == {"conservative", "moderate"}


def test_no_sharpe_is_produced_before_a_year_of_forward_sessions():
    rep = fwd.build_profile("moderate", _returns())
    assert "sharpe" not in rep["summary"] and rep["summary"]["withheld_reason"].startswith("withheld: 4 of 252")


def test_the_latest_file_is_valid_json_and_refuses_nan(tmp_path):
    rep = fwd.build_profile("moderate", _returns())
    path = tmp_path / "latest.json"
    fwd.write_latest([rep], str(path))
    assert '"profiles"' in path.read_text(encoding="utf-8")
    bad = dict(rep, summary=dict(rep["summary"], return_pct=float("nan")))
    with pytest.raises(ValueError):
        fwd.write_latest([bad], str(tmp_path / "bad.json"))


def test_a_trend_rule_is_tracked_from_the_same_freeze_and_a_not_started_one_runs_no_simulation():
    import multiasset_trend as mt
    idx = pd.bdate_range(end="2026-10-23", periods=1700)
    rng = np.random.default_rng(9)
    r = pd.DataFrame({k: rng.normal(0.0003, 0.01, 1700) for k in adv.RISKY_IDS}, index=idx)
    r["cash"] = (1 + adv.CASH_RATE) ** (1 / adv.TRADING_DAYS) - 1
    prices = (1 + r[adv.RISKY_IDS]).cumprod() * 100.0
    sims = mt.run_all(prices, r)
    rep = fwd.build_trend("trend_equal_weight", "Trend filter, equal weight", r, sims["trend_equal_weight"])
    assert rep["status"] == "RUNNING" and rep["n_trading_days"] == 4 and rep["growth_strategy"]["values"][0] == 100.0
    assert rep["growth_strategy"]["dates"][0] == "2026-10-19" and abs(sum(m["weight_pct"] for m in rep["current_mix"]) - 100) < 0.2
    early = fwd.build_trend("trend_equal_weight", "x", r.loc[:"2026-10-19"], None)             # the clock has not started: no simulation is needed
    assert early["status"] == "NOT_STARTED" and early["summary"] is None
