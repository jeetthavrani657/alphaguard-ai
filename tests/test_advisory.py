"""
tests/test_advisory.py

research/advisory.py is the multi-asset, risk-managed allocation engine. These tests use made-up returns (no network)
and check the properties that make a risk-managed allocation trustworthy: the caps hold, volatility targeting never
leverages, nothing sees the future, costs are charged, the drawdown guard bites, and registering hypotheses in the
ledger happens only when asked.
"""

import json

import numpy as np
import pandas as pd
import pytest

import advisory as adv
import harness


def _returns(n=1500, seed=3, start="2020-01-01"):
    """Daily returns for every risky asset (different volatilities) plus cash, on business days."""
    rng = np.random.default_rng(seed)
    vols = {"equity_large": 0.010, "equity_mid": 0.013, "intl_equity": 0.012, "gold": 0.008, "debt": 0.004, "crypto": 0.035}
    idx = pd.bdate_range(start, periods=n)
    r = pd.DataFrame({k: rng.normal(0.0003, v, n) for k, v in vols.items()}, index=idx)
    r["cash"] = (1 + adv.CASH_RATE) ** (1 / adv.TRADING_DAYS) - 1
    return r


def _caps(**over):
    base = {k: 1.0 for k in adv.RISKY_IDS}
    base.update(over)
    return pd.Series(base)


# --- weights ---------------------------------------------------------------------------------------------------------

def test_inverse_volatility_gives_calmer_assets_more_money_and_sums_to_one():
    vols = pd.Series({"equity_large": 0.20, "equity_mid": 0.30, "intl_equity": 0.25, "gold": 0.15, "debt": 0.05, "crypto": 0.80})
    w = adv.capped_inverse_vol(vols, _caps())
    assert w.sum() == pytest.approx(1.0) and (w >= 0).all()
    assert w["debt"] > w["gold"] > w["equity_large"] > w["equity_mid"] > w["crypto"]


def test_a_cap_is_never_exceeded_and_the_excess_goes_to_the_others():
    vols = pd.Series({"equity_large": 0.20, "equity_mid": 0.30, "intl_equity": 0.25, "gold": 0.15, "debt": 0.01, "crypto": 0.80})
    w = adv.capped_inverse_vol(vols, _caps(debt=0.30))                 # debt would take ~70% uncapped
    assert w["debt"] == pytest.approx(0.30) and w.sum() == pytest.approx(1.0)
    assert (w <= _caps(debt=0.30) + 1e-9).all()


def test_an_asset_with_a_zero_cap_gets_nothing_and_impossible_caps_leave_the_rest_unplaced():
    vols = pd.Series({k: 0.2 for k in adv.RISKY_IDS})
    assert adv.capped_inverse_vol(vols, _caps(crypto=0.0))["crypto"] == 0.0
    tight = pd.Series({k: 0.05 for k in adv.RISKY_IDS})                # six assets capped at 5% can hold only 30%
    w = adv.capped_inverse_vol(vols, tight)
    assert w.sum() == pytest.approx(0.30) and (w <= 0.05 + 1e-9).all()


def test_target_weights_never_lever_never_go_negative_and_always_sum_to_one():
    r = _returns()
    for p in adv.PROFILES.values():
        for guard in (False, True):
            w = adv.target_weights(r.iloc[:adv.VOL_LOOKBACK], p, guard)
            assert w.sum() == pytest.approx(1.0) and (w >= -1e-12).all()
            assert w[adv.RISKY_IDS].sum() <= 1.0 + 1e-12
            for k in adv.RISKY_IDS:
                assert w[k] <= p["caps"][k] + 1e-9


def test_volatility_targeting_scales_a_wild_market_down_toward_the_target_and_leaves_a_calm_one_alone():
    wild = _returns().copy()
    wild[adv.RISKY_IDS] = wild[adv.RISKY_IDS] * 4                     # four times as volatile
    p = adv.PROFILES["moderate"]
    w_wild = adv.target_weights(wild.iloc[:adv.VOL_LOOKBACK], p, False)
    cov = wild.iloc[:adv.VOL_LOOKBACK][adv.RISKY_IDS].cov() * adv.TRADING_DAYS
    port_vol = float(np.sqrt(w_wild[adv.RISKY_IDS].values @ cov.values @ w_wild[adv.RISKY_IDS].values))
    assert port_vol == pytest.approx(p["target_vol"], rel=0.02)       # sized to the target
    assert w_wild["cash"] > 0.2                                        # the rest sits in cash
    calm = _returns().copy()
    calm[adv.RISKY_IDS] = calm[adv.RISKY_IDS] * 0.1
    w_calm = adv.target_weights(calm.iloc[:adv.VOL_LOOKBACK], p, False)
    base = adv.capped_inverse_vol(calm.iloc[:adv.VOL_LOOKBACK][adv.RISKY_IDS].std() * np.sqrt(252),
                                  pd.Series({k: p["caps"][k] for k in adv.RISKY_IDS}))
    assert w_calm[adv.RISKY_IDS].sum() == pytest.approx(base.sum())    # no scaling down, and no leverage up


def test_the_drawdown_guard_halves_the_risky_share():
    r = _returns().iloc[:adv.VOL_LOOKBACK]
    p = adv.PROFILES["aggressive"]
    on, off = adv.target_weights(r, p, True), adv.target_weights(r, p, False)
    assert on[adv.RISKY_IDS].sum() == pytest.approx(off[adv.RISKY_IDS].sum() / 2)


# --- the simulation -------------------------------------------------------------------------------------------------------

def test_nothing_in_the_future_can_change_what_was_already_decided_or_earned():
    r = _returns(700)
    base = adv.simulate(r, adv.PROFILES["moderate"])
    k = 500
    shocked = r.copy()
    shocked.iloc[k + 1:, :] = shocked.iloc[k + 1:, :] * 7 - 0.02       # a violent change AFTER day k
    alt = adv.simulate(shocked, adv.PROFILES["moderate"])
    upto = base["equity"].index[base["equity"].index <= r.index[k]]
    pd.testing.assert_series_equal(base["equity"].loc[upto], alt["equity"].loc[upto])
    pd.testing.assert_series_equal(base["exposure_pct"].loc[upto], alt["exposure_pct"].loc[upto])


def test_a_decision_is_carried_out_one_day_after_it_is_made():
    r = _returns(600)
    r.iloc[250:, :6] = r.iloc[250:, :6] * 4                            # volatility jumps, so the targets really change over time
    sim = adv.simulate(r, adv.PROFILES["moderate"])
    exposure = sim["exposure_pct"]
    dates = list(exposure.index)
    not_yet_in_force = 0
    for decision in sim["rebalances"][1:-1]:                           # each decision is taken at the close of its date ...
        i = dates.index(decision["date"])
        target_risky = (1.0 - decision["weights"]["cash"]) * 100.0
        assert exposure.iloc[i + 1] == pytest.approx(target_risky, abs=1e-6)   # ... and is in force at the close of the NEXT trading day
        not_yet_in_force += abs(exposure.iloc[i] - target_risky) > 1e-6        # on its own day the old weights were still held
    assert not_yet_in_force >= 1


def test_exposure_is_a_share_of_the_portfolio_never_above_100_percent():
    sim = adv.simulate(_returns(800), adv.PROFILES["aggressive"])
    assert sim["exposure_pct"].between(0, 100.0 + 1e-6).all()


def test_costs_are_charged_on_what_is_traded(monkeypatch):
    r = _returns(700)
    with_cost = adv.simulate(r, adv.PROFILES["moderate"])
    monkeypatch.setattr(adv, "COST_PCT", 0.0)
    free = adv.simulate(r, adv.PROFILES["moderate"])
    assert with_cost["cost_paid"] > 0 and free["cost_paid"] == 0
    assert with_cost["equity"].iloc[-1] < free["equity"].iloc[-1]


def test_after_a_crash_the_guard_switches_on_and_the_next_decision_is_more_defensive():
    r = _returns(900, seed=8)
    crash_at = 400
    r.iloc[crash_at:crash_at + 10, :6] = -0.04                          # ten days of heavy losses in every risky asset
    sim = adv.simulate(r, adv.PROFILES["conservative"])
    guard_flags = [x["guard_on"] for x in sim["rebalances"] if x["date"] > r.index[crash_at]]
    assert any(guard_flags)                                            # the guard engaged after the crash


def test_a_pure_cash_world_earns_the_cash_rate():
    r = _returns(500)
    r[adv.RISKY_IDS] = 0.0                                              # nothing risky moves at all
    sim = adv.simulate(r, adv.PROFILES["moderate"])
    years = len(sim["equity"]) / adv.TRADING_DAYS
    growth = sim["equity"].iloc[-1] / sim["equity"].iloc[0]
    assert growth == pytest.approx((1 + adv.CASH_RATE) ** years, rel=0.01)


# --- measuring ----------------------------------------------------------------------------------------------------------------

def test_value_at_risk_and_expected_shortfall_match_a_hand_calculation():
    daily = pd.Series(np.arange(-0.10, 0.10, 0.002))                    # 100 evenly spaced days from -10% to +9.8%
    var, cvar = adv.var_cvar(daily, 0.95)
    assert var == pytest.approx(9.0, abs=0.25)                          # the 5th percentile loss, about 9%
    assert cvar > var and cvar == pytest.approx(9.6, abs=0.3)          # the average of the worst 5%


def test_window_metrics_reports_drawdown_volatility_and_var():
    eq = pd.Series(100 * np.cumprod(1 + np.random.default_rng(1).normal(0.0004, 0.01, 600)), index=pd.bdate_range("2021-01-01", periods=600))
    m = adv.window_metrics(eq)
    assert m["max_drawdown_pct"] < 0 and m["volatility_pct"] > 0 and m["var95_pct"] > 0 and m["cvar95_pct"] >= m["var95_pct"]
    assert m["n_days"] == 600


# --- the questionnaire ----------------------------------------------------------------------------------------------------------

def test_every_questionnaire_total_maps_to_exactly_one_profile():
    assert [adv.profile_for_points(p) for p in (0, 5)] == ["conservative"] * 2
    assert [adv.profile_for_points(p) for p in (6, 10)] == ["moderate"] * 2
    assert [adv.profile_for_points(p) for p in (11, 15)] == ["aggressive"] * 2
    assert all(len(q["options"]) == 4 and [o["points"] for o in q["options"]] == [0, 1, 2, 3] for q in adv.QUESTIONS)
    assert sum(max(o["points"] for o in q["options"]) for q in adv.QUESTIONS) == adv.BANDS[-1]["max_points"]


# --- the whole file and the ledger ------------------------------------------------------------------------------------------------

@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"cumulative_hypotheses": 205, "runs": []}))
    monkeypatch.setattr(harness, "LEDGER_PATH", str(path))
    return path


def test_building_the_file_without_registering_leaves_the_ledger_untouched(ledger):
    payload = adv.build(_returns(), None, register=False)
    assert json.loads(ledger.read_text())["cumulative_hypotheses"] == 205
    assert payload["ledger_total"] == 205 and [p["id"] for p in payload["profiles"]] == ["conservative", "moderate", "aggressive"]
    json.dumps(payload, allow_nan=False)                                # valid JSON: no NaN anywhere


def test_registering_counts_the_three_profiles_once(ledger):
    payload = adv.build(_returns(), None, register=True)
    assert json.loads(ledger.read_text())["cumulative_hypotheses"] == 208 and payload["ledger_total"] == 208
    again = adv.build(_returns(), None, register=False)                  # regenerating later does not count them again
    assert json.loads(ledger.read_text())["cumulative_hypotheses"] == 208 and again["ledger_total"] == 208


def test_each_profile_carries_its_allocation_metrics_for_both_windows_and_a_status(ledger):
    p = adv.build(_returns(), None)["profiles"][1]
    assert sum(a["weight_pct"] for a in p["allocation"]) == pytest.approx(100.0, abs=0.1)
    for w in ("full", "in_sample", "out_of_sample"):
        assert {"sharpe", "max_drawdown_pct", "var95_pct", "cvar95_pct"} <= set(p["metrics"][w])
        assert "sharpe" in p["benchmark_metrics"][w]
    assert p["harness_status"] in {"UNVALIDATED", "VALIDATED_FAILED", "VALIDATED_CONFIRMED", "OOS_ONLY_SIGNIFICANT"}
    assert len(p["growth_strategy"]["dates"]) == len(p["growth_benchmark"]["dates"]) == len(p["exposure_pct"]["dates"])
    assert p["growth_strategy"]["values"][0] == 100.0 and p["growth_benchmark"]["values"][0] == 100.0


# --- data cleaning -------------------------------------------------------------------------------------------------------------

def test_a_one_day_bad_print_is_removed_but_a_real_crash_is_kept():
    idx = pd.bdate_range("2020-01-01", periods=12)
    price = pd.Series(100.0, index=idx)
    price.iloc[5] = 10.0                                  # a bad print: one tenth of the price for a day, then normal again
    crash = pd.Series([100.0] * 6 + [40.0] * 6, index=idx)   # a real crash: down 60% and stays down
    clean, removed = adv.clean_prices(pd.DataFrame({"gold": price, "equity_large": crash}))
    assert clean["gold"].iloc[5] == 100.0                  # carried forward from the day before
    assert [r["asset_id"] for r in removed] == ["gold"] and removed[0]["date"] == idx[5].strftime("%Y-%m-%d")
    pd.testing.assert_series_equal(clean["equity_large"], crash, check_names=False)    # the crash is untouched


def test_a_bad_print_lasting_two_days_is_removed_whole_and_clean_data_is_returned_unchanged():
    idx = pd.bdate_range("2020-01-01", periods=12)
    p = pd.Series(50.0, index=idx)
    p.iloc[4:6] = 0.5                                      # two bad days in a row
    clean, removed = adv.clean_prices(pd.DataFrame({"x": p}))
    assert (clean["x"] == 50.0).all() and len(removed) == 2
    ok = pd.DataFrame({"x": np.linspace(10, 20, 12)}, index=idx)
    same, none = adv.clean_prices(ok)
    pd.testing.assert_frame_equal(same, ok) and none == []
