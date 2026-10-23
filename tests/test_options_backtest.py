"""
tests/test_options_backtest.py

The condor engine frozen in OPTIONS_IDEAS.md, checked on a synthetic option market built from Black-76 with a flat volatility, so that the right answer to every question
(which strikes, what the credit is, what a crash costs) can be worked out independently. Each test also states what would be wrong if it failed.
"""

import math

import numpy as np
import pandas as pd
import pytest

import options_backtest as ob
import options_chain as ch
import options_costs as oc
import options_math as om

RATE, SIGMA = 0.06, 0.15
DAYS = list(pd.bdate_range("2026-01-05", "2026-06-30"))                       # weekdays; no holidays, which the engine does not need
MONTHLY = [pd.Timestamp(d) for d in ("2026-02-26", "2026-03-26", "2026-04-30", "2026-05-28", "2026-06-25")]      # the last Thursday-ish of each month


def spot_path(overrides=None):
    """A calm market near 22,000. `overrides` maps dates to a spot (a crash, say)."""
    out = {d: 22000.0 + 40.0 * math.sin(i / 7.0) for i, d in enumerate(DAYS)}
    out.update({pd.Timestamp(k): v for k, v in (overrides or {}).items()})
    return out


def make_table(spots, expiries, sigma=SIGMA, horizon_days=40, step=50.0, skip=None, zero_price=None):
    """Settlement prices for every day and expiry still alive, strikes every `step` points. `skip` drops (date, strike, kind); `zero_price` sets some to 0."""
    rows = []
    for d in DAYS:
        for e in expiries:
            if d > e or (e - d).days > horizon_days:
                continue
            t = (e - d).days / 365.0
            fwd = spots[d] * math.exp(RATE * t)
            for k in np.arange(spots[d] - 3500, spots[d] + 3500, step):
                k = round(k / step) * step
                for kind in ("CE", "PE"):
                    if skip and (d, k, kind) in skip:
                        continue
                    # on the expiry day the exchange's files carry the underlying's FINAL SETTLEMENT LEVEL as the settlement value of every contract (checked on all 258 real expiries)
                    px = om.price(fwd, k, t, sigma, RATE, kind == "CE") if t > 0 else spots[d]
                    if zero_price and (d, k, kind) in zero_price:
                        px = 0.0
                    rows.append({"date": d, "instrument": "OPTIDX", "symbol": "NIFTY", "expiry": e, "strike": float(k), "option_type": kind, "settle": px, "volume": 1000})
    return pd.DataFrame(rows).drop_duplicates(["date", "expiry", "strike", "option_type"])


@pytest.fixture(scope="module")
def calm():
    table = make_table(spot_path(), MONTHLY)
    return ob.index_table(table), table


def run(book, **kw):
    kw.setdefault("initial", ob.INITIAL)
    return ob.run_condor_backtest(book, "monthly", cash_rate=kw.pop("cash_rate", 0.0), **kw)


# ---- calendar and timing ------------------------------------------------------------------------------------------------------------------

def test_a_cycle_is_decided_the_day_after_the_previous_expiry_and_carried_out_the_day_after_that(calm):
    book, _ = calm
    cyc = ob.cycles(book, "monthly")
    first = cyc[0]
    assert first["expiry"] == pd.Timestamp("2026-03-26")
    assert first["decision_day"] == pd.Timestamp("2026-02-27") and first["entry_day"] == pd.Timestamp("2026-03-02")      # Friday the 27th, then Monday
    assert all(c["decision_day"] < c["entry_day"] < c["expiry"] for c in cyc) and len(cyc) == 4 and cyc[-1]["expiry"] == pd.Timestamp("2026-06-25")        # five expiries make four cycles


def test_only_cycles_that_have_already_expired_in_the_data_are_traded(calm):
    book, table = calm
    short = ob.index_table(table[table["date"] <= pd.Timestamp("2026-05-20")])
    assert [c["expiry"] for c in ob.cycles(short, "monthly")] == [pd.Timestamp("2026-03-26"), pd.Timestamp("2026-04-30")]


def test_the_fallback_lot_schedule_follows_the_change_dates_seen_in_the_exchanges_files():
    assert [ob.lot_size(d) for d in ("2024-04-25", "2024-04-26", "2025-01-30", "2025-01-31", "2025-12-30", "2025-12-31")] == [50, 25, 25, 75, 75, 65]


def test_a_contracts_own_lot_size_from_the_file_wins_over_the_schedule_and_the_schedule_is_the_fallback(calm):
    book, table = calm
    cyc = ob.cycles(book, "monthly")[0]
    assert ob.contract_lot(book, cyc["entry_day"], cyc["expiry"]) == ob.lot_size(cyc["entry_day"])               # no lot_size column: the schedule
    t = table.copy()
    t["lot_size"] = 0
    t.loc[t["expiry"] == cyc["expiry"], "lot_size"] = 33                                                           # a made-up lot for this expiry only
    book2 = ob.index_table(t)
    assert ob.contract_lot(book2, cyc["entry_day"], cyc["expiry"]) == 33
    other = ob.cycles(book2, "monthly")[1]
    assert ob.contract_lot(book2, other["entry_day"], other["expiry"]) == ob.lot_size(other["entry_day"])         # an expiry whose rows carry none: the schedule again
    r = run(book2)
    assert r["cycles"].iloc[0]["lot_size"] == 33 and r["cycles"].iloc[0]["units"] == r["cycles"].iloc[0]["lots"] * 33


# ---- choosing the strikes -------------------------------------------------------------------------------------------------------------------

def _expected_strikes(spot, t, step=50.0, short=0.16, wing=0.05):
    """The four strikes worked out independently with numpy from the same flat-volatility model."""
    fwd = spot * math.exp(RATE * t)
    ks = np.array([round(k / step) * step for k in np.arange(spot - 3500, spot + 3500, step)])
    call_delta = np.array([om.delta(fwd, k, t, SIGMA, RATE, True) for k in ks])
    put_delta = call_delta - math.exp(-RATE * t)
    return (ks[np.argmin(np.abs(put_delta + wing))], ks[np.argmin(np.abs(put_delta + short))], ks[np.argmin(np.abs(call_delta - short))], ks[np.argmin(np.abs(call_delta - wing))])


def test_the_condor_strikes_are_the_16_and_5_delta_ones_found_independently(calm):
    book, _ = calm
    cyc = ob.cycles(book, "monthly")[0]
    legs, why = ob.plan_cycle(book, cyc, 0.16, 0.05, RATE)
    assert why == "" and [l["strike"] for l in legs] == list(_expected_strikes(spot_path()[cyc["decision_day"]], (cyc["expiry"] - cyc["decision_day"]).days / 365.0))
    assert [(l["kind"], l["sign"]) for l in legs] == [("PE", 1), ("PE", -1), ("CE", -1), ("CE", 1)]                # long put, short put, short call, long call


def test_the_strikes_come_only_from_the_decision_day_so_later_prices_cannot_change_them(calm):
    book, table = calm
    cyc = ob.cycles(book, "monthly")[0]
    base, _ = ob.plan_cycle(book, cyc, 0.16, 0.05, RATE)
    changed = table.copy()
    later = changed["date"] > cyc["decision_day"]
    changed.loc[later, "settle"] = changed.loc[later, "settle"] * 3.0 + 7.0                                  # wreck every price after the decision day
    other, _ = ob.plan_cycle(ob.index_table(changed), cyc, 0.16, 0.05, RATE)
    assert [l["strike"] for l in other] == [l["strike"] for l in base]                                        # same strikes; only the entry prices differ
    assert [l["entry_price"] for l in other] != [l["entry_price"] for l in base]


def test_a_wing_that_lands_on_its_short_strike_is_moved_one_strike_out():
    ks = np.arange(21000.0, 22900.0, 100.0)                                                                   # 19 strikes
    put_delta = -np.linspace(0.02, 0.98, len(ks))                                                               # |delta| grows with the strike
    table = pd.DataFrame({"iv": 0.15, "call_delta": put_delta + 1.0, "put_delta": put_delta, "call": 10.0, "put": 10.0}, index=ks)
    picked = ch.pick_condor(table, short_delta=0.05, wing_delta=0.05)                                           # the same delta for short and wing forces a collision
    assert picked == {"long_put": ks[0], "short_put": ks[1], "short_call": ks[-2], "long_call": ks[-1]}


def test_a_chain_too_thin_to_build_a_condor_gives_none():
    table = pd.DataFrame({"iv": [0.15, 0.15], "call_delta": [0.6, 0.4], "put_delta": [-0.4, -0.6], "call": [1.0, 1.0], "put": [1.0, 1.0]}, index=[22000.0, 22100.0])
    assert ch.pick_condor(table) is None


# ---- the final level and the money ------------------------------------------------------------------------------------------------------------------

def test_the_final_level_is_the_settlement_value_every_contract_carries_on_the_expiry_day():
    exp = pd.Timestamp("2026-03-26")
    table = make_table(spot_path({"2026-03-26": 21500.0}), MONTHLY)
    on_day = table[(table["date"] == exp) & (table["expiry"] == exp)]
    assert on_day["settle"].nunique() == 1 and on_day["settle"].iloc[0] == 21500.0                            # the real files' convention, which the synthetic market now follows
    assert ob.final_level_with_source(ob.index_table(table), exp) == (21500.0, "settlement")
    odd = on_day.index[:6]                                                                                      # a few rows (< 5%) that disagree do not change the answer
    t2 = table.copy()
    t2.loc[odd, "settle"] = 0.0
    assert ob.final_level_with_source(ob.index_table(t2), exp) == (21500.0, "settlement")


def test_when_the_file_holds_intrinsic_values_instead_the_recorded_underlying_and_then_parity_recover_the_level():
    exp = pd.Timestamp("2026-03-26")
    table = make_table(spot_path({"2026-03-26": 21500.0}), MONTHLY)
    day = (table["date"] == exp) & (table["expiry"] == exp)
    t = table.copy()
    t.loc[day, "settle"] = np.where(t.loc[day, "option_type"] == "CE", np.maximum(21500.0 - t.loc[day, "strike"], 0), np.maximum(t.loc[day, "strike"] - 21500.0, 0))   # intrinsic
    t["underlying"] = float("nan")
    assert ob.final_level_with_source(ob.index_table(t), exp)[1] == "parity" and ob.final_level(ob.index_table(t), exp) == pytest.approx(21500.0, abs=1e-6)
    t.loc[day, "underlying"] = 21500.0
    assert ob.final_level_with_source(ob.index_table(t), exp) == (21500.0, "underlying")


def test_an_expiry_whose_own_day_has_no_rows_uses_the_last_earlier_day_and_says_how_approximate_that_is():
    exp = pd.Timestamp("2026-03-26")
    table = make_table(spot_path(), MONTHLY)
    gone = table[~((table["date"] == exp) & (table["expiry"] == exp))]
    level, source = ob.final_level_with_source(ob.index_table(gone), exp)
    assert source == "parity" and level == pytest.approx(spot_path()[pd.Timestamp("2026-03-25")], rel=0.01)       # the day before, by parity: close, and labelled as approximate


def test_in_a_calm_market_every_leg_expires_worthless_and_the_account_gains_the_credit_less_costs(calm):
    book, _ = calm
    r = run(book)
    c = r["cycles"]
    assert len(c) == 4 and r["skipped"] == []
    assert (c["gross_pnl"] > 0).all() and np.allclose(c["gross_pnl"], c["credit_per_unit"] * c["units"])           # every leg worthless: the whole credit is kept
    assert (c["net_pnl"] > 0).all() and (c["net_pnl"] < c["gross_pnl"]).all()                                        # and costs are real


def test_the_accounts_change_equals_the_sum_of_the_trades_when_cash_earns_nothing(calm):
    book, _ = calm
    r = run(book)
    assert r["equity"].iloc[-1] - ob.INITIAL == pytest.approx(r["cycles"]["net_pnl"].sum(), abs=1e-6)


def test_a_crash_through_the_put_wing_loses_that_sides_width_less_the_credit_and_never_more_than_the_worst_case_used_for_sizing(calm):
    table = make_table(spot_path({"2026-03-26": 18500.0}), MONTHLY)                                                  # a 16% fall on expiry day
    r = run(ob.index_table(table))
    first = r["cycles"].iloc[0]
    assert first["final_level"] == pytest.approx(18500.0, abs=1e-6)
    put_width = first["short_put"] - first["long_put"]
    assert first["gross_pnl"] == pytest.approx(-(put_width - first["credit_per_unit"]) * first["units"], rel=1e-9)
    assert first["gross_pnl"] >= -first["max_loss_per_unit"] * first["units"] - 1e-6                               # the sizing used the WIDER wing, so this is never exceeded
    assert first["exit_cost"] > 0                                                                                    # the in-the-money long put pays exercise STT
    assert first["net_pnl"] < first["gross_pnl"]
    assert r["equity"].min() > 0                                                                                     # 10% of the account was at risk, not all of it


def test_a_rally_through_the_call_wing_is_capped_the_same_way(calm):
    table = make_table(spot_path({"2026-03-26": 25800.0}), MONTHLY)
    first = run(ob.index_table(table))["cycles"].iloc[0]
    call_width = first["long_call"] - first["short_call"]
    assert first["gross_pnl"] == pytest.approx(-(call_width - first["credit_per_unit"]) * first["units"], rel=1e-9)
    assert first["gross_pnl"] >= -first["max_loss_per_unit"] * first["units"] - 1e-6


def test_the_entry_cost_is_the_sum_of_the_four_orders_under_the_cost_model(calm):
    book, _ = calm
    first = run(book)["cycles"].iloc[0]
    day, units = pd.Timestamp("2026-03-02"), first["units"]
    legs, _ = ob.plan_cycle(book, ob.cycles(book, "monthly")[0], 0.16, 0.05, RATE)
    expected = sum(oc.leg_cost(l["entry_price"] * units, units, "buy" if l["sign"] > 0 else "sell", day)["total"] for l in legs)
    assert first["entry_cost"] == pytest.approx(expected)


def test_position_size_is_whole_lots_with_the_worst_case_inside_the_risk_budget_and_at_least_one(calm):
    book, _ = calm
    big = run(book, initial=50_000_000.0)["cycles"].iloc[0]
    assert big["lots"] > 1 and big["lots"] * big["lot_size"] * big["max_loss_per_unit"] <= 0.10 * 50_000_000.0
    assert (big["lots"] + 1) * big["lot_size"] * big["max_loss_per_unit"] > 0.10 * 50_000_000.0       # the largest whole number that fits
    tiny = run(book, initial=50_000.0)["cycles"].iloc[0]
    assert tiny["lots"] == 1                                                                                          # never fewer than one lot, even if that exceeds the 10% budget
    assert tiny["max_loss_per_unit"] * tiny["units"] > 0.10 * 50_000.0 and tiny["max_loss_per_unit"] * tiny["units"] <= 50_000.0


def test_a_cycle_whose_single_lot_could_lose_more_than_the_whole_account_is_skipped(calm):
    book, _ = calm
    r = run(book, initial=2_000.0)                                                                                   # one lot's worst case is far above Rs 2,000
    assert r["cycles"].empty or len(r["cycles"]) == 0
    assert len(r["skipped"]) == 4 and all("more than the whole account" in why for _, _, why in r["skipped"])
    assert r["equity"].iloc[-1] == pytest.approx(2_000.0)                                                             # nothing traded: the cash is untouched (interest is 0 here)


def test_the_account_can_never_go_below_zero_however_many_cycles_lose(calm):
    """A market that crashes through the put wing every cycle: the account shrinks, and the rule must stop before a forced lot could risk more than is left."""
    spots = spot_path({d: 17000.0 for d in ("2026-02-26", "2026-03-26", "2026-04-30", "2026-05-28", "2026-06-25")})
    r = run(ob.index_table(make_table(spots, MONTHLY)), initial=60_000.0)
    assert r["equity"].min() > 0


def test_worse_slippage_lowers_every_cycles_profit(calm):
    book, _ = calm
    base, bad = run(book)["cycles"], run(book, slippage_pct=0.02)["cycles"]
    assert (bad["net_pnl"] < base["net_pnl"]).all() and np.allclose(bad["gross_pnl"], base["gross_pnl"])


def test_cash_interest_accrues_every_day_on_the_whole_account(calm):
    book, _ = calm
    with_interest = ob.run_condor_backtest(book, "monthly", initial=ob.INITIAL, cash_rate=0.06)
    without = run(book)
    first = with_interest["equity"].index[0]
    daily = 1.06 ** (1 / 252) - 1
    assert with_interest["equity"].loc[first] - without["equity"].loc[first] == pytest.approx(ob.INITIAL * daily, rel=1e-6)    # one day's interest on the starting money
    assert with_interest["equity"].iloc[-1] > without["equity"].iloc[-1] + 0.01 * ob.INITIAL                                    # and months of it by the end
    gap_day = pd.Timestamp("2026-03-27")                                                                                         # between the first expiry and the next entry: flat in cash
    assert with_interest["equity"].loc[gap_day] > with_interest["equity"].shift(1).loc[gap_day]


# ---- missing data ---------------------------------------------------------------------------------------------------------------------------------------

def test_a_cycle_whose_entry_day_lacks_a_leg_price_is_skipped_with_the_reason_and_nothing_is_traded(calm):
    book, table = calm
    cyc = ob.cycles(book, "monthly")[0]
    legs, _ = ob.plan_cycle(book, cyc, 0.16, 0.05, RATE)
    skip = {(cyc["entry_day"], legs[1]["strike"], "PE")}
    book2 = ob.index_table(make_table(spot_path(), MONTHLY, skip=skip))
    r = run(book2)
    assert len(r["cycles"]) == 3 and r["skipped"][0][1] == cyc["expiry"] and "no price for the short_put" in r["skipped"][0][2]


def test_a_leg_with_no_price_on_a_day_keeps_its_last_price_exactly(calm):
    """
    Two markets that differ in one thing only: on one day the short put's price is the same as the day before (A), or is printed as 0 (B). If the engine carries the
    last price forward, the account in B is IDENTICAL to A on every day. If it accepted the zero, B would jump on that day.
    """
    book, table = calm
    cyc = ob.cycles(book, "monthly")[0]
    legs, _ = ob.plan_cycle(book, cyc, 0.16, 0.05, RATE)
    strike = legs[1]["strike"]
    mid = [d for d in DAYS if cyc["entry_day"] < d < cyc["expiry"]][5]
    prev = [d for d in DAYS if d < mid][-1]
    prev_price = float(table[(table["date"] == prev) & (table["expiry"] == cyc["expiry"]) & (table["strike"] == strike) & (table["option_type"] == "PE")]["settle"].iloc[0])

    def variant(price_on_mid):
        t = table.copy()
        sel = (t["date"] == mid) & (t["expiry"] == cyc["expiry"]) & (t["strike"] == strike) & (t["option_type"] == "PE")
        t.loc[sel, "settle"] = price_on_mid
        return run(ob.index_table(t))
    a, b = variant(prev_price), variant(0.0)
    assert (a["equity"] - b["equity"]).abs().max() < 1e-9
    assert a["cycles"]["gross_pnl"].tolist() == pytest.approx(b["cycles"]["gross_pnl"].tolist())


def test_the_account_is_marked_to_market_with_the_right_sign_in_the_middle_of_a_cycle(calm):
    """Equity = starting money - costs + units x (credit received + the position's value, which is negative for a short condor). Time decay in a calm market must therefore ADD to it."""
    book, table = calm
    cyc = ob.cycles(book, "monthly")[0]
    r = run(book)
    first = r["cycles"].iloc[0]
    legs = [("PE", first["long_put"], +1), ("PE", first["short_put"], -1), ("CE", first["short_call"], -1), ("CE", first["long_call"], +1)]
    mid = [d for d in DAYS if cyc["entry_day"] < d < cyc["expiry"]][10]
    px = lambda kind, k: float(table[(table["date"] == mid) & (table["expiry"] == cyc["expiry"]) & (table["strike"] == k) & (table["option_type"] == kind)]["settle"].iloc[0])
    position_value = sum(sign * px(kind, k) for kind, k, sign in legs)                                               # longs count +, shorts -: a net short condor is NEGATIVE
    expected = ob.INITIAL - first["entry_cost"] + first["units"] * (first["credit_per_unit"] + position_value)     # credit kept, less what the open position is now worth against us
    assert r["equity"].loc[mid] == pytest.approx(expected, rel=1e-12)
    assert r["equity"].loc[mid] > r["equity"].loc[cyc["entry_day"]]                                                  # a calm market: the premium decays in the seller's favour


def test_no_cycles_in_the_data_is_an_error_not_an_empty_result():
    with pytest.raises(ValueError, match="no cycles"):
        ob.run_condor_backtest({(pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-29")): pd.DataFrame()}, "monthly")
    with pytest.raises(ValueError, match="monthly"):
        ob.expiries({}, "daily")


# ---- weekly cycles use the same machinery -------------------------------------------------------------------------------------------------------------------

def test_weekly_cycles_are_decided_and_traded_around_each_weekly_expiry():
    weeklies = [pd.Timestamp(d) for d in pd.date_range("2026-02-05", "2026-04-30", freq="7D")]                         # Thursdays
    table = make_table(spot_path(), weeklies, horizon_days=16)
    book = ob.index_table(table)
    r = ob.run_condor_backtest(book, "weekly", initial=ob.INITIAL, cash_rate=0.0)
    cyc = ob.cycles(book, "weekly")
    assert len(cyc) == len(weeklies) - 1 and len(r["cycles"]) == len(cyc) and r["skipped"] == []
    assert all((c["expiry"] - c["entry_day"]).days <= 7 for c in cyc)
    assert r["equity"].iloc[-1] - ob.INITIAL == pytest.approx(r["cycles"]["net_pnl"].sum(), abs=1e-6)
