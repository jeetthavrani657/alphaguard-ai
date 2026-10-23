"""
research/intraday_costs.py

What a round trip (buy and sell the same shares on the same day, the "MIS" product) costs on the NSE cash segment, and so how much an intraday trade must gain, on average, before it
earns anything. A plain function of the trade value; no data access. The figures are the ones in the table below and are ASSUMPTIONS to be re-checked against the exchange and
SEBI circulars (broker notices and calculators were the sources):

    brokerage   the LOWER of Rs 20 and 0.03% of the order value, per order                     (broker notices)
    STT         0.025% of the SELL value only                                                   (unchanged in 2026 per several sources)
    exchange    0.00345% of each side's value (sources give 0.00297% to 0.00345%: the high end)
    SEBI fee    Rs 10 per crore of each side's value
    stamp duty  0.003% of the BUY value only                                                    (from memory; not confirmed by the sources found)
    GST         18% of (brokerage + exchange charge + SEBI fee)
    slippage    a share of each side's value paid to cross the spread (an assumption; 0.05% by default)
"""

BROKERAGE_FLAT = 20.0
BROKERAGE_PCT = 0.0003
STT_SELL = 0.00025
EXCHANGE_PCT = 0.0000345
SEBI_PER_CRORE = 10.0
STAMP_BUY = 0.00003
GST = 0.18
SLIPPAGE_PCT = 0.0005


def leg_cost(value: float, side: str, slippage_pct: float = SLIPPAGE_PCT) -> dict:
    """The itemised cost, in rupees, of one intraday order of the given rupee value. `side` is 'buy' or 'sell'."""
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")
    if value < 0:
        raise ValueError("the value of an order cannot be negative")
    brokerage = min(BROKERAGE_FLAT, value * BROKERAGE_PCT)
    exchange = value * EXCHANGE_PCT
    sebi = value / 1e7 * SEBI_PER_CRORE
    gst = GST * (brokerage + exchange + sebi)
    stt = value * STT_SELL if side == "sell" else 0.0
    stamp = value * STAMP_BUY if side == "buy" else 0.0
    slippage = value * slippage_pct
    total = brokerage + exchange + sebi + gst + stt + stamp + slippage
    return {"brokerage": brokerage, "exchange": exchange, "sebi": sebi, "gst": gst, "stt": stt, "stamp": stamp, "slippage": slippage, "total": total}


def round_trip_cost(value: float, slippage_pct: float = SLIPPAGE_PCT) -> dict:
    """The whole cost of buying and selling `value` worth of shares on one day (the order of the two legs does not change the total: a short sale pays the same items)."""
    buy, sell = leg_cost(value, "buy", slippage_pct), leg_cost(value, "sell", slippage_pct)
    items = {k: buy[k] + sell[k] for k in buy}
    items["pct_of_value"] = items["total"] / value * 100.0 if value else float("nan")
    return items


def breakeven_move_pct(value: float, slippage_pct: float = SLIPPAGE_PCT) -> float:
    """The average gross price move, in percent of the trade value, a trade must capture just to cover its round-trip cost."""
    return round_trip_cost(value, slippage_pct)["pct_of_value"]
