"""
tests/test_paper_oms.py

execution/paper_oms.py is the order-handling core of the paper execution layer. The limits and the kill switch are only worth anything if
each one is shown to stop an order, so every rule has a test that makes it bite, and one test proves the whole folder is local-only.
"""

import glob
import json
import math
import os

import pytest

import paper_oms as oms

EQUITY = 1_000_000.0
LIMITS = oms.default_limits(EQUITY)
DAY = "2026-10-23"


# ---- ticket ids and building tickets ---------------------------------------------------------------------------------------

def test_a_client_id_is_the_same_for_the_same_decision_and_changes_with_any_part_of_it():
    base = oms.client_id("momentum", "2026-10-22", "TCS", "BUY", 100)
    assert base == oms.client_id("momentum", "2026-10-22", "TCS", "BUY", 100) and len(base) == 16
    for changed in (oms.client_id("other", "2026-10-22", "TCS", "BUY", 100), oms.client_id("momentum", "2026-10-23", "TCS", "BUY", 100),
                    oms.client_id("momentum", "2026-10-22", "INFY", "BUY", 100), oms.client_id("momentum", "2026-10-22", "TCS", "SELL", 100),
                    oms.client_id("momentum", "2026-10-22", "TCS", "BUY", 101)):
        assert changed != base


def _build(targets, positions, prices):
    return oms.build_tickets("momentum_nifty50", "2026-10-22", targets, positions, prices, EQUITY, LIMITS)


def test_tickets_buy_to_the_target_in_whole_shares_and_sell_what_is_no_longer_a_target():
    out = _build({"A": 10.0, "B": 10.0}, {"C": 50}, {"A": 100.0, "B": 250.0, "C": 40.0})
    by = {t["symbol"]: t for t in out["tickets"]}
    assert by["A"]["side"] == "BUY" and by["A"]["quantity"] == 1000                      # 10% of 1,000,000 at 100
    assert by["B"]["quantity"] == 400                                                      # 100,000 / 250, exactly
    assert by["C"]["side"] == "SELL" and by["C"]["quantity"] == 50 and "no longer a target" in by["C"]["reason"]   # an exit goes even though it is tiny
    assert all(t["status"] == "PROPOSED" and t["order_type"] == "LIMIT" and "momentum_nifty50" in t["reason"] for t in out["tickets"])
    assert by["A"]["client_id"] == oms.client_id("momentum_nifty50", "2026-10-22", "A", "BUY", 1000)


def test_whole_shares_are_rounded_down_so_the_target_is_never_exceeded():
    out = _build({"A": 10.0}, {}, {"A": 333.0})                                          # 100,000 / 333 = 300.3
    assert out["tickets"][0]["quantity"] == 300 and 300 * 333.0 <= 0.10 * EQUITY


def test_a_trade_too_small_to_be_worth_its_costs_is_not_proposed_but_an_exit_always_is():
    out = _build({"A": 10.0}, {"A": 995}, {"A": 100.0})                                  # 5 shares = Rs 500, under the 0.25% minimum
    assert out["tickets"] == []
    exit_only = _build({}, {"A": 3}, {"A": 100.0})
    assert [t["side"] for t in exit_only["tickets"]] == ["SELL"] and exit_only["tickets"][0]["quantity"] == 3


def test_limit_prices_go_one_percent_through_the_last_close_on_the_exchanges_price_step():
    out = _build({"A": 10.0}, {"C": 10}, {"A": 100.0, "C": 40.03})
    by = {t["symbol"]: t for t in out["tickets"]}
    assert by["A"]["limit_price"] == 101.0                                                # buy: 1% above
    assert by["C"]["limit_price"] == 39.65                                                # sell: 39.6297 rounded to the 0.05 step
    for t in out["tickets"]:
        assert abs(t["limit_price"] / 0.05 - round(t["limit_price"] / 0.05)) < 1e-6


@pytest.mark.parametrize("bad_price", [None, float("nan"), 0.0, -5.0, float("inf")])
def test_a_symbol_without_a_usable_price_is_skipped_and_reported_never_guessed(bad_price):
    out = _build({"A": 10.0, "B": 10.0}, {}, {"A": 100.0, "B": bad_price})
    assert [t["symbol"] for t in out["tickets"]] == ["A"] and out["skipped"] == [("B", "no usable last price")]


# ---- the hard limits -----------------------------------------------------------------------------------------------------------

def _ticket(symbol="A", side="BUY", qty=100, ref=100.0, limit=None, **kw):
    t = {"client_id": f"id-{symbol}-{side}-{qty}", "rule_id": "r", "formation_date": "2026-10-22", "symbol": symbol, "side": side, "quantity": qty,
         "order_type": "LIMIT", "limit_price": limit if limit is not None else ref, "reference_price": ref, "status": "PROPOSED", "reason": "x"}
    t.update(kw)
    return t


def _check(tickets, positions=None, limits=None, allowed=("A", "B", "C"), state_dir=None):
    return oms.check_tickets(tickets, positions or {}, EQUITY, limits or LIMITS, set(allowed), DAY, state_dir)


@pytest.fixture
def state(tmp_path):
    return str(tmp_path / "state")


def test_an_ordinary_ticket_passes_every_limit(state):
    out = _check([_ticket()], state_dir=state)
    assert len(out["passed"]) == 1 and out["rejected"] == []


@pytest.mark.parametrize("ticket,positions,text", [
    (_ticket(symbol="Z"), {}, "not on the allowed list"),
    (_ticket(order_type="MARKET"), {}, "only LIMIT"),
    (_ticket(side="HOLD"), {}, "only LIMIT"),
    (_ticket(limit=110.0), {}, "from the last close"),                                    # 10% away from the last close
    (_ticket(qty=2000), {}, "per-order limit"),                                           # 200,000 against a 150,000 limit
    (_ticket(side="SELL", qty=60), {"A": 50}, "no short selling"),
    (_ticket(qty=1900, ref=100.0), {"A": 200}, "pass 20%"),                               # a 190,000 order would also break the order limit; weight is reported too
])
def test_each_limit_rejects_the_ticket_that_breaks_it(state, ticket, positions, text):
    out = _check([ticket], positions, state_dir=state)
    assert out["passed"] == [] and any(text in r for r in out["rejected"][0][1])


@pytest.mark.parametrize("bad", [dict(quantity=0), dict(quantity=-5), dict(quantity=True), dict(quantity=2.5), dict(reference_price=float("nan")),
                                  dict(limit_price=0.0), dict(limit_price=float("inf")), dict(reference_price=None)])
def test_a_missing_zero_negative_or_non_numeric_quantity_or_price_is_rejected(state, bad):
    out = _check([_ticket(**bad)], state_dir=state)
    assert out["passed"] == [] and "not a number" in out["rejected"][0][1][0]


def test_the_same_order_cannot_be_submitted_twice(state):
    t = _ticket()
    oms.append_event("SUBMITTED", {"client_id": t["client_id"], "trade_day": DAY, "value": 10_000.0}, state)
    out = _check([t], state_dir=state)
    assert out["passed"] == [] and "already submitted" in out["rejected"][0][1][0]


def test_the_orders_per_day_limit_counts_what_was_already_sent_today(state):
    limits = dict(LIMITS, max_orders_per_day=2)
    oms.append_event("SUBMITTED", {"client_id": "x1", "trade_day": DAY, "value": 1.0}, state)
    oms.append_event("SUBMITTED", {"client_id": "x2", "trade_day": "2026-10-22", "value": 1.0}, state)        # yesterday's does not count
    out = _check([_ticket("A"), _ticket("B")], limits=limits, state_dir=state)
    assert [t["symbol"] for t in out["passed"]] == ["A"] and "order number 3" in out["rejected"][0][1][0]            # one sent today, A is the 2nd, B would be the 3rd
    oms.append_event("SUBMITTED", {"client_id": "x3", "trade_day": DAY, "value": 1.0}, state)
    assert _check([_ticket("C")], limits=limits, state_dir=state)["passed"] == []


def test_the_daily_turnover_limit_is_cumulative_across_the_batch_and_the_journal(state):
    limits = dict(LIMITS, max_daily_turnover=250_000.0)
    batch = [_ticket(s, qty=1000, ref=100.0) for s in ("A", "B", "C")]                    # 100,000 each
    out = _check(batch, limits=limits, state_dir=state)
    assert [t["symbol"] for t in out["passed"]] == ["A", "B"] and "daily limit" in out["rejected"][0][1][0]
    oms.append_event("SUBMITTED", {"client_id": "old", "trade_day": DAY, "value": 200_000.0}, state)
    assert len(_check([_ticket("A", qty=1000, ref=100.0), _ticket("B", qty=1000, ref=100.0)], limits=limits, state_dir=state)["passed"]) == 0


# ---- the kill switch -----------------------------------------------------------------------------------------------------------

def test_the_kill_switch_stops_everything_and_releasing_it_restores_normal_checking(state):
    assert oms.kill_switch_engaged(state) == (False, "")
    oms.engage_kill("testing", state)
    engaged, why = oms.kill_switch_engaged(state)
    assert engaged and "kill switch" in why
    out = _check([_ticket("A"), _ticket("B")], state_dir=state)
    assert out["passed"] == [] and len(out["rejected"]) == 2 and "kill switch" in out["rejected"][0][1][0]
    oms.release_kill(state)
    assert not oms.kill_switch_engaged(state)[0] and len(_check([_ticket()], state_dir=state)["passed"]) == 1


def test_a_reconciliation_halt_is_a_separate_switch_that_needs_a_written_note_to_clear(state):
    oms.set_halt("positions differ", state)
    assert oms.kill_switch_engaged(state)[0]
    oms.release_kill(state)                                                               # releasing the kill switch does not clear a halt
    assert oms.kill_switch_engaged(state)[0]
    with pytest.raises(ValueError, match="written note"):
        oms.clear_halt("   ", state)
    oms.clear_halt("checked the broker statement; the difference was a rounding share", state)
    assert not oms.kill_switch_engaged(state)[0]
    assert [e["kind"] for e in oms.read_journal(state)] == ["HALT_SET", "HALT_CLEARED"]


def test_the_kill_switch_fails_closed_when_its_folder_cannot_be_read(tmp_path):
    blocker = tmp_path / "state"
    blocker.write_text("this is a file where the folder should be")
    engaged, why = oms.kill_switch_engaged(str(blocker))
    assert engaged and "fails closed" in why
    assert _check([_ticket()], state_dir=str(blocker))["passed"] == []


# ---- the journal -------------------------------------------------------------------------------------------------------------------

def test_the_journal_chains_every_line_and_verifies(state):
    for i in range(4):
        oms.append_event("PROPOSED", {"n": i}, state)
    log = oms.read_journal(state)
    assert [e["seq"] for e in log] == [1, 2, 3, 4] and log[0]["prev"] == oms.GENESIS and log[2]["prev"] == log[1]["hash"]
    assert oms.verify_journal(state) == (True, "") and oms.verify_journal(state + "_none") == (True, "")


def _rewrite(state, mutate):
    path = os.path.join(state, oms.JOURNAL_FILE)
    lines = [json.loads(x) for x in open(path, encoding="utf-8").read().splitlines()]
    lines = mutate(lines)
    open(path, "w", encoding="utf-8").write("\n".join(json.dumps(x, sort_keys=True) for x in lines) + "\n")


@pytest.mark.parametrize("name,mutate,text", [
    ("an edited payload", lambda ls: [dict(l, payload={"n": 99}) if l["seq"] == 2 else l for l in ls], "hash"),
    ("a deleted line", lambda ls: [l for l in ls if l["seq"] != 2], "sequence"),
    ("swapped lines", lambda ls: [ls[0], ls[2], ls[1], ls[3]], "sequence"),
])
def test_an_edit_a_deletion_or_a_reordering_is_detected(state, name, mutate, text):
    for i in range(4):
        oms.append_event("PROPOSED", {"n": i}, state)
    _rewrite(state, mutate)
    ok, problem = oms.verify_journal(state)
    assert not ok and text in problem


# ---- local only, enforced -----------------------------------------------------------------------------------------------------------

FORBIDDEN = ["import urllib", "from urllib", "import requests", "import socket", "import http", "from http", "import httpx", "import aiohttp", "import ftplib",
             "import smtplib", "import websocket", "upstox_client", "upstox_tail", "api.upstox.com", "/order", "place_order", "UPSTOX_", "ACCESS_TOKEN"]


def test_the_execution_folder_cannot_reach_a_network_or_a_broker():
    files = glob.glob(os.path.join(os.path.dirname(oms.__file__), "*.py"))
    assert files
    for path in files:
        code = [line for line in open(path, encoding="utf-8").read().splitlines() if not line.strip().startswith(("#", '"""', "*", "-"))]
        text = "\n".join(code)
        for token in FORBIDDEN:
            code_lines = [l for l in code if token in l and not l.strip().startswith(('"', "'")) and "FORBIDDEN" not in l]
            assert not code_lines, f"{os.path.basename(path)} contains '{token}': {code_lines[:2]}"
