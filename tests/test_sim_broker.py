"""
tests/test_sim_broker.py

The simulated broker decides fills and reconciliation decides whether the account can be trusted. The rules that matter: nothing fills on the
day it was decided, a fill needs the open to be within the limit, costs are the engine's, cash and shares always follow from the fills, and an
unexplained difference stops everything. Small price tables, no network.
"""

import json

import pandas as pd
import pytest

import costs
import paper_oms as oms
import sim_broker as sb

DAY = "2026-10-22"          # the day orders are sent (a Thursday); the next session is 2026-10-23


@pytest.fixture
def state(tmp_path):
    return str(tmp_path / "state")


def _prices(rows: dict) -> pd.DataFrame:
    """{date: open} to a frame with an open column."""
    return pd.DataFrame({"open": list(rows.values())}, index=pd.DatetimeIndex(list(rows.keys())))


def _ticket(symbol="A", side="BUY", qty=100, ref=100.0, limit=101.0, status="APPROVED"):
    return {"client_id": f"{symbol}-{side}-{qty}", "rule_id": "r", "formation_date": "2026-10-22", "symbol": symbol, "side": side, "quantity": qty,
            "order_type": "LIMIT", "limit_price": limit, "reference_price": ref, "status": status, "reason": "t"}


def _send(account, state, *tickets):
    for t in tickets:
        assert sb.submit(t, account, DAY, state)["accepted"]


# ---- submitting ------------------------------------------------------------------------------------------------------------------

def test_an_approved_ticket_is_accepted_once_and_journalled_and_a_repeat_is_refused(state):
    acct = sb.new_account(1_000_000)
    t = _ticket()
    assert sb.submit(t, acct, DAY, state) == {"accepted": True, "reason": ""}
    again = sb.submit(t, acct, DAY, state)
    assert not again["accepted"] and "already submitted" in again["reason"]
    assert len(acct["orders"]) == 1 and [e["kind"] for e in oms.read_journal(state)] == ["SUBMITTED"]


def test_only_an_approved_ticket_can_be_sent_and_a_stopped_system_sends_nothing(state):
    acct = sb.new_account(1_000_000)
    assert "approved" in sb.submit(_ticket(status="PROPOSED"), acct, DAY, state)["reason"] and acct["orders"] == {}
    oms.engage_kill("test", state)
    assert "kill switch" in sb.submit(_ticket(), acct, DAY, state)["reason"] and acct["orders"] == {}


# ---- fills --------------------------------------------------------------------------------------------------------------------------

def test_a_buy_fills_at_the_next_sessions_open_with_the_engines_costs(state):
    acct = sb.new_account(1_000_000)
    _send(acct, state, _ticket(qty=100, limit=101.0))
    changes = sb.process_fills(acct, {"A": _prices({"2026-10-22": 99.0, "2026-10-23": 100.5})}, "2026-10-23", state)
    assert [c["status"] for c in changes] == ["FILLED"]
    fee = costs.calculate_trade_cost(100 * 100.5, "buy")["total"]
    assert acct["positions"] == {"A": 100} and acct["cash"] == pytest.approx(1_000_000 - 100 * 100.5 - fee)
    fill = next(iter(acct["orders"].values()))["fill"]
    assert fill["price"] == 100.5 and fill["date"] == "2026-10-23" and fill["costs"] == pytest.approx(fee)       # the day after, not the 22nd's 99.0


def test_an_order_never_fills_on_the_day_it_was_sent(state):
    acct = sb.new_account(1_000_000)
    _send(acct, state, _ticket(limit=101.0))
    assert sb.process_fills(acct, {"A": _prices({"2026-10-21": 99.0, "2026-10-22": 99.5})}, "2026-10-22", state) == []          # no later session yet
    assert acct["positions"] == {} and next(iter(acct["orders"].values()))["status"] == "WORKING"
    sb.process_fills(acct, {"A": _prices({"2026-10-22": 99.5, "2026-10-26": 100.0})}, "2026-10-26", state)                       # the next one is Monday
    assert next(iter(acct["orders"].values()))["fill"]["date"] == "2026-10-26"


def test_a_buy_with_the_open_above_the_limit_and_a_sell_with_the_open_below_it_are_cancelled_unfilled(state):
    acct = sb.new_account(1_000_000)
    acct["positions"] = {"B": 50}
    _send(acct, state, _ticket("A", "BUY", 100, limit=101.0), _ticket("B", "SELL", 50, ref=40.0, limit=39.6))
    frames = {"A": _prices({"2026-10-23": 103.0}), "B": _prices({"2026-10-23": 38.0})}                                            # both gap against us
    changes = sb.process_fills(acct, frames, "2026-10-23", state)
    assert {c["status"] for c in changes} == {"CANCELLED"} and all("beyond the limit" in c["note"] for c in changes)
    assert acct["cash"] == 1_000_000 and acct["positions"] == {"B": 50}


def test_a_sell_fills_when_the_open_is_at_or_above_the_limit_and_removes_the_position(state):
    acct = sb.new_account(0.0)
    acct["positions"] = {"B": 50}
    _send(acct, state, _ticket("B", "SELL", 50, ref=40.0, limit=39.6))
    sb.process_fills(acct, {"B": _prices({"2026-10-23": 40.2})}, "2026-10-23", state)
    fee = costs.calculate_trade_cost(50 * 40.2, "sell")["total"]
    assert acct["positions"] == {} and acct["cash"] == pytest.approx(50 * 40.2 - fee)


def test_sells_are_processed_first_so_their_proceeds_can_fund_a_buy(state):
    acct = sb.new_account(1_000.0)                                                       # far too little for the buy on its own
    acct["positions"] = {"B": 1000}
    _send(acct, state, _ticket("A", "BUY", 100, limit=101.0), _ticket("B", "SELL", 1000, ref=40.0, limit=39.6))
    changes = sb.process_fills(acct, {"A": _prices({"2026-10-23": 100.0}), "B": _prices({"2026-10-23": 40.0})}, "2026-10-23", state)
    assert [c["status"] for c in changes] == ["FILLED", "FILLED"] and acct["positions"] == {"A": 100}       # the sell was handled before the buy


def test_a_buy_the_cash_cannot_cover_is_rejected_and_changes_nothing(state):
    acct = sb.new_account(5_000.0)
    _send(acct, state, _ticket(qty=100, limit=101.0))
    changes = sb.process_fills(acct, {"A": _prices({"2026-10-23": 100.0})}, "2026-10-23", state)
    assert changes[0]["status"] == "REJECTED" and "insufficient cash" in changes[0]["note"]
    assert acct["cash"] == 5_000.0 and acct["positions"] == {}
    assert oms.read_journal(state)[-1]["kind"] == "REJECTED_BY_BROKER"


def test_an_order_with_no_session_in_the_data_waits_and_then_expires(state):
    acct = sb.new_account(1_000_000)
    _send(acct, state, _ticket())
    assert sb.process_fills(acct, {}, "2026-10-25", state) == [] and next(iter(acct["orders"].values()))["status"] == "WORKING"
    changes = sb.process_fills(acct, {}, "2026-11-02", state)
    assert changes[0]["status"] == "CANCELLED" and "expired" in changes[0]["note"]


def test_processing_twice_never_fills_an_order_twice(state):
    acct = sb.new_account(1_000_000)
    _send(acct, state, _ticket())
    frames = {"A": _prices({"2026-10-23": 100.0})}
    sb.process_fills(acct, frames, "2026-10-23", state)
    cash, positions = acct["cash"], dict(acct["positions"])
    assert sb.process_fills(acct, frames, "2026-10-23", state) == [] and acct["cash"] == cash and acct["positions"] == positions


def test_the_account_saves_and_loads_exactly_and_is_valued_at_last_prices(state):
    acct = sb.new_account(1_000_000)
    _send(acct, state, _ticket())
    sb.process_fills(acct, {"A": _prices({"2026-10-23": 100.0})}, "2026-10-23", state)
    sb.save_account(acct, state)
    assert sb.load_account(state) == json.loads(json.dumps(acct))
    assert sb.account_equity(acct, {"A": 110.0}) == pytest.approx(acct["cash"] + 100 * 110.0)
    with pytest.raises(ValueError, match="no price for A"):
        sb.account_equity(acct, {})


# ---- reconciliation ---------------------------------------------------------------------------------------------------------------

def _filled_batch(state, intended=None, frames=None):
    acct = sb.new_account(1_000_000)
    t1, t2 = _ticket("A", "BUY", 100, limit=101.0), _ticket("B", "BUY", 50, ref=200.0, limit=202.0)
    _send(acct, state, t1, t2)
    sb.process_fills(acct, frames or {"A": _prices({"2026-10-23": 100.0}), "B": _prices({"2026-10-23": 200.0})}, "2026-10-23", state)
    batch = {"start_positions": {}, "intended_positions": intended or {"A": 100, "B": 50}, "client_ids": [t1["client_id"], t2["client_id"]]}
    return acct, batch


def test_when_the_fills_explain_the_account_it_reconciles_cleanly_and_nothing_halts(state):
    acct, batch = _filled_batch(state)
    report = sb.reconcile(acct, batch, state)
    assert report["ok"] and report["unexplained_positions"] == {} and report["unfilled_vs_intended"] == {} and abs(report["cash_gap"]) < 1e-6
    assert not oms.kill_switch_engaged(state)[0] and oms.read_journal(state)[-1]["kind"] == "RECONCILED"


def test_a_cancelled_order_is_an_unfilled_difference_that_is_reported_but_does_not_halt(state):
    acct, batch = _filled_batch(state, frames={"A": _prices({"2026-10-23": 100.0}), "B": _prices({"2026-10-23": 210.0})})      # B gaps above its limit
    report = sb.reconcile(acct, batch, state)
    assert report["ok"] and report["unfilled_vs_intended"] == {"B": {"intended": 50, "actual": 0}} and not oms.kill_switch_engaged(state)[0]


def test_a_position_no_order_explains_halts_everything(state):
    acct, batch = _filled_batch(state)
    acct["positions"]["A"] += 7                                                    # shares appeared that no fill accounts for
    report = sb.reconcile(acct, batch, state)
    assert not report["ok"] and report["unexplained_positions"]["A"] == {"expected_from_fills": 100, "actual": 107}
    engaged, why = oms.kill_switch_engaged(state)
    assert engaged and "no order explains" in why
    assert sb.submit(_ticket("C"), acct, DAY, state)["accepted"] is False         # and nothing new can be sent
    oms.clear_halt("compared with the statement: the 7 shares were a bonus credit, recorded", state)
    assert not oms.kill_switch_engaged(state)[0]


def test_a_cash_difference_no_fill_explains_halts_everything(state):
    acct, batch = _filled_batch(state)
    acct["cash"] -= 250.0                                                          # money left the account without an order
    report = sb.reconcile(acct, batch, state)
    assert not report["ok"] and report["cash_gap"] == pytest.approx(-250.0) and oms.kill_switch_engaged(state)[0]


def test_the_whole_journal_still_verifies_after_a_full_cycle(state):
    acct, batch = _filled_batch(state)
    sb.reconcile(acct, batch, state)
    assert oms.verify_journal(state) == (True, "") and {"SUBMITTED", "FILLED", "RECONCILED"} <= {e["kind"] for e in oms.read_journal(state)}
