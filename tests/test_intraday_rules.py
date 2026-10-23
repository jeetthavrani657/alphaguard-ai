"""
tests/test_intraday_rules.py

research/intraday_rules.py runs the three rules frozen in INTRADAY_IDEAS.md. Each rule is checked on hand-built sessions where the right entry candle, side and prices
are known: the entry is always the OPEN of a LATER candle than the signal (never the signal candle itself), exits are the 15:15 close, shorts gain when the price falls, a
missing candle or a short session means no trade, and the costs split the account over the day's trades.
"""

import numpy as np
import pandas as pd
import pytest

import intraday_costs as ic
import intraday_rules as ir

TIMES = [f"{9 + (15 + 15 * k) // 60:02d}:{(15 + 15 * k) % 60:02d}" for k in range(25)]      # 09:15 ... 15:15


def _session(date, overrides=None, drop=(), flat=100.0):
    """A 25-candle session, every candle flat at `flat` unless overridden: {'HH:MM': (open, high, low, close)}."""
    rows, idx = [], []
    for t in TIMES:
        if t in drop:
            continue
        o, h, l, c = (overrides or {}).get(t, (flat, flat, flat, flat))
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": 1000.0})
        idx.append(pd.Timestamp(f"{date} {t}"))
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx, name="time"))


def _two_days(second_overrides, drop=(), first_close=100.0):
    first = _session("2026-10-19", {"15:15": (first_close, first_close, first_close, first_close)}, flat=first_close)
    return pd.concat([first, _session("2026-10-20", second_overrides, drop=drop)])


# --- orb_30 ---------------------------------------------------------------------------------------------------------------------

def test_orb_buys_after_the_first_close_above_the_range_at_the_NEXT_candles_open_and_exits_at_the_close():
    f = _session("2026-10-20", {"09:15": (100, 101, 99, 100), "09:30": (100, 102, 99.5, 101),          # range: high 102, low 99
                                "10:30": (102.5, 104, 102, 103), "10:45": (103.2, 103.5, 103, 103.3), "15:15": (103, 105, 103, 104)})
    t = ir.trades_for_symbol(f, "orb_30", "X")
    assert len(t) == 1
    r = t.iloc[0]
    assert r["side"] == 1 and r["entry_time"] == "10:45" and r["entry_price"] == 103.2 and r["exit_price"] == 104.0       # the 10:30 candle closed at 103 > 102: enter at the 10:45 OPEN
    assert r["gross_return"] == pytest.approx(104.0 / 103.2 - 1)


def test_orb_sells_short_below_the_range_and_a_falling_price_is_a_gain():
    f = _session("2026-10-20", {"09:15": (100, 101, 99, 100), "09:30": (100, 101, 99, 100),
                                "11:00": (98.5, 98.7, 97.5, 98.0), "11:15": (97.9, 98, 97, 97.5), "15:15": (96, 96.5, 95.5, 96.0)})
    r = ir.trades_for_symbol(f, "orb_30", "X").iloc[0]
    assert r["side"] == -1 and r["entry_time"] == "11:15" and r["entry_price"] == 97.9 and r["exit_price"] == 96.0
    assert r["gross_return"] == pytest.approx(-(96.0 / 97.9 - 1)) and r["gross_return"] > 0


def test_orb_takes_only_the_first_breakout_and_nothing_when_the_range_holds():
    both = _session("2026-10-20", {"09:15": (100, 101, 99, 100), "09:30": (100, 101, 99, 100), "10:00": (101, 103, 101, 102.5), "10:15": (102.6, 102.7, 102.5, 102.6),
                                   "12:00": (98, 98, 97, 97.5), "12:15": (97.5, 98, 97, 97.8)})
    t = ir.trades_for_symbol(both, "orb_30", "X")
    assert len(t) == 1 and t.iloc[0]["side"] == 1 and t.iloc[0]["entry_time"] == "10:15"
    assert ir.trades_for_symbol(_session("2026-10-20", {"09:15": (100, 101, 99, 100), "09:30": (100, 101, 99, 100)}), "orb_30", "X").empty


def test_orb_ignores_a_break_that_closes_after_the_last_signal_candle():
    late = _session("2026-10-20", {"09:15": (100, 101, 99, 100), "09:30": (100, 101, 99, 100), "14:45": (100, 104, 100, 103)})      # the 14:45 candle is not a signal candle
    assert ir.trades_for_symbol(late, "orb_30", "X").empty
    last = _session("2026-10-20", {"09:15": (100, 101, 99, 100), "09:30": (100, 101, 99, 100), "14:30": (100, 104, 100, 103), "14:45": (103.5, 104, 103, 103.8)})
    r = ir.trades_for_symbol(last, "orb_30", "X").iloc[0]
    assert r["entry_time"] == "14:45" and r["entry_price"] == 103.5                                                     # the 14:30 candle IS the last signal candle


# --- gap_fade -------------------------------------------------------------------------------------------------------------------

def test_gap_fade_sells_a_gap_up_of_one_percent_at_the_0930_open_and_buys_a_gap_down():
    up = ir.trades_for_symbol(_two_days({"09:15": (101.5, 101.8, 101.0, 101.2), "09:30": (101.4, 101.5, 100.5, 101.0), "15:15": (100.0, 100.5, 99.5, 100.0)}), "gap_fade", "X")
    assert len(up) == 1 and up.iloc[0]["side"] == -1 and up.iloc[0]["entry_time"] == "09:30" and up.iloc[0]["entry_price"] == 101.4
    assert up.iloc[0]["gross_return"] == pytest.approx(-(100.0 / 101.4 - 1))
    down = ir.trades_for_symbol(_two_days({"09:15": (98.5, 98.8, 98.0, 98.2), "09:30": (98.4, 99, 98, 98.6), "15:15": (99.0, 99.5, 98.5, 99.0)}), "gap_fade", "X")
    assert len(down) == 1 and down.iloc[0]["side"] == 1 and down.iloc[0]["entry_price"] == 98.4


def test_gap_fade_needs_a_gap_of_one_percent_and_a_prior_close(monkeypatch):
    assert ir.trades_for_symbol(_two_days({"09:15": (100.9, 101, 100.8, 100.9)}), "gap_fade", "X").empty                  # a 0.9% gap is not enough
    assert len(ir.trades_for_symbol(_two_days({"09:15": (101.5, 101.6, 101.4, 101.5)}), "gap_fade", "X")) == 1              # 1.5% is
    assert ir.trades_for_symbol(_session("2026-10-20", {"09:15": (105, 105, 105, 105)}), "gap_fade", "X").empty            # the first session in the data has no prior close
    # A gap EQUAL to the threshold trades (">=", not ">"). A 1% gap in floating point is not exactly 0.01, so the threshold is set to the very float the rule computes.
    monkeypatch.setattr(ir, "GAP_THRESHOLD", 101.0 / 100.0 - 1.0)
    assert len(ir.trades_for_symbol(_two_days({"09:15": (101.0, 101, 100.9, 101.0)}), "gap_fade", "X")) == 1             # equal on the upside trades
    monkeypatch.setattr(ir, "GAP_THRESHOLD", -(99.0 / 100.0 - 1.0))
    assert len(ir.trades_for_symbol(_two_days({"09:15": (99.0, 99.1, 98.9, 99.0)}), "gap_fade", "X")) == 1               # equal on the downside trades too


def test_the_prior_close_is_the_previous_sessions_1515_close_not_its_last_price_of_any_other_candle():
    first = _session("2026-10-19", {"10:00": (110, 110, 110, 110), "14:45": (110, 110, 110, 110), "15:15": (100, 100, 100, 100)})      # 110 earlier in the day, 100 at the close
    second = _session("2026-10-20", {"09:15": (101.5, 101.8, 101.0, 101.2)})
    assert len(ir.trades_for_symbol(pd.concat([first, second]), "gap_fade", "X")) == 1                                       # gap measured from 100 (1.5%), not from 110 (a gap DOWN of 7.7%)
    assert ir.trades_for_symbol(pd.concat([first, second]), "gap_fade", "X").iloc[0]["side"] == -1


# --- late_momentum ---------------------------------------------------------------------------------------------------------------

def test_late_momentum_buys_after_a_big_up_first_half_hour_at_the_1500_open_and_exits_at_the_close():
    f = _two_days({"09:15": (100.8, 101.2, 100.7, 101.0), "09:30": (101.0, 101.6, 100.9, 101.5), "15:00": (101.6, 101.9, 101.5, 101.8), "15:15": (101.8, 102.4, 101.7, 102.2)})
    r = ir.trades_for_symbol(f, "late_momentum", "X").iloc[0]
    assert r["side"] == 1 and r["entry_time"] == "15:00" and r["entry_price"] == 101.6 and r["exit_price"] == 102.2
    assert r["gross_return"] == pytest.approx(102.2 / 101.6 - 1)


def test_late_momentum_sells_after_a_big_down_move_and_does_nothing_for_a_small_one():
    down = _two_days({"09:30": (99.0, 99.1, 98.4, 98.5), "15:00": (98.4, 98.5, 98.3, 98.4), "15:15": (98.0, 98.1, 97.8, 97.9)})
    r = ir.trades_for_symbol(down, "late_momentum", "X").iloc[0]
    assert r["side"] == -1 and r["gross_return"] == pytest.approx(-(97.9 / 98.4 - 1))
    assert ir.trades_for_symbol(_two_days({"09:30": (100.5, 100.6, 100.4, 100.5)}), "late_momentum", "X").empty             # +0.5% only


def test_late_momentum_acts_on_a_move_exactly_at_the_threshold_in_both_directions(monkeypatch):
    monkeypatch.setattr(ir, "GAP_THRESHOLD", 101.0 / 100.0 - 1.0)
    assert len(ir.trades_for_symbol(_two_days({"09:30": (101.0, 101.0, 101.0, 101.0)}), "late_momentum", "X")) == 1
    monkeypatch.setattr(ir, "GAP_THRESHOLD", -(99.0 / 100.0 - 1.0))
    assert len(ir.trades_for_symbol(_two_days({"09:30": (99.0, 99.0, 99.0, 99.0)}), "late_momentum", "X")) == 1


def test_the_opening_range_is_both_of_the_first_two_candles_not_just_the_first():
    # 09:15 high 101, 09:30 high 103: a later close of 102 is above the FIRST candle's high but inside the 30-minute range, so there is no breakout.
    inside = _session("2026-10-20", {"09:15": (100, 101, 99, 100), "09:30": (100, 103, 98, 100), "10:00": (101, 102.2, 101, 102.0), "10:15": (102, 102, 102, 102)})
    assert ir.trades_for_symbol(inside, "orb_30", "X").empty
    below = _session("2026-10-20", {"09:15": (100, 101, 99, 100), "09:30": (100, 101, 97, 100), "10:00": (98.5, 98.6, 98, 98.2), "10:15": (98, 98, 98, 98)})
    assert ir.trades_for_symbol(below, "orb_30", "X").empty                                                                  # 98.2 is below the first candle's low (99) but inside the range (low 97)
    first_extreme = _session("2026-10-20", {"09:15": (100, 103, 97, 100), "09:30": (100, 101, 99, 100), "10:00": (101, 102.2, 98.5, 102.0), "10:15": (102, 102, 102, 102)})
    assert ir.trades_for_symbol(first_extreme, "orb_30", "X").empty                                                          # the extremes are in the FIRST candle: 102 is above the second candle's high only
    first_low = _session("2026-10-20", {"09:15": (100, 101, 97, 100), "09:30": (100, 101, 99, 100), "10:00": (98.5, 98.6, 98, 98.2), "10:15": (98, 98, 98, 98)})
    assert ir.trades_for_symbol(first_low, "orb_30", "X").empty                                                              # 98.2 is below the second candle's low (99) but inside the range


def test_a_session_needs_at_least_23_of_its_25_candles():
    orb = {"09:15": (100, 101, 99, 100), "09:30": (100, 101, 99, 100), "10:30": (102.5, 104, 102, 103), "10:45": (103.2, 103.5, 103, 103.3)}
    assert len(ir.trades_for_symbol(_session("2026-10-20", orb, drop=("12:00", "12:15")), "orb_30", "X")) == 1               # 23 candles: traded
    assert ir.trades_for_symbol(_session("2026-10-20", orb, drop=("12:00", "12:15", "12:30")), "orb_30", "X").empty          # 22 candles: not


# --- the common rules -------------------------------------------------------------------------------------------------------------

def test_a_short_session_or_a_missing_entry_candle_means_no_trade_and_no_prior_close_for_the_next_day():
    orb = {"09:15": (100, 101, 99, 100), "09:30": (100, 101, 99, 100), "10:30": (102.5, 104, 102, 103), "10:45": (103.2, 103.5, 103, 103.3)}
    assert len(ir.trades_for_symbol(_session("2026-10-20", orb), "orb_30", "X")) == 1
    assert ir.trades_for_symbol(_session("2026-10-20", orb, drop=("10:45",)), "orb_30", "X").empty                           # the entry candle is missing
    assert ir.trades_for_symbol(_session("2026-10-20", orb, drop=("15:15",)), "orb_30", "X").empty                           # no final candle to exit on
    short = _session("2026-10-20", orb, drop=TIMES[12:])                                                                     # only 12 candles
    assert ir.trades_for_symbol(short, "orb_30", "X").empty
    after_short = pd.concat([_session("2026-10-19", flat=100.0, drop=TIMES[12:]), _session("2026-10-20", {"09:15": (105, 105, 105, 105)})])
    assert ir.trades_for_symbol(after_short, "gap_fade", "X").empty                                                          # the short day gives no prior close


def test_a_prior_close_from_before_a_long_gap_in_the_data_is_not_trusted():
    first = _session("2026-10-05", flat=100.0)
    later = _session("2026-10-20", {"09:15": (105, 105, 105, 105)})
    assert ir.trades_for_symbol(pd.concat([first, later]), "gap_fade", "X").empty


# --- costs and the daily series ---------------------------------------------------------------------------------------------------

def test_costs_split_the_account_over_the_days_trades_and_a_busy_day_pays_more_per_trade():
    trades = pd.DataFrame({"date": [pd.Timestamp("2026-10-19")] + [pd.Timestamp("2026-10-20")] * 4, "symbol": list("ABCDE"),
                           "side": 1, "entry_time": "10:00", "entry_price": 100.0, "exit_price": 101.0, "gross_return": 0.01})
    n = ir.add_net_returns(trades, account=1_000_000.0)
    one = ic.round_trip_cost(1_000_000.0)["pct_of_value"] / 100
    four = ic.round_trip_cost(250_000.0)["pct_of_value"] / 100
    assert n["cost_return"].iloc[0] == pytest.approx(one) and n["cost_return"].iloc[1] == pytest.approx(four) and four > one
    assert n["net_return"].iloc[0] == pytest.approx(0.01 - one)


def test_the_equity_curve_compounds_the_equal_weighted_daily_net_return_and_is_flat_on_days_without_trades():
    sessions = pd.DatetimeIndex(["2026-10-19", "2026-10-20", "2026-10-21"])
    net = pd.DataFrame({"date": [pd.Timestamp("2026-10-19")] * 2 + [pd.Timestamp("2026-10-21")], "symbol": list("ABC"),
                        "net_return": [0.02, 0.00, -0.01]})
    eq = ir.daily_equity(net, sessions, account=1000.0)
    assert eq.iloc[0] == 1000.0 and eq.index[0] == pd.Timestamp("2026-10-18")
    assert list(eq.values[1:]) == pytest.approx([1000 * 1.01, 1000 * 1.01, 1000 * 1.01 * 0.99])                               # day 1: mean(0.02, 0) = 1%; day 2 flat; day 3: -1%


def test_the_trade_summary_sets_gross_gain_against_the_bar_and_windows_cut_by_date():
    t = pd.DataFrame({"date": pd.to_datetime(["2024-06-28", "2024-06-28", "2024-07-01", "2024-07-02"]), "symbol": list("ABCD"), "side": [1, -1, 1, 1],
                      "gross_return": [0.004, 0.002, -0.001, 0.003], "cost_return": 0.002})
    t["net_return"] = t["gross_return"] - t["cost_return"]
    a, b = ir.trade_summary(t, None, ir.IS_END), ir.trade_summary(t, ir.OOS_START)
    assert a["n_trades"] == 2 and b["n_trades"] == 2
    assert a["mean_gross_pct"] == pytest.approx(0.3) and a["gross_minus_bar_pct"] == pytest.approx(0.3 - 0.2) and a["mean_net_pct"] == pytest.approx(0.1)
    assert b["mean_gross_pct"] == pytest.approx(0.1) and b["win_rate_pct"] == 50.0 and a["long_share_pct"] == 50.0
    assert ir.trade_summary(t, "2030-01-01")["n_trades"] == 0
