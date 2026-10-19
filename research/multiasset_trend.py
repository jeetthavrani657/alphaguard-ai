"""
research/multiasset_trend.py

Multi-asset algorithmic TRADING rules: a trend filter over the six assets of the advisory (Nifty 50 ETF, Nifty Midcap 150
ETF, Nasdaq-100 fund, gold ETF, long government-bond ETF, Bitcoin), with cash as the alternative. Research only: it
simulates what a rule would have done, places no orders and is NOT investment advice.

The design was frozen in MULTIASSET_TREND.md before this file was ever run. Two hypotheses are registered (once, with
--register) and judged by the same harness as every other strategy:

  trend_equal_weight   each asset has an equal slot, held when its close is above its 210-day average, else cash
  trend_risk_managed   only assets in an uptrend are eligible; weights are the advisory's moderate-profile risk machinery
                       (inverse volatility within caps, volatility target, drawdown guard)

Benchmarks (not hypotheses): the same six assets held with equal weights and no timing (the right null for a timing
rule), and the Nifty 50 ETF.

It reuses the advisory's simulation loop (research/advisory.py `simulate`): same costs, same one-day execution lag, same
cash rate, same windows. Run:

    python research/multiasset_trend.py --register    # ONCE: counts 2 hypotheses in the ledger
    python research/multiasset_trend.py               # regenerate the file without touching the ledger
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("data", "engine", "research"):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd

import advisory as adv
import harness

OUT_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "multiasset_trend_latest.json")

# ---- FROZEN in MULTIASSET_TREND.md (2026-10-20). Do not edit. ---------------------------------
TREND_DAYS = adv.TREND_DAYS                 # 210 trading days, from convention; never swept
RISK_PROFILE_ID = "moderate"                # the advisory profile whose caps, target volatility and guard the risk-managed rule uses
STRATEGIES = [
    {"id": "trend_equal_weight", "name": "Trend filter, equal weight",
     "blurb": "Each of the six assets has an equal slot. A slot holds its asset while the close is above its own 210-day average and sits in cash otherwise."},
    {"id": "trend_risk_managed", "name": "Trend filter, risk-managed",
     "blurb": "Only assets above their 210-day average are eligible. They are weighted by inverse volatility within the moderate profile's caps, volatility-targeted to 10% a year, with the drawdown guard."},
]
BENCH_STATIC_ID = "static_equal_weight"
STATIC_NAME = "Same six assets, equal weights, no timing"
DISCLAIMER = adv.DISCLAIMER


# ---- the rules ----------------------------------------------------------------------------------

def uptrend_flags(prices: pd.DataFrame, date: pd.Timestamp) -> dict:
    """True for each risky asset whose close on `date` is above its own average close of the last TREND_DAYS days (nothing after `date` is used)."""
    window = prices.loc[:date].iloc[-TREND_DAYS:]
    if len(window) < TREND_DAYS:
        return {k: False for k in adv.RISKY_IDS}
    last, avg = window.iloc[-1], window.mean()
    return {k: bool(last[k] > avg[k]) for k in adv.RISKY_IDS}


def equal_weight_slots(flags: dict) -> pd.Series:
    """One equal slot per asset; a slot in a downtrend (or all of them, for the static benchmark) is held as cash."""
    w = pd.Series(0.0, index=adv.RISKY_IDS + ["cash"])
    for k in adv.RISKY_IDS:
        if flags[k]:
            w[k] = 1.0 / len(adv.RISKY_IDS)
    w["cash"] = 1.0 - float(w.sum())
    return w


def risk_managed_weights(flags: dict, window: pd.DataFrame, guard_on: bool) -> pd.Series:
    """The advisory's risk machinery, restricted to the assets in an uptrend (a downtrend asset gets a cap of zero)."""
    profile = adv.PROFILES[RISK_PROFILE_ID]
    allowed = dict(profile, caps={k: (profile["caps"].get(k, 0.0) if flags[k] else 0.0) for k in adv.RISKY_IDS})
    return adv.target_weights(window, allowed, guard_on)


def make_chooser(prices: pd.DataFrame, returns: pd.DataFrame, strategy_id: str):
    """The function adv.simulate calls at each rebalance with (row index, the last 63 days of returns, guard state)."""
    def chooser(i, window, guard_on):
        flags = uptrend_flags(prices, returns.index[i])
        if strategy_id == "trend_equal_weight":
            return equal_weight_slots(flags)
        if strategy_id == "trend_risk_managed":
            return risk_managed_weights(flags, window, guard_on)
        if strategy_id == BENCH_STATIC_ID:
            return equal_weight_slots({k: True for k in adv.RISKY_IDS})
        raise ValueError(f"unknown strategy '{strategy_id}'")
    return chooser


def run_all(prices: pd.DataFrame, returns: pd.DataFrame) -> dict:
    """The two hypotheses and the static benchmark through history, each by the advisory's own simulation loop."""
    profile = adv.PROFILES[RISK_PROFILE_ID]        # only its drawdown limit is used here (to track the guard state)
    return {sid: adv.simulate(returns, profile, chooser=make_chooser(prices, returns, sid), warmup=TREND_DAYS)
            for sid in [s["id"] for s in STRATEGIES] + [BENCH_STATIC_ID]}


# ---- the output file ----------------------------------------------------------------------------

def _windows(equity: pd.Series) -> dict:
    return {"full": adv.window_metrics(equity), "in_sample": adv.window_metrics(equity.loc[:adv.IS_END]),
            "out_of_sample": adv.window_metrics(equity.loc[adv.OOS_START:])}


def _plain(m: dict) -> dict:
    return {k: (adv._clean(v) if k != "n_days" else v) for k, v in m.items()}


def build(prices: pd.DataFrame, returns: pd.DataFrame, register: bool = False, ledger_total_now: int | None = None) -> dict:
    sims = run_all(prices, returns)
    start = sims[STRATEGIES[0]["id"]]["equity"].index[0]
    nifty = (1.0 + returns[adv.BENCHMARK_ID].loc[start:]).cumprod() * 100.0
    windows = {sid: _windows(s["equity"]) for sid, s in sims.items()}
    nifty_windows = _windows(nifty)

    results = [harness.evaluate_strategy(
        f"multiasset_{s['id']}", s["blurb"], windows[s["id"]]["in_sample"]["sharpe"], windows[s["id"]]["in_sample"]["n_days"],
        windows[s["id"]]["out_of_sample"]["sharpe"], windows[s["id"]]["out_of_sample"]["n_days"]) for s in STRATEGIES]
    if register:
        out = harness.run_harness(results, "Multi-asset trend trading: 2 hypotheses (research/multiasset_trend.py), registered once")
        total, results = int(out["cumulative_hypotheses_all_time"]), out["results"]
    else:
        total = ledger_total_now if ledger_total_now is not None else harness.cumulative_hypotheses()
        harness.classify_results(results, total)

    flags_now = uptrend_flags(prices, prices.index[-1])
    strategies = []
    for s, res in zip(STRATEGIES, results):
        sim = sims[s["id"]]
        eq = sim["equity"]
        last = sim["rebalances"][-1]
        held = [{"asset_id": k, "weight_pct": round(float(v) * 100.0, 2)} for k, v in last["weights"].sort_values(ascending=False).items() if v > 1e-6]
        strategies.append({
            "id": s["id"], "name": s["name"], "blurb": s["blurb"], "harness_status": str(getattr(res, "status", None) or "UNVALIDATED"),
            "p_value_in_sample": adv._clean(getattr(res, "in_sample_p_value", None)), "p_value_out_of_sample": adv._clean(getattr(res, "out_of_sample_p_value", None)),
            "bonferroni_bar": adv._clean(getattr(res, "bonferroni_alpha", None)),
            "metrics": {w: _plain(m) for w, m in windows[s["id"]].items()},
            "growth": adv._series(eq / eq.iloc[0] * 100.0), "drawdown_pct": adv._series(adv.drawdown_series_pct(eq), 2),
            "exposure_pct": adv._series(sim["exposure_pct"], 1), "n_rebalances": len(sim["rebalances"]),
            "cost_paid_pct_of_start": round(sim["cost_paid"] / 100.0 * 100.0, 3),
            "held_now": held, "held_decided_on": last["date"].strftime("%Y-%m-%d"),
        })
    static_eq = sims[BENCH_STATIC_ID]["equity"]
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "data_through": returns.index[-1].strftime("%Y-%m-%d"),
        "simulation_start": start.strftime("%Y-%m-%d"), "in_sample_end": adv.IS_END, "out_of_sample_start": adv.OOS_START,
        "ledger_total": int(total), "disclaimer": DISCLAIMER, "trend_days": TREND_DAYS, "design_document": "MULTIASSET_TREND.md",
        "rule": {"rebalance_every_days": adv.REBALANCE_EVERY, "cost_pct_per_side": adv.COST_PCT * 100.0, "cash_rate_pct": adv.CASH_RATE * 100.0,
                 "execution": "decided at the close of day t, carried out one day later"},
        "strategies": strategies,
        "benchmarks": {
            "static": {"id": BENCH_STATIC_ID, "name": STATIC_NAME, "metrics": {w: _plain(m) for w, m in windows[BENCH_STATIC_ID].items()},
                       "growth": adv._series(static_eq / static_eq.iloc[0] * 100.0), "drawdown_pct": adv._series(adv.drawdown_series_pct(static_eq), 2)},
            "nifty": {"id": "nifty50_etf", "name": "Nifty 50 ETF, buy and hold", "metrics": {w: _plain(m) for w, m in nifty_windows.items()},
                      "growth": adv._series(nifty / nifty.iloc[0] * 100.0), "drawdown_pct": adv._series(adv.drawdown_series_pct(nifty), 2)},
        },
        "assets": [{"id": a["id"], "name": a["name"], "ticker": a["ticker"], "asset_class": a["asset_class"], "role": adv.ROLES[a["id"]]}
                   for a in adv.ASSETS if a["risky"]],
        "signals_now": [{"asset_id": k, "uptrend": flags_now[k]} for k in adv.RISKY_IDS],
        "stress": adv.stress_tests({**{s["id"]: sims[s["id"]] for s in STRATEGIES}, BENCH_STATIC_ID: sims[BENCH_STATIC_ID]}, returns),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Multi-asset trend trading rules (research only, no orders).")
    ap.add_argument("--register", action="store_true", help="count the 2 hypotheses in the ledger (do this ONCE)")
    ap.add_argument("--refresh", action="store_true", help="re-download prices")
    args = ap.parse_args(argv)
    prices = adv.load_prices(args.refresh)
    returns = adv.daily_returns(prices)
    payload = build(prices, returns, register=args.register)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, allow_nan=False)
    os.replace(tmp, OUT_PATH)
    b = payload["benchmarks"]
    for s in payload["strategies"]:
        o, i = s["metrics"]["out_of_sample"], s["metrics"]["in_sample"]
        print(f"[trend] {s['name']:28s} IS sharpe {i['sharpe']:.2f}  OOS sharpe {o['sharpe']:.2f}  OOS max drawdown {o['max_drawdown_pct']:.1f}%  status {s['harness_status']}")
    for k in ("static", "nifty"):
        o, i = b[k]["metrics"]["out_of_sample"], b[k]["metrics"]["in_sample"]
        print(f"[trend] {b[k]['name'][:28]:28s} IS sharpe {i['sharpe']:.2f}  OOS sharpe {o['sharpe']:.2f}  OOS max drawdown {o['max_drawdown_pct']:.1f}%")
    print(f"[trend] wrote {OUT_PATH}; ledger now {payload['ledger_total']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
