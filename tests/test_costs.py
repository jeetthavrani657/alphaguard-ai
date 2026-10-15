"""
tests/test_costs.py

One test per cost component in engine/costs.py, each against a value
computed by hand on a round trade size (Rs 10,00,000), using the actual
default rates in config.COSTS -- plus the totals, not just that the
function runs. The brokerage "whichever is lower" formula is tested
separately with monkeypatched rates, since the default brokerage_pct is
0 and would never actually exercise the min() logic otherwise.
"""

import pytest

import config
from costs import calculate_trade_cost

TRADE_VALUE = 1_000_000.0  # Rs 10,00,000, a round number for clean hand arithmetic


def test_brokerage_is_zero_at_default_rate():
    # Default config: brokerage_pct = 0.0 -> brokerage = min(0, flat) = 0, always.
    result = calculate_trade_cost(TRADE_VALUE, "buy")
    assert result["brokerage"] == pytest.approx(0.0, abs=1e-9)


def test_brokerage_whichever_is_lower_picks_the_flat_fee(monkeypatch):
    # 0.1% of a Rs 50,000 trade = Rs 50, above the Rs 20 flat cap -> flat wins.
    monkeypatch.setitem(config.COSTS, "brokerage_pct", 0.001)
    monkeypatch.setitem(config.COSTS, "brokerage_flat", 20.0)
    result = calculate_trade_cost(50_000.0, "buy")
    assert result["brokerage"] == pytest.approx(20.0, abs=1e-9)


def test_brokerage_whichever_is_lower_picks_the_percentage(monkeypatch):
    # 0.1% of a Rs 5,000 trade = Rs 5, below the Rs 20 flat cap -> percentage wins.
    monkeypatch.setitem(config.COSTS, "brokerage_pct", 0.001)
    monkeypatch.setitem(config.COSTS, "brokerage_flat", 20.0)
    result = calculate_trade_cost(5_000.0, "buy")
    assert result["brokerage"] == pytest.approx(5.0, abs=1e-9)


def test_stt_is_0_1_percent_on_both_sides():
    # 0.1% of 10,00,000 = Rs 1,000, same on buy and sell (delivery STT is symmetric).
    buy = calculate_trade_cost(TRADE_VALUE, "buy")
    sell = calculate_trade_cost(TRADE_VALUE, "sell")
    assert buy["stt"] == pytest.approx(1_000.0, abs=1e-9)
    assert sell["stt"] == pytest.approx(1_000.0, abs=1e-9)


def test_exchange_transaction_charge():
    # 0.00307% of 10,00,000 = Rs 30.70
    result = calculate_trade_cost(TRADE_VALUE, "buy")
    assert result["exchange_charges"] == pytest.approx(30.70, abs=1e-9)


def test_sebi_turnover_fee():
    # Rs 10/crore = 0.0001% -> 0.000001 of 10,00,000 = Rs 1.00
    result = calculate_trade_cost(TRADE_VALUE, "buy")
    assert result["sebi_charges"] == pytest.approx(1.00, abs=1e-9)


def test_gst_base_excludes_stt_and_stamp_duty():
    # GST = 18% of (brokerage + sebi + exchange) = 18% of (0 + 1.00 + 30.70) = 18% of 31.70 = 5.706
    # NOT 18% of the whole cost stack -- STT (1000) and stamp duty are taxes, not a GST base.
    result = calculate_trade_cost(TRADE_VALUE, "buy")
    assert result["gst"] == pytest.approx(5.706, abs=1e-9)


def test_stamp_duty_buy_side_only():
    # 0.015% of 10,00,000 = Rs 150 on buy; exactly 0 on sell.
    buy = calculate_trade_cost(TRADE_VALUE, "buy")
    sell = calculate_trade_cost(TRADE_VALUE, "sell")
    assert buy["stamp_duty"] == pytest.approx(150.0, abs=1e-9)
    assert sell["stamp_duty"] == pytest.approx(0.0, abs=1e-9)


def test_slippage_both_sides():
    # 0.05% of 10,00,000 = Rs 500, both sides.
    buy = calculate_trade_cost(TRADE_VALUE, "buy")
    sell = calculate_trade_cost(TRADE_VALUE, "sell")
    assert buy["slippage"] == pytest.approx(500.0, abs=1e-9)
    assert sell["slippage"] == pytest.approx(500.0, abs=1e-9)


def test_total_buy_cost():
    # By hand: brokerage 0 + stt 1000 + exchange 30.70 + sebi 1.00
    #        + gst 5.706 + stamp_duty 150 + slippage 500 = 1687.406
    result = calculate_trade_cost(TRADE_VALUE, "buy")
    assert result["total"] == pytest.approx(1687.406, abs=1e-6)


def test_total_sell_cost():
    # Same as buy but no stamp duty: 1687.406 - 150 = 1537.406
    result = calculate_trade_cost(TRADE_VALUE, "sell")
    assert result["total"] == pytest.approx(1537.406, abs=1e-6)


def test_invalid_side_raises():
    with pytest.raises(AssertionError):
        calculate_trade_cost(TRADE_VALUE, "hold")


def test_slippage_override_replaces_default_rate():
    # 0.30% override instead of the default 0.05% -> Rs 3,000 slippage on Rs 10,00,000, not Rs 500.
    result = calculate_trade_cost(TRADE_VALUE, "buy", slippage_pct_override=0.003)
    assert result["slippage"] == pytest.approx(3_000.0, abs=1e-6)


def test_no_override_reproduces_default_behavior():
    # None (the default) must give byte-for-byte the same result as calling without the parameter at all.
    with_none = calculate_trade_cost(TRADE_VALUE, "buy", slippage_pct_override=None)
    without_param = calculate_trade_cost(TRADE_VALUE, "buy")
    assert with_none == without_param
