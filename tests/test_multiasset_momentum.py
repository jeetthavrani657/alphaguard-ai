"""
tests/test_multiasset_momentum.py

research/multiasset_momentum.py holds two dual-momentum rules and a no-selection benchmark (MULTIASSET_MOMENTUM.md). These tests
use made-up prices (no network) and check what makes a selection rule trustworthy: it uses only the past, it picks exactly the
assets with the best positive twelve-month return, a falling asset is replaced by cash, the risk-managed variant keeps the advisory's
caps, and registering hypotheses in the ledger happens only when asked.
"""

import json

import numpy as np
import pandas as pd
import pytest

import advisory as adv
import harness
import multiasset_momentum as mm


def _market(n=1800, seed=21, start="2019-01-01"):
    rng = np.random.default_rng(seed)
    vols = {"equity_large": 0.010, "equity_mid": 0.013, "intl_equity": 0.012, "gold": 0.008, "debt": 0.004, "crypto": 0.035}
    idx = pd.bdate_range(start, periods=n)
    r = pd.DataFrame({k: rng.normal(0.0003, v, n) for k, v in vols.items()}, index=idx)
    r["cash"] = (1 + adv.CASH_RATE) ** (1 / adv.TRADING_DAYS) - 1
    return (1 + r[adv.RISKY_IDS]).cumprod() * 100.0, r


def test_the_twelve_month_return_uses_only_prices_up_to_the_date_and_needs_a_full_year():
    prices, _ = _market()
    date = prices.index[600]
    before = mm.twelve_month_returns(prices, date)
    scrambled = prices.copy()
    scrambled.iloc[601:] = scrambled.iloc[601:] * 5.0                          # change everything after the date
    assert mm.twelve_month_returns(scrambled, date) == before
    assert mm.twelve_month_returns(prices, prices.index[mm.LOOKBACK_DAYS - 1]) == {}                # 252 prices are not enough for a 252-day return
    assert mm.twelve_month_returns(prices, prices.index[mm.LOOKBACK_DAYS]) != {}


def test_the_return_is_the_price_now_over_the_price_252_trading_days_earlier():
    idx = pd.bdate_range("2020-01-01", periods=400)
    prices = pd.DataFrame({k: 100.0 for k in adv.RISKY_IDS}, index=idx)
    prices["gold"] = np.linspace(100, 200, 400)
    r = mm.twelve_month_returns(prices, idx[-1])
    assert r["gold"] == pytest.approx(prices["gold"].iloc[-1] / prices["gold"].iloc[-253] - 1) and r["debt"] == 0.0


def test_pick_takes_the_best_n_that_are_positive_and_breaks_ties_by_list_order():
    r = {"equity_large": 0.10, "equity_mid": 0.30, "intl_equity": -0.05, "gold": 0.20, "debt": 0.02, "crypto": 0.50}
    assert [k for k, v in mm.pick(r, 2).items() if v] == ["equity_mid", "crypto"]
    assert [k for k, v in mm.pick(r, 3).items() if v] == ["equity_mid", "gold", "crypto"]
    falling = {k: -0.1 for k in adv.RISKY_IDS}
    assert not any(mm.pick(falling, 3).values())                                  # nothing positive: nothing is held
    flat = {k: 0.0 for k in adv.RISKY_IDS}
    assert not any(mm.pick(flat, 2).values())                                     # zero is not a positive return
    tie = {k: 0.1 for k in adv.RISKY_IDS}
    assert [k for k, v in mm.pick(tie, 2).items() if v] == adv.RISKY_IDS[:2]


def test_top2_holds_half_in_each_chosen_asset_and_cash_for_a_failed_slot():
    w = mm.top2_weights({k: k in ("gold", "crypto") for k in adv.RISKY_IDS})
    assert w["gold"] == w["crypto"] == 0.5 and w["cash"] == 0.0 and w.sum() == pytest.approx(1.0)
    one = mm.top2_weights({k: k == "gold" for k in adv.RISKY_IDS})
    assert one["gold"] == 0.5 and one["cash"] == 0.5
    assert mm.top2_weights({k: False for k in adv.RISKY_IDS})["cash"] == 1.0


def test_nothing_sees_the_future_equity_up_to_a_day_is_the_same_with_or_without_later_data():
    prices, r = _market()
    cut = 1000
    full = mm.run_all(prices, r)
    part = mm.run_all(prices.iloc[:cut], r.iloc[:cut])
    for sid, sim in part.items():
        pd.testing.assert_series_equal(full[sid]["equity"].loc[:sim["equity"].index[-1]].iloc[:-1], sim["equity"].iloc[:-1], check_names=False)


def test_when_every_asset_is_always_falling_both_rules_sit_in_cash():
    idx = pd.bdate_range("2019-01-01", periods=900)
    r = pd.DataFrame({k: -0.0008 for k in adv.RISKY_IDS}, index=idx)
    r["cash"] = (1 + adv.CASH_RATE) ** (1 / adv.TRADING_DAYS) - 1
    prices = (1 + r[adv.RISKY_IDS]).cumprod() * 100.0
    sims = mm.run_all(prices, r)
    for sid in ("momentum_top2", "momentum_top3_risk_managed"):
        assert sims[sid]["exposure_pct"].iloc[10:].max() == pytest.approx(0.0, abs=1e-9)


def test_the_risk_managed_variant_never_leverages_and_never_exceeds_the_moderate_caps():
    prices, r = _market()
    s = mm.run_all(prices, r)["momentum_top3_risk_managed"]
    caps = adv.PROFILES["moderate"]["caps"]
    assert s["exposure_pct"].max() <= 100.0 + 1e-6
    for entry in s["rebalances"]:
        assert all(entry["weights"][k] <= caps[k] + 1e-9 for k in adv.RISKY_IDS) and entry["weights"].sum() == pytest.approx(1.0)


# --- the whole file and the ledger --------------------------------------------------------------------------------------------

@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"cumulative_hypotheses": 210, "runs": []}))
    monkeypatch.setattr(harness, "LEDGER_PATH", str(path))
    return path


def test_building_the_file_without_registering_leaves_the_ledger_untouched(ledger):
    prices, r = _market()
    payload = mm.build(prices, r, register=False)
    assert json.loads(ledger.read_text())["cumulative_hypotheses"] == 210 and payload["ledger_total"] == 210
    assert [s["id"] for s in payload["strategies"]] == ["momentum_top2", "momentum_top3_risk_managed"]
    json.dumps(payload, allow_nan=False)


def test_registering_counts_the_two_hypotheses_once(ledger):
    prices, r = _market()
    payload = mm.build(prices, r, register=True)
    assert json.loads(ledger.read_text())["cumulative_hypotheses"] == 212 and payload["ledger_total"] == 212
    again = mm.build(prices, r, register=False)
    assert json.loads(ledger.read_text())["cumulative_hypotheses"] == 212 and again["ledger_total"] == 212


def test_each_strategy_carries_both_windows_a_status_and_the_two_benchmarks(ledger):
    prices, r = _market()
    p = mm.build(prices, r)
    s = p["strategies"][0]
    for w in ("full", "in_sample", "out_of_sample"):
        assert {"sharpe", "max_drawdown_pct", "var95_pct", "cvar95_pct"} <= set(s["metrics"][w])
        assert "sharpe" in p["benchmarks"]["static"]["metrics"][w] and "sharpe" in p["benchmarks"]["nifty"]["metrics"][w]
    assert s["harness_status"] in {"UNVALIDATED", "VALIDATED_FAILED", "VALIDATED_CONFIRMED", "OOS_ONLY_SIGNIFICANT"}
    assert s["growth"]["values"][0] == 100.0 and abs(sum(a["weight_pct"] for a in s["held_now"]) - 100) < 0.2
    assert [x["asset_id"] for x in p["signals_now"]] == adv.RISKY_IDS
