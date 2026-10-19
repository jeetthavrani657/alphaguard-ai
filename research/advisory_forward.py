"""
research/advisory_forward.py

Forward paper tracking for the three multi-asset advisory profiles (ADVISORY.md). The rule is frozen and the three
profiles are already counted in the hypothesis ledger (208), so this adds NO hypothesis: it only collects out-of-time
evidence, the same way research/forward_books.py does for the equity books. Research only: it logs what each profile
WOULD have done, places no orders and connects to no broker. It tracks the three advisory profiles and the two multi-asset
trend rules (MULTIASSET_TREND.md).

  * Everything is recomputed from raw prices with the same simulate() as the advisory page, so running it twice on the
    same data gives the same answer. The clock starts at the close of FORWARD_START; the first countable session is
    FIRST_COUNTED_DAY, the first session after the rules were frozen.
  * Nothing is judged early. No Sharpe is computed or shown before MIN_DAYS_FOR_SHARPE forward sessions exist; until
    then the numbers (return, drawdown, exposure) are monitoring only.

Outputs (under reports/output/):
    advisory_forward.csv           one row per (profile, data date): the history of the numbers, so a vendor
                                   re-adjustment of the free price data would show
    advisory_forward_latest.json   the current picture per profile for the web app

    python research/advisory_forward.py            # use cached prices
    python research/advisory_forward.py --refresh  # download fresh prices first (the daily task does this)
"""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("engine", "research"):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd

import advisory as adv
import multiasset_trend as mt

# ---- FROZEN. Do not edit. -----------------------------------------------------------------------
# The advisory rule was committed on the evening of 2026-10-19, AFTER that day's close, so 2026-10-19 had already been seen
# when the rule was frozen and is not out-of-time. (An earlier version of this file counted it as day 1, copying the paper
# books' dates; that was wrong and is corrected here, see ADVISORY.md.) The trend rules were frozen on 2026-10-20 before
# any result existed. Both therefore start from the 2026-10-19 close, and the first session that counts is 2026-10-20.
FORWARD_START = "2026-10-19"          # base day: the 2026-10-19 close is 100
FIRST_COUNTED_DAY = "2026-10-20"      # first session that counts
MIN_DAYS_FOR_SHARPE = 252             # no Sharpe, and no verdict, before a year of forward data
HISTORY_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "advisory_forward.csv")
LATEST_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "advisory_forward_latest.json")


def _series(s: pd.Series, nd: int = 3) -> dict:
    """A dated series as two parallel lists, the shape the web app's charts read."""
    return {"dates": [d.strftime("%Y-%m-%d") for d in s.index], "values": [round(float(v), nd) for v in s.values]}


def build_profile(pid: str, returns: pd.DataFrame) -> dict:
    """One advisory profile's forward picture: the frozen rule run on all data, then read from the freeze day onward."""
    return _forward_picture(pid, adv.PROFILES[pid]["name"], returns, lambda: adv.simulate(returns, adv.PROFILES[pid]))


def build_trend(sid: str, name: str, returns: pd.DataFrame, sim: dict | None) -> dict:
    """The same forward picture for one multi-asset trend rule (MULTIASSET_TREND.md), from its already-run simulation."""
    return _forward_picture(sid, name, returns, lambda: sim)


def _forward_picture(pid: str, name: str, returns: pd.DataFrame, run) -> dict:
    last = returns.index[-1]
    base = {"id": pid, "name": name, "data_through": last.strftime("%Y-%m-%d")}
    if last < pd.Timestamp(FIRST_COUNTED_DAY):
        return {**base, "status": "NOT_STARTED", "n_trading_days": 0, "summary": None, "growth_strategy": None, "growth_benchmark": None,
                "current_mix": [], "mix_as_of": None, "guard_on": False, "n_rebalances_since_start": 0,
                "note": f"The first countable session is {FIRST_COUNTED_DAY}; data currently ends {last.date()}. The clock has started."}

    sim = run()
    equity = sim["equity"]
    base_day = equity.index[equity.index <= pd.Timestamp(FORWARD_START)][-1]       # the freeze-day close, the base of 100
    fwd = equity.loc[base_day:] / float(equity.loc[base_day]) * 100.0
    br = returns[adv.BENCHMARK_ID].loc[base_day:].copy()
    br.iloc[0] = 0.0                                                                # the base day itself earned nothing in the forward window
    bench = (1.0 + br).cumprod() * 100.0

    n_days = int((fwd.index >= pd.Timestamp(FIRST_COUNTED_DAY)).sum())             # the base day is day 0, not a forward day
    rebalances = [r for r in sim["rebalances"] if r["date"] >= base_day]
    latest = sim["rebalances"][-1]                                                  # the mix the rule currently recommends
    mix = [{"asset_id": k, "weight_pct": round(float(v) * 100.0, 2)} for k, v in latest["weights"].sort_values(ascending=False).items() if v > 1e-6]
    exposure = float(sim["exposure_pct"].iloc[-1])
    return {
        **base, "status": "RUNNING", "n_trading_days": n_days,
        "summary": {
            "return_pct": round(float(fwd.iloc[-1] / 100.0 - 1.0) * 100.0, 3),
            "benchmark_return_pct": round(float(bench.iloc[-1] / 100.0 - 1.0) * 100.0, 3),
            "max_drawdown_pct": round(float(adv.drawdown_series_pct(fwd).min()), 3),
            "benchmark_max_drawdown_pct": round(float(adv.drawdown_series_pct(bench).min()), 3),
            "exposure_pct": round(exposure, 2),
            "withheld_reason": ("" if n_days >= MIN_DAYS_FOR_SHARPE else f"withheld: {n_days} of {MIN_DAYS_FOR_SHARPE} trading days of forward data"),
        },
        "growth_strategy": _series(fwd), "growth_benchmark": _series(bench),
        "current_mix": mix, "mix_as_of": latest["date"].strftime("%Y-%m-%d"), "guard_on": bool(latest["guard_on"]),
        "n_rebalances_since_start": len(rebalances), "note": "",
    }


def append_history(report: dict, path: str = HISTORY_PATH) -> None:
    s = report["summary"] or {}
    row = pd.DataFrame([{
        "run_date": pd.Timestamp.today().strftime("%Y-%m-%d"), "profile_id": report["id"], "data_through": report["data_through"],
        "status": report["status"], "n_trading_days": report["n_trading_days"], "return_pct": s.get("return_pct"),
        "benchmark_return_pct": s.get("benchmark_return_pct"), "max_drawdown_pct": s.get("max_drawdown_pct"), "exposure_pct": s.get("exposure_pct"),
    }])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        old = pd.read_csv(path)
        # one row per (profile, data date): re-running on the same data replaces, not duplicates
        keep = ~((old["profile_id"] == report["id"]) & (old["data_through"] == report["data_through"]))
        row = pd.concat([old[keep], row], ignore_index=True)
    row.to_csv(path, index=False)


def write_latest(reports: list, path: str = LATEST_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {"generated_at": pd.Timestamp.now("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"), "start": FORWARD_START,
               "first_counted_day": FIRST_COUNTED_DAY, "min_days_for_sharpe": MIN_DAYS_FOR_SHARPE,
               "disclaimer": adv.DISCLAIMER, "benchmark": "Nifty 50 ETF buy-and-hold", "profiles": reports}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, allow_nan=False)           # NaN would be invalid JSON: fail loudly, never write it
    os.replace(tmp, path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Forward paper tracking of the three advisory profiles (research only, no orders).")
    ap.add_argument("--refresh", action="store_true", help="download fresh prices first")
    args = ap.parse_args(argv)
    prices = adv.load_prices(args.refresh)
    returns = adv.daily_returns(prices)
    reports = []
    for pid in adv.PROFILES:
        reports.append(build_profile(pid, returns))
    trend_sims = mt.run_all(prices, returns) if returns.index[-1] >= pd.Timestamp(FIRST_COUNTED_DAY) else {}
    for s in mt.STRATEGIES:
        reports.append(build_trend(s["id"], s["name"], returns, trend_sims.get(s["id"])))
    for rep in reports:
        append_history(rep)
        s = rep["summary"]
        print(f"[advisory-forward] {rep['id']}: {rep['status']}, data through {rep['data_through']}, {rep['n_trading_days']} forward days"
              + (f", return {s['return_pct']:+.2f}% vs Nifty 50 ETF {s['benchmark_return_pct']:+.2f}%, drawdown {s['max_drawdown_pct']:.1f}%" if s else ""))
    write_latest(reports)
    print(f"[advisory-forward] wrote {LATEST_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
