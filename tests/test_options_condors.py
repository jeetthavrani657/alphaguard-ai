"""
tests/test_options_condors.py

The helpers of research/options_condors.py that shape what is reported: the window split and the per-window trade summary. The summary is where "the strategy looks great"
could quietly be misreported, so each number is checked against a hand calculation.
"""

import numpy as np
import pandas as pd
import pytest

import options_condors as oc


def cycles(pnls, entries, costs=10.0):
    return pd.DataFrame({"entry_day": pd.to_datetime(entries), "net_pnl": pnls, "gross_pnl": [p + 2 * costs for p in pnls],
                         "entry_cost": costs, "exit_cost": costs})


def test_the_windows_split_on_the_last_day_of_2023_and_never_overlap():
    idx = pd.bdate_range("2023-12-20", "2024-01-12")
    eq = pd.Series(np.arange(len(idx), dtype=float), index=idx)
    w = oc.windows_of(eq)
    assert w["in_sample"].index.max() == pd.Timestamp("2023-12-29") and w["out_of_sample"].index.min() == pd.Timestamp("2024-01-01")
    assert len(w["in_sample"]) + len(w["out_of_sample"]) == len(eq) and w["in_sample"].index.intersection(w["out_of_sample"].index).empty


def test_the_summary_reports_the_win_rate_the_worst_cycle_and_the_profit_without_it():
    c = cycles([300.0, 200.0, -1500.0, 250.0], ["2024-01-02", "2024-02-01", "2024-03-01", "2024-04-01"])
    s = oc.cycle_summary(c)
    assert s["n_cycles"] == 4 and s["win_rate_pct"] == 75.0 and s["total_net_pnl"] == -750.0
    assert s["worst_cycle"] == -1500.0 and s["best_cycle"] == 300.0 and s["total_net_pnl_without_worst_cycle"] == 750.0           # one bad month turns a gain into a loss
    assert s["costs_paid"] == 80.0 and s["mean_net_pnl"] == -187.5 and s["gross_pnl"] == -750.0 + 80.0


def test_the_summary_can_be_cut_to_a_window_by_entry_day_and_an_empty_window_says_so():
    c = cycles([100.0, 200.0, 300.0], ["2023-11-01", "2024-01-03", "2024-02-01"])
    assert oc.cycle_summary(c, None, "2023-12-31")["n_cycles"] == 1 and oc.cycle_summary(c, "2024-01-01", None)["total_net_pnl"] == 500.0
    assert oc.cycle_summary(c, "2030-01-01", None) == {"n_cycles": 0}


def test_the_frozen_settings_are_the_ones_in_the_design_note():
    assert oc.IS_END == "2023-12-31" and oc.OOS_START == "2024-01-01" and oc.START == "2022-01-03"
    assert [r["id"] for r in oc.RULES] == ["condor_monthly", "condor_weekly"] and [r["kind"] for r in oc.RULES] == ["monthly", "weekly"]
    import options_backtest as ob
    assert (ob.SHORT_DELTA, ob.WING_DELTA, ob.RISK_FRACTION, ob.INITIAL, ob.DISCOUNT_RATE) == (0.16, 0.05, 0.10, 1_000_000.0, 0.06)
    assert oc.SLIPPAGE_LEVELS == [0.0025, 0.01, 0.02]


def test_rejudging_the_condors_changes_only_the_status_and_the_bar(tmp_path, monkeypatch):
    import json
    import harness
    m = lambda sh: {"sharpe": sh, "n_days": 700}
    data = {"ledger_total": 217, "rules": {r["id"]: {"metrics": {"in_sample": m(0.6), "out_of_sample": m(0.2)}, "harness_status": "OLD", "p_in_sample": 1, "p_out_of_sample": 1,
                                                        "bonferroni_bar": 1} for r in oc.RULES}}
    path = tmp_path / "condors.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(harness, "cumulative_hypotheses", lambda: 500)
    out = oc.rejudge(str(path))
    assert out["ledger_total"] == 500
    for rule in out["rules"].values():
        assert rule["harness_status"] != "OLD" and rule["bonferroni_bar"] == pytest.approx(0.05 / 500) and rule["metrics"]["out_of_sample"] == m(0.2)
