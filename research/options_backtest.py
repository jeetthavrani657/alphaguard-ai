"""
research/options_backtest.py

The iron-condor backtest frozen in OPTIONS_IDEAS.md: sell the 16-delta put and call, buy the 5-delta wings, hold to expiry, on Nifty index options, one cycle per
monthly expiry (`condor_monthly`) or per weekly expiry (`condor_weekly`). Plain functions over the end-of-day table from data/fo_bhavcopy.py.

Rules that keep it honest:
  * The decision is taken from the settlement prices of one day and carried out at the settlement prices of the NEXT trading day (one-day lag).
  * Every trade pays the cost model in options_costs.py: brokerage, STT, exchange and SEBI fees, stamp duty, GST and slippage, on each of the four orders;
    a long wing that expires in the money pays the exercise STT.
  * Positions are whole lots of the exchange's lot size (at least one, unless one lot's worst case is more than the whole account, in which case the cycle is skipped) such
    that the worst-case loss (widest wing minus the credit, times the lot size) is at most `risk_fraction` of the account.
  * The account is marked to market every day. A leg with no price that day keeps its last price. At expiry each leg is valued at its intrinsic value against the
    final settlement level of the underlying, which the exchange's files carry as the settlement value of every contract on the expiry day (see final_level_with_source).
  * The whole account earns the cash rate every day (the margin is assumed posted in liquid collateral), so the curve is comparable with leaving the money in cash.
  * A cycle that cannot be traded (no condor, a missing price, no credit) is skipped and recorded with the reason, never filled in.
"""

import math

import numpy as np
import pandas as pd

import options_chain as ch
import options_costs as oc

DISCOUNT_RATE = 0.06                     # for Black-76 and the cash return: the project's 6% a year
INITIAL = 1_000_000.0
RISK_FRACTION = 0.10
SHORT_DELTA, WING_DELTA = 0.16, 0.05
# NIFTY lot size by date. It is only a FALLBACK, for the 2022-2023 files, which do not carry the lot size; from 2024 each contract's own lot size is read from the file,
# because the size can differ between expiries around a change. The change dates below are the ones seen in the exchange's files.
LOT_SCHEDULE = [("2000-01-01", 50), ("2024-04-26", 25), ("2025-01-31", 75), ("2025-12-31", 65)]
TRADING_DAYS = 252


def lot_size(day) -> int:
    iso = day if isinstance(day, str) else pd.Timestamp(day).strftime("%Y-%m-%d")
    size = LOT_SCHEDULE[0][1]
    for start, value in LOT_SCHEDULE:
        if start <= iso:
            size = value
    return size


def contract_lot(book: dict, day, expiry) -> int:
    """The lot size of that day's contracts for one expiry, as the file states it; the date schedule when the file does not carry one."""
    g = book.get((day, expiry))
    if g is not None and "lot_size" in g.columns:
        known = g.loc[g["lot_size"] > 0, "lot_size"]
        if len(known):
            return int(known.median())
    return lot_size(day)


# ---- organising the table --------------------------------------------------------------------------------------------------------------

def index_table(table: pd.DataFrame, symbol: str = "NIFTY") -> dict:
    """{(date, expiry): the contracts of that expiry on that day} for the symbol's index options, so a day's chain is a dictionary lookup."""
    t = table[(table["symbol"] == symbol) & (table["instrument"] == "OPTIDX")]
    return {key: g for key, g in t.groupby(["date", "expiry"])}


def trading_days(book: dict) -> list:
    return sorted({d for d, _ in book})


def expiries(book: dict, kind: str) -> list:
    """Expiry dates that appear in the data: every one for 'weekly', the last of each calendar month for 'monthly'."""
    every = sorted({e for _, e in book})
    if kind == "weekly":
        return every
    if kind == "monthly":
        last = {}
        for e in every:
            last[(e.year, e.month)] = e
        return sorted(last.values())
    raise ValueError("kind must be 'monthly' or 'weekly'")


def cycles(book: dict, kind: str) -> list:
    """
    One cycle per consecutive pair of expiries: decided at the close of the first trading day after the earlier expiry, carried out the trading day after that,
    and held to the later expiry. Only cycles whose expiry has already happened in the data are returned.
    """
    days, exps, out = trading_days(book), expiries(book, kind), []
    last_day = days[-1]
    for prev, exp in zip(exps[:-1], exps[1:]):
        if exp > last_day:
            break
        after = [d for d in days if d > prev]
        if len(after) < 2:
            continue
        decision, entry = after[0], after[1]
        if entry < exp:                                            # there must be at least one session between entry and expiry
            out.append({"decision_day": decision, "entry_day": entry, "expiry": exp})
    return out


def final_level_with_source(book: dict, expiry) -> tuple:
    """
    (level, source): the final settlement level of the underlying for an expiry, and where it came from.

    On the exchange's expiry day EVERY contract of that expiry carries the same settlement value in the file: the underlying's final settlement level (checked on all
    258 expiries of 2022 to 2026, in both file formats; an option's own settlement price is not what the file holds on that day). So:
      'settlement'  >= 95% of that day's rows share one settlement value: that value is the level.
      'underlying'  otherwise, the underlying price recorded in the file (the newer format has one), if there is one.
      'parity'      otherwise (last resort, approximate): K + call - put at the strikes that have a price.
    The latest day on or before the expiry that has rows for it is used, so an expiry whose own date has no rows is not lost.
    """
    days = sorted(d for d, e in book if e == expiry and d <= expiry)
    if not days:
        return float("nan"), "none"
    g = book[(days[-1], expiry)]
    settle = g["settle"].round(2)
    top = settle.value_counts()
    if len(settle) and top.iloc[0] / len(settle) >= 0.95 and top.index[0] > 0:
        return float(top.index[0]), "settlement"
    if "underlying" in g.columns:
        und = g["underlying"].dropna()
        und = und[und > 0]
        if len(und):
            return float(und.median()), "underlying"
    c = g[g["option_type"] == "CE"].set_index("strike")["settle"]
    p = g[g["option_type"] == "PE"].set_index("strike")["settle"]
    both = pd.concat([c.rename("c"), p.rename("p")], axis=1).dropna()
    both = both[(both["c"] + both["p"]) > 0]
    if both.empty:
        return float("nan"), "none"
    return float(np.median(both.index.to_numpy() + both["c"].to_numpy() - both["p"].to_numpy())), "parity"


def final_level(book: dict, expiry) -> float:
    return final_level_with_source(book, expiry)[0]


# ---- building one position ---------------------------------------------------------------------------------------------------------------

def _price(book: dict, day, expiry, strike: float, kind: str) -> float:
    g = book.get((day, expiry))
    if g is None:
        return float("nan")
    row = g[(g["strike"] == strike) & (g["option_type"] == kind)]
    return float(row["settle"].iloc[0]) if len(row) else float("nan")


def plan_cycle(book: dict, cyc: dict, short_delta: float, wing_delta: float, rate: float) -> tuple:
    """(legs or None, reason). A leg is {strike, kind ('CE'/'PE'), sign (+1 long, -1 short), entry_price}."""
    day_table = book.get((cyc["decision_day"], cyc["expiry"]))
    if day_table is None:
        return None, "no chain on the decision day"
    table, forward, t = ch.with_greeks(ch.chain(day_table, "NIFTY", cyc["expiry"]), cyc["decision_day"], cyc["expiry"], rate)
    if not math.isfinite(forward):
        return None, "no forward could be found"
    strikes = ch.pick_condor(table, short_delta, wing_delta)
    if strikes is None:
        return None, "no condor could be built from the chain"
    spec = [("long_put", "PE", +1), ("short_put", "PE", -1), ("short_call", "CE", -1), ("long_call", "CE", +1)]
    legs = []
    for name, kind, sign in spec:
        px = _price(book, cyc["entry_day"], cyc["expiry"], strikes[name], kind)
        if not (math.isfinite(px) and px > 0):
            return None, f"no price for the {name} strike {strikes[name]:.0f} on the entry day"
        legs.append({"strike": strikes[name], "kind": kind, "sign": sign, "entry_price": px, "last_price": px,
                     "lot": contract_lot(book, cyc["entry_day"], cyc["expiry"])})
    return legs, ""


def size_position(legs: list, equity: float, risk_fraction: float) -> tuple:
    """(lots, per-unit credit, per-unit width, per-unit worst loss), or lots = 0 when there is no credit, or when one lot's worst case is more than the whole account."""
    credit = -sum(l["sign"] * l["entry_price"] for l in legs)
    put_width = next(l["strike"] for l in legs if l["kind"] == "PE" and l["sign"] < 0) - next(l["strike"] for l in legs if l["kind"] == "PE" and l["sign"] > 0)
    call_width = next(l["strike"] for l in legs if l["kind"] == "CE" and l["sign"] > 0) - next(l["strike"] for l in legs if l["kind"] == "CE" and l["sign"] < 0)
    width = max(put_width, call_width)
    max_loss = width - credit
    if credit <= 0 or max_loss <= 0:
        return 0, credit, width, max_loss
    lots = int(math.floor(risk_fraction * equity / (max_loss * legs[0]["lot"])))
    if lots < 1:
        # Not even one lot fits the risk budget. One lot is still taken (the design says at least one), but NEVER if its worst case is more than the whole account:
        # a rule must not be able to lose more than it has. Found on a run with wrong settlement levels, where the account had shrunk to 4% and a forced lot risked 123% of it.
        if max_loss * legs[0]["lot"] > equity:
            return 0, credit, width, max_loss
        lots = 1
    return lots, credit, width, max_loss


# ---- the run -------------------------------------------------------------------------------------------------------------------------------

def run_condor_backtest(book: dict, kind: str, initial: float = INITIAL, risk_fraction: float = RISK_FRACTION, rate: float = DISCOUNT_RATE,
                        slippage_pct: float = oc.SLIPPAGE_PCT, short_delta: float = SHORT_DELTA, wing_delta: float = WING_DELTA,
                        cash_rate: float | None = None) -> dict:
    """
    Run the rule over every cycle in the data. Returns {"equity": daily account value, "cycles": one row per trade, "skipped": [(entry day, expiry, reason)]}.
    `cash_rate` is the yearly return on the whole account (default: the same as `rate`).
    """
    cash_rate = rate if cash_rate is None else cash_rate
    daily_cash = (1.0 + cash_rate) ** (1.0 / TRADING_DAYS) - 1.0
    days = trading_days(book)
    plan = cycles(book, kind)
    if not plan:
        raise ValueError("no cycles in the data")
    by_entry = {c["entry_day"]: c for c in plan}
    first = plan[0]["entry_day"]
    cash, position, log, skipped, equity = float(initial), None, [], [], {}
    prev_equity = float(initial)
    for t in [d for d in days if d >= first]:
        cash += prev_equity * daily_cash                                         # the whole account earns the cash rate
        if position is None and t in by_entry:
            cyc = by_entry[t]
            legs, why = plan_cycle(book, cyc, short_delta, wing_delta, rate)
            if legs is None:
                skipped.append((t, cyc["expiry"], why))
            else:
                lots, credit, width, max_loss = size_position(legs, prev_equity, risk_fraction)
                if lots == 0:
                    skipped.append((t, cyc["expiry"], "no credit for this condor" if credit <= 0 or max_loss <= 0 else "one lot's worst case is more than the whole account"))
                else:
                    units = lots * legs[0]["lot"]
                    cost = sum(oc.leg_cost(l["entry_price"] * units, units, "buy" if l["sign"] > 0 else "sell", t, slippage_pct)["total"] for l in legs)
                    cash += credit * units - cost
                    position = {"legs": legs, "units": units, "lots": lots, "expiry": cyc["expiry"], "entry_day": t, "credit": credit, "width": width,
                                "max_loss": max_loss, "entry_cost": cost}
        value = 0.0
        if position is not None:
            if t >= position["expiry"]:
                value = _settle_position(book, position, t, log)
                cash += value                                                   # cash settlement: shorts pay out (negative), longs receive
                exit_cost = log[-1]["exit_cost"]
                cash -= exit_cost
                position, value = None, 0.0
            else:
                for leg in position["legs"]:
                    px = _price(book, t, position["expiry"], leg["strike"], leg["kind"])
                    if math.isfinite(px) and px > 0:
                        leg["last_price"] = px                                  # a leg with no price today keeps its last one
                value = sum(l["sign"] * l["last_price"] for l in position["legs"]) * position["units"]
        equity[t] = cash + value
        prev_equity = equity[t]
    return {"equity": pd.Series(equity).rename("equity"), "cycles": pd.DataFrame(log), "skipped": skipped}


def _settle_position(book: dict, position: dict, day, log: list) -> float:
    """Value the legs at expiry against the final level, record the cycle, and return the cash that changes hands (negative if the account pays)."""
    level, source = final_level_with_source(book, position["expiry"])
    legs, units, value, long_itm = position["legs"], position["units"], 0.0, 0.0
    for leg in legs:
        if math.isfinite(level):
            intrinsic = max(level - leg["strike"], 0.0) if leg["kind"] == "CE" else max(leg["strike"] - level, 0.0)
        else:
            intrinsic = leg["last_price"]                                       # no final level at all: the last price is the best that is known
        leg["final"] = intrinsic
        value += leg["sign"] * intrinsic * units
        if leg["sign"] > 0:
            long_itm += intrinsic * units
    exit_cost = oc.expiry_stt(long_itm, position["expiry"])
    payoff = sum(l["sign"] * l["final"] for l in legs)
    gross = (position["credit"] + payoff) * units                               # credit received plus what the legs settle at (shorts are negative)
    log.append({"entry_day": position["entry_day"], "expiry": position["expiry"], "lots": position["lots"], "lot_size": legs[0]["lot"], "units": units,
                "long_put": legs[0]["strike"], "short_put": legs[1]["strike"], "short_call": legs[2]["strike"], "long_call": legs[3]["strike"],
                "credit_per_unit": position["credit"], "width": position["width"], "max_loss_per_unit": position["max_loss"], "final_level": level, "final_level_source": source,
                "gross_pnl": gross, "entry_cost": position["entry_cost"], "exit_cost": exit_cost, "net_pnl": gross - position["entry_cost"] - exit_cost})
    return value
