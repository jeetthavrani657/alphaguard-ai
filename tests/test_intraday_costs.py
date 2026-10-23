"""
tests/test_intraday_costs.py

research/intraday_costs.py says how much an intraday trade must gain before it earns anything. Each item is checked against a hand calculation, and the properties that must hold
(the flat brokerage fee cap, STT on the sell only, costs growing with size and with slippage) are stated as tests.
"""

import pytest

import intraday_costs as ic


def test_a_one_lakh_buy_matches_a_hand_calculation():
    c = ic.leg_cost(100_000.0, "buy")
    assert c["brokerage"] == pytest.approx(20.0)                                  # 0.03% of 1,00,000 is 30, so the flat Rs 20 is the lower
    assert c["exchange"] == pytest.approx(3.45) and c["sebi"] == pytest.approx(0.10)
    assert c["gst"] == pytest.approx(0.18 * (20.0 + 3.45 + 0.10))
    assert c["stt"] == 0.0 and c["stamp"] == pytest.approx(3.0) and c["slippage"] == pytest.approx(50.0)
    assert c["total"] == pytest.approx(sum(v for k, v in c.items() if k != "total"))


def test_a_one_lakh_sell_pays_stt_and_no_stamp_duty():
    c = ic.leg_cost(100_000.0, "sell")
    assert c["stt"] == pytest.approx(25.0) and c["stamp"] == 0.0


def test_brokerage_is_the_lower_of_the_flat_fee_and_the_percentage():
    assert ic.leg_cost(10_000.0, "buy")["brokerage"] == pytest.approx(3.0)        # 0.03% of 10,000 is below Rs 20
    assert ic.leg_cost(1_000_000.0, "buy")["brokerage"] == pytest.approx(20.0)    # 0.03% of ten lakh would be 300


def test_the_round_trip_is_the_sum_of_its_two_legs():
    rt = ic.round_trip_cost(200_000.0)
    assert rt["total"] == pytest.approx(ic.leg_cost(200_000.0, "buy")["total"] + ic.leg_cost(200_000.0, "sell")["total"])
    assert rt["stt"] == pytest.approx(50.0) and rt["stamp"] == pytest.approx(6.0)


def test_a_one_lakh_round_trip_costs_about_a_fifth_of_a_percent_mostly_slippage():
    rt = ic.round_trip_cost(100_000.0)
    assert 0.17 < rt["pct_of_value"] < 0.21
    assert rt["slippage"] / rt["total"] > 0.5                                       # the part nobody can see on the contract note is the biggest


def test_small_trades_pay_a_higher_percentage_and_big_ones_approach_a_floor():
    pcts = [ic.breakeven_move_pct(v) for v in (5_000.0, 25_000.0, 100_000.0, 1_000_000.0)]
    assert pcts == sorted(pcts, reverse=True) and pcts[0] > pcts[-1] + 0.05
    assert ic.breakeven_move_pct(50_000_000.0) == pytest.approx(0.1 + 0.025 + 2 * 0.00345 + 0.003 + 2 * 0.0001 + 0.18 * (2 * 0.00345 + 2 * 0.0001), abs=0.002)   # the floor in percent


def test_worse_slippage_raises_the_cost_one_for_one_and_zero_slippage_is_the_statutory_floor():
    base, bad = ic.round_trip_cost(100_000.0, 0.0005), ic.round_trip_cost(100_000.0, 0.0015)
    assert bad["total"] - base["total"] == pytest.approx(2 * 100_000.0 * 0.0010)
    assert ic.round_trip_cost(100_000.0, 0.0)["slippage"] == 0.0 and ic.round_trip_cost(100_000.0, 0.0)["pct_of_value"] < 0.1


def test_bad_input_is_refused_and_a_zero_order_has_no_percentage():
    with pytest.raises(ValueError):
        ic.leg_cost(1000.0, "short")
    with pytest.raises(ValueError):
        ic.leg_cost(-1.0, "buy")
    assert ic.round_trip_cost(0.0)["total"] == pytest.approx(0.0 + 0.0)
    import math
    assert math.isnan(ic.round_trip_cost(0.0)["pct_of_value"])
