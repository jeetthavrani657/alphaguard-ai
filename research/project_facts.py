"""
research/project_facts.py

Writes ONE plain markdown file with every headline number of the project, taken from the same read-only API the web app uses
(so it cannot disagree with the screen) and never typed by hand. It exists so a write-up (the college report, slides, a viva
sheet) is built from a single, current source of facts instead of from memory or old drafts.

    python research/project_facts.py                     # writes submission/PROJECT_FACTS.md
    python research/project_facts.py --out some/file.md

It reads files and prints nothing about any account; it places no orders.
"""

import argparse
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from fastapi.testclient import TestClient

from webapp.backend.main import app

DEFAULT_OUT = os.path.join(PROJECT_ROOT, "submission", "PROJECT_FACTS.md")


def _f(x, dp=2, suffix=""):
    return "n/a" if x is None else f"{x:.{dp}f}{suffix}"


def _ratio(r) -> str:
    """A Sharpe with its status, as the app shows it. Never a bare number."""
    if r is None or r.get("value") is None:
        return "n/a"
    bar = "" if r.get("clears_bar") is None else (", clears the bar" if r["clears_bar"] else ", below the bar")
    return f"{r['value']:.2f} ({r['status'].replace('_', ' ').lower()}, as of {r['as_of_hypotheses']}{bar})"


def _table(header: list, rows: list) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def build(client: TestClient) -> str:
    get = lambda path: client.get(path).json()
    health, ledger, strategies = get("/api/health"), get("/api/ledger"), get("/api/strategies")
    advisory, multi = get("/api/advisory"), get("/api/multiasset")
    books, fwd = get("/api/forward-books"), get("/api/advisory/forward")
    total = ledger["cumulative_hypotheses"]
    bar = ledger["bonferroni_bar_at_snapshot"]
    lines = []
    add = lines.append

    add("# AlphaGuard AI: project facts (generated, do not edit by hand)\n")
    add(f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} from the application's own read-only data service. "
        "Every figure below is what the app shows; regenerate this file instead of editing it.\n")

    add("## 1. Headline\n")
    add(f"* Ideas (hypotheses) tried and counted: **{total}**. Significance bar (Bonferroni, 0.05 divided by the count): **{bar:.6f}**.")
    add(f"* Backtest prices run through **{health['data_through']}**. Paper tests run on newer days.")
    add("* No idea has been validated as an edge. The research record is mostly a list of results that looked good and were not; "
        "four apparent positives turned out to be bugs in the project's own measurement code (see FINDINGS.md).")
    add("* The project is research only: it places no orders and has no order code (CLAUDE.md rule 5; EXECUTION_DESIGN.md).\n")

    add("## 2. Equity strategies (in-sample 2015-01-01 to 2020-06-30, out-of-sample 2020-07-01 to 2025-12-31)\n")
    rows = []
    for s in strategies["strategies"]:
        o, i = s["out_of_sample_sharpe"], s["in_sample_sharpe"]
        rows.append([s["name"], s["universe"], s["status"].replace("_", " ").lower(), _ratio(i), _ratio(o),
                     _f(o.get("p_value"), 6) if o else "n/a"])
    add(_table(["Strategy", "Universe", "Status", "Sharpe in-sample", "Sharpe out-of-sample", "Out-of-sample p"], rows))
    add("\nA status is only true as of the hypothesis count beside it; the bar gets harder as more is tried.\n")

    add("## 3. Multi-asset advisory (three risk profiles)\n")
    add(f"Simulated from {advisory['simulation_start']} to {advisory['data_through']}; in-sample ends {advisory['in_sample_end']}. "
        f"Weights decided at one close, carried out the next day, rebalanced every {advisory['rule']['rebalance_every_days']} trading days, "
        f"{advisory['rule']['cost_pct_per_side']:.2f}% cost each way, cash at {advisory['rule']['cash_rate_pct']:.0f}%.\n")
    rows = []
    for p in advisory["profiles"]:
        o, b = p["strategy"]["out_of_sample"], p["benchmark"]["out_of_sample"]
        rows.append([p["name"], _f(p["target_volatility_pct"], 0, "%"), _f(o["cagr_pct"], 1, "%"), _f(o["max_drawdown_pct"], 1, "%"),
                     _f(b["max_drawdown_pct"], 1, "%"), _ratio(o["sharpe"]), _ratio(b["sharpe"])])
    add(_table(["Profile", "Target volatility", "OOS return a year", "OOS worst fall", "Nifty 50 ETF worst fall", "OOS Sharpe", "Nifty 50 ETF Sharpe"], rows))
    add("\nReading: risk management lowered the worst fall; it did not prove higher returns (every profile failed the bar).\n")
    add("### Stress test (named bad stretches, read from the close before each started)\n")
    rows = []
    for e in advisory["stress"]:
        if not e["covered"]:
            rows.append([e["name"], f"{e['start']} to {e['end']}", "not covered", "", "", ""])
            continue
        by = {p["id"]: p for p in e["profiles"]}
        rows.append([e["name"], f"{e['start']} to {e['end']}"] + [_f(by[k]["return_pct"], 1, "%") for k in ("conservative", "moderate", "aggressive")] + [_f(e["benchmark"]["return_pct"], 1, "%")])
    add(_table(["Stretch", "Dates", "Conservative", "Moderate", "Aggressive", "Nifty 50 ETF"], rows))
    add("")

    add("## 4. Multi-asset trading rules (trend filter, 210-day, six assets)\n")
    add(f"Registered once as hypotheses (ledger {multi['ledger_total_at_generation']} at generation). Benchmarks: the same six assets with no timing, and the Nifty 50 ETF.\n")
    rows = []
    for s in multi["strategies"]:
        m = s["metrics"]
        rows.append([s["name"], _ratio(m["in_sample"]["sharpe"]), _ratio(m["out_of_sample"]["sharpe"]), _f(m["out_of_sample"]["max_drawdown_pct"], 1, "%")])
    for key in ("static_benchmark", "nifty_benchmark"):
        b = multi[key]
        rows.append([b["name"] + " (comparison)", _ratio(b["metrics"]["in_sample"]["sharpe"]), _ratio(b["metrics"]["out_of_sample"]["sharpe"]),
                     _f(b["metrics"]["out_of_sample"]["max_drawdown_pct"], 1, "%")])
    add(_table(["Rule", "Sharpe in-sample", "Sharpe out-of-sample", "OOS worst fall"], rows))
    add("\nReading: the trend filter lowered drawdowns but did not beat holding the same assets without timing.\n")

    add("## 5. Paper (forward) tests: nothing is judged before the pre-registered number of days\n")
    rows = []
    for b in books["books"]:
        s = b["summary"] or {}
        rows.append([b["name"], b["status"].replace("_", " ").lower(), f"{b['n_trading_days']} of {b['days_needed_for_verdict']}",
                     _f(s.get("return_pct"), 2, "%"), _f(s.get("benchmark_return_pct"), 2, "%")])
    for p in fwd["profiles"]:
        s = p["summary"] or {}
        rows.append([p["name"], p["status"].replace("_", " ").lower(), f"{p['n_trading_days']} of {fwd['days_needed_for_verdict']}",
                     _f(s.get("return_pct"), 2, "%"), _f(s.get("benchmark_return_pct"), 2, "%")])
    add(_table(["Test", "Status", "Days so far", "Return since start", "Holding the same instead"], rows))
    add("\nThese numbers are monitoring, not evidence, until a year of days has passed.\n")

    add("## 6. Order execution\n")
    add("Not built, deliberately. EXECUTION_DESIGN.md lists the gates: a rule must first pass its own pre-registered forward test, the owner must change "
        "rule 5 in writing, and the execution layer needs hard limits, a kill switch, idempotency, reconciliation, paper-first and human confirmation. "
        "Retail algorithmic-trading rules (SEBI, exchanges, brokers) were not verified and must be checked before any build.\n")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Write one markdown file of every headline number, from the app's own data service.")
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    text = build(TestClient(app))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[facts] wrote {args.out} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
