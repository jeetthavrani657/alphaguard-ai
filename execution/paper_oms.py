"""
execution/paper_oms.py

The order-handling core of the PAPER execution layer (EXECUTION_DESIGN.md, Gate 3). Everything here is LOCAL and SIMULATED:

  * It never touches a network, a broker, an account, or a market-data service. There is no import that could. A test scans this folder
    for network libraries and broker addresses and fails if one appears (tests/test_paper_oms.py), so the file cannot quietly grow a
    live order path. CLAUDE.md rule 5 stands: no order, GTT, position or funds call exists anywhere in the project.
  * It consumes a frozen rule's already-computed target list (symbol -> target weight) and never computes a signal itself.
  * Its purpose is to rehearse the plumbing a real system would need BEFORE any real money is near it: order tickets with written
    reasons, hard limits, a kill switch that fails closed, idempotent client ids, a tamper-evident journal, and (in sim_broker.py)
    reconciliation of what was done against what was intended.

Flow:  build_tickets  ->  check_tickets (limits)  ->  a person approves  ->  sim_broker fills at the next session's open  ->  reconcile.
Nothing is ever "approved" by code on its own: the human step is a separate, explicit call.
"""

import hashlib
import json
import math
import os
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.join(PROJECT_ROOT, "execution", "state")      # git-ignored run state: journal, account, tickets, the kill file
KILL_FILE = "KILL"                                                  # exists = nothing new may be submitted
HALT_FILE = "HALT_RECON"                                            # written when reconciliation finds a difference; needs a person to clear it
JOURNAL_FILE = "journal.jsonl"
GENESIS = "0" * 64                                                  # the "previous hash" of the very first journal line


# ---------------------------------------------------------------------------------------------------------------------
# Kill switch. It FAILS CLOSED: if the state folder cannot be read, trading is treated as stopped.
# ---------------------------------------------------------------------------------------------------------------------

def kill_switch_engaged(state_dir: str | None = None) -> tuple:
    """(engaged, why). Engaged when the KILL file exists, when a reconciliation halt is in force, or when the state cannot be read at all."""
    folder = state_dir or STATE_DIR
    try:
        os.makedirs(folder, exist_ok=True)
        names = set(os.listdir(folder))
    except OSError as e:                                            # cannot tell: the safe answer is "stopped"
        return True, f"the state folder cannot be read ({type(e).__name__}), so the switch fails closed"
    if KILL_FILE in names:
        return True, "the kill switch is engaged"
    if HALT_FILE in names:
        try:                                                        # say WHAT was found, so whoever looks does not have to dig for it
            with open(os.path.join(folder, HALT_FILE), encoding="utf-8") as f:
                detail = f.read().strip()
        except OSError:
            detail = "(the reason could not be read)"
        return True, f"halted after a reconciliation difference; a person must look and clear it: {detail}"
    return False, ""


def engage_kill(reason: str, state_dir: str | None = None) -> None:
    folder = state_dir or STATE_DIR
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, KILL_FILE), "w", encoding="utf-8") as f:
        f.write(reason + "\n")
    append_event("KILL_ENGAGED", {"reason": reason}, folder)


def release_kill(state_dir: str | None = None) -> None:
    """Removes the KILL file only. A reconciliation halt is a separate switch and is NOT cleared here."""
    folder = state_dir or STATE_DIR
    path = os.path.join(folder, KILL_FILE)
    if os.path.exists(path):
        os.remove(path)
        append_event("KILL_RELEASED", {}, folder)


def set_halt(reason: str, state_dir: str | None = None) -> None:
    folder = state_dir or STATE_DIR
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, HALT_FILE), "w", encoding="utf-8") as f:
        f.write(reason + "\n")
    append_event("HALT_SET", {"reason": reason}, folder)


def clear_halt(note: str, state_dir: str | None = None) -> None:
    """A person has looked at the reconciliation difference. The note is required and goes into the journal."""
    if not note.strip():
        raise ValueError("clearing a halt needs a written note saying what was checked")
    folder = state_dir or STATE_DIR
    path = os.path.join(folder, HALT_FILE)
    if os.path.exists(path):
        os.remove(path)
        append_event("HALT_CLEARED", {"note": note}, folder)


# ---------------------------------------------------------------------------------------------------------------------
# The journal: append-only, one JSON line per event, each line carrying the hash of the line before it, so an edit,
# a deletion or a reordering in the middle is detectable. (It shows tampering; it does not prevent it.)
# ---------------------------------------------------------------------------------------------------------------------

def _hash_entry(entry: dict) -> str:
    body = {k: entry[k] for k in ("seq", "time", "kind", "payload", "prev")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def read_journal(state_dir: str | None = None) -> list:
    path = os.path.join(state_dir or STATE_DIR, JOURNAL_FILE)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_event(kind: str, payload: dict, state_dir: str | None = None, now: datetime | None = None) -> dict:
    """Add one event to the journal and return it. `now` is for tests."""
    folder = state_dir or STATE_DIR
    os.makedirs(folder, exist_ok=True)
    existing = read_journal(folder)
    entry = {"seq": len(existing) + 1, "time": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"), "kind": kind,
             "payload": payload, "prev": existing[-1]["hash"] if existing else GENESIS}
    entry["hash"] = _hash_entry(entry)
    with open(os.path.join(folder, JOURNAL_FILE), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
    return entry


def verify_journal(state_dir: str | None = None) -> tuple:
    """(ok, problem). Recomputes the whole chain: every sequence number, link and hash must be as written."""
    prev = GENESIS
    for i, entry in enumerate(read_journal(state_dir), start=1):
        if entry.get("seq") != i:
            return False, f"line {i}: the sequence number is {entry.get('seq')}"
        if entry.get("prev") != prev:
            return False, f"line {i}: it does not follow the line before it"
        if _hash_entry(entry) != entry.get("hash"):
            return False, f"line {i}: its contents do not match its hash"
        prev = entry["hash"]
    return True, ""


def already_submitted_ids(state_dir: str | None = None) -> set:
    """Client ids that have already been submitted, so the same order can never go out twice."""
    return {e["payload"]["client_id"] for e in read_journal(state_dir) if e["kind"] == "SUBMITTED"}


def _submitted_today(state_dir: str | None, day: str) -> list:
    return [e["payload"] for e in read_journal(state_dir) if e["kind"] == "SUBMITTED" and e["payload"].get("trade_day") == day]


# ---------------------------------------------------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------------------------------------------------

def default_limits(equity: float) -> dict:
    """Hard limits, as numbers. They are enforced in check_tickets and tested; they are not just a document."""
    return {"max_order_value": 0.15 * equity,          # one order may not be worth more than 15% of the account
            "max_position_weight": 0.20,               # no stock may end up above 20% of the account
            "max_orders_per_day": 60,
            "max_daily_turnover": 1.5 * equity,        # the value of everything bought and sold in a day
            "price_band": 0.03,                        # a limit price must be within 3% of the last close
            "limit_pad": 0.01,                         # the limit is set 1% through the last close, so an order is likely to fill
            "min_trade_value": 0.0025 * equity,        # a trade smaller than 0.25% of the account is not worth its costs
            "tick": 0.05}                              # NSE equity price step, in rupees


# ---------------------------------------------------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------------------------------------------------

def client_id(rule_id: str, formation_date: str, symbol: str, side: str, quantity: int) -> str:
    """
    The same decision always gets the same id, so submitting it twice (a retry after a timeout, a double click, a rerun) is recognised
    and refused rather than sent again.
    """
    return hashlib.sha256(f"{rule_id}|{formation_date}|{symbol}|{side}|{int(quantity)}".encode("utf-8")).hexdigest()[:16]


def _tick_round(price: float, tick: float) -> float:
    return round(round(price / tick) * tick, 2)


def build_tickets(rule_id: str, formation_date: str, targets_pct: dict, positions: dict, prices: dict, equity: float, limits: dict) -> dict:
    """
    Turn a target list into order tickets. `targets_pct` is {symbol: target weight in percent}; `positions` is {symbol: shares held};
    `prices` is {symbol: last close}. Returns {"tickets": [...], "skipped": [(symbol, why)]}. A symbol with no usable price is skipped and
    reported, never guessed at; a stock that is held but no longer in the target list is sold in full.
    """
    tickets, skipped = [], []
    for symbol in sorted(set(targets_pct) | {s for s, q in positions.items() if q}):
        price = prices.get(symbol)
        if price is None or not math.isfinite(price) or price <= 0:
            skipped.append((symbol, "no usable last price"))
            continue
        held = int(positions.get(symbol, 0))
        target_shares = int(math.floor(targets_pct.get(symbol, 0.0) / 100.0 * equity / price))      # whole shares, rounded down
        delta = target_shares - held
        if delta == 0 or (target_shares > 0 and abs(delta) * price < limits["min_trade_value"]):    # too small to be worth trading; exits always go
            continue
        side = "BUY" if delta > 0 else "SELL"
        pad = limits["limit_pad"] if side == "BUY" else -limits["limit_pad"]
        tickets.append({
            "client_id": client_id(rule_id, formation_date, symbol, side, abs(delta)), "rule_id": rule_id, "formation_date": formation_date,
            "symbol": symbol, "side": side, "quantity": abs(delta), "order_type": "LIMIT",
            "limit_price": _tick_round(price * (1.0 + pad), limits["tick"]), "reference_price": price, "status": "PROPOSED",
            "reason": (f"{rule_id}: hold {targets_pct.get(symbol, 0.0):.1f}% (formed {formation_date}); holding {held}, target {target_shares} shares"
                       if symbol in targets_pct else f"{rule_id}: no longer a target (formed {formation_date}); sell all {held}")})
    return {"tickets": tickets, "skipped": skipped}


def check_tickets(tickets: list, positions: dict, equity: float, limits: dict, allowed_symbols: set, trade_day: str,
                  state_dir: str | None = None) -> dict:
    """
    Run every ticket through the hard limits. Returns {"passed": [...], "rejected": [(ticket, [reasons])]}. Totals (orders and turnover for
    the day) include what the journal says was already submitted today, plus the tickets that have passed so far in this batch.
    """
    engaged, why = kill_switch_engaged(state_dir)
    if engaged:
        return {"passed": [], "rejected": [(t, [why]) for t in tickets]}                           # nothing gets through while stopped
    sent = already_submitted_ids(state_dir)
    today = _submitted_today(state_dir, trade_day)
    orders_so_far, turnover_so_far = len(today), sum(float(p.get("value", 0.0)) for p in today)
    passed, rejected = [], []
    for t in tickets:
        reasons = []
        qty, ref, lim = t.get("quantity"), t.get("reference_price"), t.get("limit_price")
        usable = (isinstance(qty, int) and not isinstance(qty, bool) and qty > 0 and all(isinstance(x, (int, float)) and math.isfinite(x) and x > 0 for x in (ref, lim)))
        if not usable:
            rejected.append((t, ["the quantity or a price is missing, zero, negative or not a number"]))
            continue
        if t["client_id"] in sent:
            reasons.append("this exact order was already submitted")
        if t["symbol"] not in allowed_symbols:
            reasons.append("the symbol is not on the allowed list")
        if t["side"] not in ("BUY", "SELL") or t.get("order_type") != "LIMIT":
            reasons.append("only LIMIT orders to buy or sell are allowed")
        if abs(lim / ref - 1.0) > limits["price_band"]:
            reasons.append(f"the limit price is more than {limits['price_band']:.0%} from the last close")
        value = qty * ref
        if value > limits["max_order_value"]:
            reasons.append(f"the order value {value:,.0f} is above the per-order limit {limits['max_order_value']:,.0f}")
        held = int(positions.get(t["symbol"], 0))
        if t["side"] == "SELL" and qty > held:
            reasons.append(f"it would sell {qty} but only {held} are held (no short selling)")
        if t["side"] == "BUY" and (held + qty) * ref / equity > limits["max_position_weight"]:
            reasons.append(f"the position would pass {limits['max_position_weight']:.0%} of the account")
        if orders_so_far + 1 > limits["max_orders_per_day"]:
            reasons.append(f"it would be order number {orders_so_far + 1} today, above {limits['max_orders_per_day']}")
        if turnover_so_far + value > limits["max_daily_turnover"]:
            reasons.append("it would take the day's traded value above the daily limit")
        if reasons:
            rejected.append((t, reasons))
        else:
            passed.append(t)
            orders_so_far += 1
            turnover_so_far += value
    return {"passed": passed, "rejected": rejected}
