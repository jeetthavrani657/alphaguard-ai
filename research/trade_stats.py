"""
research/trade_stats.py

The numbers the go-live gates (GO_LIVE_GATES.md) need about a paper book's trades: how many, how many won, the average win and loss, the profit factor, the average
trade, and the worst single loss as a share of the account. Pure functions: a list of trades goes in, a dict comes out. Nothing here reads a file or touches a broker.

Two honest choices:
  * A "trade" is the life of a position, from the fill that opened it to the fill that brought it back to zero shares (several buys and trims in between are all part
    of it). A trim at a rebalance is not a closed trade.
  * Every figure comes in two versions: `closed` (only trades that have ended) and `all_in` (closed trades plus the positions still open, each marked at the last
    close with the sale's costs deducted). A rule that holds its losers open would look perfect on closed trades alone; the gates use `all_in`.
"""


def summarize(trades: list, account: float) -> dict:
    """
    `trades` is a list of {"pnl": rupees after all costs, "ret_pct": the same as a % of what the trade cost}. `account` is the capital the loss is measured against.
    Returns the counts and the averages; every average is None when there is nothing to average.
    """
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    won, lost = sum(t["pnl"] for t in wins), -sum(t["pnl"] for t in losses)
    worst = min((t["pnl"] for t in trades), default=None)
    return {
        "n_trades": n,
        "n_winning": len(wins),
        "win_rate_pct": 100.0 * len(wins) / n if n else None,
        "avg_win_pct": sum(t["ret_pct"] for t in wins) / len(wins) if wins else None,
        "avg_loss_pct": sum(t["ret_pct"] for t in losses) / len(losses) if losses else None,
        "profit_factor": won / lost if lost > 0 else None,                 # None when no trade lost: there is no ratio to show
        "expectancy_pct": sum(t["ret_pct"] for t in trades) / n if n else None,
        "worst_loss_inr": (worst if worst < 0 else 0.0) if n else None,    # no trade lost: the worst loss is zero; no trade at all: nothing to say
        "worst_loss_pct_of_account": 100.0 * (worst if worst < 0 else 0.0) / account if n and account > 0 else None,
    }


def closed_from_log(log) -> list:
    """Closed trades of a per-stock book from its trade log (columns quantity, entry_price, exit_price, total_costs, return_pct; return_pct is already after costs)."""
    out = []
    for t in log.itertuples():
        out.append({"pnl": t.quantity * (t.exit_price - t.entry_price) - t.total_costs, "ret_pct": float(t.return_pct)})
    return out


def open_marked(positions: list, sell_cost) -> list:
    """
    Still-open positions of a per-stock book, marked at the last close: [{"quantity", "entry_price", "buy_costs_total", "last_close"}].
    `sell_cost(value)` is the cost of selling that much, deducted because the position would pay it on the way out.
    """
    out = []
    for p in positions:
        basis = p["quantity"] * p["entry_price"] + p["buy_costs_total"]
        value = p["quantity"] * p["last_close"]
        pnl = value - sell_cost(value) - basis
        out.append({"pnl": pnl, "ret_pct": 100.0 * pnl / basis if basis > 0 else 0.0})
    return out


def round_trips(fills: list, last_price: dict, sell_cost) -> tuple:
    """
    (closed, open) trades of a one-account book from its fills, [{"date", "symbol", "side": "buy"|"sell", "shares", "price", "costs" (None counts as 0)}], oldest first.
    A trade is a position's whole life; buys add to its cost, sells add to its proceeds, and when the shares are back to zero it is closed. A position still held at the end is
    marked at `last_price[symbol]` with `sell_cost(value)` deducted. Raises ValueError if a sell exceeds what is held, or a held symbol has no last price: wrong statistics
    would be worse than none.
    """
    pos, closed = {}, []
    for f in sorted(fills, key=lambda f: str(f["date"])):          # stable: fills of one day keep their order
        p = pos.setdefault(f["symbol"], {"shares": 0, "cost": 0.0, "proceeds": 0.0})
        costs = f["costs"] or 0.0
        if f["side"].lower() == "buy":
            p["shares"] += f["shares"]
            p["cost"] += f["shares"] * f["price"] + costs
        else:
            if f["shares"] > p["shares"]:
                raise ValueError(f"{f['symbol']}: sold {f['shares']} shares on {f['date']} but held {p['shares']}")
            p["shares"] -= f["shares"]
            p["proceeds"] += f["shares"] * f["price"] - costs
            if p["shares"] == 0:
                pnl = p["proceeds"] - p["cost"]
                closed.append({"pnl": pnl, "ret_pct": 100.0 * pnl / p["cost"] if p["cost"] > 0 else 0.0})
                pos[f["symbol"]] = {"shares": 0, "cost": 0.0, "proceeds": 0.0}
    still_open = []
    for symbol, p in pos.items():
        if p["shares"] > 0:
            if symbol not in last_price:
                raise ValueError(f"{symbol} is still held but has no last price")
            value = p["shares"] * last_price[symbol]
            pnl = p["proceeds"] + value - sell_cost(value) - p["cost"]
            still_open.append({"pnl": pnl, "ret_pct": 100.0 * pnl / p["cost"] if p["cost"] > 0 else 0.0})
    return closed, still_open


def book_stats(closed: list, still_open: list, account: float) -> dict:
    """The two versions of the numbers: closed trades only, and closed plus open (marked)."""
    return {"account_inr": account, "n_open": len(still_open), "closed": summarize(closed, account), "all_in": summarize(closed + still_open, account)}
