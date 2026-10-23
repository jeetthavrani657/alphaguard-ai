"""
tests/test_intraday_rules_real.py

The hand-built sessions in test_intraday_rules.py prove the engine does what its author thought. This test checks it against the REAL cached candles with a second
implementation written a different way (whole-column pandas pivots instead of a loop over sessions): every trade, for every symbol that has a candle file, must have the
same date, side, entry time, entry price and exit price. It compares trades only; it never computes or prints a return, so it can run before the rules are registered.
Skipped on a machine without the candle cache.
"""

import os

import numpy as np
import pandas as pd
import pytest

import intraday
import intraday_rules as ir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYMBOLS = sorted(f.split("_")[0] for f in os.listdir(intraday.CACHE_DIR) if f.endswith("_15m.csv")) if os.path.isdir(intraday.CACHE_DIR) else []
SYMBOLS = [s for s in SYMBOLS if s not in ("RELIANCE", "TCS")][:8]                  # the first symbols downloaded in full (the two probe files cover only weeks)
SIGNALS = ir.SIGNAL_STARTS


def _pivot(frame):
    keys = frame.index.strftime("%H:%M")
    day = frame.index.normalize()
    cols = {c: frame[c].groupby([day, keys]).first().unstack() for c in ("open", "high", "low", "close")}
    return cols, frame.groupby(day).size()


def _plus(hhmm, minutes):
    t = int(hhmm[:2]) * 60 + int(hhmm[3:]) + minutes
    return f"{t // 60:02d}:{t % 60:02d}"


def _col(m, key):
    return m[key] if key in m.columns else pd.Series(np.nan, index=m.index)


def _independent(frame, rule):
    """(date, side, entry_time, entry_price, exit_price) tuples for one symbol, from whole-column operations."""
    m, count = _pivot(frame)
    days = m["close"].index
    ok = count.reindex(days) >= ir.MIN_CANDLES
    close_last = _col(m["close"], "15:15")
    prev_close = close_last.shift(1).where(ok.shift(1, fill_value=False))
    prev_date = pd.Series(days, index=days).shift(1)
    prev_close = prev_close.where((pd.Series(days, index=days) - prev_date).dt.days <= 5)
    exit_price = close_last
    out = []

    def emit(side_series, entry_key):
        entry = _col(m["open"], entry_key)
        for d in days[ok & side_series.ne(0) & entry.notna() & exit_price.notna()]:
            out.append((d, int(side_series[d]), entry_key, float(entry[d]), float(exit_price[d])))

    if rule == "gap_fade":
        gap = _col(m["open"], "09:15") / prev_close - 1.0
        side = pd.Series(0, index=days).mask(gap >= ir.GAP_THRESHOLD, -1).mask(gap <= -ir.GAP_THRESHOLD, 1)
        emit(side, "09:30")
    elif rule == "late_momentum":
        first = _col(m["close"], "09:30") / prev_close - 1.0
        side = pd.Series(0, index=days).mask(first >= ir.GAP_THRESHOLD, 1).mask(first <= -ir.GAP_THRESHOLD, -1)
        emit(side, "15:00")
    else:
        top = pd.concat([_col(m["high"], "09:15"), _col(m["high"], "09:30")], axis=1).max(axis=1, skipna=False)
        bottom = pd.concat([_col(m["low"], "09:15"), _col(m["low"], "09:30")], axis=1).min(axis=1, skipna=False)
        closes = pd.concat([_col(m["close"], s) for s in SIGNALS], axis=1).to_numpy()
        up, down = closes > top.to_numpy()[:, None], closes < bottom.to_numpy()[:, None]
        hit = up | down                                                                  # NaN compares False: a missing signal candle never signals
        first_hit = np.where(hit.any(axis=1), hit.argmax(axis=1), -1)
        for i, d in enumerate(days):
            k = first_hit[i]
            if k < 0 or not ok.iloc[i]:
                continue
            side, entry_key = (1 if up[i, k] else -1), _plus(SIGNALS[k], 15)
            entry = _col(m["open"], entry_key)[d]
            if np.isnan(entry) or np.isnan(exit_price[d]):
                continue
            out.append((d, side, entry_key, float(entry), float(exit_price[d])))
    return sorted(out, key=lambda t: t[0])


@pytest.mark.skipif(not SYMBOLS, reason="no 15-minute candle cache on this machine")
@pytest.mark.parametrize("rule", ["orb_30", "gap_fade", "late_momentum"])
def test_a_second_implementation_reproduces_every_trade_of_the_engine_on_real_candles(rule):
    checked = 0
    for symbol in SYMBOLS:
        frame = intraday._read_cache(intraday._cache_path(symbol, 15))
        mine = _independent(frame, rule)
        theirs = ir.trades_for_symbol(frame, rule, symbol)
        assert len(mine) == len(theirs), f"{rule} {symbol}: {len(mine)} trades independently, {len(theirs)} from the engine"
        for a, (_, b) in zip(mine, theirs.iterrows()):
            assert a[0] == b["date"] and a[1] == b["side"] and a[2] == b["entry_time"], f"{rule} {symbol} {a[0].date()}: day, side or entry time differ"
            assert a[3] == pytest.approx(b["entry_price"], rel=1e-12) and a[4] == pytest.approx(b["exit_price"], rel=1e-12), f"{rule} {symbol} {a[0].date()}: prices differ"
        checked += len(mine)
    assert checked > 0, "no trades to compare: the check proved nothing"
