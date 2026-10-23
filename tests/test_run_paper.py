"""
tests/test_run_paper.py

The paper execution steps end to end on small, fully synthetic files: a target list, a price cache and an empty state folder. The point of the layer is
the order of events and who may do what, so these tests walk the whole cycle (propose, approve, submit, fill, reconcile) and then each way it must refuse.
"""

import json
import os

import pandas as pd
import pytest

import paper_oms as oms
import run_paper as rp
import sim_broker as sb

CASH = 1_000_000.0


@pytest.fixture
def paths(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    return {"state": str(tmp_path / "state"), "books": str(tmp_path / "books.json"), "cache": str(cache)}


def write_cache(paths, symbol, rows):
    """rows: {date: (open, close)}; high and low are set around them."""
    df = pd.DataFrame({"open": [o for o, c in rows.values()], "high": [max(o, c) * 1.01 for o, c in rows.values()],
                       "low": [min(o, c) * 0.99 for o, c in rows.values()], "close": [c for o, c in rows.values()], "volume": 1000.0},
                      index=pd.DatetimeIndex(list(rows), name="date"))
    df.to_csv(os.path.join(paths["cache"], f"{symbol}.NS.csv"))


def write_books(paths, targets, formation="2026-10-22", book="rule1"):
    holdings = [{"symbol": s, "target_weight_pct": w, "as_of_formation_date": formation} for s, w in targets.items()]
    with open(paths["books"], "w", encoding="utf-8") as f:
        json.dump({"books": [{"id": book, "holdings": holdings}]}, f)


def market(paths, day2=None):
    """A, B, C trade at 100, 200, 50 through the 22nd; `day2` adds the 23rd as {symbol: open}."""
    base = {"A": 100.0, "B": 200.0, "C": 50.0}
    for s, px in base.items():
        rows = {"2026-10-20": (px, px), "2026-10-21": (px, px), "2026-10-22": (px, px)}
        if day2:
            rows["2026-10-23"] = (day2[s], day2[s])
        write_cache(paths, s, rows)


TARGETS = {"A": 10.0, "B": 10.0, "C": 10.0}                       # 1000, 500 and 2000 shares: 100,000 each, inside the 150,000 order limit


def propose(paths, **kw):
    return rp.cmd_propose("rule1", paths, initial_cash=CASH, **kw)


# ---- the whole cycle -------------------------------------------------------------------------------------------------------------------

def test_a_full_cycle_from_proposal_to_a_clean_reconciliation(paths):
    market(paths)
    write_books(paths, TARGETS)
    batch = propose(paths)
    assert {t["symbol"]: (t["side"], t["quantity"]) for t in batch["tickets"]} == {"A": ("BUY", 1000), "B": ("BUY", 500), "C": ("BUY", 2000)}
    assert all(t["status"] == "PROPOSED" for t in batch["tickets"]) and sb.load_account(paths["state"], CASH)["orders"] == {}        # nothing is sent by proposing

    approved = rp.cmd_approve(paths, None, True, "checked the three buys against the target list", initial_cash=CASH)
    assert len(approved["approved"]) == 3
    sent = rp.cmd_submit(paths, initial_cash=CASH)
    assert len(sent["sent"]) == 3 and sent["refused"] == []

    early = rp.cmd_fill(paths, initial_cash=CASH)                  # the 23rd is not in the data yet
    assert early["changes"] == []
    market(paths, day2={"A": 100.5, "B": 200.5, "C": 50.0})        # the next session arrives
    filled = rp.cmd_fill(paths, initial_cash=CASH)
    assert filled["as_of"] == "2026-10-23" and {c["status"] for c in filled["changes"]} == {"FILLED"}

    report = rp.cmd_reconcile(paths, initial_cash=CASH)
    assert report["ok"] and report["unfilled_vs_intended"] == {} and abs(report["cash_gap"]) < 1e-6
    status = rp.cmd_status(paths, initial_cash=CASH)
    assert status["positions"] == {"A": 1000, "B": 500, "C": 2000} and status["orders_by_status"] == {"FILLED": 3} and status["journal_ok"] and not status["stopped"]
    assert status["equity"] < CASH + 1_000 and status["equity"] > CASH - 10_000                                                      # a little spent on costs and drift, not more
    kinds = [e["kind"] for e in oms.read_journal(paths["state"])]
    assert kinds[0] == "PROPOSED" and {"APPROVED", "SUBMITTED", "FILLED", "RECONCILED"} <= set(kinds)


def test_a_stock_held_but_no_longer_a_target_is_sold(paths):
    market(paths)
    write_books(paths, {"A": 10.0})
    acct = sb.new_account(CASH)
    acct["positions"] = {"B": 300}
    sb.save_account(acct, paths["state"])
    batch = rp.cmd_propose("rule1", paths, initial_cash=CASH)
    by = {t["symbol"]: t for t in batch["tickets"]}
    assert by["B"]["side"] == "SELL" and by["B"]["quantity"] == 300 and "no longer a target" in by["B"]["reason"]


# ---- the human step -----------------------------------------------------------------------------------------------------------------------

def test_approving_needs_a_written_note_and_a_choice_of_tickets(paths):
    market(paths)
    write_books(paths, TARGETS)
    propose(paths)
    with pytest.raises(rp.StepError, match="written note"):
        rp.cmd_approve(paths, None, True, "   ")
    with pytest.raises(rp.StepError, match="--ids"):
        rp.cmd_approve(paths, None, False, "fine")
    with pytest.raises(rp.StepError, match="not tickets of this batch"):
        rp.cmd_approve(paths, ["nope"], False, "fine")
    assert sb.load_account(paths["state"], CASH)["orders"] == {}


def test_only_the_named_tickets_are_approved_and_only_approved_tickets_are_sent(paths):
    market(paths)
    write_books(paths, TARGETS)
    batch = propose(paths)
    first = batch["tickets"][0]["client_id"]
    assert rp.cmd_approve(paths, [first], False, "only this one", initial_cash=CASH)["approved"] == [first]
    sent = rp.cmd_submit(paths, initial_cash=CASH)
    assert sent["sent"] == [first]
    assert list(sb.load_account(paths["state"], CASH)["orders"]) == [first]


def test_a_ticket_the_limits_rejected_can_never_be_approved(paths):
    market(paths)
    write_books(paths, {"A": 40.0, "B": 10.0})                      # 400,000 in A breaks the 150,000 per-order limit
    batch = propose(paths)
    assert [t["symbol"] for t in batch["tickets"]] == ["B"] and "per-order limit" in batch["rejected"][0]["reasons"][0]
    rejected_id = batch["rejected"][0]["ticket"]["client_id"]
    with pytest.raises(rp.StepError, match="not tickets of this batch"):
        rp.cmd_approve(paths, [rejected_id], False, "please", initial_cash=CASH)


def test_the_limits_run_again_at_approval_so_a_kill_switch_engaged_since_the_proposal_stops_it(paths):
    market(paths)
    write_books(paths, TARGETS)
    propose(paths)
    oms.engage_kill("stop", paths["state"])
    r = rp.cmd_approve(paths, None, True, "approving anyway", initial_cash=CASH)
    assert r["approved"] == [] and len(r["refused_now"]) == 3 and "kill switch" in r["refused_now"][0][1][0]


def test_a_kill_switch_engaged_after_approval_stops_the_send_and_releasing_it_allows_it(paths):
    market(paths)
    write_books(paths, TARGETS)
    propose(paths)
    rp.cmd_approve(paths, None, True, "ok", initial_cash=CASH)
    oms.engage_kill("stop", paths["state"])
    r = rp.cmd_submit(paths, initial_cash=CASH)
    assert r["sent"] == [] and len(r["refused"]) == 3 and "kill switch" in r["refused"][0][1]
    oms.release_kill(paths["state"])
    assert len(rp.cmd_submit(paths, initial_cash=CASH)["sent"]) == 3


# ---- proposals that must be refused or cut down -------------------------------------------------------------------------------------------

def test_a_batch_is_not_rebuilt_unless_asked_and_never_once_anything_was_approved(paths):
    market(paths)
    write_books(paths, TARGETS)
    propose(paths)
    with pytest.raises(rp.StepError, match="--replace"):
        propose(paths)
    propose(paths, replace=True)                                    # allowed while nothing is approved
    rp.cmd_approve(paths, None, True, "ok", initial_cash=CASH)
    with pytest.raises(rp.StepError, match="approved or sent"):
        propose(paths, replace=True)


def test_a_stock_whose_price_is_older_than_the_others_is_skipped_not_traded_on(paths):
    market(paths)
    write_cache(paths, "C", {"2026-10-19": (50.0, 50.0), "2026-10-20": (50.0, 50.0)})              # C stops on the 20th
    write_books(paths, TARGETS)
    batch = propose(paths)
    assert [t["symbol"] for t in batch["tickets"]] == ["A", "B"] and batch["skipped"][0][0] == "C" and "last price is from 2026-10-20" in batch["skipped"][0][1]


def test_missing_files_give_plain_messages(paths):
    with pytest.raises(rp.StepError, match="does not exist"):
        propose(paths)
    write_books(paths, TARGETS)
    with pytest.raises(rp.StepError, match="no cached prices"):
        propose(paths)
    market(paths)
    with pytest.raises(rp.StepError, match="unknown book"):
        rp.cmd_propose("nope", paths, initial_cash=CASH)
    assert rp.local_prices("ZZZ", paths["cache"]) is None
    with pytest.raises(rp.StepError, match="no batch yet"):
        rp.cmd_submit(paths, initial_cash=CASH)


# ---- fills that do not go the rule's way, and halts ---------------------------------------------------------------------------------------

def test_a_gap_above_the_limit_cancels_the_buy_and_the_shortfall_is_reported_not_halted(paths):
    market(paths)
    write_books(paths, TARGETS)
    propose(paths)
    rp.cmd_approve(paths, None, True, "ok", initial_cash=CASH)
    rp.cmd_submit(paths, initial_cash=CASH)
    market(paths, day2={"A": 100.5, "B": 215.0, "C": 50.0})        # B opens 7.5% above its 1% limit
    filled = rp.cmd_fill(paths, initial_cash=CASH)
    assert sorted(c["status"] for c in filled["changes"]) == ["CANCELLED", "FILLED", "FILLED"]
    report = rp.cmd_reconcile(paths, initial_cash=CASH)
    assert report["ok"] and report["unfilled_vs_intended"] == {"B": {"intended": 500, "actual": 0}} and not oms.kill_switch_engaged(paths["state"])[0]


def test_an_unexplained_change_halts_and_a_new_proposal_is_refused_by_the_limits_until_a_person_clears_it(paths, capsys):
    market(paths)
    write_books(paths, TARGETS)
    propose(paths)
    rp.cmd_approve(paths, None, True, "ok", initial_cash=CASH)
    rp.cmd_submit(paths, initial_cash=CASH)
    market(paths, day2={"A": 100.5, "B": 200.5, "C": 50.0})
    rp.cmd_fill(paths, initial_cash=CASH)
    acct = sb.load_account(paths["state"], CASH)
    acct["positions"]["A"] += 7                                     # shares appear that no order explains
    sb.save_account(acct, paths["state"])
    assert rp.main(["reconcile"], paths) == 2 and "HALTED" in capsys.readouterr().out
    write_books(paths, {"A": 5.0, "B": 10.0, "C": 10.0}, formation="2026-10-23")       # the rule now wants less A, so there is a trade to refuse
    market(paths, day2={"A": 100.5, "B": 200.5, "C": 50.0})
    batch = rp.cmd_propose("rule1", paths, initial_cash=CASH)
    assert batch["tickets"] == [] and batch["rejected"] and all("halted" in r["reasons"][0] and "no order explains" in r["reasons"][0] for r in batch["rejected"])
    assert rp.main(["clear-halt", "--note", "compared with the statement; recorded"], paths) == 0 and not oms.kill_switch_engaged(paths["state"])[0]


def test_reconciling_while_orders_still_wait_for_their_session_is_refused(paths):
    market(paths)
    write_books(paths, TARGETS)
    propose(paths)
    rp.cmd_approve(paths, None, True, "ok", initial_cash=CASH)
    rp.cmd_submit(paths, initial_cash=CASH)
    with pytest.raises(rp.StepError, match="still waiting"):
        rp.cmd_reconcile(paths, initial_cash=CASH)


# ---- the command line itself ------------------------------------------------------------------------------------------------------------------

def test_the_command_line_prints_a_readable_proposal_and_explains_a_refusal(paths, capsys):
    market(paths)
    write_books(paths, TARGETS)
    assert rp.main(["propose", "--book", "rule1"], paths) == 0
    out = capsys.readouterr().out
    assert "BUY" in out and "wait for your approval; nothing has been sent" in out and "rule1: hold 10.0%" in out
    assert rp.main(["approve", "--all"], paths) == 1 and "written note" in capsys.readouterr().out
    assert rp.main(["status"], paths) == 0 and '"stopped": false' in capsys.readouterr().out
    assert rp.main(["kill", "--reason", "test"], paths) == 0 and rp.main(["status"], paths) == 0 and '"stopped": true' in capsys.readouterr().out
    assert rp.main(["release"], paths) == 0
