"""
engine/costs.py

India equity-DELIVERY trading costs. All rates live in config.py's
COSTS dict -- nothing here is hardcoded.

Verified against Zerodha's published charges (zerodha.com/charges/,
checked 2026-09-02) rather than written from memory, per your request.
This system trades daily-timeframe signals held across multiple days,
i.e. delivery trades, not intraday -- all rates below are the delivery
rates specifically, which differ from intraday/F&O rates.

CORRECTIONS TO THE ORIGINAL SPEC -- what changed and why:

1. STT is 0.1% on delivery BUY *and* SELL, not sell-only. The
   sell-only rule applies to INTRADAY equity (0.025%, sell side only);
   delivery charges STT symmetrically on both legs.

2. Brokerage: Zerodha (and most major discount brokers) now charge
   ZERO brokerage on equity delivery. The "0.03% or Rs 20, whichever
   is lower" figure you gave is Zerodha's INTRADAY/F&O brokerage, not
   delivery -- delivery brokerage was dropped to zero some time ago.
   Since every trade this system generates is a multi-day hold
   (delivery), config.py defaults brokerage_pct to 0. The
   whichever-is-lower formula is still implemented below and fully
   configurable, in case you want to model a different/older broker.

3. SEBI turnover fees (Rs 10/crore) were missing from the original
   list entirely. Small, but real, and it feeds into the GST base --
   added as sebi_pct.

4. GST base is (brokerage + SEBI charges + exchange transaction
   charges), not just (brokerage + transaction charges) as stated --
   SEBI charges are part of the actual GST base per Zerodha's own
   breakdown. Corrected below.

Everything else you specified (exchange transaction charges, 18% GST
rate, 0.015% stamp duty on buy only, configurable slippage) checked out
as currently correct.
"""

import config


def calculate_trade_cost(trade_value: float, side: str, slippage_pct_override: float = None) -> dict:
    """
    trade_value: gross value of the trade (fill price * quantity),
        before any costs are applied.
    side: "buy" or "sell" -- stamp duty only applies on buy; every
        other charge here applies to both sides.
    slippage_pct_override: if given, replaces config.COSTS["slippage_pct"]
        for this call only -- the hook a liquidity-based slippage model
        (research/liquidity_costs.py) uses to apply a per-symbol rate
        instead of the flat large-cap-calibrated default. Every other
        charge is untouched; this exists specifically because slippage
        is the one line-item in this file that is a modeling assumption
        rather than a statutory rate, so it's the only one that should
        ever vary by symbol. Omitting it reproduces the exact prior
        behavior -- nothing about the default Nifty 50 cost calculation
        changes because this parameter exists.
    """
    assert side in ("buy", "sell"), f"side must be 'buy' or 'sell', got {side!r}"

    c = config.COSTS

    # Brokerage: percentage of trade value, or a flat fee, whichever is
    # lower -- the standard discount-broker formula. Defaults to 0 for
    # delivery (see module docstring), but the formula still applies if
    # you configure a non-zero brokerage_pct to model a different broker.
    brokerage = min(trade_value * c["brokerage_pct"], c["brokerage_flat"])

    # STT (Securities Transaction Tax): same 0.1% rate on both legs for
    # delivery trades.
    stt = trade_value * c["stt_pct"]

    # NSE's own cut of the trade, both sides.
    exchange_charges = trade_value * c["exchange_txn_pct"]

    # SEBI turnover fee, both sides.
    sebi_charges = trade_value * c["sebi_pct"]

    # GST: 18% on (brokerage + SEBI charges + exchange transaction
    # charges) only -- NOT on STT or stamp duty, since those are
    # themselves taxes, not a service GST applies to.
    gst = c["gst_pct"] * (brokerage + sebi_charges + exchange_charges)

    # Stamp duty: buy side only, state-mandated, uniform nationwide.
    stamp_duty = trade_value * c["stamp_duty_pct"] if side == "buy" else 0.0

    # Slippage: a MODELING ASSUMPTION (not a statutory charge) for the
    # gap between the price a strategy signals at and what you'd
    # actually get filled at in a live market. Treated as a cost
    # line-item here, deducted from trade proceeds, rather than
    # adjusted into the fill price itself -- so the fill price shown in
    # the trade log always matches the raw OHLC data exactly, which
    # matters for tracing a trade by hand against the source data.
    slippage_pct = c["slippage_pct"] if slippage_pct_override is None else slippage_pct_override
    slippage = trade_value * slippage_pct

    total = brokerage + stt + exchange_charges + sebi_charges + gst + stamp_duty + slippage

    return {
        "brokerage": brokerage,
        "stt": stt,
        "exchange_charges": exchange_charges,
        "sebi_charges": sebi_charges,
        "gst": gst,
        "stamp_duty": stamp_duty,
        "slippage": slippage,
        "total": total,
    }


if __name__ == "__main__":
    # Quick manual check: a Rs 1,00,000 buy and sell at the current defaults.
    buy = calculate_trade_cost(100_000, "buy")
    sell = calculate_trade_cost(100_000, "sell")
    print("Buy Rs 1,00,000:", buy)
    print("Sell Rs 1,00,000:", sell)
