"""
research/golive_gates.py

Checks every paper-traded rule against the go-live gates in GO_LIVE_GATES.md and says, plainly, which are met and which are not. It READS result files and
prints/writes a verdict. It places no order, has no way to, and does not unlock anything: execution stays locked until the owner amends CLAUDE.md rule 5 in
writing (Gate 2 of EXECUTION_DESIGN.md), whatever this script prints.

    python research/golive_gates.py          # print the gate table for every book; writes reports/output/golive_gates_latest.json

The thresholds below are the DRAFT defaults of GO_LIVE_GATES.md. The win-rate threshold is the owner's own (85% at least); the others are proposals the
owner has not confirmed yet, and are changed in one place, here, with GO_LIVE_GATES.md updated beside them.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT_ROOT, "reports", "output")
OUTPUT_PATH = os.path.join(OUT_DIR, "golive_gates_latest.json")

# The owner's number, and the proposals that go with it (all must hold together: see GO_LIVE_GATES.md).
THRESHOLDS = {
    "win_rate_min_pct": 85.0,            # the owner's: 85% to 90% or better
    "win_rate_lower_bound_min_pct": 70.0,   # luck guard: the LOW end of the 95% interval of the win rate must clear this (proposal)
    "min_closed_trades": 100,            # fewer trades than this say nothing about a win rate (proposal)
    "min_profit_factor": 1.5,            # total won divided by total lost, after costs (proposal)
    "worst_loss_max_pct_of_account": 2.0,   # no single trade may have lost more than this share of the account (proposal)
    "max_drawdown_pct": 10.0,            # the forward test's worst fall must stay inside this (proposal)
    "cash_rate_pct_a_year": 6.0,         # the project's cash rate (config.RISK_FREE_RATE)
    "trading_days_a_year": 252,
}

MET, NOT_MET, NOT_YET, CANNOT_MEASURE = "MET", "NOT_MET", "NOT_YET", "CANNOT_MEASURE"


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple:
    """The 95% confidence interval of a win rate from `wins` of `n` trades, as (low, high) in percent. (0, 100) when there are no trades."""
    if n <= 0:
        return 0.0, 100.0
    p = wins / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return 100.0 * max(0.0, centre - half), 100.0 * min(1.0, centre + half)


def _gate(name: str, status: str, detail: str) -> dict:
    return {"gate": name, "status": status, "detail": detail}


def _flat(summary: dict) -> dict:
    """The summary with its ALL-IN trade statistics (closed trades plus open positions marked at the last close) lifted to the top level. A rule that holds its losers
    open would look perfect on closed trades alone, so the gates never read the closed-only version."""
    s = dict(summary or {})
    s.update((s.get("trade_stats") or {}).get("all_in") or {})
    return s


def evaluate(days: int, gate_days: int, summary: dict, t: dict = THRESHOLDS) -> list:
    """The gates for one paper-traded rule. `summary` is the book's summary block from the daily run (return, benchmark, drawdown and its trade statistics)."""
    s = _flat(summary)
    out = []

    # 1. The forward test has run its full, pre-registered length.
    if days < gate_days:
        out.append(_gate("Forward test complete", NOT_YET, f"{days} of {gate_days} trading days"))
    else:
        out.append(_gate("Forward test complete", MET, f"{days} of {gate_days} trading days"))

    # 2. After costs it beat both its benchmark (buy-and-hold of the same stocks, or the Nifty ETF) and cash over the same days.
    ret, bench = s.get("return_pct"), s.get("benchmark_return_pct")
    cash = t["cash_rate_pct_a_year"] * days / t["trading_days_a_year"]
    if ret is None or bench is None:
        out.append(_gate("Beat its benchmark and cash", CANNOT_MEASURE, "no return figure"))
    elif days < gate_days:
        out.append(_gate("Beat its benchmark and cash", NOT_YET, f"{ret:+.2f}% so far against {bench:+.2f}% for its benchmark and {cash:+.2f}% cash; judged only at the end"))
    else:
        ok = ret > bench and ret > cash
        out.append(_gate("Beat its benchmark and cash", MET if ok else NOT_MET, f"{ret:+.2f}% against {bench:+.2f}% for its benchmark and {cash:+.2f}% cash"))

    # 3. Enough closed trades for a win rate to mean something.
    n, wins = s.get("n_trades"), s.get("n_winning")
    if n is None or wins is None:
        out.append(_gate("At least %d trades (open ones at their mark)" % t["min_closed_trades"], CANNOT_MEASURE, "this rule's trade statistics are not available"))
    elif n < t["min_closed_trades"]:
        out.append(_gate("At least %d trades (open ones at their mark)" % t["min_closed_trades"], NOT_YET, f"{n} so far"))
    else:
        out.append(_gate("At least %d trades (open ones at their mark)" % t["min_closed_trades"], MET, f"{n} trades"))

    # 4. The win rate itself, and its low end (a few lucky trades must not unlock anything).
    if n is None or wins is None:
        out.append(_gate("Win rate at least %.0f%%" % t["win_rate_min_pct"], CANNOT_MEASURE, "no trade statistics"))
    elif n == 0:
        out.append(_gate("Win rate at least %.0f%%" % t["win_rate_min_pct"], NOT_YET, "no closed trade yet"))
    else:
        rate, (low, high) = 100.0 * wins / n, wilson_interval(wins, n)
        ok = n >= t["min_closed_trades"] and rate >= t["win_rate_min_pct"] and low >= t["win_rate_lower_bound_min_pct"]
        status = MET if ok else (NOT_YET if n < t["min_closed_trades"] else NOT_MET)
        out.append(_gate("Win rate at least %.0f%%" % t["win_rate_min_pct"], status,
                         f"{rate:.1f}% ({wins} of {n}); the 95% range is {low:.0f}% to {high:.0f}% and its low end must be {t['win_rate_lower_bound_min_pct']:.0f}% or more"))

    # 5. The trades make money after costs, not just often.
    pf, expectancy = s.get("profit_factor"), s.get("expectancy_pct")
    if pf is None and n and wins == n:
        pf = float("inf")                         # no trade lost: there is no loss to divide by
    if pf is None or expectancy is None:
        out.append(_gate("Profit factor and expectancy after costs", CANNOT_MEASURE, "no trade statistics"))
    else:
        ok = expectancy > 0 and pf >= t["min_profit_factor"] and (n or 0) >= t["min_closed_trades"]
        status = MET if ok else (NOT_YET if (n or 0) < t["min_closed_trades"] else NOT_MET)
        out.append(_gate("Profit factor and expectancy after costs", status, f"profit factor {"no losing trade" if math.isinf(pf) else format(pf, ".2f")} (needs {t['min_profit_factor']:.1f}), average trade {expectancy:+.3f}% (needs above 0)"))

    # 6. No single trade has hurt the account too much.
    worst = s.get("worst_loss_pct_of_account")
    if worst is None:
        out.append(_gate("Worst single loss within %.1f%% of the account" % t["worst_loss_max_pct_of_account"], CANNOT_MEASURE, "no trade statistics"))
    else:
        out.append(_gate("Worst single loss within %.1f%% of the account" % t["worst_loss_max_pct_of_account"],
                         MET if worst >= -t["worst_loss_max_pct_of_account"] else NOT_MET, f"worst single loss {worst:.2f}% of the account"))

    # 7. The forward test's worst fall stayed inside the owner's limit.
    dd = s.get("max_drawdown_pct")
    if dd is None:
        out.append(_gate("Drawdown within %.0f%%" % t["max_drawdown_pct"], CANNOT_MEASURE, "no drawdown figure"))
    else:
        inside = dd >= -t["max_drawdown_pct"]
        status = (MET if days >= gate_days else NOT_YET) if inside else NOT_MET
        out.append(_gate("Drawdown within %.0f%%" % t["max_drawdown_pct"], status, f"worst fall so far {dd:.2f}%"))
    return out


def project_gates(claude_md: str) -> list:
    """The two gates that belong to the project rather than to a rule: the paper layer's dry run, and the owner's written amendment of rule 5."""
    amended = "Never write live order placement code" not in claude_md        # rule 5 still says it, so no amendment has been made
    return [
        _gate("Paper layer: weeks of clean reconciliation", NOT_YET, "not automated yet: read the journal in execution/state by hand before any live step"),
        _gate("Owner's written amendment of rule 5", MET if amended else NOT_MET,
              "CLAUDE.md rule 5 still forbids order placement: the owner has not amended it" if not amended else "rule 5 no longer carries the prohibition: check what it now allows"),
    ]


def verdict(rule_gates: list, shared: list) -> dict:
    """ELIGIBLE only if every gate is MET; otherwise the unmet gates, in order. Even ELIGIBLE does not unlock anything: the owner decides."""
    unmet = [g for g in rule_gates + shared if g["status"] != MET]
    return {"eligible": not unmet, "unmet": [g["gate"] for g in unmet]}


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def run(root: str = PROJECT_ROOT) -> dict:
    out_dir = os.path.join(root, "reports", "output")
    books = (_read_json(os.path.join(out_dir, "forward_books_latest.json")) or {}).get("books", [])
    profiles = (_read_json(os.path.join(out_dir, "advisory_forward_latest.json")) or {}).get("profiles", [])
    try:
        with open(os.path.join(root, "CLAUDE.md"), encoding="utf-8") as f:
            claude_md = f.read()
    except OSError:
        claude_md = "Never write live order placement code"            # unreadable: assume the prohibition stands (fail closed)
    shared = project_gates(claude_md)
    rules = []
    for b in books:
        g = evaluate(int(b.get("n_trading_days") or 0), int(b.get("verdict_gate_days") or 252), b.get("summary"))
        rules.append({"id": b["id"], "name": b["name"], "kind": "book", "gates": g, **verdict(g, shared)})
    for p in profiles:
        g = evaluate(int(p.get("n_trading_days") or 0), 252, p.get("summary"))
        rules.append({"id": p["id"], "name": p["name"], "kind": "allocation", "gates": g, **verdict(g, shared)})
    return {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "thresholds": THRESHOLDS, "project_gates": shared, "rules": rules,
            "note": "Allocation profiles hold weights, not trades: under a win-rate gate they cannot unlock. They would need a separate gate the owner agrees."}


def main() -> int:
    result = run()
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp = OUTPUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    os.replace(tmp, OUTPUT_PATH)
    print("Go-live gates (execution stays locked whatever this says; only the owner's written amendment of rule 5 can change that)\n")
    for r in result["rules"]:
        met = sum(1 for g in r["gates"] if g["status"] == MET)
        print(f"{r['name']}: {'ELIGIBLE FOR THE OWNER TO CONSIDER' if r['eligible'] else 'not eligible'}  ({met} of {len(r['gates'])} rule gates met)")
        for g in r["gates"]:
            print(f"    [{g['status']:<14}] {g['gate']}: {g['detail']}")
    print("\nProject gates:")
    for g in result["project_gates"]:
        print(f"    [{g['status']:<14}] {g['gate']}: {g['detail']}")
    print("\n" + result["note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
