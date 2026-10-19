"""
tests/test_multiasset_trend.py

research/multiasset_trend.py holds two multi-asset trend rules and a no-timing benchmark (MULTIASSET_TREND.md). These tests
use made-up prices (no network) and check what makes a timing rule trustworthy: it uses only the past, an asset in a downtrend
is really replaced by cash, the risk-managed variant keeps the advisory's caps, the benchmark is the same rule with the
filter switched off, and registering hypotheses in the ledger happens only when asked.
"""

import json

import numpy as np
import pandas as pd
import pytest

import advisory as adv
import harness
import multiasset_trend as mt


def _market(n=1700, seed=11, drift=None, start="2019-01-01"):
    """Returns for every asset plus cash, and the matching prices (price on day d = 100 x the product of returns up to d)."""
    rng = np.random.default_rng(seed)
    vols = {"equity_large": 0.010, "equity_mid": 0.013, "intl_equity": 0.012, "gold": 0.008, "debt": 0.004, "crypto": 0.035}
    idx = pd.bdate_range(start, periods=n)
    r = pd.DataFrame({k: rng.normal(0.0003 if drift is None else drift, v, n) for k, v in vols.items()}, index=idx)
    r["cash"] = (1 + adv.CASH_RATE) ** (1 / adv.TRADING_DAYS) - 1
    prices = (1 + r[adv.RISKY_IDS]).cumprod() * 100.0
    return prices, r


def test_the_trend_flag_uses_only_prices_up_to_the_date():
    prices, _ = _market()
    date = prices.index[600]
    before = mt.uptrend_flags(prices, date)
    scrambled = prices.copy()
    scrambled.iloc[601:] = scrambled.iloc[601:] * 3.0                       # change everything after the date
    assert mt.uptrend_flags(scrambled, date) == before
    assert mt.uptrend_flags(prices, prices.index[mt.TREND_DAYS - 2]) == {k: False for k in adv.RISKY_IDS}   # too little history: no trend, so no position


def test_an_asset_is_in_an_uptrend_exactly_when_its_close_is_above_its_own_210_day_average():
    idx = pd.bdate_range("2020-01-01", periods=300)
    prices = pd.DataFrame({k: 100.0 for k in adv.RISKY_IDS}, index=idx)
    prices["gold"] = np.linspace(100, 200, 300)                              # rising: last close above its average
    prices["crypto"] = np.linspace(200, 100, 300)                            # falling: below
    flags = mt.uptrend_flags(prices, idx[-1])
    assert flags["gold"] is True and flags["crypto"] is False and flags["debt"] is False    # flat: equal to its average is not "above"


def test_equal_slots_hold_one_sixth_per_uptrend_asset_and_the_rest_in_cash():
    w = mt.equal_weight_slots({k: k in ("gold", "debt") for k in adv.RISKY_IDS})
    assert w["gold"] == w["debt"] == pytest.approx(1 / 6) and w["equity_large"] == 0
    assert w["cash"] == pytest.approx(1 - 2 / 6) and w.sum() == pytest.approx(1.0)
    assert mt.equal_weight_slots({k: False for k in adv.RISKY_IDS})["cash"] == pytest.approx(1.0)


def test_the_risk_managed_variant_gives_a_downtrend_asset_nothing_and_keeps_the_advisorys_caps_and_no_leverage():
    _, r = _market()
    window = r.iloc[600:663]
    flags = {k: k != "crypto" for k in adv.RISKY_IDS}
    w = mt.risk_managed_weights(flags, window, guard_on=False)
    caps = adv.PROFILES["moderate"]["caps"]
    assert w["crypto"] == 0 and w.sum() == pytest.approx(1.0) and (w >= -1e-12).all()
    assert all(w[k] <= caps[k] + 1e-9 for k in adv.RISKY_IDS)
    none = mt.risk_managed_weights({k: False for k in adv.RISKY_IDS}, window, guard_on=False)
    assert none["cash"] == pytest.approx(1.0)                                # nothing in an uptrend: all cash


def test_nothing_sees_the_future_equity_up_to_a_day_is_the_same_with_or_without_later_data():
    prices, r = _market()
    cut = 900
    full = mt.run_all(prices, r)
    part = mt.run_all(prices.iloc[:cut], r.iloc[:cut])
    for sid, sim in part.items():
        pd.testing.assert_series_equal(full[sid]["equity"].loc[:sim["equity"].index[-1]].iloc[:-1], sim["equity"].iloc[:-1], check_names=False)


def test_with_every_asset_always_rising_the_equal_weight_trend_rule_is_the_static_benchmark():
    idx = pd.bdate_range("2019-01-01", periods=900)
    r = pd.DataFrame({k: 0.0008 for k in adv.RISKY_IDS}, index=idx)          # a steady rise in every asset
    r["cash"] = (1 + adv.CASH_RATE) ** (1 / adv.TRADING_DAYS) - 1
    prices = (1 + r[adv.RISKY_IDS]).cumprod() * 100.0
    sims = mt.run_all(prices, r)
    pd.testing.assert_series_equal(sims["trend_equal_weight"]["equity"], sims[mt.BENCH_STATIC_ID]["equity"], check_names=False)


def test_with_every_asset_always_falling_the_trend_rules_sit_in_cash_and_earn_only_the_cash_rate():
    idx = pd.bdate_range("2019-01-01", periods=900)
    r = pd.DataFrame({k: -0.0008 for k in adv.RISKY_IDS}, index=idx)
    r["cash"] = (1 + adv.CASH_RATE) ** (1 / adv.TRADING_DAYS) - 1
    prices = (1 + r[adv.RISKY_IDS]).cumprod() * 100.0
    sims = mt.run_all(prices, r)
    for sid in ("trend_equal_weight", "trend_risk_managed"):
        exposure = sims[sid]["exposure_pct"]
        assert exposure.iloc[10:].max() == pytest.approx(0.0, abs=1e-9)      # all in cash once the first decision has been carried out
    assert sims["trend_risk_managed"]["equity"].iloc[-1] > sims[mt.BENCH_STATIC_ID]["equity"].iloc[-1]   # cash beat a falling market


# --- the whole file and the ledger --------------------------------------------------------------------------------------------

@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"cumulative_hypotheses": 208, "runs": []}))
    monkeypatch.setattr(harness, "LEDGER_PATH", str(path))
    return path


def test_building_the_file_without_registering_leaves_the_ledger_untouched(ledger):
    prices, r = _market()
    payload = mt.build(prices, r, register=False)
    assert json.loads(ledger.read_text())["cumulative_hypotheses"] == 208 and payload["ledger_total"] == 208
    assert [s["id"] for s in payload["strategies"]] == ["trend_equal_weight", "trend_risk_managed"]
    json.dumps(payload, allow_nan=False)                                    # valid JSON: no NaN anywhere


def test_registering_counts_the_two_hypotheses_once(ledger):
    prices, r = _market()
    payload = mt.build(prices, r, register=True)
    assert json.loads(ledger.read_text())["cumulative_hypotheses"] == 210 and payload["ledger_total"] == 210
    again = mt.build(prices, r, register=False)
    assert json.loads(ledger.read_text())["cumulative_hypotheses"] == 210 and again["ledger_total"] == 210


def test_each_strategy_carries_both_windows_a_status_and_the_two_benchmarks(ledger):
    prices, r = _market()
    p = mt.build(prices, r)
    s = p["strategies"][1]
    for w in ("full", "in_sample", "out_of_sample"):
        assert {"sharpe", "max_drawdown_pct", "var95_pct", "cvar95_pct"} <= set(s["metrics"][w])
        assert "sharpe" in p["benchmarks"]["static"]["metrics"][w] and "sharpe" in p["benchmarks"]["nifty"]["metrics"][w]
    assert s["harness_status"] in {"UNVALIDATED", "VALIDATED_FAILED", "VALIDATED_CONFIRMED", "OOS_ONLY_SIGNIFICANT"}
    assert s["growth"]["values"][0] == 100.0 and len(s["growth"]["dates"]) == len(s["exposure_pct"]["dates"])
    assert abs(sum(a["weight_pct"] for a in s["held_now"]) - 100) < 0.2
    assert [x["asset_id"] for x in p["signals_now"]] == adv.RISKY_IDS and {e["id"] for e in p["stress"]} >= {"covid", "rates_2022"}
