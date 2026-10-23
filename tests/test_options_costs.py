"""
tests/test_options_costs.py

research/options_costs.py is the cost model frozen in OPTIONS_IDEAS.md. Short-premium results live and die by costs, so each item is checked against a hand calculation
and the date-dependent rates against the dates the design note states.
"""

from datetime import date

import pytest

import options_costs as oc


@pytest.mark.parametrize("day,stt_rate", [("2023-06-01", 0.000625), ("2024-09-30", 0.000625), ("2024-10-01", 0.001), ("2025-12-31", 0.001), ("2026-03-31", 0.001),
                                           ("2026-04-01", 0.0015), ("2026-10-23", 0.0015)])
def test_the_stt_rate_follows_the_schedule_on_each_side_of_every_change(day, stt_rate):
    sell = oc.leg_cost(100_000.0, 75, "sell", day)
    assert sell["stt"] == pytest.approx(100_000.0 * stt_rate)


def test_the_exchange_charge_steps_up_on_the_first_of_march_2026():
    assert oc.leg_cost(1e6, 75, "buy", "2026-02-27")["exchange"] == pytest.approx(1e6 * 0.0003503)
    assert oc.leg_cost(1e6, 75, "buy", date(2026, 3, 2))["exchange"] == pytest.approx(1e6 * 0.0003553)      # a date object works like its ISO string


def test_a_sell_pays_stt_and_no_stamp_and_a_buy_pays_stamp_and_no_stt():
    sell, buy = oc.leg_cost(200_000.0, 75, "sell", "2026-05-04"), oc.leg_cost(200_000.0, 75, "buy", "2026-05-04")
    assert sell["stt"] > 0 and sell["stamp"] == 0.0 and buy["stt"] == 0.0 and buy["stamp"] == pytest.approx(200_000.0 * 0.00003)


def test_every_item_matches_a_hand_calculation_for_one_sell():
    # premium Rs 1,00,000, 75 units, a sell on 2026-05-04
    c = oc.leg_cost(100_000.0, 75, "sell", "2026-05-04")
    assert c["brokerage"] == 20.0
    assert c["exchange"] == pytest.approx(100_000 * 0.0003553)
    assert c["sebi"] == pytest.approx(100_000 / 1e7 * 10)                                                  # Rs 0.10
    assert c["gst"] == pytest.approx(0.18 * (20.0 + 35.53 + 0.10))
    assert c["stt"] == pytest.approx(150.0)                                                                 # 0.15% of 1,00,000
    assert c["slippage"] == pytest.approx(500.0)                                                            # 0.5%
    assert c["total"] == pytest.approx(sum(v for k, v in c.items() if k != "total"))


def test_slippage_has_a_floor_for_cheap_options_and_scales_with_the_premium_otherwise():
    assert oc.slippage(100.0, 75) == pytest.approx(0.05 * 75)                                              # a Rs 100 premium: 0.5 is under the floor of 3.75
    assert oc.slippage(1_000_000.0, 75) == pytest.approx(5_000.0)
    assert oc.leg_cost(1_000_000.0, 75, "sell", "2026-05-04", slippage_pct=0.02)["slippage"] == pytest.approx(20_000.0)


def test_costs_are_higher_for_a_bigger_trade_and_a_zero_premium_leg_still_pays_brokerage():
    small, big = oc.leg_cost(50_000.0, 75, "sell", "2026-05-04")["total"], oc.leg_cost(500_000.0, 75, "sell", "2026-05-04")["total"]
    assert big > small
    zero = oc.leg_cost(0.0, 75, "sell", "2026-05-04")
    assert zero["brokerage"] == 20.0 and zero["stt"] == 0.0 and zero["total"] >= 20.0


def test_a_long_wing_that_expires_in_the_money_pays_stt_on_its_intrinsic_value_and_one_that_expires_worthless_pays_none():
    assert oc.expiry_stt(40_000.0, "2026-05-28") == pytest.approx(60.0)                                     # 0.15%
    assert oc.expiry_stt(40_000.0, "2024-05-30") == pytest.approx(40_000.0 * 0.000625)
    assert oc.expiry_stt(0.0, "2026-05-28") == 0.0 and oc.expiry_stt(-5.0, "2026-05-28") == 0.0


def test_bad_input_is_refused():
    with pytest.raises(ValueError):
        oc.leg_cost(1000.0, 75, "short", "2026-05-04")
    with pytest.raises(ValueError):
        oc.leg_cost(-1.0, 75, "sell", "2026-05-04")
    with pytest.raises(ValueError):
        oc.leg_cost(1000.0, 0, "sell", "2026-05-04")
