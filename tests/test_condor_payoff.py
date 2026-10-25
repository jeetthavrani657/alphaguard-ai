"""
tests/test_condor_payoff.py

research/condor_payoff.py describes how the two frozen condor rules really paid. Each piece is checked by hand: the payoff of a condor at expiry (a flat top between the shorts, a flat
floor beyond the wings), the four real trades picked out of a list, the breakevens, the yearly implied-against-realised table, and that every trade is in the file exactly once.
"""

import pandas as pd
import pytest

import condor_payoff as cp


def trade(**over):
    t = {"long_put": 100.0, "short_put": 110.0, "short_call": 130.0, "long_call": 140.0, "credit_per_unit": 2.0, "units": 10.0}
    t.update(over)
    return t


def test_a_condor_pays_its_credit_between_the_shorts_and_loses_the_width_less_the_credit_beyond_the_wings():
    pts = cp.payoff_points(trade())
    assert [p["level"] for p in pts] == [90.0, 100.0, 110.0, 130.0, 140.0, 150.0]                    # the four strikes and one wing's width beyond each end
    assert [p["pnl"] for p in pts] == [-80.0, -80.0, 20.0, 20.0, -80.0, -80.0]                      # credit 2 x 10 units = 20 at best; (10 wide - 2) x 10 = 80 at worst
    assert max(p["pnl"] for p in pts) == 2.0 * 10 and min(p["pnl"] for p in pts) == -(10.0 - 2.0) * 10


def test_the_payoff_between_a_short_strike_and_its_wing_falls_in_a_straight_line():
    # per unit at expiry between the short put (110) and the long put (100): credit - (110 - level); at 105 that is 2 - 5 = -3, so -30 for 10 units
    s = 105.0
    per_unit = 2.0 + max(100 - s, 0) - max(110 - s, 0)
    assert per_unit * 10 == -30.0
    a, b = cp.payoff_points(trade())[1], cp.payoff_points(trade())[2]                                # (100, -80) to (110, +20): the midpoint is (105, -30)
    assert (a["pnl"] + b["pnl"]) / 2 == -30.0


def test_unequal_wings_extend_the_curve_by_the_wider_one():
    pts = cp.payoff_points(trade(long_call=150.0))                                                    # put wing 10 wide, call wing 20 wide: the ends move out by 20
    assert pts[0]["level"] == 80.0 and pts[-1]["level"] == 170.0
    assert pts[-1]["pnl"] == -180.0           # at 170 per unit: credit 2 - (170 - 130) short call + (170 - 150) long call = -18, the put side is flat; so -180 for 10 units (the wider wing's width less the credit)


def cycle_log():
    rows = [("2024-01-02", "2024-01-25", -50.0), ("2024-02-01", "2024-02-22", 10.0), ("2024-03-01", "2024-03-28", 20.0), ("2024-04-01", "2024-04-25", 30.0), ("2024-05-02", "2024-05-30", 100.0)]
    return pd.DataFrame([{"entry_day": pd.Timestamp(e), "expiry": pd.Timestamp(x), "lots": 2, "units": 10.0, "long_put": 100.0, "short_put": 110.0, "short_call": 130.0, "long_call": 140.0,
                          "credit_per_unit": 2.0, "width": 10.0, "final_level": 120.0 + i, "gross_pnl": pnl + 5, "net_pnl": pnl, "entry_cost": 3.0, "exit_cost": 2.0}
                         for i, (e, x, pnl) in enumerate(rows)])


def test_the_four_picked_trades_are_the_worst_the_best_the_middle_one_and_the_latest():
    picks = {t["label"]: t for t in cp.pick_trades(cycle_log())}
    assert list(picks) == ["worst", "best", "typical", "latest"]
    assert picks["worst"]["net_pnl"] == -50.0 and picks["best"]["net_pnl"] == 100.0
    assert picks["typical"]["net_pnl"] == 20.0 and picks["typical"]["expiry"] == "2024-03-28"       # the median of -50, 10, 20, 30, 100 is 20
    assert picks["latest"]["entry_day"] == "2024-05-02"


def test_a_picked_trade_carries_its_breakevens_its_best_and_worst_case_and_its_curve():
    t = {t["label"]: t for t in cp.pick_trades(cycle_log())}["best"]
    assert t["breakeven_low"] == 108.0 and t["breakeven_high"] == 132.0                               # short put - credit, short call + credit
    assert t["max_profit"] == 20.0 and t["max_loss"] == 80.0                                          # 2 x 10; (10 - 2) x 10
    assert t["payoff"] == cp.payoff_points(t) and t["lots"] == 2


def test_an_empty_cycle_log_picks_nothing():
    assert cp.pick_trades(cycle_log().iloc[0:0]) == []


def test_every_trade_is_one_dot_in_expiry_order_with_its_result_after_costs():
    shuffled = cycle_log().sample(frac=1.0, random_state=1)
    dots = cp.cycle_points(shuffled)
    assert [d["expiry"] for d in dots] == ["2024-01-25", "2024-02-22", "2024-03-28", "2024-04-25", "2024-05-30"]
    assert [d["net_pnl"] for d in dots] == [-50.0, 10.0, 20.0, 30.0, 100.0] and dots[0]["short_put"] == 110.0


def test_the_yearly_table_averages_each_year_and_counts_the_days_implied_was_above_realised():
    frame = pd.DataFrame({"date": ["2022-01-03", "2022-01-04", "2022-01-05", "2023-01-02"],
                          "implied_30d": [0.20, 0.22, 0.18, 0.15], "realised_30d": [0.16, 0.20, 0.20, 0.145], "premium": [0.04, 0.02, -0.02, 0.005]})
    y = {r["year"]: r for r in cp.yearly_vol(frame)}
    assert y[2022]["days"] == 3 and y[2022]["implied_pct"] == pytest.approx(20.0) and y[2022]["realised_pct"] == pytest.approx(18.6667, abs=1e-3)
    assert y[2022]["premium_pct"] == pytest.approx(1.3333, abs=1e-3) and y[2022]["share_implied_above_pct"] == pytest.approx(66.6667, abs=1e-3)
    assert y[2022]["worst_premium_pct"] == pytest.approx(-2.0)
    assert y[2023]["days"] == 1 and y[2023]["premium_pct"] == pytest.approx(0.5) and y[2023]["share_implied_above_pct"] == 100.0


def test_the_volatility_line_keeps_every_nth_day_and_days_without_a_following_month_are_left_out():
    frame = pd.DataFrame({"date": [f"2024-01-{d:02d}" for d in range(1, 11)], "implied_30d": [0.2] * 10, "realised_30d": [0.1] * 9 + [float("nan")], "premium": [0.1] * 9 + [float("nan")]})
    built = cp.build({}, frame, "2024-01-10")
    assert built["volatility"]["years"][0]["days"] == 9                                              # the tenth day has no realised volatility yet
    assert [p["date"] for p in built["volatility"]["series"]] == ["2024-01-01", "2024-01-06"]        # every 5th of the nine kept days
    assert built["data_through"] == "2024-01-10"


def test_the_written_file_has_every_trade_once_and_matches_the_registered_results_when_the_real_files_exist():
    import json, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mine, theirs = (os.path.join(root, "reports", "output", n) for n in ("condor_payoff_latest.json", "options_condors_latest.json"))
    if not (os.path.exists(mine) and os.path.exists(theirs)):
        pytest.skip("the real result files have not been generated")
    p, o = json.load(open(mine, encoding="utf-8")), json.load(open(theirs, encoding="utf-8"))
    for rid, r in o["rules"].items():
        n = r["cycles_in_sample"].get("n_cycles", 0) + r["cycles_out_of_sample"].get("n_cycles", 0)
        cycles = p["rules"][rid]["cycles"]
        assert len(cycles) == n, f"{rid}: the payoff file has {len(cycles)} trades, the registered result {n}"
        total = r["cycles_in_sample"].get("total_net_pnl", 0.0) + r["cycles_out_of_sample"].get("total_net_pnl", 0.0)
        assert sum(c["net_pnl"] for c in cycles) == pytest.approx(total, abs=1.0), f"{rid}: the trades do not add up to the registered profit"
