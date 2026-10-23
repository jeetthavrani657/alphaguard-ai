"""
research/options_condors.py

Runs the two rules frozen in OPTIONS_IDEAS.md on the stored Nifty option data and judges them with the project's usual harness:

    condor_monthly   sell the 16-delta put and call, buy the 5-delta wings, hold to the monthly expiry
    condor_weekly    the same around every weekly expiry

    python research/options_condors.py              # run and print; counts nothing in the ledger
    python research/options_condors.py --register   # ONCE: counts the 2 hypotheses (ledger 215 -> 217)
    python research/options_condors.py --rejudge    # re-judge the stored results at today's ledger count; runs nothing and counts nothing

Windows: in-sample 2022-01-03 to 2023-12-31, out-of-sample 2024-01-01 to the last day of data. The cost sensitivity (slippage of 0.25%, 1% and 2% a side instead of 0.5%) is a
DIAGNOSTIC and registers nothing.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("data", "engine", "research", ""):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub) if sub else PROJECT_ROOT)

import numpy as np
import pandas as pd

import advisory as adv
import harness
import options_backtest as ob
import options_costs as oc

OUTPUT_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "options_condors_latest.json")
IS_END, OOS_START = "2023-12-31", "2024-01-01"
START = "2022-01-03"
SLIPPAGE_LEVELS = [0.0025, 0.01, 0.02]
RULES = [
    {"id": "condor_monthly", "kind": "monthly", "name": "Nifty monthly iron condor (16-delta shorts, 5-delta wings, to expiry)"},
    {"id": "condor_weekly", "kind": "weekly", "name": "Nifty weekly iron condor (16-delta shorts, 5-delta wings, to expiry)"},
]
RATIONALE = ("Option buyers pay for protection and speculation, so the volatility priced into Nifty options has tended to exceed the volatility that follows (the variance risk premium); a seller "
             "of premium whose risk is capped by cheaper wings collects the difference and survives the bad months. The profile is many small gains and rare large losses, so a short history can "
             "look better than it is. Frozen in OPTIONS_IDEAS.md before any result existed.")


def windows_of(equity: pd.Series) -> dict:
    """The in-sample and out-of-sample slices of a daily account-value series."""
    return {"in_sample": equity.loc[:IS_END], "out_of_sample": equity.loc[OOS_START:]}


def cycle_summary(cycles: pd.DataFrame, entry_start=None, entry_end=None) -> dict:
    """What the trades looked like in a window: how many, how often they won, the worst and best, the profit with and without the single worst cycle, and the costs paid."""
    c = cycles
    if entry_start is not None:
        c = c[c["entry_day"] >= pd.Timestamp(entry_start)]
    if entry_end is not None:
        c = c[c["entry_day"] <= pd.Timestamp(entry_end)]
    if c.empty:
        return {"n_cycles": 0}
    worst = c["net_pnl"].min()
    return {"n_cycles": int(len(c)), "win_rate_pct": float((c["net_pnl"] > 0).mean() * 100), "total_net_pnl": float(c["net_pnl"].sum()),
            "mean_net_pnl": float(c["net_pnl"].mean()), "worst_cycle": float(worst), "best_cycle": float(c["net_pnl"].max()),
            "total_net_pnl_without_worst_cycle": float(c["net_pnl"].sum() - worst),
            "costs_paid": float((c["entry_cost"] + c["exit_cost"]).sum()), "gross_pnl": float(c["gross_pnl"].sum())}


def _plain(x):
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    return x


def run_rule(book: dict, rule: dict, slippage_pct: float = oc.SLIPPAGE_PCT) -> dict:
    return ob.run_condor_backtest(book, rule["kind"], initial=ob.INITIAL, rate=ob.DISCOUNT_RATE, slippage_pct=slippage_pct)


def rejudge(path: str = OUTPUT_PATH) -> dict:
    """The registered results judged again at the CURRENT ledger count, from the Sharpe ratios already stored. Nothing is run and nothing is counted."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    m = lambda r, w: data["rules"][r["id"]]["metrics"][w]
    results = [harness.evaluate_strategy(r["name"], RATIONALE, m(r, "in_sample")["sharpe"], m(r, "in_sample")["n_days"],
                                         m(r, "out_of_sample")["sharpe"], m(r, "out_of_sample")["n_days"]) for r in RULES]
    total = harness.cumulative_hypotheses()
    harness.classify_results(results, total)
    for r, res in zip(RULES, results):
        data["rules"][r["id"]].update({"harness_status": str(getattr(res, "status", None) or "UNVALIDATED"), "p_in_sample": getattr(res, "in_sample_p_value", None),
                                       "p_out_of_sample": getattr(res, "out_of_sample_p_value", None), "bonferroni_bar": getattr(res, "bonferroni_alpha", None)})
    data["ledger_total"] = total
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, default=_plain)
    os.replace(tmp, path)
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--register", action="store_true", help="count the 2 hypotheses in the ledger (do this ONCE)")
    ap.add_argument("--rejudge", action="store_true", help="judge the stored results again at the current ledger count; runs nothing")
    args = ap.parse_args()
    if args.rejudge:
        d = rejudge()
        print(f"[condors] re-judged at {d['ledger_total']}: " + ", ".join(f"{k} {v['harness_status']}" for k, v in d["rules"].items()))
        return 0

    import fo_bhavcopy as fo
    last = pd.Timestamp.today().strftime("%Y-%m-%d")
    table = fo.load_fo(START, last, symbols=["NIFTY"], instruments=("OPTIDX",))
    if table.empty:
        print("[condors] no stored F&O data: run research/backfill_fo.py first")
        return 1
    book = ob.index_table(table)
    days = ob.trading_days(book)
    print(f"[condors] {len(days)} trading days, {days[0].date()} to {days[-1].date()}, {len(book)} day/expiry chains")

    runs = {r["id"]: run_rule(book, r) for r in RULES}
    prices = adv.load_prices()
    nifty = prices["equity_large"]
    results, out = [], {}
    for rule in RULES:
        res = runs[rule["id"]]
        w = {name: adv.window_metrics(eq) for name, eq in windows_of(res["equity"]).items()}
        print(f"[condors] {rule['id']}: {len(res['cycles'])} trades, {len(res['skipped'])} skipped; "
              f"IS Sharpe {w['in_sample']['sharpe']:.2f}, OOS Sharpe {w['out_of_sample']['sharpe']:.2f}, OOS max drawdown {w['out_of_sample']['max_drawdown_pct']:.1f}%")
        results.append(harness.evaluate_strategy(rule["name"], RATIONALE, w["in_sample"]["sharpe"], w["in_sample"]["n_days"],
                                                 w["out_of_sample"]["sharpe"], w["out_of_sample"]["n_days"]))
        sens = {}
        for s in SLIPPAGE_LEVELS:
            alt = run_rule(book, rule, s)
            ww = windows_of(alt["equity"])
            sens[f"{s * 100:.2f}%"] = {"oos_sharpe": adv.window_metrics(ww["out_of_sample"])["sharpe"], "oos_total_net_pnl": float(alt["cycles"][alt["cycles"]["entry_day"] >= OOS_START]["net_pnl"].sum())}
        out[rule["id"]] = {"name": rule["name"], "metrics": w, "cycles_in_sample": cycle_summary(res["cycles"], None, IS_END),
                           "cycles_out_of_sample": cycle_summary(res["cycles"], OOS_START, None), "skipped": [(str(a.date()), str(b.date()), c) for a, b, c in res["skipped"]],
                           "slippage_sensitivity": sens, "equity_start": str(res["equity"].index[0].date()), "equity_end": str(res["equity"].index[-1].date())}

    bench = {}
    first = min(pd.Timestamp(v["equity_start"]) for v in out.values())
    for name, eq in windows_of(nifty.loc[first:]).items():
        bench.setdefault("nifty_etf", {})[name] = adv.window_metrics(eq)
    if args.register:
        run_out = harness.run_harness(results, "Nifty iron condors, monthly and weekly: 2 hypotheses (research/options_condors.py, OPTIONS_IDEAS.md), registered once")
        total, results = int(run_out["cumulative_hypotheses_all_time"]), run_out["results"]
    else:
        total = harness.cumulative_hypotheses()
        harness.classify_results(results, total)
        print(f"[condors] NOT registered: judged at the current count {total}; registering would make it {total + len(RULES)}")
    for rule, res in zip(RULES, results):
        out[rule["id"]].update({"harness_status": str(getattr(res, "status", None) or "UNVALIDATED"), "p_in_sample": getattr(res, "in_sample_p_value", None),
                                "p_out_of_sample": getattr(res, "out_of_sample_p_value", None), "bonferroni_bar": getattr(res, "bonferroni_alpha", None)})
        print(f"[condors] {rule['id']}: {out[rule['id']]['harness_status']}  p IS {out[rule['id']]['p_in_sample']}  p OOS {out[rule['id']]['p_out_of_sample']}")
    if args.register:
        payload = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "ledger_total": total, "registered": True,
                   "rules": out, "benchmarks": bench}
        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1, default=_plain)
        print(f"[condors] wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
