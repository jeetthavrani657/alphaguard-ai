"""
execution/run_paper.py

The command-line steps of the PAPER execution layer. Everything is local and simulated (see paper_oms.py and sim_broker.py; a test keeps this
folder free of network and broker code). The steps are separate on purpose, so that a person stands between the rule and the (simulated) account:

    python execution/run_paper.py propose --book momentum_nifty50     # tickets from the rule's target list, run through the limits; sends nothing
    python execution/run_paper.py approve --all --note "why I agree"  # the HUMAN step: only approved tickets can ever be sent
    python execution/run_paper.py submit                              # send the approved tickets to the simulated broker
    python execution/run_paper.py fill                                # after the next session's prices are on disk: fills, cancels, costs
    python execution/run_paper.py reconcile                           # does the account match what the fills explain? (halts if not)
    python execution/run_paper.py status                              # switch, journal, account, orders
    python execution/run_paper.py kill --reason "..."  |  release  |  clear-halt --note "..."

Targets come from reports/output/forward_books_latest.json (the frozen rules' latest target list). Prices come from the local files in
data/cache/ and nothing else; this layer never downloads anything.
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd

import config
import paper_oms as oms
import sim_broker as sb

DEFAULT_PATHS = {"state": oms.STATE_DIR,
                 "books": os.path.join(PROJECT_ROOT, "reports", "output", "forward_books_latest.json"),
                 "cache": os.path.join(PROJECT_ROOT, "data", "cache")}
BATCH_PREFIX = "batch_"


class StepError(Exception):
    """A step that cannot go ahead, with the reason in words. The command line prints it and exits with an error."""


# ---- reading local files ---------------------------------------------------------------------------------------------------------------

def local_prices(symbol: str, cache_dir: str) -> pd.DataFrame | None:
    """The cached daily prices for one stock (date index; open, high, low, close), or None if the file is not there. Local files only."""
    path = os.path.join(cache_dir, f"{symbol}.NS.csv")
    if not os.path.exists(path):
        return None
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    return frame if not frame.empty else None


def load_book_targets(book_id: str, books_path: str) -> dict:
    """{"formation_date", "targets_pct": {symbol: weight}} for one paper book, from the forward-books file the daily run writes."""
    if not os.path.exists(books_path):
        raise StepError(f"{books_path} does not exist; run the daily forward run first")
    with open(books_path, encoding="utf-8") as f:
        books = {b["id"]: b for b in json.load(f)["books"]}
    if book_id not in books:
        raise StepError(f"unknown book '{book_id}'; choose one of: {', '.join(sorted(books))}")
    holdings = books[book_id].get("holdings") or []
    if not holdings:
        raise StepError(f"book '{book_id}' has no target holdings yet")
    dates = {h["as_of_formation_date"] for h in holdings}
    if len(dates) != 1:
        raise StepError(f"book '{book_id}' mixes formation dates {sorted(dates)}")
    return {"formation_date": dates.pop(), "targets_pct": {h["symbol"]: float(h["target_weight_pct"]) for h in holdings}}


def _batch_files(state_dir: str) -> list:
    if not os.path.isdir(state_dir):
        return []
    return sorted(n for n in os.listdir(state_dir) if n.startswith(BATCH_PREFIX) and n.endswith(".json"))


def _write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True, default=str)
    os.replace(tmp, path)


def _load_batch(paths: dict, name: str | None) -> tuple:
    files = _batch_files(paths["state"])
    if not files:
        raise StepError("there is no batch yet; run 'propose' first")
    chosen = name or files[-1]                                       # the newest one unless a name is given
    if chosen not in files:
        raise StepError(f"unknown batch '{chosen}'; the batches are: {', '.join(files)}")
    path = os.path.join(paths["state"], chosen)
    with open(path, encoding="utf-8") as f:
        return chosen, path, json.load(f)


# ---- propose -----------------------------------------------------------------------------------------------------------------------------

def cmd_propose(book_id: str, paths: dict, initial_cash: float | None = None, replace: bool = False) -> dict:
    """Build tickets for the book's latest target list and run them through the limits. Sends nothing and approves nothing."""
    initial_cash = float(config.INITIAL_CAPITAL if initial_cash is None else initial_cash)
    target = load_book_targets(book_id, paths["books"])
    account = sb.load_account(paths["state"], initial_cash)
    symbols = sorted(set(target["targets_pct"]) | set(account["positions"]))
    frames = {s: local_prices(s, paths["cache"]) for s in symbols}
    last = {s: (f.index[-1], float(f["close"].iloc[-1])) for s, f in frames.items() if f is not None}
    if not last:
        raise StepError("no cached prices for any of these stocks")
    session = max(d for d, _ in last.values())
    prices, stale = {}, []
    for s, (d, px) in last.items():
        if d == session:
            prices[s] = px
        else:
            stale.append((s, f"its last price is from {d.date()}, not {session.date()}"))
    name = f"{BATCH_PREFIX}{book_id}_{target['formation_date']}.json"
    path = os.path.join(paths["state"], name)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            earlier = json.load(f)
        if any(t["status"] != "PROPOSED" for t in earlier["tickets"]):             # once anything was approved the batch is a record: never replaced
            raise StepError(f"{name} already has approved or sent tickets; it is not replaced")
        if not replace:
            raise StepError(f"{name} already exists; use --replace to rebuild it (only possible while nothing in it was approved)")
    try:
        equity = sb.account_equity(account, prices)
    except ValueError as e:                                                         # a held stock has no current price, so the account cannot be valued
        raise StepError(f"cannot value the account: {e}") from None
    limits = oms.default_limits(equity)
    priced_targets = {s: w for s, w in target["targets_pct"].items() if s in prices}      # a stock with a stale price is reported once, below, and not traded
    built = oms.build_tickets(book_id, target["formation_date"], priced_targets, account["positions"], prices, equity, limits)
    checked = oms.check_tickets(built["tickets"], account["positions"], equity, limits, set(symbols), session.strftime("%Y-%m-%d"), paths["state"])
    intended = {s: int(math.floor(target["targets_pct"].get(s, 0.0) / 100.0 * equity / prices[s])) for s in symbols if s in prices}
    batch = {"book": book_id, "formation_date": target["formation_date"], "session_day": session.strftime("%Y-%m-%d"), "equity": equity,
             "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "start_positions": dict(account["positions"]),
             "intended_positions": intended, "limits": limits, "tickets": checked["passed"],
             "rejected": [{"ticket": t, "reasons": r} for t, r in checked["rejected"]], "skipped": built["skipped"] + stale}
    os.makedirs(paths["state"], exist_ok=True)
    _write_json(path, batch)
    oms.append_event("PROPOSED", {"batch": name, "tickets": [t["client_id"] for t in batch["tickets"]],
                                  "rejected": [(r["ticket"]["client_id"], r["reasons"]) for r in batch["rejected"]], "equity": equity}, paths["state"])
    return {"batch": name, **batch}


# ---- approve (the human step) ---------------------------------------------------------------------------------------------------------

def cmd_approve(paths: dict, ids: list | None, approve_all: bool, note: str, batch_name: str | None = None, initial_cash: float | None = None) -> dict:
    """
    A person agrees to named tickets (or all of them) and says why in a written note. The limits are run AGAIN here, because the state may have changed
    since the proposal (a kill switch, orders already sent today). Only tickets that are still PROPOSED and still pass become APPROVED.
    """
    if not (note or "").strip():
        raise StepError("approving needs a written note saying what was checked")
    if not approve_all and not ids:
        raise StepError("name the tickets to approve with --ids, or use --all")
    name, path, batch = _load_batch(paths, batch_name)
    account = sb.load_account(paths["state"], float(config.INITIAL_CAPITAL if initial_cash is None else initial_cash))
    chosen = [t for t in batch["tickets"] if t["status"] == "PROPOSED" and (approve_all or t["client_id"] in set(ids or []))]
    unknown = sorted(set(ids or []) - {t["client_id"] for t in batch["tickets"]})
    if unknown:
        raise StepError(f"not tickets of this batch (or rejected by the limits): {', '.join(unknown)}")
    prices = {t["symbol"]: t["reference_price"] for t in batch["tickets"]}
    checked = oms.check_tickets(chosen, account["positions"], batch["equity"], batch["limits"], set(prices) | set(account["positions"]),
                                batch["session_day"], paths["state"])
    approved = {t["client_id"] for t in checked["passed"]}
    for t in batch["tickets"]:
        if t["client_id"] in approved:
            t["status"] = "APPROVED"
            oms.append_event("APPROVED", {"client_id": t["client_id"], "batch": name, "note": note}, paths["state"])
    _write_json(path, batch)
    return {"batch": name, "approved": sorted(approved), "refused_now": [(t["client_id"], r) for t, r in checked["rejected"]]}


# ---- submit, fill, reconcile ---------------------------------------------------------------------------------------------------------

def cmd_submit(paths: dict, batch_name: str | None = None, initial_cash: float | None = None) -> dict:
    name, path, batch = _load_batch(paths, batch_name)
    account = sb.load_account(paths["state"], float(config.INITIAL_CAPITAL if initial_cash is None else initial_cash))
    sent, refused = [], []
    for t in batch["tickets"]:
        if t["status"] != "APPROVED":
            continue
        result = sb.submit(t, account, batch["session_day"], paths["state"])
        if result["accepted"]:
            t["status"] = "SUBMITTED"
            sent.append(t["client_id"])
        else:
            refused.append((t["client_id"], result["reason"]))
    sb.save_account(account, paths["state"])
    _write_json(path, batch)
    return {"batch": name, "sent": sent, "refused": refused}


def cmd_fill(paths: dict, initial_cash: float | None = None) -> dict:
    account = sb.load_account(paths["state"], float(config.INITIAL_CAPITAL if initial_cash is None else initial_cash))
    working = [o["ticket"]["symbol"] for o in account["orders"].values() if o["status"] == "WORKING"]
    frames = {s: local_prices(s, paths["cache"]) for s in set(working)}
    dates = [f.index[-1] for f in frames.values() if f is not None]
    if not dates:
        return {"as_of": None, "changes": [], "note": "no working orders, or no cached prices for them"}
    as_of = max(dates).strftime("%Y-%m-%d")
    changes = sb.process_fills(account, frames, as_of, paths["state"])
    sb.save_account(account, paths["state"])
    for name in _batch_files(paths["state"]):                                  # bring every batch's ticket statuses in line with the account
        path = os.path.join(paths["state"], name)
        with open(path, encoding="utf-8") as f:
            batch = json.load(f)
        for t in batch["tickets"]:
            order = account["orders"].get(t["client_id"])
            if order and order["status"] != "WORKING":
                t["status"] = order["status"]
        _write_json(path, batch)
    return {"as_of": as_of, "changes": changes}


def cmd_reconcile(paths: dict, batch_name: str | None = None, initial_cash: float | None = None) -> dict:
    name, path, batch = _load_batch(paths, batch_name)
    account = sb.load_account(paths["state"], float(config.INITIAL_CAPITAL if initial_cash is None else initial_cash))
    sent = [t["client_id"] for t in batch["tickets"] if t["status"] in ("SUBMITTED", "FILLED", "CANCELLED", "REJECTED")]
    if any(account["orders"][c]["status"] == "WORKING" for c in sent if c in account["orders"]):
        raise StepError("some orders are still waiting for their session; run 'fill' once the prices are on disk")
    report = sb.reconcile(account, {"start_positions": batch["start_positions"], "intended_positions": batch["intended_positions"], "client_ids": sent}, paths["state"])
    return {"batch": name, **report}


def cmd_status(paths: dict, initial_cash: float | None = None) -> dict:
    engaged, why = oms.kill_switch_engaged(paths["state"])
    ok, problem = oms.verify_journal(paths["state"])
    account = sb.load_account(paths["state"], float(config.INITIAL_CAPITAL if initial_cash is None else initial_cash))
    last = {}
    for s in account["positions"]:
        f = local_prices(s, paths["cache"])
        if f is not None:
            last[s] = float(f["close"].iloc[-1])
    try:
        equity = sb.account_equity(account, last)
    except ValueError as e:
        equity = None
        problem = problem or str(e)
    counts = {}
    for o in account["orders"].values():
        counts[o["status"]] = counts.get(o["status"], 0) + 1
    return {"stopped": engaged, "why_stopped": why, "journal_ok": ok, "journal_problem": problem, "cash": account["cash"], "positions": account["positions"],
            "equity": equity, "orders_by_status": counts, "batches": _batch_files(paths["state"])}


# ---- printing and the command line -----------------------------------------------------------------------------------------------------------

def _show_batch(r: dict) -> None:
    print(f"Batch {r['batch']}: rule {r['book']}, formed {r['formation_date']}, prices of {r['session_day']}, account value {r['equity']:,.0f}")
    for t in r["tickets"]:
        print(f"  {t['client_id']}  {t['side']:<4} {t['quantity']:>6} {t['symbol']:<12} limit {t['limit_price']:>9.2f}  about {t['quantity'] * t['reference_price']:>10,.0f}  | {t['reason']}")
    for item in r["rejected"]:
        t = item["ticket"]
        print(f"  REJECTED {t['side']} {t['quantity']} {t['symbol']}: {'; '.join(item['reasons'])}")
    for symbol, why in r["skipped"]:
        print(f"  skipped {symbol}: {why}")
    print(f"{len(r['tickets'])} ticket(s) wait for your approval; nothing has been sent.")


def main(argv=None, paths: dict | None = None) -> int:
    paths = paths or DEFAULT_PATHS
    ap = argparse.ArgumentParser(description="Paper execution layer: local and simulated, no broker and no network.")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("propose"); p.add_argument("--book", required=True); p.add_argument("--replace", action="store_true")
    a = sub.add_parser("approve"); a.add_argument("--ids", default=""); a.add_argument("--all", action="store_true"); a.add_argument("--note", default=""); a.add_argument("--batch")
    for name in ("submit", "reconcile"):
        q = sub.add_parser(name); q.add_argument("--batch")
    sub.add_parser("fill"); sub.add_parser("status")
    k = sub.add_parser("kill"); k.add_argument("--reason", required=True)
    sub.add_parser("release")
    c = sub.add_parser("clear-halt"); c.add_argument("--note", required=True)
    args = ap.parse_args(argv)
    try:
        if args.command == "propose":
            _show_batch(cmd_propose(args.book, paths, replace=args.replace))
        elif args.command == "approve":
            r = cmd_approve(paths, [i for i in args.ids.split(",") if i], args.all, args.note, args.batch)
            print(f"approved {len(r['approved'])} ticket(s) in {r['batch']}" + "".join(f"\n  refused now: {c}: {'; '.join(why)}" for c, why in r["refused_now"]))
        elif args.command == "submit":
            r = cmd_submit(paths, args.batch)
            print(f"sent {len(r['sent'])} ticket(s) to the simulated broker" + "".join(f"\n  refused: {c}: {why}" for c, why in r["refused"]))
        elif args.command == "fill":
            r = cmd_fill(paths)
            print(f"prices as of {r['as_of']}: " + (", ".join(f"{c['client_id']} {c['status']}" for c in r["changes"]) or r.get("note", "nothing to do")))
        elif args.command == "reconcile":
            r = cmd_reconcile(paths, args.batch)
            print("RECONCILED: the account matches what the fills explain" if r["ok"] else f"HALTED: {r['unexplained_positions']} cash gap {r['cash_gap']}")
            if r["unfilled_vs_intended"]:
                print(f"  not filled (limit orders): {r['unfilled_vs_intended']}")
            return 0 if r["ok"] else 2
        elif args.command == "status":
            print(json.dumps(cmd_status(paths), indent=1, default=str))
        elif args.command == "kill":
            oms.engage_kill(args.reason, paths["state"]); print("kill switch engaged")
        elif args.command == "release":
            oms.release_kill(paths["state"]); print("kill switch released (a reconciliation halt, if any, is separate)")
        elif args.command == "clear-halt":
            oms.clear_halt(args.note, paths["state"]); print("halt cleared and the note journalled")
    except (StepError, ValueError) as e:
        print(f"cannot do that: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
