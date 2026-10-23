"""
research/options_costs.py

What it costs to trade index options in India, as frozen in OPTIONS_IDEAS.md. Plain functions of a date and a premium value, so a rule's cost
is never a guess made inside a backtest. The statutory rates change with time; the schedule here is the one the design note states, and the
exchange and tax figures are to be re-checked against the circulars (the note says where each came from).

A "leg" is one option bought or sold; `premium_value` is the rupee value of that leg's premium (price x lot size x lots). Every function returns rupees.
"""

BROKERAGE_PER_ORDER = 20.0                 # Rs per order, a discount-broker flat fee (assumption)
SEBI_FEE_PER_CRORE = 10.0                  # Rs per crore of turnover
STAMP_DUTY_BUY = 0.00003                   # 0.003% of premium, buy side only
GST = 0.18                                 # on brokerage, exchange charge and SEBI fee
SLIPPAGE_PCT = 0.005                       # 0.5% of the premium per side (assumption)
MIN_SLIPPAGE_POINTS = 0.05                 # but never under 5 paise a unit

# (first date the rate applies, rate). The 2026 rise is from a broker bulletin; the earlier steps are from memory (see OPTIONS_IDEAS.md).
STT_SELL_SCHEDULE = [("2000-01-01", 0.000625), ("2024-10-01", 0.001), ("2026-04-01", 0.0015)]
EXCHANGE_SCHEDULE = [("2000-01-01", 0.0003503), ("2026-03-01", 0.0003553)]


def _rate(schedule: list, day) -> float:
    """The rate in force on `day` (a date or an ISO string): the last entry whose start date is not after it."""
    iso = day if isinstance(day, str) else day.isoformat()
    rate = schedule[0][1]
    for start, value in schedule:
        if start <= iso:
            rate = value
    return rate


def slippage(premium_value: float, units: float, slippage_pct: float = SLIPPAGE_PCT) -> float:
    """Half the spread paid on one side: a share of the premium, but not less than a minimum number of paise per unit."""
    return max(premium_value * slippage_pct, MIN_SLIPPAGE_POINTS * units)


def leg_cost(premium_value: float, units: float, side: str, day, slippage_pct: float = SLIPPAGE_PCT) -> dict:
    """The itemised cost of ONE order for one leg on `day`. `side` is 'buy' or 'sell'; `units` is lots x lot size."""
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")
    if premium_value < 0 or units <= 0:
        raise ValueError("premium value cannot be negative and units must be positive")
    brokerage = BROKERAGE_PER_ORDER
    exchange = premium_value * _rate(EXCHANGE_SCHEDULE, day)
    sebi = premium_value / 1e7 * SEBI_FEE_PER_CRORE
    gst = GST * (brokerage + exchange + sebi)
    stt = premium_value * _rate(STT_SELL_SCHEDULE, day) if side == "sell" else 0.0
    stamp = premium_value * STAMP_DUTY_BUY if side == "buy" else 0.0
    slip = slippage(premium_value, units, slippage_pct)
    total = brokerage + exchange + sebi + gst + stt + stamp + slip
    return {"brokerage": brokerage, "exchange": exchange, "sebi": sebi, "gst": gst, "stt": stt, "stamp": stamp, "slippage": slip, "total": total}


def expiry_stt(intrinsic_value: float, day) -> float:
    """
    STT on a LONG option that expires in the money (the buyer's exercise): charged on its intrinsic value at the sell-side rate, which is an
    assumption slightly stricter than the true exercise rate. A short option that expires in the money is cash-settled with no STT for the seller.
    """
    return max(intrinsic_value, 0.0) * _rate(STT_SELL_SCHEDULE, day)
