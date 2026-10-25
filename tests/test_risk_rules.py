"""
tests/test_risk_rules.py

execution/risk_rules.py holds the account-level risk rules of RISK_RULES.md: a drawdown breaker (warning, halt, review) and a daily loss limit. Each rule is checked at its boundary and
then in the paper layer, where a halt must stop every ticket, survive until a person writes a note, and be resumable (the highest value is reset) without hiding what happened.
"""

import json
import os

import pandas as pd
import pytest

import paper_oms as oms
import risk_rules as rk
import run_paper as rp
import sim_broker as sb

CASH = 1_000_000.0


# --- the pure rules ------------------------------------------------------------------------------------------------------------------------

def test_the_drawdown_is_the_fall_from_the_highest_value_and_a_new_high_is_zero():
    assert rk.drawdown(900_000.0, 1_000_000.0) == pytest.approx(0.10)
    assert rk.drawdown(1_100_000.0, 1_000_000.0) == 0.0 and rk.drawdown(1_000_000.0, 1_000_000.0) == 0.0
    assert rk.drawdown(500.0, 0.0) == 0.0                                                    # no peak yet: nothing to fall from


def test_each_level_starts_exactly_at_its_proposed_threshold():
    assert [rk.breaker_level(x) for x in (0.0, 0.0499, 0.05, 0.0999, 0.10, 0.1499, 0.15, 0.40)] == [rk.OK, rk.OK, rk.WARNING, rk.WARNING, rk.HALT, rk.HALT, rk.REVIEW, rk.REVIEW]
    assert rk.RISK["drawdown_halt"] == 0.10, "the halt level is the same 10% as go-live gate 7 (GO_LIVE_GATES.md)"


def test_the_levels_follow_the_numbers_they_are_given():
    tight = {**rk.RISK, "drawdown_warning": 0.01, "drawdown_halt": 0.02, "drawdown_review": 0.03}
    assert [rk.breaker_level(x, tight) for x in (0.005, 0.01, 0.02, 0.03)] == [rk.OK, rk.WARNING, rk.HALT, rk.REVIEW]


def test_a_daily_loss_is_measured_against_the_previous_value_and_a_gain_is_not_a_loss():
    assert rk.daily_loss(970_000.0, 1_000_000.0) == pytest.approx(0.03)
    assert rk.daily_loss(1_020_000.0, 1_000_000.0) == 0.0 and rk.daily_loss(100.0, 0.0) == 0.0


def account(**risk):
    return {"initial_cash": CASH, "cash": CASH, "positions": {}, "orders": {}, **({"risk": risk} if risk else {})}


def test_the_highest_value_starts_at_the_money_put_in_and_never_falls():
    a = account()
    rk.update_marks(a, 950_000.0, "2026-10-20")
    assert a["risk"]["peak_equity"] == CASH                                                   # not 950,000: the account started at 1,000,000
    rk.update_marks(a, 1_100_000.0, "2026-10-21")
    rk.update_marks(a, 1_000_000.0, "2026-10-22")
    assert a["risk"]["peak_equity"] == 1_100_000.0


def test_a_second_look_on_the_same_day_replaces_that_days_value_and_a_new_day_moves_on():
    a = account()
    rk.update_marks(a, 990_000.0, "2026-10-20")
    assert a["risk"]["prev_equity"] == CASH and a["risk"]["last_equity"] == 990_000.0         # the first day is measured against the money put in
    rk.update_marks(a, 985_000.0, "2026-10-20")                                               # run again the same evening
    assert a["risk"]["prev_equity"] == CASH and a["risk"]["last_equity"] == 985_000.0
    rk.update_marks(a, 980_000.0, "2026-10-21")
    assert a["risk"]["prev_equity"] == 985_000.0 and a["risk"]["prev_day"] == "2026-10-20"


def test_a_slow_slide_to_the_halt_level_halts_with_the_fall_named():
    a = account(peak_equity=1_000_000.0, last_equity=905_000.0, last_day="2026-10-20", prev_equity=910_000.0)
    r = rk.assess(a, 899_000.0, "2026-10-21")                                                  # 10.1% below the peak, 0.6% down on the day
    assert r["level"] == rk.HALT and r["halt"] is True and r["drawdown_pct"] == pytest.approx(10.1, abs=0.01) and r["daily_loss_pct"] < 1.0
    assert len(r["reasons"]) == 1 and "10.1% below its highest value" in r["reasons"][0] and "no new orders" in r["reasons"][0]


def test_the_review_level_says_everything_stops_until_the_rule_is_rejudged():
    a = account(peak_equity=1_000_000.0, last_equity=860_000.0, last_day="2026-10-20", prev_equity=862_000.0)
    r = rk.assess(a, 849_000.0, "2026-10-21")
    assert r["level"] == rk.REVIEW and r["halt"] and "re-judged" in r["reasons"][0]


def test_between_the_warning_and_halt_levels_nothing_stops():
    a = account(peak_equity=1_000_000.0, last_equity=945_000.0, last_day="2026-10-20", prev_equity=946_000.0)
    r = rk.assess(a, 940_000.0, "2026-10-21")
    assert r["level"] == rk.WARNING and r["halt"] is False and r["reasons"] == []


def test_a_single_bad_day_halts_even_when_the_account_is_far_from_a_new_low():
    a = account(peak_equity=1_200_000.0, last_equity=1_190_000.0, last_day="2026-10-20", prev_equity=1_195_000.0)
    r = rk.assess(a, 1_150_000.0, "2026-10-21")                                                # 3.4% in a day, but only 4.2% below the peak
    assert r["level"] == rk.OK and r["halt"] is True and "in one day" in r["reasons"][0]
    just_under = rk.assess(account(peak_equity=1_200_000.0, last_equity=1_190_000.0, last_day="2026-10-20", prev_equity=1_190_000.0), 1_155_000.0, "2026-10-21")
    assert just_under["halt"] is False                                                         # 2.9%: under the 3% limit


def test_a_first_day_far_below_the_money_put_in_halts():
    r = rk.assess(account(), 960_000.0, "2026-10-20")                                          # 4% down on day one
    assert r["halt"] and "in one day" in r["reasons"][0]


def test_resuming_resets_the_highest_value_to_the_last_value_seen():
    a = account(peak_equity=1_000_000.0, last_equity=850_000.0, last_day="2026-10-21", prev_equity=860_000.0)
    assert rk.rebase_peak(a) == (1_000_000.0, 850_000.0) and a["risk"]["peak_equity"] == 850_000.0
    assert rk.assess(a, 850_000.0, "2026-10-22")["level"] == rk.OK


# --- in the paper layer ----------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def paths(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    return {"state": str(tmp_path / "state"), "books": str(tmp_path / "books.json"), "cache": str(cache)}


def market(paths):
    for symbol, px in {"A": 100.0, "B": 200.0, "C": 50.0}.items():
        rows = {"2026-10-20": px, "2026-10-21": px, "2026-10-22": px}
        pd.DataFrame({"open": list(rows.values()), "high": [p * 1.01 for p in rows.values()], "low": [p * 0.99 for p in rows.values()], "close": list(rows.values()), "volume": 1000.0},
                     index=pd.DatetimeIndex(list(rows), name="date")).to_csv(os.path.join(paths["cache"], f"{symbol}.NS.csv"))
    holdings = [{"symbol": s, "target_weight_pct": 10.0, "as_of_formation_date": "2026-10-22"} for s in ("A", "B", "C")]
    with open(paths["books"], "w", encoding="utf-8") as f:
        json.dump({"books": [{"id": "rule1", "holdings": holdings}]}, f)


def save_account(paths, cash, **risk):
    sb.save_account({"initial_cash": CASH, "cash": cash, "positions": {}, "orders": {}, **({"risk": risk} if risk else {})}, paths["state"])


def propose(paths, **kw):
    return rp.cmd_propose("rule1", paths, initial_cash=CASH, **kw)


def test_a_healthy_account_proposes_as_before_and_records_its_highest_value(paths):
    market(paths)
    batch = propose(paths)
    assert len(batch["tickets"]) == 3 and batch["risk"]["level"] == rk.OK and batch["risk"]["halt"] is False
    assert sb.load_account(paths["state"], CASH)["risk"]["peak_equity"] == CASH and not oms.kill_switch_engaged(paths["state"])[0]


def test_a_fall_to_the_review_level_halts_the_account_and_every_ticket_is_refused(paths):
    market(paths)
    save_account(paths, 850_000.0, peak_equity=CASH, last_equity=860_000.0, last_day="2026-10-21", prev_equity=862_000.0)
    batch = propose(paths)
    assert batch["risk"]["level"] == rk.REVIEW and batch["tickets"] == [] and len(batch["rejected"]) == 3
    assert all("account risk rule" in " ".join(r["reasons"]) for r in batch["rejected"])
    engaged, why = oms.kill_switch_engaged(paths["state"])
    assert engaged and "15.0% below its highest value" in why
    assert "ACCOUNT_HALT_SET" in [e["kind"] for e in oms.read_journal(paths["state"])]


def test_a_halted_account_cannot_approve_or_send_what_was_proposed_before(paths):
    market(paths)
    batch = propose(paths)                                                                       # healthy: three tickets waiting
    assert len(batch["tickets"]) == 3
    save_account(paths, 850_000.0, peak_equity=CASH, last_equity=860_000.0, last_day="2026-10-22", prev_equity=862_000.0)
    propose(paths, replace=True)                                                                 # the account has since fallen: this proposal halts it
    approved = rp.cmd_approve(paths, None, True, "approving anyway", initial_cash=CASH)
    assert approved["approved"] == []                                                            # the limits run again at approval and see the halt


def test_a_halt_is_cleared_only_with_a_note_and_the_highest_value_is_reset_and_journalled(paths):
    market(paths)
    save_account(paths, 850_000.0, peak_equity=CASH, last_equity=860_000.0, last_day="2026-10-21", prev_equity=862_000.0)
    propose(paths)
    with pytest.raises(ValueError, match="note"):
        rp.cmd_clear_halt(paths, "   ", initial_cash=CASH)
    assert oms.account_halt_engaged(paths["state"])                                              # a refused clear changes nothing
    r = rp.cmd_clear_halt(paths, "reviewed the book and the data; the fall is the market, not a fault", initial_cash=CASH)
    assert r["rebased"] and r["old_peak"] == CASH and r["new_peak"] == 850_000.0
    assert not oms.kill_switch_engaged(paths["state"])[0]
    kinds = [e["kind"] for e in oms.read_journal(paths["state"])]
    assert "ACCOUNT_HALT_CLEARED" in kinds and "PEAK_REBASED" in kinds and oms.verify_journal(paths["state"])[0]
    again = propose(paths, replace=True)
    assert again["risk"]["level"] == rk.OK and len(again["tickets"]) == 3                        # resumed, sized to the smaller account


def test_clearing_a_reconciliation_halt_does_not_reset_the_highest_value(paths):
    market(paths)
    save_account(paths, CASH, peak_equity=1_100_000.0, last_equity=CASH, last_day="2026-10-21", prev_equity=CASH)
    oms.set_halt("positions differ", paths["state"])
    r = rp.cmd_clear_halt(paths, "found the cause: a duplicated file", initial_cash=CASH)
    assert r == {"rebased": False} and sb.load_account(paths["state"], CASH)["risk"]["peak_equity"] == 1_100_000.0


def test_the_status_shows_the_risk_and_writes_nothing(paths):
    market(paths)
    propose(paths)
    path = os.path.join(paths["state"], sb.ACCOUNT_FILE)
    before = open(path, encoding="utf-8").read()
    status = rp.cmd_status(paths, initial_cash=CASH)
    assert status["risk"]["level"] == rk.OK and open(path, encoding="utf-8").read() == before


def test_the_command_line_prints_the_halt_and_how_to_clear_it(paths, capsys):
    market(paths)
    save_account(paths, 850_000.0, peak_equity=CASH, last_equity=860_000.0, last_day="2026-10-21", prev_equity=862_000.0)
    rp.main(["propose", "--book", "rule1"], paths)
    assert "ACCOUNT HALTED" in capsys.readouterr().out
    assert rp.main(["clear-halt", "--note", "looked at it"], paths) == 0
    assert "highest value is now" in capsys.readouterr().out


def test_a_loss_exactly_at_the_limit_halts():
    exact = {"drawdown_warning": 0.9, "drawdown_halt": 0.9, "drawdown_review": 0.9, "daily_loss_halt": 0.5}      # only the daily rule can fire; 1000 down to 500 is exactly 0.5: reached, not exceeded
    a = account(peak_equity=1000.0, last_equity=1000.0, last_day="2026-10-20", prev_equity=1000.0)
    a["initial_cash"] = 1000.0
    assert rk.assess(a, 500.0, "2026-10-21", exact)["halt"] is True
    a2 = account(peak_equity=1000.0, last_equity=1000.0, last_day="2026-10-20", prev_equity=1000.0)
    a2["initial_cash"] = 1000.0
    assert rk.assess(a2, 501.0, "2026-10-21", exact)["halt"] is False


def test_halting_again_while_halted_changes_neither_the_reason_nor_the_journal(tmp_path):
    state = str(tmp_path / "state")
    oms.set_account_halt("the first reason", state)
    oms.set_account_halt("a later reason", state)
    assert oms.kill_switch_engaged(state)[1].endswith("the first reason")
    assert [e["kind"] for e in oms.read_journal(state)].count("ACCOUNT_HALT_SET") == 1
