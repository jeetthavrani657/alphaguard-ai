"""
tests/test_golive_gates.py

research/golive_gates.py says whether a paper-traded rule has earned the owner's consideration for execution. What must hold: a win rate alone never passes
(too few trades, a poor profit factor or one huge loss each keep it locked, which is what a condor-like 85% win rate with a rare large loss looks like), the
95% interval of a win rate is computed correctly, nothing is judged before the forward test is complete, the owner's own amendment of rule 5 is a gate of its own
that fails closed, and allocation profiles are never silently treated as trade systems. The script reads files only.
"""

import json

import pytest

import golive_gates as g

FULL = {"return_pct": 20.0, "benchmark_return_pct": 5.0, "max_drawdown_pct": -6.0, "n_trades": 150, "n_winning": 135,
        "profit_factor": 2.0, "expectancy_pct": 0.5, "worst_loss_pct_of_account": -1.0}
RULE5_TEXT = "5. Never write live order placement code in this project."


def status(gates, name_start):
    return [x["status"] for x in gates if x["gate"].startswith(name_start)][0]


# --- the interval of a win rate -------------------------------------------------------------------------------------------------------

def test_the_95_percent_range_of_a_win_rate_matches_hand_calculation():
    low, high = g.wilson_interval(17, 20)
    assert low == pytest.approx(64.0, abs=0.2) and high == pytest.approx(94.8, abs=0.2)          # 17 of 20 is 85%, but it could be 64% to 95%
    assert g.wilson_interval(90, 100)[0] == pytest.approx(82.6, abs=0.2)
    assert g.wilson_interval(85, 100)[0] == pytest.approx(76.7, abs=0.2)
    assert g.wilson_interval(0, 0) == (0.0, 100.0)
    low10, high10 = g.wilson_interval(10, 10)
    assert high10 == pytest.approx(100.0, abs=1e-6) and low10 < 75.0                           # ten wins in ten still says little


# --- the win-rate gate ----------------------------------------------------------------------------------------------------------------

def test_a_win_rate_of_85_percent_on_too_few_trades_is_not_yet_a_pass():
    s = {**FULL, "n_trades": 20, "n_winning": 17}
    gates = g.evaluate(300, 252, s)
    assert status(gates, "Win rate") == g.NOT_YET and status(gates, "At least") == g.NOT_YET


def test_the_gates_read_the_all_in_trade_statistics_never_the_closed_only_ones():
    """A rule that keeps its losers open has a perfect closed win rate. The gates must see the version with the open positions marked."""
    closed = {"n_trades": 100, "n_winning": 100, "win_rate_pct": 100.0, "profit_factor": None, "expectancy_pct": 1.0, "worst_loss_pct_of_account": None}
    all_in = {"n_trades": 200, "n_winning": 100, "win_rate_pct": 50.0, "profit_factor": 0.3, "expectancy_pct": -1.0, "worst_loss_pct_of_account": -3.0}
    summary = {"return_pct": 20.0, "benchmark_return_pct": 5.0, "max_drawdown_pct": -6.0, "trade_stats": {"closed": closed, "all_in": all_in}}
    gates = g.evaluate(300, 252, summary)
    assert status(gates, "Win rate") == g.NOT_MET and status(gates, "Profit factor") == g.NOT_MET and status(gates, "Worst single loss") == g.NOT_MET
    assert "50.0% (100 of 200)" in [x for x in gates if x["gate"].startswith("Win rate")][0]["detail"]


def test_a_rule_that_never_lost_a_trade_has_an_unbounded_profit_factor_and_passes_that_gate_with_enough_trades():
    all_in = {"n_trades": 120, "n_winning": 120, "win_rate_pct": 100.0, "profit_factor": None, "expectancy_pct": 0.4, "worst_loss_pct_of_account": 0.0}
    gates = g.evaluate(300, 252, {"return_pct": 20.0, "benchmark_return_pct": 5.0, "max_drawdown_pct": -6.0, "trade_stats": {"all_in": all_in}})
    assert status(gates, "Profit factor") == g.MET and "no losing trade" in [x for x in gates if x["gate"].startswith("Profit factor")][0]["detail"]
    assert status(gates, "Worst single loss") == g.MET                                                 # no trade lost anything: the worst loss is zero


def test_the_win_rate_gate_is_met_at_the_owners_number_with_enough_trades_and_missed_just_below_it():
    assert status(g.evaluate(300, 252, {**FULL, "n_trades": 100, "n_winning": 85}), "Win rate") == g.MET
    assert status(g.evaluate(300, 252, {**FULL, "n_trades": 100, "n_winning": 84}), "Win rate") == g.NOT_MET
    assert status(g.evaluate(300, 252, {**FULL, "n_trades": 100, "n_winning": 90}), "Win rate") == g.MET


def test_fifty_wins_in_fifty_trades_is_still_not_enough_trades():
    assert status(g.evaluate(300, 252, {**FULL, "n_trades": 50, "n_winning": 50}), "Win rate") == g.NOT_YET            # a perfect record on 50 trades: too few


def test_the_low_end_of_the_range_must_clear_its_floor_even_when_the_trade_count_is_met():
    """With 100 trades the floor cannot bind at 85% (the low end is already 76.7%), so the floor is tested with a lower trade requirement."""
    loose = {**g.THRESHOLDS, "min_closed_trades": 10}
    lucky = {**FULL, "n_trades": 20, "n_winning": 17}                                                                # 85%, but 64% to 95%
    assert status(g.evaluate(300, 252, lucky, loose), "Win rate") == g.NOT_MET
    assert status(g.evaluate(300, 252, {**FULL, "n_trades": 20, "n_winning": 20}, loose), "Win rate") == g.MET        # 20 of 20: low end 83.9%


def test_a_profit_factor_below_the_floor_fails_even_when_the_average_trade_is_positive():
    s = {**FULL, "profit_factor": 1.2, "expectancy_pct": 0.1}
    assert status(g.evaluate(300, 252, s), "Profit factor") == g.NOT_MET
    assert status(g.evaluate(300, 252, {**FULL, "profit_factor": 1.6, "expectancy_pct": -0.01}), "Profit factor") == g.NOT_MET
    assert status(g.evaluate(300, 252, {**FULL, "profit_factor": 1.5, "expectancy_pct": 0.01}), "Profit factor") == g.MET


def test_a_high_win_rate_with_a_poor_profit_factor_and_one_huge_loss_does_not_pass():
    """The shape of a short-option rule: it wins most trades, one loss takes it back. The win-rate gate is met; the others are not."""
    s = {**FULL, "n_trades": 120, "n_winning": 102, "profit_factor": 0.9, "expectancy_pct": -0.2, "worst_loss_pct_of_account": -14.0}
    gates = g.evaluate(300, 252, s)
    assert status(gates, "Win rate") == g.MET
    assert status(gates, "Profit factor") == g.NOT_MET and status(gates, "Worst single loss") == g.NOT_MET
    assert not g.verdict(gates, [])["eligible"] and "Worst single loss within 2.0% of the account" in g.verdict(gates, [])["unmet"]


# --- the other gates ------------------------------------------------------------------------------------------------------------------

def test_nothing_is_judged_before_the_forward_test_is_complete():
    gates = g.evaluate(4, 252, {**FULL, "n_trades": None, "n_winning": None, "profit_factor": None, "expectancy_pct": None, "worst_loss_pct_of_account": None})
    assert status(gates, "Forward test") == g.NOT_YET and status(gates, "Beat") == g.NOT_YET and status(gates, "Drawdown") == g.NOT_YET
    assert status(gates, "Win rate") == g.CANNOT_MEASURE and status(gates, "Profit factor") == g.CANNOT_MEASURE and status(gates, "Worst single loss") == g.CANNOT_MEASURE


def test_beating_buy_and_hold_is_not_enough_it_must_beat_cash_over_the_same_days():
    cash_for_252_days = g.THRESHOLDS["cash_rate_pct_a_year"]
    assert status(g.evaluate(252, 252, {**FULL, "return_pct": cash_for_252_days - 0.5, "benchmark_return_pct": -3.0}), "Beat") == g.NOT_MET
    assert status(g.evaluate(252, 252, {**FULL, "return_pct": cash_for_252_days + 0.5, "benchmark_return_pct": cash_for_252_days + 1.0}), "Beat") == g.NOT_MET
    assert status(g.evaluate(252, 252, {**FULL, "return_pct": cash_for_252_days + 2.0, "benchmark_return_pct": 1.0}), "Beat") == g.MET


def test_a_drawdown_beyond_the_limit_fails_at_once_without_waiting_for_the_end():
    assert status(g.evaluate(10, 252, {**FULL, "max_drawdown_pct": -10.5}), "Drawdown") == g.NOT_MET
    assert status(g.evaluate(10, 252, {**FULL, "max_drawdown_pct": -9.5}), "Drawdown") == g.NOT_YET
    assert status(g.evaluate(252, 252, {**FULL, "max_drawdown_pct": -9.5}), "Drawdown") == g.MET


# --- the verdict and the project's own gates -------------------------------------------------------------------------------------------

def test_eligible_only_when_every_rule_gate_and_every_project_gate_is_met():
    rule = g.evaluate(252, 252, FULL)
    assert all(x["status"] == g.MET for x in rule)
    both_met = [g._gate("a", g.MET, ""), g._gate("b", g.MET, "")]
    assert g.verdict(rule, both_met) == {"eligible": True, "unmet": []}
    unamended = g.project_gates(RULE5_TEXT)
    v = g.verdict(rule, unamended)
    assert v["eligible"] is False and "Owner's written amendment of rule 5" in v["unmet"]          # every rule gate met, still locked


def test_the_amendment_gate_follows_claude_md_and_fails_closed_when_it_cannot_be_read():
    assert status(g.project_gates(RULE5_TEXT), "Owner's") == g.NOT_MET
    assert status(g.project_gates("5. Order placement is allowed for the owner's own account at broker X, up to Rs 1,00,000."), "Owner's") == g.MET


def test_run_reads_the_result_files_marks_allocation_profiles_and_stays_locked(tmp_path):
    out = tmp_path / "reports" / "output"
    out.mkdir(parents=True)
    (tmp_path / "CLAUDE.md").write_text(RULE5_TEXT)
    (out / "forward_books_latest.json").write_text(json.dumps({"books": [
        {"id": "m", "name": "Momentum", "n_trading_days": 4, "verdict_gate_days": 252, "summary": {"return_pct": -3.3, "benchmark_return_pct": -2.3, "max_drawdown_pct": -3.2, "n_trades": None}}]}))
    (out / "advisory_forward_latest.json").write_text(json.dumps({"profiles": [
        {"id": "c", "name": "Conservative", "n_trading_days": 3, "summary": {"return_pct": -1.8, "benchmark_return_pct": -1.5, "max_drawdown_pct": -1.8}}]}))
    r = g.run(str(tmp_path))
    assert [x["kind"] for x in r["rules"]] == ["book", "allocation"] and all(x["eligible"] is False for x in r["rules"])
    assert status(r["rules"][0]["gates"], "Win rate") == g.CANNOT_MEASURE and "Owner's written amendment of rule 5" in r["rules"][0]["unmet"]
    assert "cannot unlock" in r["note"]


def test_a_missing_claude_md_means_the_prohibition_is_assumed_to_stand(tmp_path):
    (tmp_path / "reports" / "output").mkdir(parents=True)
    r = g.run(str(tmp_path))
    assert status(r["project_gates"], "Owner's") == g.NOT_MET
