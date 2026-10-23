"""
execution/sim_broker.py

A SIMULATED broker that lives entirely on this computer: an account file (cash, positions, orders), a way to "send" an approved ticket
to it, and a way to fill it from price files that are already on disk. Nothing here reaches a network, a broker or a real account (see
paper_oms.py; a test enforces it). It exists so that the plumbing around orders (limits, approval, fills, costs, reconciliation) can be
rehearsed with real prices and no money.

How a fill is decided (deliberately conservative, written down so it can be argued with):
  * An order is a one-day LIMIT order. It can only fill in the FIRST session AFTER the day it was submitted (never the same day, so a
    decision made on a close cannot trade at that close).
  * It fills at that session's OPEN, and only if the open is within the limit: a buy needs open <= limit, a sell needs open >= limit.
    If the open is on the wrong side of the limit the order is cancelled unfilled, even though a real resting order might have filled later in
    the day. A fill therefore never rests on an intraday price this layer does not have.
  * The engine's Indian cost model (STT, stamp duty, exchange fee, SEBI fee, GST, 0.05% slippage) is charged on every fill.
  * A buy that the cash cannot cover is rejected; sells are processed first so their proceeds can fund buys. Short selling is impossible.
  * If no session after the submission day exists in the data yet, the order keeps waiting; after 7 calendar days without one it expires.
"""

import json
import os
from datetime import datetime, timedelta

import pandas as pd

import costs
import paper_oms as oms

ACCOUNT_FILE = "sim_account.json"
EXPIRY_DAYS = 7


# ---- the account file ---------------------------------------------------------------------------------------------------------------

def _account_path(state_dir: str | None) -> str:
    return os.path.join(state_dir or oms.STATE_DIR, ACCOUNT_FILE)


def new_account(initial_cash: float) -> dict:
    return {"initial_cash": float(initial_cash), "cash": float(initial_cash), "positions": {}, "orders": {}}


def load_account(state_dir: str | None = None, initial_cash: float = 1_000_000.0) -> dict:
    path = _account_path(state_dir)
    if not os.path.exists(path):
        return new_account(initial_cash)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_account(account: dict, state_dir: str | None = None) -> None:
    """Written to a temporary file and then swapped in, so a crash never leaves half an account on disk."""
    folder = state_dir or oms.STATE_DIR
    os.makedirs(folder, exist_ok=True)
    tmp = _account_path(state_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(account, f, indent=1, sort_keys=True)
    os.replace(tmp, _account_path(state_dir))


def account_equity(account: dict, last_prices: dict) -> float:
    """Cash plus the shares held at their last prices. A held stock with no price makes the value unknown, which is an error, not zero."""
    total = float(account["cash"])
    for symbol, qty in account["positions"].items():
        price = last_prices.get(symbol)
        if price is None:
            raise ValueError(f"no price for {symbol}, so the account cannot be valued")
        total += qty * price
    return total


# ---- submitting ------------------------------------------------------------------------------------------------------------------------

def submit(ticket: dict, account: dict, trade_day: str, state_dir: str | None = None) -> dict:
    """
    "Send" an APPROVED ticket to the simulated broker on `trade_day` (the day it is sent, YYYY-MM-DD). Returns {"accepted": bool, "reason": str}.
    The same client id is accepted once; a second attempt is refused. The switch is checked again here, at the last moment, and fails closed.
    """
    engaged, why = oms.kill_switch_engaged(state_dir)
    if engaged:
        return {"accepted": False, "reason": why}
    if ticket.get("status") != "APPROVED":
        return {"accepted": False, "reason": "only an approved ticket can be sent"}
    cid = ticket["client_id"]
    if cid in account["orders"] or cid in oms.already_submitted_ids(state_dir):
        return {"accepted": False, "reason": "this exact order was already submitted"}
    account["orders"][cid] = {"ticket": dict(ticket), "status": "WORKING", "submitted_on": trade_day, "fill": None, "note": ""}
    oms.append_event("SUBMITTED", {"client_id": cid, "trade_day": trade_day, "symbol": ticket["symbol"], "side": ticket["side"],
                                   "quantity": ticket["quantity"], "limit_price": ticket["limit_price"],
                                   "value": ticket["quantity"] * ticket["reference_price"]}, state_dir)
    return {"accepted": True, "reason": ""}


# ---- filling -----------------------------------------------------------------------------------------------------------------------------

def _next_session_open(prices: pd.DataFrame | None, submitted_on: str):
    """(date, open) of the first session strictly after the submission day, or None if the data does not have one yet."""
    if prices is None or prices.empty:
        return None
    later = prices[prices.index > pd.Timestamp(submitted_on)]
    if later.empty:
        return None
    return later.index[0], float(later["open"].iloc[0])


def process_fills(account: dict, price_frames: dict, as_of: str, state_dir: str | None = None) -> list:
    """
    Fill, cancel, reject or keep waiting every WORKING order, sells first. `price_frames` is {symbol: DataFrame indexed by date with an `open`
    column} read from local files. Returns the list of changes made, each {"client_id", "status", "note"}. Running it twice changes nothing the second time.
    """
    changes = []
    working = [o for o in account["orders"].values() if o["status"] == "WORKING"]
    working.sort(key=lambda o: (o["ticket"]["side"] != "SELL", o["submitted_on"], o["ticket"]["symbol"]))      # sells before buys
    for order in working:
        t, cid = order["ticket"], order["ticket"]["client_id"]
        session = _next_session_open(price_frames.get(t["symbol"]), order["submitted_on"])
        if session is None:
            if (datetime.strptime(as_of, "%Y-%m-%d") - datetime.strptime(order["submitted_on"], "%Y-%m-%d")).days > EXPIRY_DAYS:
                order.update(status="CANCELLED", note=f"expired: no session in the data within {EXPIRY_DAYS} days")
                oms.append_event("CANCELLED", {"client_id": cid, "note": order["note"]}, state_dir)
                changes.append({"client_id": cid, "status": "CANCELLED", "note": order["note"]})
            continue                                                                         # no session yet: keep waiting
        day, open_price = session
        side, qty, limit = t["side"], int(t["quantity"]), float(t["limit_price"])
        within = open_price <= limit if side == "BUY" else open_price >= limit
        if not within:
            order.update(status="CANCELLED", note=f"the open {open_price:.2f} on {day.date()} was beyond the limit {limit:.2f}")
            oms.append_event("CANCELLED", {"client_id": cid, "note": order["note"]}, state_dir)
            changes.append({"client_id": cid, "status": "CANCELLED", "note": order["note"]})
            continue
        value = qty * open_price
        fee = costs.calculate_trade_cost(value, side.lower())["total"]
        held = int(account["positions"].get(t["symbol"], 0))
        if side == "BUY" and value + fee > account["cash"]:
            order.update(status="REJECTED", note=f"insufficient cash: needs {value + fee:,.2f}, has {account['cash']:,.2f}")
        elif side == "SELL" and qty > held:
            order.update(status="REJECTED", note=f"only {held} shares held")
        else:
            cash_change = -(value + fee) if side == "BUY" else value - fee
            account["cash"] = round(account["cash"] + cash_change, 6)
            account["positions"][t["symbol"]] = held + qty if side == "BUY" else held - qty
            if account["positions"][t["symbol"]] == 0:
                del account["positions"][t["symbol"]]
            order.update(status="FILLED", note="", fill={"date": day.strftime("%Y-%m-%d"), "price": open_price, "quantity": qty, "value": value,
                                                          "costs": fee, "cash_change": cash_change})
        kind = "FILLED" if order["status"] == "FILLED" else "REJECTED_BY_BROKER"
        oms.append_event(kind, {"client_id": cid, "symbol": t["symbol"], "side": side, "quantity": qty,
                                "fill": order["fill"], "note": order["note"]}, state_dir)
        changes.append({"client_id": cid, "status": order["status"], "note": order["note"]})
    return changes


# ---- reconciliation ------------------------------------------------------------------------------------------------------------------------

def reconcile(account: dict, batch: dict, state_dir: str | None = None, cash_tolerance: float = 1.0) -> dict:
    """
    Compare what the account holds with what the orders explain. `batch` carries `start_positions` (shares held before the batch),
    `intended_positions` (what the rule wanted to hold) and `client_ids` (the tickets that were sent).

      * UNEXPLAINED: the account's shares differ from start + the fills of this batch, or its cash differs from the initial cash plus every fill's
        cash flow by more than `cash_tolerance`. Something changed that no order accounts for. This sets the halt: nothing new is
        accepted until a person has looked and cleared it with a note.
      * UNFILLED: the account differs from what the rule intended only because an order was cancelled or rejected. That is expected with limit
        orders; it is reported, not treated as an error, and the next run will propose the missing trades again.
    """
    start, intended = dict(batch["start_positions"]), dict(batch["intended_positions"])
    expected = dict(start)
    for cid in batch["client_ids"]:
        order = account["orders"].get(cid)
        if order and order["status"] == "FILLED":
            sign = 1 if order["ticket"]["side"] == "BUY" else -1
            expected[order["ticket"]["symbol"]] = expected.get(order["ticket"]["symbol"], 0) + sign * order["fill"]["quantity"]
    actual = {s: q for s, q in account["positions"].items() if q}
    expected = {s: q for s, q in expected.items() if q}
    unexplained = {s: {"expected_from_fills": expected.get(s, 0), "actual": actual.get(s, 0)}
                   for s in sorted(set(expected) | set(actual)) if expected.get(s, 0) != actual.get(s, 0)}
    all_cash = sum(o["fill"]["cash_change"] for o in account["orders"].values() if o["status"] == "FILLED")
    cash_gap = account["cash"] - (account["initial_cash"] + all_cash)
    intended_clean = {s: q for s, q in intended.items() if q}
    unfilled = {s: {"intended": intended_clean.get(s, 0), "actual": actual.get(s, 0)}
                for s in sorted(set(intended_clean) | set(actual)) if intended_clean.get(s, 0) != actual.get(s, 0)}
    ok = not unexplained and abs(cash_gap) <= cash_tolerance
    report = {"ok": ok, "unexplained_positions": unexplained, "cash_gap": round(cash_gap, 2), "unfilled_vs_intended": unfilled}
    oms.append_event("RECONCILED", report, state_dir)
    if not ok:
        oms.set_halt("reconciliation found a difference no order explains: " + json.dumps({"positions": unexplained, "cash_gap": round(cash_gap, 2)}), state_dir)
    return report
