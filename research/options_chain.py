"""
research/options_chain.py

One day's option chain for one expiry, from the end-of-day table in data/fo_bhavcopy.py, with the forward, each strike's implied volatility and delta
worked out, and the choice of an iron condor's four strikes by delta. Pure functions of a table; no downloads.

Method (frozen in OPTIONS_IDEAS.md): the forward comes from put-call parity at the money; each strike is priced from its OUT-of-the-money option
(puts below the forward, calls at or above it), because those are the liquid ones; the delta of the call and the put at a strike then both follow from that one volatility.
"""

import math

import numpy as np
import pandas as pd

import options_math as om


def chain(day_table: pd.DataFrame, symbol: str, expiry) -> pd.DataFrame:
    """Settlement prices by strike for one expiry: columns call, put, call_volume, put_volume, indexed by strike. Strikes missing a side keep NaN."""
    t = day_table[(day_table["symbol"] == symbol) & (day_table["instrument"] == "OPTIDX") & (day_table["expiry"] == pd.Timestamp(expiry))]
    calls, puts = t[t["option_type"] == "CE"].set_index("strike"), t[t["option_type"] == "PE"].set_index("strike")
    out = pd.DataFrame({"call": calls["settle"], "put": puts["settle"], "call_volume": calls["volume"], "put_volume": puts["volume"]}).sort_index()
    return out[~out.index.duplicated(keep="last")]


def with_greeks(ch: pd.DataFrame, day, expiry, rate: float) -> tuple:
    """
    (table, forward, t). The table adds iv (the volatility of the out-of-the-money option at that strike), call_delta and put_delta. A strike with no usable volatility
    gets NaN and is never chosen. Returns (empty table, NaN, t) when no forward can be found.
    """
    t = om.years_between(pd.Timestamp(day).date(), pd.Timestamp(expiry).date())
    both = ch.dropna(subset=["call", "put"])
    forward = om.implied_forward(both.index.to_numpy(), both["call"].to_numpy(), both["put"].to_numpy(), t, rate)
    if not math.isfinite(forward) or t <= 0:
        return ch.iloc[0:0].assign(iv=np.nan, call_delta=np.nan, put_delta=np.nan), float("nan"), t      # empty, but with the columns a caller will ask for
    rows = []
    for strike, r in ch.iterrows():
        use_call = strike >= forward                                    # out of the money: a call above the forward, a put below it
        px = r["call"] if use_call else r["put"]
        iv = om.implied_vol(px, forward, strike, t, rate, use_call) if pd.notna(px) else float("nan")
        if math.isfinite(iv):
            cd = om.delta(forward, strike, t, iv, rate, True)
            rows.append((strike, iv, cd, cd - math.exp(-rate * t)))      # put delta = call delta minus the discount factor
        else:
            rows.append((strike, float("nan"), float("nan"), float("nan")))
    g = pd.DataFrame(rows, columns=["strike", "iv", "call_delta", "put_delta"]).set_index("strike")
    return ch.join(g), forward, t


def pick_condor(table: pd.DataFrame, short_delta: float = 0.16, wing_delta: float = 0.05) -> dict | None:
    """
    Choose the four strikes: the put and call whose deltas are closest to -short_delta and +short_delta, and the wings closest to -wing_delta and
    +wing_delta; a wing that lands on or inside its short strike is moved one strike further out. Only strikes with a volatility are considered.
    Returns {"long_put", "short_put", "short_call", "long_call"} (strikes), or None if the chain cannot supply them.
    """
    usable = table.dropna(subset=["iv", "call_delta", "put_delta", "call", "put"])
    usable = usable[(usable["call"] > 0) & (usable["put"] > 0)]
    if len(usable) < 6:
        return None
    strikes = usable.index.to_numpy()
    sp = strikes[int(np.argmin(np.abs(usable["put_delta"].to_numpy() + short_delta)))]
    sc = strikes[int(np.argmin(np.abs(usable["call_delta"].to_numpy() - short_delta)))]
    lp = strikes[int(np.argmin(np.abs(usable["put_delta"].to_numpy() + wing_delta)))]
    lc = strikes[int(np.argmin(np.abs(usable["call_delta"].to_numpy() - wing_delta)))]
    below, above = strikes[strikes < sp], strikes[strikes > sc]
    if lp >= sp:
        if len(below) == 0:
            return None
        lp = below[-1]                                                   # one strike further out than the short put
    if lc <= sc:
        if len(above) == 0:
            return None
        lc = above[0]
    if not (lp < sp < sc < lc):
        return None
    return {"long_put": float(lp), "short_put": float(sp), "short_call": float(sc), "long_call": float(lc)}
